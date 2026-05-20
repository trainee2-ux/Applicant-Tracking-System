import base64
import json
import random
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib import messages
from django.core.mail import get_connection, send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from app_settings.models import CompanyInfo, EmailDeliveryConfig, UserMaster
from app_settings.models import UiNotification
from django.db.models import Q
from super_admin.utils import is_platform_superadmin


def home_view(request):
    if is_platform_superadmin(request):
        return redirect("/super-admin/dashboard/")

    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name == "candidate":
        return redirect("/candidate-portal/")
    if role_name:
        return redirect("/dashboard/")
    return render(request, "accounts/login_chooser.html", _sso_login_context())


def logout_view(request):
    request.session.flush()
    return redirect("/login/")


def _sso_is_enabled():
    return getattr(settings, "ATS_SSO_ENABLED", False)


def _sso_provider_label():
    return getattr(settings, "ATS_SSO_PROVIDER_LABEL", "SSO")


def _sso_login_context():
    return {
        "sso_enabled": _sso_is_enabled(),
        "sso_provider_label": _sso_provider_label(),
    }


def _decode_jwt_payload(token):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + padding)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        if not email or not password:
            messages.error(request, "Email and Password are required.")
            return render(request, "accounts/login.html", _sso_login_context())

        user_row = UserMaster.objects.filter(email_id__iexact=email).first()
        if not user_row or (user_row.password or "") != password:
            messages.error(request, "Invalid email or password.")
            return render(request, "accounts/login.html", _sso_login_context())

        if not user_row.company_id:
            default_company = CompanyInfo.objects.order_by("id").first()
            if not default_company:
                default_company = CompanyInfo.objects.create(
                    company_name="Default Company",
                    agreement_status="completed",
                    status="active",
                    service_from=timezone.localdate(),
                )
            user_row.company = default_company
            user_row.save(update_fields=["company"])

        display_name = user_row.full_name or user_row.email_id.split("@")[0].replace(".", " ").title()
        role_name = user_row.role if user_row.role else "Admin"
        request.session["login_user_name"] = display_name
        request.session["login_user_email"] = user_row.email_id
        request.session["login_user_role"] = role_name
        request.session["login_user_company_id"] = user_row.company_id
        if role_name.strip().lower() == "candidate":
            return redirect("/candidate-portal/")

        # Show subscription status notifications only to company Admin role.
        try:
            if role_name.strip().lower() == "admin" and user_row.company_id:
                from super_admin.models import CompanySubscription

                subscription = (
                    CompanySubscription.objects.filter(company_id=user_row.company_id)
                    .select_related("plan")
                    .order_by("-end_date", "-created_at")
                    .first()
                )
                if subscription and subscription.status == "active":
                    today = timezone.localdate()
                    already = UiNotification.objects.filter(
                        recipient_name__iexact=user_row.email_id,
                        source="subscription",
                        title__iexact="Subscription Active",
                        created_at__date=today,
                    ).exists()
                    if not already:
                        plan_name = subscription.plan.name if subscription.plan_id else "Plan"
                        UiNotification.objects.create(
                            recipient_name=(user_row.email_id or "").strip().lower(),
                            title="Subscription Active",
                            message=f"{plan_name} active until {subscription.end_date}.",
                            link="/settings/subscription-billing/",
                            source="subscription",
                            created_by="system",
                        )
        except Exception:
            pass
        return redirect("/dashboard/")

    request.session.pop("login_user_name", None)
    request.session.pop("login_user_email", None)
    request.session.pop("login_user_role", None)
    return render(request, "accounts/login.html", _sso_login_context())


def subscription_expired_view(request):
    """
    Shown to company users when their subscription is expired/cancelled or company is inactive/expired.
    Platform superadmins are redirected to Super Admin dashboard.
    """
    if is_platform_superadmin(request):
        return redirect("/super-admin/dashboard/")

    reason = (request.GET.get("reason") or "Subscription expired").strip()
    detail = (request.GET.get("detail") or "").strip()
    support_email = getattr(settings, "ATS_SUPPORT_EMAIL", "support@ultimatix.com")
    support_phone = getattr(settings, "ATS_SUPPORT_PHONE", "")

    return render(
        request,
        "accounts/subscription_expired.html",
        {
            "reason": reason,
            "detail": detail,
            "support_email": support_email,
            "support_phone": support_phone,
        },
    )


def sso_login_view(request):
    if not _sso_is_enabled():
        messages.error(request, "SSO is not enabled.")
        return redirect("accounts:login")

    authorize_url = getattr(settings, "ATS_SSO_AUTHORIZE_URL", "").strip()
    client_id = getattr(settings, "ATS_SSO_CLIENT_ID", "").strip()
    scope = getattr(settings, "ATS_SSO_SCOPE", "openid profile email").strip()
    if not authorize_url or not client_id:
        messages.error(request, "SSO configuration is incomplete: authorize URL or client id missing.")
        return redirect("accounts:login")

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    request.session["ats_sso_state"] = state
    request.session["ats_sso_nonce"] = nonce

    redirect_uri = request.build_absolute_uri(reverse("accounts:sso_callback"))
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
    }
    return redirect(f"{authorize_url}?{urlencode(query)}")


def sso_callback_view(request):
    if not _sso_is_enabled():
        messages.error(request, "SSO is not enabled.")
        return redirect("accounts:login")

    expected_state = request.session.get("ats_sso_state", "")
    incoming_state = request.GET.get("state", "")
    code = request.GET.get("code", "").strip()
    if not expected_state or not incoming_state or incoming_state != expected_state:
        messages.error(request, "SSO failed: invalid state.")
        return redirect("accounts:login")
    if not code:
        messages.error(request, "SSO failed: authorization code missing.")
        return redirect("accounts:login")

    token_url = getattr(settings, "ATS_SSO_TOKEN_URL", "").strip()
    client_id = getattr(settings, "ATS_SSO_CLIENT_ID", "").strip()
    client_secret = getattr(settings, "ATS_SSO_CLIENT_SECRET", "").strip()
    if not token_url or not client_id or not client_secret:
        messages.error(request, "SSO configuration is incomplete: token endpoint/client credentials missing.")
        return redirect("accounts:login")

    redirect_uri = request.build_absolute_uri(reverse("accounts:sso_callback"))
    token_payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")

    try:
        token_req = Request(
            token_url,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(token_req, timeout=10) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        messages.error(request, f"SSO token exchange failed: {exc}")
        return redirect("accounts:login")

    access_token = token_data.get("access_token", "")
    id_token = token_data.get("id_token", "")
    if not access_token and not id_token:
        messages.error(request, "SSO failed: no token returned.")
        return redirect("accounts:login")

    profile = {}
    userinfo_url = getattr(settings, "ATS_SSO_USERINFO_URL", "").strip()
    if userinfo_url and access_token:
        try:
            userinfo_req = Request(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
                method="GET",
            )
            with urlopen(userinfo_req, timeout=10) as response:
                profile = json.loads(response.read().decode("utf-8"))
        except Exception:
            profile = {}

    if not profile and id_token:
        profile = _decode_jwt_payload(id_token)

    email = (
        profile.get("email")
        or profile.get("preferred_username")
        or profile.get("upn")
        or ""
    ).strip()
    display_name = (
        profile.get("name")
        or " ".join(
            value for value in [profile.get("given_name", "").strip(), profile.get("family_name", "").strip()] if value
        )
        or "Administrator"
    )

    if not email:
        messages.error(request, "SSO failed: user email/username not found in identity response.")
        return redirect("accounts:login")

    request.session["login_user_name"] = display_name
    request.session["login_user_email"] = email
    user_row = UserMaster.objects.filter(email_id__iexact=email).first()
    role_name = user_row.role if user_row and user_row.role else "Admin"
    request.session["login_user_role"] = role_name
    request.session["ats_sso_authenticated"] = True
    request.session.pop("ats_sso_state", None)
    request.session.pop("ats_sso_nonce", None)
    if role_name.strip().lower() == "candidate":
        return redirect("/candidate-portal/")
    return redirect("/dashboard/")


def forgot_password_view(request):
    otp_contact_key = "fp_contact"
    otp_value_key = "fp_otp"
    otp_time_key = "fp_otp_sent_at"
    otp_verified_key = "fp_otp_verified"
    otp_user_key = "fp_user_id"

    def _mask_email(value: str) -> str:
        raw = (value or "").strip()
        if "@" not in raw:
            return raw
        name, domain = raw.split("@", 1)
        if len(name) <= 2:
            masked = "*" * len(name)
        else:
            masked = f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"
        return f"{masked}@{domain}"

    def _clear_forgot_state():
        request.session.pop(otp_contact_key, None)
        request.session.pop(otp_value_key, None)
        request.session.pop(otp_time_key, None)
        request.session.pop(otp_verified_key, None)
        request.session.pop(otp_user_key, None)

    def _is_otp_expired():
        sent_at_raw = request.session.get(otp_time_key)
        if not sent_at_raw:
            return True
        try:
            sent_at = datetime.fromisoformat(sent_at_raw)
            if timezone.is_naive(sent_at):
                sent_at = timezone.make_aware(sent_at, timezone.get_current_timezone())
        except ValueError:
            return True
        return timezone.now() > sent_at + timedelta(minutes=10)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "send_otp":
            email_or_mobile = request.POST.get("email_or_mobile", "").strip()
            if not email_or_mobile:
                messages.error(request, "Email/Mobile is required.")
                return redirect("accounts:forgot_password")

            user_row = UserMaster.objects.filter(
                Q(email_id__iexact=email_or_mobile) | Q(employee_code__iexact=email_or_mobile)
            ).first()
            if not user_row:
                messages.error(request, "Account not found for the provided Email / Employee ID.")
                return redirect("accounts:forgot_password")

            otp = f"{random.randint(100000, 999999)}"
            request.session[otp_contact_key] = user_row.email_id
            request.session[otp_value_key] = otp
            request.session[otp_time_key] = timezone.now().isoformat()
            request.session[otp_verified_key] = False
            request.session[otp_user_key] = user_row.id

            # Use SMTP settings saved in Settings > Integration when enabled.
            email_cfg = EmailDeliveryConfig.objects.order_by("-updated_at").first()
            smtp_enabled = bool(email_cfg and email_cfg.smtp_enabled and (email_cfg.host or "").strip())
            from_email = (email_cfg.from_email or "").strip() if email_cfg else ""
            if not from_email:
                from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or "no-reply@ultimatix-ats.local"

            subject = "Ultimatix ATS - Password Reset OTP"
            body = (
                "Your password reset OTP is:\n\n"
                f"{otp}\n\n"
                "This OTP is valid for 10 minutes.\n"
                "If you did not request this, you can ignore this email."
            )
            try:
                if smtp_enabled:
                    connection = get_connection(
                        backend="django.core.mail.backends.smtp.EmailBackend",
                        host=email_cfg.host,
                        port=email_cfg.port,
                        username=email_cfg.username,
                        password=email_cfg.password,
                        use_tls=email_cfg.use_tls,
                    )
                    send_mail(subject, body, from_email, [user_row.email_id], connection=connection)
                else:
                    send_mail(subject, body, from_email, [user_row.email_id])
                messages.success(request, f"OTP sent successfully to {_mask_email(user_row.email_id)}.")
            except Exception:
                messages.error(
                    request,
                    "OTP generated, but email could not be sent. Please check email configuration (SMTP) or try again later.",
                )
            return redirect("accounts:forgot_password")

        if action == "verify_otp":
            if _is_otp_expired():
                _clear_forgot_state()
                messages.error(request, "OTP expired. Please request a new OTP.")
                return redirect("accounts:forgot_password")

            entered_otp = request.POST.get("otp_verification", "").strip()
            saved_otp = request.session.get(otp_value_key, "")
            if not entered_otp or entered_otp != saved_otp:
                messages.error(request, "Invalid OTP.")
                return redirect("accounts:forgot_password")

            request.session[otp_verified_key] = True
            messages.success(request, "OTP verified. You can now change password.")
            return redirect("accounts:forgot_password")

        if action == "reset_password":
            if not request.session.get(otp_verified_key):
                messages.error(request, "Please verify OTP first.")
                return redirect("accounts:forgot_password")

            if _is_otp_expired():
                _clear_forgot_state()
                messages.error(request, "OTP expired. Please request a new OTP.")
                return redirect("accounts:forgot_password")

            new_password = request.POST.get("new_password", "").strip()
            confirm_password = request.POST.get("confirm_password", "").strip()

            if not new_password or not confirm_password:
                messages.error(request, "New Password and Confirm Password are required.")
                return redirect("accounts:forgot_password")

            if new_password != confirm_password:
                messages.error(request, "New Password and Confirm Password must match.")
                return redirect("accounts:forgot_password")

            user_id = request.session.get(otp_user_key)
            user_row = UserMaster.objects.filter(id=user_id).first() if user_id else None
            if not user_row:
                _clear_forgot_state()
                messages.error(request, "Account not found. Please start password recovery again.")
                return redirect("accounts:forgot_password")

            user_row.password = new_password
            user_row.save(update_fields=["password"])
            _clear_forgot_state()
            messages.success(request, "Password updated successfully.")
            return redirect("accounts:login")

        if action == "reset_flow":
            _clear_forgot_state()
        return redirect("accounts:forgot_password")

    context = {
        "otp_contact": request.session.get(otp_contact_key, ""),
        "otp_requested": bool(request.session.get(otp_value_key)),
        "otp_verified": bool(request.session.get(otp_verified_key)),
    }
    return render(request, "accounts/forgot_password.html", context)


def my_profile_view(request):
    login_email = (request.session.get("login_user_email") or "").strip()
    user_row = UserMaster.objects.filter(email_id__iexact=login_email).first() if login_email else None

    if request.method == "POST":
        if not user_row:
            messages.error(request, "User profile not found in database.")
            return redirect("accounts:my_profile")

        name = request.POST.get("name", "").strip()
        mobile = request.POST.get("mobile", "").strip()

        if not name:
            messages.error(request, "Name is required.")
            return redirect("accounts:my_profile")

        name_parts = [part for part in name.split(" ") if part]
        user_row.first_name = name_parts[0] if name_parts else user_row.first_name
        user_row.last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        user_row.mobile_number = mobile or user_row.mobile_number
        if request.FILES.get("profile_photo"):
            user_row.profile_photo = request.FILES["profile_photo"]
        user_row.save()

        request.session["login_user_name"] = user_row.full_name or request.session.get("login_user_name", "Administrator")
        return redirect("accounts:my_profile")

    profile_name = request.session.get("login_user_name", "Administrator")
    profile_email = request.session.get("login_user_email", "admin@ultimatix.com")
    profile_mobile = ""
    profile_department = ""
    profile_role = request.session.get("login_user_role", "Administrator")
    profile_photo_url = ""

    if user_row:
        profile_name = user_row.full_name or profile_name
        profile_email = user_row.email_id or profile_email
        profile_mobile = user_row.mobile_number or ""
        profile_department = user_row.department or ""
        profile_role = user_row.role or profile_role
        if user_row.profile_photo:
            profile_photo_url = user_row.profile_photo.url

    context = {
        "profile_name": profile_name,
        "profile_email": profile_email,
        "profile_mobile": profile_mobile,
        "profile_department": profile_department or "-",
        "profile_role": profile_role,
        "profile_photo_url": profile_photo_url,
    }
    return render(request, "accounts/my_profile.html", context)


def global_search_view(request):
    query = request.GET.get("q", "")
    normalized_query = " ".join(query.lower().split())
    if not normalized_query:
        messages.info(request, "Enter a search value.")
        return redirect("/dashboard/")

    # Most specific routes first, broader modules later.
    route_map = [
        (["candidate registration", "registration form"], "/candidate-management/registration/"),
        (["candidate profile"], "/candidate-management/profile/"),
        (["candidate evaluation"], "/candidate-management/evaluation/"),
        (["candidate list"], "/candidate-management/list/"),
        (["candidate management"], "/candidate-management/"),
        (["job posting", "posting form", "job position form"], "/job-requisition/posting-form/"),
        (["job position dashboard", "position dashboard"], "/job-requisition/job-position-dashboard/"),
        (["job approval form"], "/job-requisition/job-approval/form/"),
        (["job approval", "approval workflow"], "/job-requisition/job-approval/"),
        (["requisition management", "job requisition"], "/job-requisition/"),
        (["application pipeline", "pipeline"], "/applicant-tracking/application-pipeline/"),
        (["interview scheduling", "schedule interview"], "/applicant-tracking/interview-scheduling/"),
        (["applicant tracking"], "/applicant-tracking/"),
        (["background verification submission", "bgv submission", "submission form"], "/background-verification/submission/"),
        (["background verification dashboard", "bgv dashboard", "verification dashboard"], "/background-verification/verification-dashboard/"),
        (["background verification report", "bgv report"], "/background-verification/report/"),
        (["background verification"], "/background-verification/"),
        (["interview evaluation"], "/interview-evaluation/"),
        (["interview recording"], "/interview-recording/"),
        (["candidate portal"], "/candidate-portal/"),
        (["recruitment team", "team management"], "/recruitment-teams/"),
        (["task management", "task"], "/task-management/"),
        (["candidate database"], "/candidate-database/"),
        (["assessment form"], "/settings/assessment-form/"),
        (["masters"], "/settings/masters/"),
        (["members"], "/settings/members/"),
        (["email templates"], "/settings/email-templates/"),
        (["feedback form"], "/settings/feedback-form/"),
        (["bulk upload"], "/settings/bulk-upload/"),
        (["integration"], "/settings/integration/"),
        (["workflow", "mautic dashboard"], "/settings/workflow/"),
        (["data export"], "/settings/data-export/"),
        (["subscription", "billing"], "/settings/subscription-billing/"),
        (["company careers"], "/settings/company/careers/"),
        (["company info", "company management"], "/settings/company/info/"),
        (["company"], "/settings/company/"),
        (["role", "role master"], "/settings/role/"),
        (["user master", "user management"], "/settings/user-master/"),
        (["permission management", "permission"], "/settings/permission-management/"),
        (["settings"], "/settings/"),
        (["profile", "administrator"], "/profile/"),
        (["dashboard", "home"], "/dashboard/"),
    ]

    for keywords, target_url in route_map:
        if any(keyword in normalized_query for keyword in keywords):
            return redirect(target_url)

    messages.info(request, f'No matching module/form found for "{query}".')
    return redirect("/dashboard/")
