from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.http import HttpResponse
from django.template import Template, Context
from django.template.loader import render_to_string
import re

from app_settings.models import EmailDeliveryConfig, EmailTemplate, UiNotification, UserMaster
from candidate_management.models import Candidate, CandidateJobApplication

from .models import (
    EmployeeCodeAssignment,
    OfferLetter,
    OnboardingDocument,
    OnboardingFormTemplate,
    OnboardingInvitation,
    OnboardingSignDocument,
    OnboardingSignatureRequest,
    OnboardingSubmission,
    OnboardingAuditLog,
    OnboardingSigningCertificate,
)
from .utils import log_onboarding_action
import os
from django.core import signing



ONBOARDING_FIELD_CHOICES = [
    ("full_name", "Full Name"),
    ("email", "Email"),
    ("contact_number", "Contact Number"),
    ("date_of_birth", "Date of Birth"),
    ("gender", "Gender"),
    ("address", "Address"),
    ("current_city", "Current City"),
    ("state", "State"),
    ("country", "Country"),
    ("experience", "Previous Experience (years)"),
    ("employment_history", "Employment History"),
    ("skills", "Skills"),
    ("pan", "PAN"),
    ("aadhaar", "Aadhaar"),
    ("pf", "PF Number"),
    ("esic", "ESIC Number"),
]

ONBOARDING_DOCUMENT_CHOICES = [
    ("pan", "PAN Card"),
    ("aadhaar", "Aadhaar Card"),
    ("resume", "Resume"),
    ("photo", "Passport-size Photo"),
    ("address_proof", "Address Proof"),
    ("education_certificate", "Education Certificate"),
    ("experience_letter", "Experience Letter"),
]

ONBOARDING_FIELD_KEYS = [key for key, _label in ONBOARDING_FIELD_CHOICES]
ONBOARDING_DOCUMENT_KEYS = [key for key, _label in ONBOARDING_DOCUMENT_CHOICES]


def _normalized(value: str) -> str:
    return (value or "").strip().lower()


def _final_stage_for_job(job) -> str:
    stages_text = (getattr(job, "stages", "") or "").strip()
    if not stages_text:
        return "Hired"
    stages = [item.strip() for item in stages_text.split(",") if item.strip()]
    return stages[-1] if stages else "Hired"

def _get_current_user(request):
    current_email = (request.session.get("login_user_email") or "").strip()
    return UserMaster.objects.filter(email_id__iexact=current_email).first()


def onboarding_dashboard_view(request):
    return render(request, "onboarding/dashboard.html")


def _candidate_onboarding_stage(candidate: Candidate) -> str:
    if hasattr(candidate, "employee_assignment"):
        return "Employee Code Assigned"

    invitation = (
        candidate.onboarding_invitations.select_related("offer_letter")
        .order_by("-created_at")
        .first()
    )
    if invitation and hasattr(invitation, "submission"):
        submission = invitation.submission
        if submission.status == "approved":
            return "HR Approved"
        if submission.status == "submitted":
            return "Documents Submitted"

    offer = candidate.offer_letters.order_by("-created_at").first()
    if offer:
        if offer.status == "accepted":
            return "Offer Accepted"
        if offer.status == "sent":
            return "Offer Sent"
    return "Finalized"


def onboarding_board_view(request):
    query = (request.GET.get("q") or "").strip()

    base_rows = CandidateJobApplication.objects.select_related("candidate", "job").order_by("-applied_on")
    cards_by_stage = {
        "Finalized": [],
        "Offer Sent": [],
        "Offer Accepted": [],
        "Documents Submitted": [],
        "HR Approved": [],
        "Employee Code Assigned": [],
    }

    for row in base_rows:
        final_stage = _final_stage_for_job(row.job)
        stage = row.stage or ""
        if _normalized(stage) != _normalized(final_stage):
            continue

        candidate = row.candidate
        job_title = (row.job.title if row.job else "") or (candidate.applied_position or "")

        if query:
            qn = query.strip().lower()
            if (
                qn not in (candidate.candidate_id or "").lower()
                and qn not in (candidate.full_name or "").lower()
                and qn not in (candidate.email or "").lower()
                and qn not in (candidate.contact_number or "").lower()
                and qn not in (job_title or "").lower()
            ):
                continue

        onboarding_stage = _candidate_onboarding_stage(candidate)
        submission_id = None
        try:
            invitation = (
                candidate.onboarding_invitations.select_related("offer_letter")
                .order_by("-created_at")
                .first()
            )
            if invitation and hasattr(invitation, "submission"):
                submission_id = invitation.submission.id
        except Exception:
            submission_id = None

        cards_by_stage.setdefault(onboarding_stage, []).append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "email": candidate.email,
                "job_applied": job_title,
                "stage": onboarding_stage,
                "last_updated": candidate.updated_at.strftime("%Y-%m-%d %H:%M"),
                "submission_id": submission_id,
            }
        )

    columns = [{"name": name, "items": cards_by_stage.get(name, [])} for name in cards_by_stage.keys()]
    # "Finalized candidates in onboarding" should exclude completed onboarding (employee code assigned).
    finalized_count = sum(len(col["items"]) for col in columns if col["name"] != "Employee Code Assigned")
    return render(
        request,
        "onboarding/board.html",
        {"columns": columns, "query": query, "finalized_count": finalized_count},
    )


def onboarding_offer_create_view(request, candidate_id: str):
    is_ajax = (request.GET.get("ajax") or "").strip() == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    application = (
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate)
        .order_by("-applied_on")
        .first()
    )
    job_title = ""
    if application and application.job:
        job_title = application.job.title or ""

    email_templates = list(
        EmailTemplate.objects.filter(is_active=True)
        .filter(Q(module__icontains="onboarding") | Q(trigger__icontains="offer") | Q(name__icontains="offer"))
        .order_by("-updated_at")[:200]
    )
    if not email_templates:
        email_templates = list(EmailTemplate.objects.filter(is_active=True).order_by("-updated_at")[:200])

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    smtp_from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

    default_subject = f"Offer Letter - {candidate.full_name}"

    issue_date = timezone.localdate()
    deadline_date = issue_date + timedelta(days=3)

    default_body = (
    f"<p>Dear {candidate.full_name},</p>"
    f"<p>We are pleased to extend an offer for the position of "
    f"<strong>{job_title or 'the role'}</strong> at {getattr(settings, 'ATS_COMPANY_NAME', 'Ultimatix ATS')}.</p>"
    "<p>After careful evaluation, we believe your skills and experience are well aligned "
    "with our team, and we are excited about the opportunity to have you onboard.</p>"
    "<p>Please review the offer details and confirm your response using the options provided below.</p>"
    f"<p>Kindly provide your response by <strong>{deadline_date.strftime('%Y-%m-%d')}</strong>.</p>"
    "<p>If you have any questions or require further clarification, please feel free to contact us.</p>"
    "<p>We look forward to your response and hope to welcome you to our team.</p>"
    "<p>Warm regards,<br>HR Team</p>"
 )

    selected_email_template = None
    selected_email_template_id = (request.POST.get("email_template_id") or request.GET.get("email_template_id") or "").strip()
    if selected_email_template_id:
        selected_email_template = EmailTemplate.objects.filter(id=selected_email_template_id, is_active=True).first()
        if selected_email_template:
            default_subject = (selected_email_template.subject or "").strip() or default_subject
            default_body = (selected_email_template.body or "").strip() or default_body
    else:
        # If user didn't choose a template, prefer the standard onboarding offer trigger.
        selected_email_template = (
            EmailTemplate.objects.filter(is_active=True, trigger__iexact="onboarding_offer_send").order_by("-updated_at").first()
        )
        if selected_email_template:
            selected_email_template_id = str(selected_email_template.id)
            default_subject = (selected_email_template.subject or "").strip() or default_subject
            default_body = (selected_email_template.body or "").strip() or default_body

    def _build_offer_template_context(extra: dict | None = None) -> dict:
        ctx = {
            "company_name": getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS"),
            "candidate_name": candidate.full_name or "Candidate",
            "candidate_id": candidate.candidate_id,
            "candidate_email": candidate.email or "",
            "job_title": job_title or "",
            "offer_id": "",
            "offer_date": timezone.localdate().strftime("%Y-%m-%d"),
            "department": getattr(application.job, "department", "") if application and application.job else "",
            "work_location": getattr(application.job, "location", "") if application and application.job else "",
            "employment_type": getattr(application.job, "employment_type", "") if application and application.job else "",
            "reporting_manager": "",
            "joining_date": "",
            "ctc_annual": "",
            "base_pay": "",
            "benefits": "",
            "hr_email": "",
            "portal_url": request.build_absolute_uri("/candidate-portal/"),
            "offer_view_url": "#",
            "accept_url": "#",
            "reject_url": "#",
            "onboarding_url": "#",
        }
        if extra:
            ctx.update(extra)
        return ctx

    def _render_template_text(value: str, ctx: dict) -> str:
        if not (value or "").strip():
            return ""
        try:
            return Template(str(value)).render(Context(ctx, autoescape=True))
        except Exception:
            return str(value)

    def _looks_like_full_html(html: str) -> bool:
        h = (html or "").lstrip().lower()
        return h.startswith("<!doctype") or "<html" in h[:500] or "<head" in h[:500] or "<body" in h[:500]

    def _looks_like_email_safe_document(html: str) -> bool:
        h = (html or "").lower()
        # Heuristic: table-based email layouts include role="presentation".
        if 'role="presentation"' not in h and "role='presentation'" not in h:
            return False
        # Avoid modern CSS patterns that commonly break in email clients.
        if "position:fixed" in h or "display:grid" in h:
            return False
        return True

    def _extract_body_inner(full_html: str) -> str:
        """
        Email templates pasted from the UI often include full HTML documents with CSS/layout patterns
        (grid/flex/fixed) that render poorly in email clients. We extract only the <body> inner HTML
        and drop <style> blocks to keep the email client-friendly wrapper.
        """
        html = str(full_html or "")
        m = re.search(r"<body[^>]*>(?P<body>.*)</body>", html, flags=re.IGNORECASE | re.DOTALL)
        inner = m.group("body") if m else html
        # Drop style blocks (many clients strip/partially support them and they can break layout)
        inner = re.sub(r"<style[^>]*>.*?</style>", "", inner, flags=re.IGNORECASE | re.DOTALL)
        # Drop obvious "sticky" bars that rely on position:fixed
        inner = re.sub(
            r"<div[^>]*(?:id|class)=(?:\"|')[^\"']*sticky[^\"']*(?:\"|')[^>]*>.*?</div>",
            "",
            inner,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return inner.strip()

    if request.method == "GET" and is_ajax:
        return JsonResponse(
            {
                "ok": True,
                "candidate": {
                    "candidate_id": candidate.candidate_id,
                    "full_name": candidate.full_name,
                    "email": candidate.email,
                },
                "job_title": job_title,
                "email_templates": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "module": t.module,
                        "trigger": t.trigger,
                    }
                    for t in email_templates
                ],
                "selected_email_template_id": selected_email_template_id,
                "default_subject": default_subject,
                "default_body": default_body,
                "smtp_from_email": smtp_from_email,
                "to_email": candidate.email,
            }
        )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action == "preview_offer":
            subject = (request.POST.get("subject") or "").strip() or default_subject
            body_html = (request.POST.get("body_html") or "").strip() or default_body
            ctx = _build_offer_template_context(
                {
                    "subject": subject,
                }
            )
            rendered_body = _render_template_text(body_html, ctx)

            if _looks_like_full_html(rendered_body) and _looks_like_email_safe_document(rendered_body):
                preview_html = rendered_body
            else:
                snippet = _extract_body_inner(rendered_body) if _looks_like_full_html(rendered_body) else rendered_body
                preview_html = render_to_string(
                    "onboarding/emails/offer_letter.html",
                    {
                        "candidate": candidate,
                        "offer": None,
                        "body_html": snippet,
                        "offer_view_url": ctx["offer_view_url"],
                        "accept_url": ctx["accept_url"],
                        "reject_url": ctx["reject_url"],
                        "onboarding_url": ctx["onboarding_url"],
                        "company_name": ctx["company_name"],
                        "job_title": ctx.get("job_title", ""),
                        "department": ctx.get("department", ""),
                        "work_location": ctx.get("work_location", ""),
                        "employment_type": ctx.get("employment_type", ""),
                        "reporting_manager": ctx.get("reporting_manager", ""),
                        "joining_date": ctx.get("joining_date", ""),
                        "ctc_annual": ctx.get("ctc_annual", ""),
                        "base_pay": ctx.get("base_pay", ""),
                        "benefits": ctx.get("benefits", ""),
                        "hr_email": ctx.get("hr_email", ""),
                    },
                )
            return JsonResponse({"ok": True, "preview_html": preview_html})

        if action != "send_offer":
            if is_ajax:
                return JsonResponse({"ok": False, "message": "Invalid action."}, status=400)
            messages.error(request, "Invalid action.")
            return redirect(request.path)

        subject_template = (request.POST.get("subject") or "").strip() or default_subject
        body_template = (request.POST.get("body_html") or "").strip() or default_body
        form_template = None
        if selected_email_template:
            form_template = (
                OnboardingFormTemplate.objects.filter(is_active=True, offer_email_template=selected_email_template)
                .order_by("-updated_at")
                .first()
            )
        if not form_template:
            form_template = OnboardingFormTemplate.objects.filter(is_active=True).order_by("-updated_at").first()

        if not selected_email_template_id and form_template and form_template.offer_email_template_id:
            selected_email_template = EmailTemplate.objects.filter(
                id=form_template.offer_email_template_id, is_active=True
            ).first()
            if selected_email_template:
                if subject_template == default_subject:
                    subject_template = (selected_email_template.subject or "").strip() or subject_template
                if body_template == default_body:
                    body_template = (selected_email_template.body or "").strip() or body_template

        created_by = (request.session.get("login_user_name") or "").strip()

        with transaction.atomic():
            offer = OfferLetter(
                candidate=candidate,
                application=application,
                subject=subject_template,
                body_html=body_template,
                status="sent",
                sent_to_email=candidate.email,
                sent_at=timezone.now(),
                created_by=created_by,
            )
            offer.ensure_token()
            offer.save()

            invite = OnboardingInvitation(
                candidate=candidate,
                offer_letter=offer,
                form_template=form_template,
                status="pending",
                created_by=created_by,
            )
            invite.ensure_token()
            invite.save()

        accept_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/accept/?as=candidate")
        reject_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/reject/?as=candidate")
        offer_view_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/?as=candidate")
        onboarding_url = request.build_absolute_uri(f"/candidate-portal/onboarding/{invite.token}/")

        ctx = _build_offer_template_context(
            {
                "offer_id": str(offer.id),
                "offer_date": timezone.localdate().strftime("%Y-%m-%d"),
                "offer_view_url": offer_view_url,
                "accept_url": accept_url,
                "reject_url": reject_url,
                "onboarding_url": onboarding_url,
            }
        )
        subject = (_render_template_text(subject_template, ctx)).strip() or subject_template
        rendered_body = _render_template_text(body_template, ctx)

        if _looks_like_full_html(rendered_body) and _looks_like_email_safe_document(rendered_body):
            html_body = rendered_body
        else:
            snippet = _extract_body_inner(rendered_body) if _looks_like_full_html(rendered_body) else rendered_body
            html_body = render_to_string(
                "onboarding/emails/offer_letter.html",
                {
                    "candidate": candidate,
                    "offer": offer,
                    "body_html": snippet,
                    "offer_view_url": offer_view_url,
                    "accept_url": accept_url,
                    "reject_url": reject_url,
                    "onboarding_url": onboarding_url,
                    "company_name": ctx["company_name"],
                    "job_title": ctx.get("job_title", ""),
                    "department": ctx.get("department", ""),
                    "work_location": ctx.get("work_location", ""),
                    "employment_type": ctx.get("employment_type", ""),
                    "reporting_manager": ctx.get("reporting_manager", ""),
                    "joining_date": ctx.get("joining_date", ""),
                    "ctc_annual": ctx.get("ctc_annual", ""),
                    "base_pay": ctx.get("base_pay", ""),
                    "benefits": ctx.get("benefits", ""),
                    "hr_email": ctx.get("hr_email", ""),
                },
            )

        text_body = (
            f"Dear {candidate.full_name},\n\n"
            f"View offer: {offer_view_url}\n\n"
            f"Please respond to your offer:\n"
            f"Accept: {accept_url}\n"
            f"Reject: {reject_url}\n\n"
            f"Onboarding link: {onboarding_url}\n"
        )

        email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
        from_email = (
            (getattr(email_config, "from_email", "") or "").strip()
            or (getattr(email_config, "username", "") or "").strip()
            or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        )

        connection = None
        host = (getattr(email_config, "host", "") or "").strip() if email_config else ""
        if email_config and getattr(email_config, "smtp_enabled", False):
            port = int(getattr(email_config, "port", 587) or 587)
            username = (getattr(email_config, "username", "") or "").strip()
            password = (getattr(email_config, "password", "") or "")
            password = " ".join(str(password).split()).replace(" ", "")
            use_tls = bool(getattr(email_config, "use_tls", True))

            if host:
                connection = get_connection(
                    backend="django.core.mail.backends.smtp.EmailBackend",
                    host=host,
                    port=port,
                    username=username or None,
                    password=password or None,
                    use_tls=use_tls,
                    fail_silently=False,
                )
        if not connection:
            offer.status = "draft"
            offer.sent_at = None
            offer.sent_to_email = ""
            offer.save(update_fields=["status", "sent_at", "sent_to_email", "updated_at"])
            message = "SMTP email is not configured. Enable SMTP and set Host/From Email in Settings -> Integration, then resend the offer."
            if is_ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return redirect(request.path)

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email or None,
            to=[candidate.email],
            connection=connection,
        )
        email.attach_alternative(html_body, "text/html")
        try:
            email.send(fail_silently=False)
        except Exception:
            offer.status = "draft"
            offer.sent_at = None
            offer.sent_to_email = ""
            offer.save(update_fields=["status", "sent_at", "sent_to_email", "updated_at"])
            message = "Offer saved as draft, but email could not be sent. Please check SMTP settings."
            if is_ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return redirect(request.path)

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=candidate,
            action="OFFER_SENT",
            details={
                "subject": subject,
                "offer_id": offer.id
            },
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        if is_ajax:
            return JsonResponse({"ok": True, "redirect_url": "/onboarding/board/"})
        messages.success(request, f"Offer letter sent to {candidate.email}.")
        return redirect("/onboarding/board/")

    return render(
        request,
        "onboarding/offer_create.html",
        {
            "candidate": candidate,
            "application": application,
            "job_title": job_title,
            "email_templates": email_templates,
            "selected_email_template_id": selected_email_template_id,
            "default_subject": default_subject,
            "default_body": default_body,
            "smtp_from_email": smtp_from_email,
            "to_email": candidate.email,
        },
    )


def onboarding_form_templates_view(request):
    return redirect("/settings/email-templates/")


def onboarding_document_request_view(request, candidate_id: str):
    is_ajax = (request.GET.get("ajax") or "").strip() == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)

    offer = candidate.offer_letters.order_by("-created_at").first()
    if not offer or offer.status != "accepted":
        message = "Document request is available only after the offer is accepted."
        if is_ajax:
            return JsonResponse({"ok": False, "message": message}, status=400)
        messages.error(request, message)
        return redirect("/onboarding/board/")

    invitation = (
        OnboardingInvitation.objects.select_related("offer_letter", "form_template")
        .filter(candidate=candidate)
        .order_by("-created_at")
        .first()
    )
    if not invitation:
        form_template = OnboardingFormTemplate.objects.filter(is_active=True).order_by("-updated_at").first()
        invitation = OnboardingInvitation(candidate=candidate, offer_letter=offer, form_template=form_template, status="pending")
        invitation.ensure_token()
        invitation.save()
    elif not (invitation.token or "").strip():
        invitation.ensure_token()
        invitation.save(update_fields=["token", "expires_at", "updated_at"])

    def _candidate_magic_portal_url(req, email: str, next_path: str = "/candidate-portal/") -> str:
        if not (email or "").strip():
            return next_path or "/candidate-portal/"
        if not next_path or not next_path.startswith("/candidate-portal/"):
            next_path = "/candidate-portal/"
        signer = signing.TimestampSigner(salt="candidate_portal_magic")
        token = signer.sign((email or "").strip())
        return req.build_absolute_uri(f"/candidate-portal/magic/{token}/?next={next_path}")

    # Send a magic-link that logs the candidate in and redirects directly to the upload form.
    onboarding_form_path = f"/candidate-portal/onboarding/{invitation.token}/form/"
    onboarding_url = _candidate_magic_portal_url(request, candidate.email or "", onboarding_form_path)
    document_requirements = []
    try:
        has_override = isinstance(getattr(invitation, "document_requirements_override", None), list) and bool(invitation.document_requirements_override)
        if has_override:
            document_requirements = list(invitation.document_requirements_override or [])
        elif invitation.form_template and isinstance(getattr(invitation.form_template, "document_requirements", None), list):
            document_requirements = list(invitation.form_template.document_requirements or [])
    except Exception:
        document_requirements = []
        has_override = False

    document_options = [
        {"key": "passport_photo", "label": "Affix Recent Passport Size Photograph (Blue Background only)"},
        {"key": "residency_proof", "label": "Please attach residency proof"},
        {"key": "pan_card_copy", "label": "Attach Copy of PAN Card"},
        {"key": "aadhaar_card_copy_pdf", "label": "Attach full copy of Aadhar Card with front and back (In PDF only)"},
        {"key": "passport_copy", "label": "Attach Copy of Passport"},
        {"key": "educational_qualification", "label": "Educational Qualification"},
        {"key": "cancelled_cheque_copy", "label": "Attach copy of cancelled cheque"},
    ]

    email_templates = list(
        EmailTemplate.objects.filter(is_active=True)
        .filter(
            Q(trigger__iexact="onboarding_document_request")
            | Q(trigger__icontains="onboarding_document")
            | Q(module__icontains="onboarding")
            | Q(name__icontains="document")
        )
        .order_by("-updated_at")[:200]
    )
    if not email_templates:
        email_templates = list(EmailTemplate.objects.filter(is_active=True).order_by("-updated_at")[:200])

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    smtp_from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

    selected_email_template = None
    selected_email_template_id = (request.GET.get("email_template_id") or "").strip()
    if selected_email_template_id:
        selected_email_template = EmailTemplate.objects.filter(id=selected_email_template_id, is_active=True).first()
        if not selected_email_template:
            selected_email_template_id = ""
    if not selected_email_template:
        selected_email_template = EmailTemplate.objects.filter(
            is_active=True, trigger__iexact="onboarding_document_request"
        ).order_by("-updated_at").first()
        selected_email_template_id = str(selected_email_template.id) if selected_email_template else ""

    default_subject = f"Action Required: Upload Onboarding Documents - {candidate.full_name}"
    default_body = (
        f"<p>Dear {candidate.full_name},</p>"
        "<p>Congratulations again on accepting the offer. To proceed with onboarding, please upload the required documents using the link below.</p>"
        f"<p><a href=\"{onboarding_url}\" target=\"_blank\" rel=\"noopener noreferrer\">Upload Documents</a></p>"
        + "<p>Thank you,<br>HR Team</p>"
    )

    if selected_email_template:
        default_subject = (selected_email_template.subject or "").strip() or default_subject
        default_body = (selected_email_template.body or "").strip() or default_body

    def _render_template_text(value: str, ctx: dict) -> str:
        if not (value or "").strip():
            return ""
        try:
            return Template(str(value)).render(Context(ctx, autoescape=True))
        except Exception:
            return str(value)

    def _looks_like_full_html(html: str) -> bool:
        h = (html or "").lstrip().lower()
        return h.startswith("<!doctype") or "<html" in h[:500] or "<head" in h[:500] or "<body" in h[:500]

    def _looks_like_email_safe_document(html: str) -> bool:
        h = (html or "").lower()
        if 'role="presentation"' not in h and "role='presentation'" not in h:
            return False
        if "position:fixed" in h or "display:grid" in h:
            return False
        return True

    def _extract_body_inner(full_html: str) -> str:
        html = str(full_html or "")
        m = re.search(r"<body[^>]*>(?P<body>.*)</body>", html, flags=re.IGNORECASE | re.DOTALL)
        inner = m.group("body") if m else html
        inner = re.sub(r"<style[^>]*>.*?</style>", "", inner, flags=re.IGNORECASE | re.DOTALL)
        inner = re.sub(
            r"<div[^>]*(?:id|class)=(?:\"|')[^\"']*sticky[^\"']*(?:\"|')[^>]*>.*?</div>",
            "",
            inner,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return inner.strip()

    ctx = {
        "company_name": getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS"),
        "candidate_name": candidate.full_name or "Candidate",
        "candidate_id": candidate.candidate_id,
        "candidate_email": candidate.email or "",
        "portal_url": request.build_absolute_uri("/candidate-portal/"),
        "onboarding_url": onboarding_url,
        "document_requirements": document_requirements,
    }

    if request.method == "GET" and is_ajax:
        return JsonResponse(
            {
                "ok": True,
                "candidate": {
                    "candidate_id": candidate.candidate_id,
                    "full_name": candidate.full_name,
                    "email": candidate.email,
                },
                "onboarding_url": onboarding_url,
                "document_requirements": document_requirements,
                "available_documents": document_options,
                "document_mode": "manual" if has_override else "default",
                "email_templates": [
                    {"id": t.id, "name": t.name, "module": t.module, "trigger": t.trigger} for t in email_templates
                ],
                "selected_email_template_id": selected_email_template_id,
                "default_subject": default_subject,
                "default_body": default_body,
                "smtp_from_email": smtp_from_email,
                "to_email": candidate.email,
            }
        )

    if request.method == "POST" and is_ajax:
        action = (request.POST.get("action") or "").strip()
        template_id = (request.POST.get("email_template_id") or "").strip()
        subject_template = (request.POST.get("subject") or "").strip() or default_subject
        body_template = (request.POST.get("body_html") or "").strip() or default_body
        document_mode = (request.POST.get("document_mode") or "").strip().lower() or "default"
        selected_docs_raw = (request.POST.get("document_requirements") or "").strip()
        selected_docs = []
        if selected_docs_raw:
            try:
                import json

                parsed = json.loads(selected_docs_raw)
                if isinstance(parsed, list):
                    selected_docs = [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                selected_docs = [p.strip() for p in selected_docs_raw.split(",") if p.strip()]

        if document_mode == "manual":
            allowed = {d["key"] for d in document_options}
            selected_docs = [d for d in selected_docs if d in allowed]
            invitation.document_requirements_override = selected_docs
            invitation.save(update_fields=["document_requirements_override", "updated_at"])
            ctx["document_requirements"] = selected_docs
            document_requirements = selected_docs
        else:
            if getattr(invitation, "document_requirements_override", None):
                invitation.document_requirements_override = []
                invitation.save(update_fields=["document_requirements_override", "updated_at"])

        if template_id:
            selected = EmailTemplate.objects.filter(id=template_id, is_active=True).first()
            if selected:
                if not (request.POST.get("subject") or "").strip():
                    subject_template = (selected.subject or "").strip() or subject_template
                if not (request.POST.get("body_html") or "").strip():
                    body_template = (selected.body or "").strip() or body_template

        rendered_subject = (_render_template_text(subject_template, ctx)).strip() or subject_template
        rendered_body = _render_template_text(body_template, ctx)

        if _looks_like_full_html(rendered_body) and _looks_like_email_safe_document(rendered_body):
            html_body = rendered_body
        else:
            snippet = _extract_body_inner(rendered_body) if _looks_like_full_html(rendered_body) else rendered_body
            html_body = render_to_string(
                "onboarding/emails/document_request.html",
                {
                    "candidate": candidate,
                    "onboarding_url": onboarding_url,
                    "document_requirements": document_requirements,
                    "body_html": snippet,
                    "company_name": ctx["company_name"],
                },
            )

        if action == "preview_request":
            return JsonResponse({"ok": True, "preview_html": html_body})

        if action != "send_request":
            return JsonResponse({"ok": False, "message": "Invalid action."}, status=400)

        connection = None
        host = (getattr(email_config, "host", "") or "").strip() if email_config else ""
        if email_config and getattr(email_config, "smtp_enabled", False):
            port = int(getattr(email_config, "port", 587) or 587)
            username = (getattr(email_config, "username", "") or "").strip()
            password = (getattr(email_config, "password", "") or "")
            password = " ".join(str(password).split()).replace(" ", "")
            use_tls = bool(getattr(email_config, "use_tls", True))

            if host:
                connection = get_connection(
                    backend="django.core.mail.backends.smtp.EmailBackend",
                    host=host,
                    port=port,
                    username=username or None,
                    password=password or None,
                    use_tls=use_tls,
                    fail_silently=False,
                )

        if not connection:
            return JsonResponse(
                {
                    "ok": False,
                    "message": "SMTP email is not configured. Enable SMTP in Settings -> Integration to send document requests.",
                },
                status=400,
            )

        text_body = (
            f"Dear {candidate.full_name},\n\n"
            "Please upload your onboarding documents using the link below:\n"
            f"{onboarding_url}\n"
        )

        email = EmailMultiAlternatives(
            subject=rendered_subject,
            body=text_body,
            from_email=(smtp_from_email or None),
            to=[candidate.email],
            connection=connection,
        )
        email.attach_alternative(html_body, "text/html")
        try:
            email.send(fail_silently=False)
        except Exception:
            return JsonResponse(
                {"ok": False, "message": "Email could not be sent. Please check SMTP settings."},
                status=400,
            )

        try:
            UiNotification.objects.create(
                recipient_name=candidate.email or "",
                title="Onboarding Documents Requested",
                message="Please upload your onboarding documents using the shared link.",
                link="/candidate-portal/",
                source="onboarding",
                created_by=(request.session.get("login_user_name") or "").strip(),
            )
        except Exception:
            pass

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=candidate,
            action="DOCUMENT_REQUEST_SENT",
            details={"subject": rendered_subject, "onboarding_url": onboarding_url, "template_id": template_id or None},
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT"),
        )

        return JsonResponse({"ok": True, "redirect_url": "/onboarding/board/"})

    messages.error(request, "Invalid request.")
    return redirect("/onboarding/board/")


def onboarding_approvals_view(request):
    query = (request.GET.get("q") or "").strip()
    submissions = (
        OnboardingSubmission.objects.select_related("invitation__candidate")
        .filter(status="submitted")
        .order_by("-submitted_at", "-updated_at")
    )
    if query:
        submissions = submissions.filter(
            Q(invitation__candidate__full_name__icontains=query)
            | Q(invitation__candidate__candidate_id__icontains=query)
            | Q(invitation__candidate__email__icontains=query)
        )
    rows = list(submissions[:250])
    return render(request, "onboarding/approvals.html", {"submissions": rows, "query": query})


def onboarding_submission_detail_view(request, submission_id: int):
    submission = get_object_or_404(
        OnboardingSubmission.objects.select_related("invitation__candidate", "invitation__offer_letter", "invitation__form_template"),
        id=submission_id,
    )
    documents = list(submission.documents.all())
    signature_request = getattr(submission, "signature_request", None)
    signature_request_pdf_url = ""
    try:
        if signature_request and getattr(signature_request, "document_pdf", None) and getattr(signature_request.document_pdf, "name", ""):
            signature_request_pdf_url = signature_request.document_pdf.url
    except Exception:
        signature_request_pdf_url = ""
    sign_documents = list(signature_request.documents.all()) if signature_request else []
    sign_documents_json = []
    for item in sign_documents:
        sign_documents_json.append(
            {
                "id": item.id,
                "title": item.title,
                "document_pdf": item.document_pdf.url if getattr(item, "document_pdf", None) and getattr(item.document_pdf, "name", "") else "",
                "signed_pdf": item.signed_pdf.url if getattr(item, "signed_pdf", None) and getattr(item.signed_pdf, "name", "") else "",
                "page_number": item.page_number,
                "position_x": float(item.position_x or 0),
                "position_y": float(item.position_y or 0),
                "width": float(item.width or 0),
                "height": float(item.height or 0),
                "status": item.status,
            }
        )
    return render(
        request,
        "onboarding/submission_detail.html",
        {
            "submission": submission,
            "documents": documents,
            "signature_request": signature_request,
            "signature_request_pdf_url": signature_request_pdf_url,
            "sign_documents": sign_documents,
            "sign_documents_json": sign_documents_json,
        },
    )


def onboarding_signature_block_place_view(request, submission_id: int):
    submission = get_object_or_404(
        OnboardingSubmission.objects.select_related("invitation__candidate"),
        id=submission_id,
    )
    signature_request = getattr(submission, "signature_request", None)
    if not signature_request or not getattr(signature_request, "document_pdf", None):
        messages.error(request, "Upload the offer letter PDF first.")
        return redirect(f"/onboarding/approvals/{submission_id}/")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action != "save_signature_block":
            messages.error(request, "Invalid action.")
            return redirect(request.path)

        try:
            position_x = float((request.POST.get("position_x") or "").strip())
            position_y = float((request.POST.get("position_y") or "").strip())
            width = float((request.POST.get("width") or "").strip() or signature_request.width)
            height = float((request.POST.get("height") or "").strip() or signature_request.height)
        except Exception:
            messages.error(request, "Invalid signature position.")
            return redirect(request.path)

        # For now, lock to page 1 to match your requirement.
        signature_request.page_number = 1
        signature_request.position_x = max(0.0, min(100.0, position_x))
        signature_request.position_y = max(0.0, min(100.0, position_y))
        signature_request.width = max(20.0, width)
        signature_request.height = max(20.0, height)
        signature_request.save(update_fields=["page_number", "position_x", "position_y", "width", "height", "updated_at"])
        
        log_onboarding_action(
            user=_get_current_user(request),
            candidate=submission.invitation.candidate,
            action="SIGNATURE_BLOCK_PLACED",
            details={
                "submission_id": submission.id,
                "x": position_x,
                "y": position_y
            },
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        messages.success(request, "Signature block placed.")
        return redirect(f"/onboarding/approvals/{submission_id}/")

    return render(
        request,
        "onboarding/signature_block_place.html",
        {
            "submission": submission,
            "candidate": submission.invitation.candidate,
            "signature_request": signature_request,
        },
    )


def onboarding_submission_action_view(request, submission_id: int):
    submission = get_object_or_404(
        OnboardingSubmission.objects.select_related("invitation__candidate"),
        id=submission_id,
    )
    if request.method != "POST":
        return redirect(f"/onboarding/approvals/{submission_id}/")

    action = (request.POST.get("action") or "").strip().lower()
    actor = (request.session.get("login_user_name") or "").strip()

    if action == "approve_submission":
        submission.status = "approved"
        submission.approved_by = actor
        submission.approved_at = timezone.now()
        submission.rejection_reason = ""
        submission.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason", "updated_at"])
        submission.invitation.status = "approved"
        submission.invitation.save(update_fields=["status", "updated_at"])

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=submission.invitation.candidate,
            action="SUBMISSION_APPROVED",
            details={"submission_id": submission.id},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        # Create signature request (required before employee code assignment).
        signature_request = getattr(submission, "signature_request", None)
        if not signature_request:
            signature_request = OnboardingSignatureRequest(submission=submission)
            signature_request.ensure_token()
            signature_request.save()
        else:
            signature_request.ensure_token()
            signature_request.save(update_fields=["token", "updated_at"])

        messages.success(request, "Onboarding submission approved. Upload the offer letter PDF for signature.")
        return redirect(f"/onboarding/approvals/{submission.id}/")

    if action == "upload_sign_document":
        signature_request = getattr(submission, "signature_request", None)
        if not signature_request:
            messages.error(request, "Approve the submission first.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        uploads = request.FILES.getlist("document_pdfs") or []
        if not uploads:
            upload = request.FILES.get("document_pdf")
            if upload:
                uploads = [upload]

        if not uploads:
            messages.error(request, "Please upload one or more PDF files.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        created = 0
        for upload in uploads:
            name = (upload.name or "").lower()
            if not name.endswith(".pdf"):
                continue
            title = (upload.name or "Document").rsplit(".", 1)[0][:150]
            OnboardingSignDocument.objects.create(
                signature_request=signature_request,
                title=title or "Document",
                document_pdf=upload,
            )
            created += 1

        if created <= 0:
            messages.error(request, "Only PDF files are supported.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        # Keep legacy fields in sync with the most recent uploaded document for older screens.
        latest_doc = signature_request.documents.order_by("-created_at").first()
        if latest_doc and not signature_request.document_pdf:
            signature_request.document_pdf = latest_doc.document_pdf
            signature_request.save(update_fields=["document_pdf", "updated_at"])

        signature_request.signed_pdf = ""
        signature_request.status = "pending"
        signature_request.signature_data = ""
        signature_request.signed_at = None
        signature_request.ensure_token()
        signature_request.save(update_fields=["signed_pdf", "status", "signature_data", "signed_at", "token", "updated_at"])

        messages.success(request, f"{created} document(s) uploaded. Place signature blocks, then send for signature.")
        
        log_onboarding_action(
            user=_get_current_user(request),
            candidate=submission.invitation.candidate,
            action="SIGNATURE_DOC_UPLOADED",
            details={"submission_id": submission.id, "count": created},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return redirect(f"/onboarding/approvals/{submission.id}/")

    if action == "final_approve_signature":
        signature_request = getattr(submission, "signature_request", None)
        if not signature_request or signature_request.status != "signed":
            messages.error(request, "Candidate signature is not completed yet.")
            return redirect(f"/onboarding/approvals/{submission_id}/")
        signature_request.status = "final_approved"
        signature_request.final_approved_by = actor
        signature_request.final_approved_at = timezone.now()
        signature_request.rejection_reason = ""
        signature_request.save(update_fields=["status", "final_approved_by", "final_approved_at", "rejection_reason", "updated_at"])
        
        log_onboarding_action(
            user=_get_current_user(request),
            candidate=submission.invitation.candidate,
            action="SIGNATURE_FINAL_APPROVED",
            details={"submission_id": submission.id},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        messages.success(request, "Signature final approved.")
        return redirect(f"/onboarding/employee-code/{submission.id}/")

    if action == "send_signature_request":
        signature_request = getattr(submission, "signature_request", None)
        if not signature_request:
            messages.error(request, "Approve the submission first.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        docs = list(signature_request.documents.all())
        if not docs:
            # fallback legacy single document
            if not getattr(signature_request, "document_pdf", None):
                messages.error(request, "Upload at least one PDF first.")
                return redirect(f"/onboarding/approvals/{submission_id}/")

        # Require block placement for every uploaded doc before sending.
        pending_blocks = [d for d in docs if not (d.page_number and d.position_x and d.position_y)]
        if pending_blocks:
            messages.error(request, "Please place and save the signature block for all uploaded documents before sending.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        candidate = submission.invitation.candidate
        sign_url = request.build_absolute_uri(f"/candidate-portal/sign/{signature_request.token}/?as=candidate")

        email_sent = False
        try:
            email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
            from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

            connection = None
            if email_config and getattr(email_config, "smtp_enabled", False):
                host = (getattr(email_config, "host", "") or "").strip()
                port = int(getattr(email_config, "port", 587) or 587)
                username = (getattr(email_config, "username", "") or "").strip()
                password = (getattr(email_config, "password", "") or "").strip()
                use_tls = bool(getattr(email_config, "use_tls", True))
                if host:
                    connection = get_connection(
                        backend="django.core.mail.backends.smtp.EmailBackend",
                        host=host,
                        port=port,
                        username=username or None,
                        password=password or None,
                        use_tls=use_tls,
                        fail_silently=False,
                    )

            if connection:
                subject = f"Signature Required - {getattr(settings, 'ATS_COMPANY_NAME', 'Ultimatix ATS')}"
                doc_section = ""
                if docs:
                    doc_section = "Documents:\n" + "\n".join([f"- {d.title}" for d in docs]) + "\n\n"
                text_body = (
                    f"Dear {candidate.full_name},\n\n"
                    "Your onboarding documents have been approved. Please sign the required document(s) to proceed.\n\n"
                    f"{doc_section}"
                    f"Sign link: {sign_url}\n\n"
                    f"Regards,\n{getattr(settings, 'ATS_COMPANY_NAME', 'HR Team')}"
                )
                html_body = render(
                    request,
                    "onboarding/emails/sign_request.html",
                    {
                        "candidate": candidate,
                        "sign_url": sign_url,
                        "company_name": getattr(settings, "ATS_COMPANY_NAME", "Company"),
                    },
                ).content.decode("utf-8")

                email = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=from_email or None,
                    to=[candidate.email],
                    connection=connection,
                )
                email.attach_alternative(html_body, "text/html")
                email.send(fail_silently=False)
                email_sent = True
            else:
                messages.warning(request, "SMTP is not configured. Candidate will be notified in the Candidate Portal.")
        except Exception:
            # Do not abort the flow; still create the portal notification so the candidate
            # can see the request without relying on email delivery.
            messages.warning(request, "Signature request saved, but email could not be sent right now.")

        try:
            UiNotification.objects.create(
                recipient_name=(candidate.email or "").strip().lower(),
                title="Signature Required",
                message="Please sign your onboarding document(s) to continue.",
                link=f"/candidate-portal/sign/{signature_request.token}/?as=candidate",
                source="signature",
                created_by=actor or "system",
            )
        except Exception:
            pass

        if email_sent:
            messages.success(request, "Signature request sent to candidate.")
        else:
            messages.success(request, "Signature request created. Candidate can see it in Candidate Portal notifications.")

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=submission.invitation.candidate,
            action="SIGNATURE_REQUEST_SENT",
            details={"submission_id": submission.id, "email_sent": email_sent},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return redirect(f"/onboarding/approvals/{submission_id}/")

    if action == "save_signature_block":
        signature_request = getattr(submission, "signature_request", None)
        if not signature_request:
            messages.error(request, "Approve the submission first.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        try:
            page_number = int((request.POST.get("page_number") or "1").strip() or 1)
            position_x = float((request.POST.get("position_x") or "").strip())
            position_y = float((request.POST.get("position_y") or "").strip())
            width = float((request.POST.get("width") or "").strip() or signature_request.width)
            height = float((request.POST.get("height") or "").strip() or signature_request.height)
            doc_id = int((request.POST.get("doc_id") or "").strip() or 0)
        except Exception:
            messages.error(request, "Invalid signature position.")
            return redirect(f"/onboarding/approvals/{submission_id}/")

        doc = None
        if doc_id:
            doc = OnboardingSignDocument.objects.filter(id=doc_id, signature_request=signature_request).first()
        if doc:
            doc.page_number = max(1, page_number)
            doc.position_x = max(0.0, min(100.0, position_x))
            doc.position_y = max(0.0, min(100.0, position_y))
            doc.width = max(20.0, width)
            doc.height = max(20.0, height)
            doc.save(update_fields=["page_number", "position_x", "position_y", "width", "height", "updated_at"])
        else:
            # fallback legacy
            signature_request.page_number = max(1, page_number)
            signature_request.position_x = max(0.0, min(100.0, position_x))
            signature_request.position_y = max(0.0, min(100.0, position_y))
            signature_request.width = max(20.0, width)
            signature_request.height = max(20.0, height)
            signature_request.save(update_fields=["page_number", "position_x", "position_y", "width", "height", "updated_at"])
        messages.success(request, "Signature block saved.")
        return redirect(f"/onboarding/approvals/{submission_id}/")

    if action == "reject_submission":
        reason = (request.POST.get("rejection_reason") or "").strip()
        if not reason:
            messages.error(request, "Rejection reason is required.")
            return redirect(f"/onboarding/approvals/{submission_id}/")
        submission.status = "rejected"
        submission.rejection_reason = reason
        submission.approved_by = ""
        submission.approved_at = None
        submission.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at", "updated_at"])
        submission.invitation.status = "rejected"
        submission.invitation.save(update_fields=["status", "updated_at"])
        candidate = submission.invitation.candidate

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=candidate,
            action="SUBMISSION_REJECTED",
            details={"submission_id": submission.id, "reason": reason},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        try:
            email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
            from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

            connection = None
            if email_config and getattr(email_config, "smtp_enabled", False):
                host = (getattr(email_config, "host", "") or "").strip()
                port = int(getattr(email_config, "port", 587) or 587)
                username = (getattr(email_config, "username", "") or "").strip()
                password = (getattr(email_config, "password", "") or "").strip()
                use_tls = bool(getattr(email_config, "use_tls", True))
                if host:
                    connection = get_connection(
                        backend="django.core.mail.backends.smtp.EmailBackend",
                        host=host,
                        port=port,
                        username=username or None,
                        password=password or None,
                        use_tls=use_tls,
                        fail_silently=False,
                    )

            register_url = request.build_absolute_uri(f"/candidate-portal/onboarding/{submission.invitation.token}/")
            upload_url = request.build_absolute_uri(f"/candidate-portal/onboarding/{submission.invitation.token}/form/")

            subject = f"Onboarding Documents Rejected - {candidate.full_name}"
            text_body = (
                f"Dear {candidate.full_name},\n\n"
                f"Your onboarding documents were rejected.\n\n"
                f"Reason:\n{reason}\n\n"
                f"Please re-upload your documents using the link below:\n{upload_url}\n\n"
                f"If you haven't registered yet, use:\n{register_url}\n\n"
                f"Regards,\n{getattr(settings, 'ATS_COMPANY_NAME', 'HR Team')}"
            )
            html_body = render(
                request,
                "onboarding/emails/onboarding_rejected.html",
                {
                    "candidate": candidate,
                    "reason": reason,
                    "register_url": register_url,
                    "upload_url": upload_url,
                    "company_name": getattr(settings, "ATS_COMPANY_NAME", "Company"),
                },
            ).content.decode("utf-8")

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email or None,
                to=[candidate.email],
                connection=connection,
            )
            email.attach_alternative(html_body, "text/html")
            email.send(fail_silently=False)
        except Exception:
            messages.warning(request, "Submission rejected, but the email to candidate could not be sent right now.")

        try:
            UiNotification.objects.create(
                recipient_name=(candidate.email or "").strip().lower(),
                title="Onboarding Documents Rejected",
                message="Your documents were rejected. Please upload again from Candidate Portal.",
                link=f"/candidate-portal/onboarding/{submission.invitation.token}/form/",
                source="onboarding",
                created_by=actor or "system",
            )
        except Exception:
            pass

        messages.success(request, "Onboarding submission rejected.")
        return redirect("/onboarding/approvals/")

    messages.error(request, "Invalid action.")
    return redirect(f"/onboarding/approvals/{submission_id}/")


def onboarding_employee_code_assign_view(request, submission_id: int):
    submission = get_object_or_404(
        OnboardingSubmission.objects.select_related("invitation__candidate"),
        id=submission_id,
    )
    candidate = submission.invitation.candidate

    existing_assignment = EmployeeCodeAssignment.objects.filter(candidate=candidate).first()
    if existing_assignment:
        messages.info(request, f"Employee code already assigned: {existing_assignment.employee_code}")
        return redirect("/onboarding/board/")

    if submission.status != "approved":
        messages.error(request, "Employee code can be assigned only after approval.")
        return redirect(f"/onboarding/approvals/{submission_id}/")

    signature_request = getattr(submission, "signature_request", None)
    if not signature_request or signature_request.status != "final_approved":
        messages.error(request, "Employee code can be assigned only after signature is completed and final approved.")
        return redirect(f"/onboarding/approvals/{submission_id}/")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action != "assign_employee_code":
            messages.error(request, "Invalid action.")
            return redirect(request.path)
        employee_code = (request.POST.get("employee_code") or "").strip()
        if not employee_code:
            messages.error(request, "Employee code is required.")
            return redirect(request.path)

        actor = (request.session.get("login_user_name") or "").strip()
        EmployeeCodeAssignment.objects.create(
            candidate=candidate,
            submission=submission,
            employee_code=employee_code,
            assigned_by=actor,
        )

        # Convert candidate -> employee (tracking switches from candidate_id to employee_code).
        try:
            candidate.candidate_code = employee_code
            candidate.status = "Employee"
            candidate.save(update_fields=["candidate_code", "status", "updated_at"])
        except Exception:
            pass

        try:
            user = UserMaster.objects.filter(email_id__iexact=candidate.email).first()
            if user:
                user.employee_code = employee_code
                user.role = "Employee"
                user.status = "Active"
                # Employees shouldn't use candidate portal by default.
                user.allowed_modules = (user.allowed_modules or "").replace("candidate_portal", "").strip(", ")
                user.save(update_fields=["employee_code", "role", "status", "allowed_modules"])
        except Exception:
            pass

        try:
            from candidate_portal.models import CandidatePortalProfile

            CandidatePortalProfile.objects.filter(candidate=candidate).update(is_active=False)
        except Exception:
            pass

        log_onboarding_action(
            user=_get_current_user(request),
            candidate=candidate,
            action="EMPLOYEE_CODE_ASSIGNED",
            details={
                "submission_id": submission.id,
                "employee_code": employee_code
            },
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        messages.success(request, f"Employee code '{employee_code}' assigned to {candidate.full_name}.")
        return redirect("/onboarding/board/")

    return render(
        request,
        "onboarding/employee_code_assign.html",
        {"submission": submission, "candidate": candidate},
    )


def onboarding_employee_code_assign_by_candidate_view(request, candidate_id: str):
    normalized = (candidate_id or "").strip()
    if not normalized:
        messages.error(request, "Invalid candidate id.")
        return redirect("/onboarding/board/")

    from candidate_management.models import Candidate

    candidate = Candidate.objects.filter(Q(candidate_id__iexact=normalized) | Q(candidate_code__iexact=normalized)).first()
    if not candidate:
        messages.error(request, f"Candidate '{normalized}' not found.")
        return redirect("/onboarding/board/")

    submission = (
        OnboardingSubmission.objects.select_related("invitation__candidate")
        .filter(invitation__candidate=candidate)
        .order_by("-updated_at")
        .first()
    )
    if not submission:
        messages.error(request, f"No onboarding submission found for '{candidate.candidate_id}'.")
        return redirect("/onboarding/board/")

    return redirect("onboarding:employee_code_assign", submission_id=submission.id)


def onboarding_offer_reports_view(request):
    query = (request.GET.get("q") or "").strip()
    offers_qs = OfferLetter.objects.select_related("candidate", "application__job").order_by("-created_at")
    if query:
        offers_qs = offers_qs.filter(
            Q(candidate__candidate_id__icontains=query)
            | Q(candidate__full_name__icontains=query)
            | Q(candidate__email__icontains=query)
            | Q(status__icontains=query)
        )
    offers = list(offers_qs[:500])

    if (request.GET.get("format") or "").strip().lower() == "pdf":
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.units import inch
            from reportlab.pdfgen import canvas
        except Exception:
            return HttpResponse("PDF generation is not available (missing reportlab).", status=503)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="offer_letter_report.pdf"'

        pdf = canvas.Canvas(response, pagesize=letter)
        width, height = letter
        x0 = 0.7 * inch
        y = height - 0.8 * inch

        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(x0, y, "Offer Letter Report")
        y -= 0.25 * inch
        pdf.setFont("Helvetica", 9)
        pdf.drawString(x0, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M UTC')}")
        y -= 0.35 * inch

        headers = ["Candidate ID", "Name", "Email", "Job", "Status", "Sent", "Response"]
        col_widths = [1.1 * inch, 1.6 * inch, 1.8 * inch, 1.1 * inch, 0.8 * inch, 0.9 * inch, 0.9 * inch]

        def draw_row(values, bold=False):
            nonlocal y
            if y < 0.8 * inch:
                pdf.showPage()
                y = height - 0.8 * inch
            pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 8)
            x = x0
            for value, w in zip(values, col_widths):
                text = (value or "")[:55]
                pdf.drawString(x, y, text)
                x += w
            y -= 0.18 * inch

        draw_row(headers, bold=True)
        pdf.setLineWidth(0.5)
        pdf.line(x0, y + 0.08 * inch, width - x0, y + 0.08 * inch)
        y -= 0.05 * inch

        for offer in offers:
            job_title = ""
            try:
                job_title = offer.application.job.title if offer.application and offer.application.job else ""
            except Exception:
                job_title = ""
            sent = offer.sent_at.strftime("%Y-%m-%d") if offer.sent_at else ""
            resp = offer.responded_at.strftime("%Y-%m-%d") if offer.responded_at else ""
            draw_row(
                [
                    offer.candidate.candidate_id,
                    offer.candidate.full_name,
                    offer.candidate.email,
                    job_title,
                    offer.status,
                    sent,
                    resp,
                ]
            )

        pdf.showPage()
        pdf.save()
        return response

    return render(request, "onboarding/offer_reports.html", {"offers": offers, "query": query})


def onboarding_finalized_board_view(request):
    query = (request.GET.get("q") or "").strip()

    cards = []
    rows = CandidateJobApplication.objects.select_related("candidate", "job").order_by("-applied_on")
    for row in rows:
        final_stage = _final_stage_for_job(row.job)
        stage = row.stage or ""
        if _normalized(stage) != _normalized(final_stage):
            continue
        candidate = row.candidate
        job_title = (row.job.title if row.job else "") or (candidate.applied_position or "")

        if query:
            qn = query.strip().lower()
            if (
                qn not in (candidate.candidate_id or "").lower()
                and qn not in (candidate.full_name or "").lower()
                and qn not in (candidate.email or "").lower()
                and qn not in (candidate.contact_number or "").lower()
                and qn not in (job_title or "").lower()
            ):
                continue

        cards.append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "job_applied": job_title,
                "stage": stage or final_stage,
                "last_updated": candidate.updated_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    columns = [{"name": "Finalized", "items": cards}]
    return render(
        request,
        "onboarding/finalized_board.html",
        {"columns": columns, "query": query, "finalized_count": len(cards)},
    )


def onboarding_candidate_view(request):
    query = (request.GET.get("q") or "").strip()
    rows = CandidateJobApplication.objects.select_related("candidate", "job").order_by("-applied_on")
    columns_by_job = {}
    for row in rows:
        final_stage = _final_stage_for_job(row.job)
        stage = row.stage or ""
        if _normalized(stage) != _normalized(final_stage):
            continue

        candidate = row.candidate
        job_title = (row.job.title if row.job else "") or (candidate.applied_position or "")
        job_id = (row.job.job_id if row.job else "") or ""
        job_label = (f"{job_id} - {job_title}".strip(" -")) or job_title or "Job"
        onboarding_stage = _candidate_onboarding_stage(candidate)
        employee_code = ""
        try:
            if hasattr(candidate, "employee_assignment") and candidate.employee_assignment:
                employee_code = candidate.employee_assignment.employee_code
        except Exception:
            employee_code = ""

        if query:
            qn = query.strip().lower()
            if (
                qn not in (candidate.candidate_id or "").lower()
                and qn not in (candidate.full_name or "").lower()
                and qn not in (candidate.email or "").lower()
                and qn not in (candidate.contact_number or "").lower()
                and qn not in (job_title or "").lower()
                and qn not in (job_id or "").lower()
                and qn not in (onboarding_stage or "").lower()
                and qn not in (employee_code or "").lower()
            ):
                continue

        columns_by_job.setdefault(job_label, []).append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "email": candidate.email,
                "job_applied": job_title,
                "stage": onboarding_stage or (stage or final_stage),
                "employee_code": employee_code,
                "last_updated": candidate.updated_at.strftime("%Y-%m-%d %H:%M"),
            }
        )
        if sum(len(items) for items in columns_by_job.values()) >= 500:
            break

    columns = [{"name": name, "items": items} for name, items in columns_by_job.items()]
    columns.sort(key=lambda col: col["name"].lower())
    return render(
        request,
        "onboarding/candidates.html",
        {"columns": columns, "query": query, "finalized_count": sum(len(c["items"]) for c in columns)},
    )

def onboarding_audit_logs_view(request):
    from app_settings.models import GlobalAuditLog
    query = (request.GET.get("q") or "").strip()
    logs = GlobalAuditLog.objects.filter(module="onboarding").select_related("candidate", "performed_by").order_by("-timestamp")
    if query:
        logs = logs.filter(
            Q(candidate__full_name__icontains=query) |
            Q(candidate__email__icontains=query) |
            Q(action__icontains=query)
        )
    
    rows = list(logs[:500])
    return render(request, "onboarding/audit_logs.html", {"logs": rows, "query": query, "nav_onboarding": "active"})


def onboarding_certificate_download_view(request, cert_id):
    cert = get_object_or_404(OnboardingSigningCertificate, id=cert_id)
    if not cert.certificate_pdf:
        messages.error(request, "Certificate file not found.")
        return redirect("/onboarding/audit-logs/")
        
    try:
        data = cert.certificate_pdf.open("rb").read()
        filename = os.path.basename(cert.certificate_pdf.name)
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception:
        messages.error(request, "Could not download certificate.")
        return redirect("/onboarding/audit-logs/")


def onboarding_certificate_view(request, cert_id):
    cert = get_object_or_404(OnboardingSigningCertificate, id=cert_id)
    candidate = cert.signature_request.submission.invitation.candidate
    doc_title = None
    try:
        doc_title = cert.document.title if cert.document else None
    except Exception:
        doc_title = None

    return render(
        request,
        "onboarding/certificate_view.html",
        {
            "cert": cert,
            "candidate": candidate,
            "doc_title": doc_title,
            "nav_onboarding": "active",
        },
    )


def onboarding_certificate_regenerate_view(request, cert_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return HttpResponse(status=403)

    if not getattr(request.user, "is_staff", False):
        return HttpResponse(status=403)

    cert = get_object_or_404(OnboardingSigningCertificate, id=cert_id)
    ip_address = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    from .utils import regenerate_signing_certificate_pdf

    try:
        regenerate_signing_certificate_pdf(cert, ip_address=ip_address, user_agent=user_agent)
        messages.success(request, "Certificate PDF regenerated.")
    except Exception:
        messages.error(request, "Could not regenerate certificate PDF.")

    return redirect("onboarding:certificate_view", cert_id=cert.id)
