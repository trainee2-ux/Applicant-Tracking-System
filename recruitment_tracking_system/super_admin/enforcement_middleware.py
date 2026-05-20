from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from app_settings.models import CompanyInfo, UserMaster

from .models import CompanySubscription
from .utils import is_platform_superadmin, is_superadmin_request


class CompanyEnforcementMiddleware:
    """
    Enforce company service agreement + subscription constraints for all ATS routes.

    - Super Admin bypasses all checks.
    - If agreement is pending -> redirect to service agreement page.
    - If company is inactive/suspended/expired -> block.
    - If subscription expired/missing -> block.
    """

    PUBLIC_PREFIXES = (
        "/static/",
        "/media/",
        "/admin/",
    )

    PUBLIC_PATHS = {
        "/",
        "/login/",
        "/logout/",
        "/subscription-expired/",
        "/forgot-password/",
        "/sso/login/",
        "/sso/callback/",
        "/careers/",
        "/super-admin/login/",
        "/super-admin/logout/",
    }

    ALLOW_WHEN_BLOCKED_PREFIXES = (
        "/super-admin/access-blocked/",
        "/super-admin/service-agreement/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = (request.path or "").strip()

        if path in self.PUBLIC_PATHS or any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return self.get_response(request)

        # Platform superadmin should only see the Super Admin module (not company ATS features).
        if is_platform_superadmin(request):
            if path.startswith("/super-admin/") or path.startswith("/admin/"):
                return self.get_response(request)
            return redirect("/super-admin/dashboard/")

        role_name = (request.session.get("login_user_role") or "").strip().lower()
        if role_name == "candidate":
            return self.get_response(request)

        if any(path.startswith(p) for p in self.ALLOW_WHEN_BLOCKED_PREFIXES):
            return self.get_response(request)

        if path.startswith("/super-admin/") and not path.startswith("/super-admin/login/") and not path.startswith(
            "/super-admin/logout/"
        ):
            # Always send non-platform users to the Super Admin login screen (separate auth).
            return redirect("/super-admin/login/")

        login_email = (request.session.get("login_user_email") or "").strip()
        if not login_email:
            return self.get_response(request)

        user = UserMaster.objects.select_related("company").filter(email_id__iexact=login_email).first()
        if not user:
            request.session.flush()
            return redirect("/login/")

        company = user.company or CompanyInfo.objects.order_by("id").first()
        if not company:
            return self._block(request, "Company inactive", "No company configured for this account.")

        today = timezone.localdate()

        # Automatic company expiry based on service window.
        if company.service_to and today > company.service_to:
            if company.status != "expired":
                company.status = "expired"
                company.save(update_fields=["status"])

        if company.agreement_status != "completed":
            return redirect("/super-admin/service-agreement/")

        if company.status in {"inactive", "suspended", "expired"}:
            reason = {
                "inactive": "Company inactive",
                "suspended": "Company suspended",
                "expired": "Subscription expired",
            }.get(company.status, "Company inactive")
            if company.status == "expired":
                return redirect(f"/subscription-expired/?reason=Subscription%20expired&detail=Company%20service%20period%20ended.")
            return self._block(request, reason, f"Company status is {company.status}.")

        subscription = (
            CompanySubscription.objects.filter(company=company).select_related("plan").order_by("-end_date", "-created_at").first()
        )
        if not subscription:
            return redirect(f"/subscription-expired/?reason=Subscription%20expired&detail=No%20subscription%20assigned%20to%20this%20company.")

        # Automatic subscription expiry.
        if subscription.end_date and today > subscription.end_date:
            if subscription.status == "active":
                subscription.status = "expired"
                subscription.save(update_fields=["status"])
            if company.status != "expired":
                company.status = "expired"
                company.save(update_fields=["status"])
            return redirect(f"/subscription-expired/?reason=Subscription%20expired&detail=Your%20subscription%20has%20expired.")

        if subscription.status != "active":
            return redirect(
                f"/subscription-expired/?reason=Subscription%20expired&detail=Subscription%20status%20is%20{subscription.status}."
            )

        return self.get_response(request)

    def _expects_json(self, request) -> bool:
        accept = (request.headers.get("Accept") or "").lower()
        xrw = (request.headers.get("X-Requested-With") or "").lower()
        path = (request.path or "").lower()
        return "application/json" in accept or xrw == "xmlhttprequest" or path.startswith("/api/")

    def _block(self, request, reason: str, detail: str):
        if self._expects_json(request):
            return JsonResponse({"success": False, "error": reason, "detail": detail}, status=403)
        try:
            messages.error(request, reason)
        except Exception:
            pass
        return redirect(f"/super-admin/access-blocked/?reason={reason}&detail={detail}")
