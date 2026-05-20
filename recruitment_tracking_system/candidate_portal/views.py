import os
import json
import re
from datetime import timedelta
import logging
from django.core import signing

from django.conf import settings
from django.apps import apps
from django.contrib import messages
from django.utils import timezone
from django.db import IntegrityError
from django.db.models import Q
from django.core.mail import EmailMultiAlternatives, get_connection, send_mail
from django.template.loader import render_to_string
from django.template import Template, Context
from django.core.files.storage import default_storage
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import get_valid_filename

from app_settings.models import EmailDeliveryConfig, EmailTemplate, UiNotification, UserMaster
from app_settings.views import _normalize_smtp_password as _normalize_smtp_password_shared  # reuse gmail app-password cleanup when available
from applicant_tracking.models import (
    ApplicationPipelineCandidate,
    CandidateAssessmentAssignment,
    CandidateAssessmentSubmission,
)
from candidate_management.models import Candidate, CandidateEvaluation, CandidateJobApplication
from candidate_management.views import (
    _is_pdf_upload as _is_pdf_resume_upload,
    _parse_resume_autofill_from_upload as _parse_resume_autofill_from_upload_shared,
    _save_resume_upload_versioned as _save_resume_upload_versioned_shared,
    _save_candidate_education_records as _save_candidate_education_records_shared,
    _read_storage_bytes as _read_storage_bytes_shared,
)
from job_requisition.models import JobRequisition
from .models import CandidatePortalProfile

from onboarding.models import (
    OfferLetter,
    OnboardingDocument,
    OnboardingInvitation,
    OnboardingSignDocument,
    OnboardingSignatureRequest,
    OnboardingSubmission,
    OnboardingAuditLog,
)
from onboarding.utils import generate_signing_certificate
from recruitment_tracking_system.ollama_client import ollama_chat

try:
    from pyresparser import ResumeParser
except Exception:
    ResumeParser = None

PORTAL_REFERENCE_LABEL = "Ultimatix Portal"
logger = logging.getLogger(__name__)
PYRESPARSER_ENABLED = False
PYRESPARSER_DISABLE_REASON = ""
if ResumeParser is not None:
    try:
        import pyresparser

        pyresparser_dir = os.path.dirname(pyresparser.__file__)
        cfg_path = os.path.join(pyresparser_dir, "config.cfg")
        if os.path.exists(cfg_path):
            PYRESPARSER_ENABLED = True
        else:
            PYRESPARSER_DISABLE_REASON = f"Missing pyresparser config: {cfg_path}"
    except Exception as exc:
        PYRESPARSER_DISABLE_REASON = f"pyresparser import check failed: {exc}"
if not PYRESPARSER_ENABLED and ResumeParser is not None:
    logger.warning("pyresparser disabled. reason=%s", PYRESPARSER_DISABLE_REASON)


def _hr_admin_recipient_emails():
    roles = {"hr manager", "admin", "super admin"}
    rows = (
        UserMaster.objects.filter(status="Active")
        .exclude(email_id__isnull=True)
        .exclude(email_id__exact="")
        .values_list("email_id", "role")
    )
    emails = []
    for email, role in rows:
        if (role or "").strip().lower() in roles:
            emails.append((email or "").strip())
    return sorted({email for email in emails if email})


def _send_hr_notification_email(*, request, subject: str, body_html: str, action_url: str = "", action_label: str = "") -> None:
    recipients = _hr_admin_recipient_emails()
    if not recipients:
        return

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    host = (getattr(email_config, "host", "") or "").strip() if email_config else ""
    if not (email_config and getattr(email_config, "smtp_enabled", False) and host):
        return

    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=int(getattr(email_config, "port", 587) or 587),
        username=(getattr(email_config, "username", "") or "").strip() or None,
        password=(getattr(email_config, "password", "") or "").strip() or None,
        use_tls=bool(getattr(email_config, "use_tls", True)),
        fail_silently=False,
    )
    from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

    wrapper_html = render_to_string(
        "onboarding/emails/hr_notification.html",
        {
            "company_name": getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS"),
            "subject": subject,
            "body_html": body_html,
            "action_url": action_url,
            "action_label": action_label,
        },
    )
    body_text = re.sub(r"<[^>]+>", "", body_html or "").strip() or subject

    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email or None,
        to=recipients,
        connection=connection,
    )
    message.attach_alternative(wrapper_html, "text/html")
    message.send(fail_silently=False)


def _create_ui_notifications(*, recipient_emails: list[str], title: str, message: str = "", link: str = "", source: str = "") -> None:
    emails = [((item or "").strip().lower()) for item in (recipient_emails or []) if (item or "").strip()]
    if not emails:
        return
    rows = []
    for email in sorted(set(emails)):
        rows.append(
            UiNotification(
                recipient_name=email,
                title=(title or "").strip()[:180] or "Notification",
                message=(message or "").strip(),
                link=(link or "").strip()[:255],
                source=(source or "").strip()[:60],
            )
        )
    try:
        UiNotification.objects.bulk_create(rows)
    except Exception:
        logger.exception("UI notification create failed. title=%s", title)


def _send_candidate_notification_email(*, request, to_email: str, subject: str, template_name: str, context: dict) -> None:
    to_email = (to_email or "").strip()
    if not to_email:
        return

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    host = (getattr(email_config, "host", "") or "").strip() if email_config else ""
    if not (email_config and getattr(email_config, "smtp_enabled", False) and host):
        return

    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=int(getattr(email_config, "port", 587) or 587),
        username=(getattr(email_config, "username", "") or "").strip() or None,
        password=(getattr(email_config, "password", "") or "").strip() or None,
        use_tls=bool(getattr(email_config, "use_tls", True)),
        fail_silently=False,
    )
    from_email = (getattr(email_config, "from_email", "") or "").strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")

    company_name = getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS")
    html_body = render_to_string(template_name, {"company_name": company_name, **(context or {})})
    text_body = re.sub(r"<[^>]+>", "", html_body or "").strip() or subject

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or None,
        to=[to_email],
        connection=connection,
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)


def _candidate_magic_portal_url(request, email: str, next_path: str = "/candidate-portal/") -> str:
    email = (email or "").strip()
    if not request or not email:
        return next_path or "/candidate-portal/"
    try:
        if not next_path or not next_path.startswith("/candidate-portal/"):
            next_path = "/candidate-portal/"
        signer = signing.TimestampSigner(salt="candidate_portal_magic")
        token = signer.sign(email)
        return request.build_absolute_uri(f"/candidate-portal/magic/{token}/?next={next_path}")
    except Exception:
        return next_path or "/candidate-portal/"


def _reset_login_session(request):
    request.session.pop("login_user_name", None)
    request.session.pop("login_user_email", None)
    request.session.pop("login_user_role", None)


def _split_name(full_name):
    parts = [item for item in (full_name or "").strip().split(" ") if item]
    if not parts:
        return "Candidate", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _clean_candidate_name(value):
    if not value:
        return ""
    cleaned = str(value).strip()
    cleaned = re.split(r"[|/]", cleaned, 1)[0].strip()
    cleaned = re.split(r"\s+-\s+", cleaned, 1)[0].strip()
    cleaned = cleaned.strip("-").strip()
    if "@" in cleaned or any(ch.isdigit() for ch in cleaned):
        return ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z\s\.\-']{1,60}", cleaned):
        return ""
    lower = cleaned.lower()
    blocked = {
        "resume",
        "curriculum vitae",
        "curriculum",
        "vitae",
        "email",
        "phone",
        "contact",
        "address",
        "skills",
        "education",
        "experience",
        "objective",
        "profile",
    }
    if any(token in lower for token in blocked):
        return ""
    return cleaned


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _calculate_assessment_score(*, fields: list, answers: dict) -> tuple[float, float]:
    score = 0.0
    max_score = 0.0

    for field in fields:
        field_name = field["field_name"]
        field_type = field["field_type"]
        points = float(field.get("points") or 0.0)
        correct_answer = (field.get("correct_answer") or "").strip()

        if points > 0:
            max_score += points

        if not correct_answer:
            continue

        value = answers.get(field_name)

        if field_type in {"select", "radio"}:
            if (str(value or "").strip() == correct_answer):
                score += points
            continue

        if field_type == "checkbox":
            submitted = set([str(v).strip() for v in (value or []) if str(v).strip()])
            expected = set(_split_csv(correct_answer))
            if submitted == expected and expected:
                score += points
            continue

        # text/number/textarea/date/email/etc: exact match (case-insensitive for text)
        submitted_value = str(value or "").strip()
        if field_type in {"text", "textarea"}:
            if submitted_value.lower() == correct_answer.lower():
                score += points
        else:
            if submitted_value == correct_answer:
                score += points

    return score, max_score


def candidate_assessment_form_view(request, token):
    assignment = get_object_or_404(
        CandidateAssessmentAssignment.objects.select_related("candidate", "assessment_form").prefetch_related("assessment_form__fields"),
        token=token,
    )

    # Ensure the shared app shell renders in Candidate mode (hide admin/HR navigation).
    candidate = assignment.candidate
    request.session["login_user_name"] = candidate.full_name
    request.session["login_user_email"] = candidate.email
    request.session["login_user_role"] = "Candidate"

    client_ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()
    try:
        assignment.mark_opened(ip_address=client_ip)
    except Exception:
        pass

    form = assignment.assessment_form
    fields = []
    for f in form.fields.all():
        options_list = _split_csv(getattr(f, "options", "") or "")
        fields.append(
            {
                "label": f.label,
                "field_name": f.field_name,
                "field_type": f.field_type,
                "required": bool(f.required),
                "options_list": options_list,
                "points": float(getattr(f, "points", 1) or 0),
                "correct_answer": (getattr(f, "correct_answer", "") or "").strip(),
            }
        )

    existing_submission = getattr(assignment, "submission", None)
    if assignment.status == "Completed" and existing_submission:
        return render(
            request,
            "candidate_portal/assessment_submitted.html",
            {
                "assignment": assignment,
                "candidate": assignment.candidate,
                "form": form,
                "submission": existing_submission,
            },
        )

    # ── Proctoring ──────────────────────────────────────────────────────────
    PROCTOR_MAX_WARNINGS = 3
    proctor_session_token = ""
    try:
        from proctoring.models import ProctoringSession
        proctor_session = ProctoringSession.objects.create(
            context="assessment",
            reference_id=str(token),
            candidate_name=candidate.full_name or "",
            candidate_email=candidate.email or "",
            max_warnings=PROCTOR_MAX_WARNINGS,
            ip_address=client_ip or None,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )
        proctor_session_token = str(proctor_session.session_token)
    except Exception:
        logger.exception("Failed to create proctoring session for assessment token=%s", token)
    # ────────────────────────────────────────────────────────────────────────

    if request.method == "POST":
        # Check whether the proctoring session was terminated before allowing submission
        submitted_proctor_token = (request.POST.get("proctor_session_token") or "").strip()
        proctor_terminated = False
        if submitted_proctor_token:
            try:
                from proctoring.models import ProctoringSession as PS
                from django.utils import timezone as tz
                ps = PS.objects.filter(session_token=submitted_proctor_token).first()
                if ps:
                    proctor_terminated = ps.is_terminated
                    if ps.status == "active":
                        ps.status = "completed"
                        ps.ended_at = tz.now()
                        ps.save(update_fields=["status", "ended_at"])
            except Exception:
                logger.exception("Proctor session post-processing failed token=%s", submitted_proctor_token)

        if proctor_terminated:
            return render(
                request,
                "candidate_portal/assessment_submitted.html",
                {
                    "assignment": assignment,
                    "candidate": assignment.candidate,
                    "form": form,
                    "submission": None,
                    "proctor_terminated": True,
                },
            )

        answers = {}
        errors = {}
        for field in fields:
            name = field["field_name"]
            ftype = field["field_type"]
            if ftype == "checkbox":
                value = request.POST.getlist(name)
            else:
                value = (request.POST.get(name) or "").strip()
            answers[name] = value

            if field["required"]:
                if ftype == "checkbox":
                    missing = not value
                else:
                    missing = value in ("", None)
                if missing:
                    errors[name] = "This field is required."

        if errors:
            return render(
                request,
                "candidate_portal/assessment_form.html",
                {
                    "assignment": assignment,
                    "candidate": assignment.candidate,
                    "form": form,
                    "fields": fields,
                    "answers": answers,
                    "errors": errors,
                    "proctor_session_token": proctor_session_token,
                    "proctor_max_warnings": PROCTOR_MAX_WARNINGS,
                },
            )

        score, max_score = _calculate_assessment_score(fields=fields, answers=answers)
        submission = CandidateAssessmentSubmission.objects.create(
            assignment=assignment,
            answers=answers,
            score=score,
            max_score=max_score,
        )
        try:
            assignment.mark_completed()
        except Exception:
            pass

        # UI notifications (candidate + HR/Admin)
        try:
            _create_ui_notifications(
                recipient_emails=[candidate.email],
                title="Assessment submitted",
                message=f"Submitted: {form.name}",
                link=request.build_absolute_uri(request.path),
                source="assessment",
            )
        except Exception:
            pass
        try:
            hr_action_url = request.build_absolute_uri("/applicant-tracking/interview-scheduling/assessments/")
            _create_ui_notifications(
                recipient_emails=_hr_admin_recipient_emails(),
                title="Candidate assessment submitted",
                message=f"{candidate.full_name} submitted {form.name}. Score: {score:.0f}/{max_score:.0f}",
                link=hr_action_url,
                source="assessment",
            )
        except Exception:
            pass

        return render(
            request,
            "candidate_portal/assessment_submitted.html",
            {
                "assignment": assignment,
                "candidate": assignment.candidate,
                "form": form,
                "submission": submission,
            },
        )

    return render(
        request,
        "candidate_portal/assessment_form.html",
        {
            "assignment": assignment,
            "candidate": assignment.candidate,
            "form": form,
            "fields": fields,
            "answers": {},
            "errors": {},
            "proctor_session_token": proctor_session_token,
            "proctor_max_warnings": PROCTOR_MAX_WARNINGS,
        },
    )



def _save_resume_upload(file_obj):
    if not file_obj:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    return default_storage.save(f"resumes/{safe_name}", file_obj)


def _empty_resume_payload():
    return {
        "full_name": "",
        "email": "",
        "contact_number": "",
        "skills": "",
        "experience": "",
        "highest_education_level": "",
        "degree_name": "",
        "institute_name": "",
    }


def _normalize_contact_number(value):
    if not value:
        return ""
    return re.sub(r"[^\d+]", "", str(value))[:20]


def _normalize_text_list(value):
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(items)
    if value is None:
        return ""
    return str(value).strip()


def _format_experience(value):
    if value is None or value == "":
        return ""
    try:
        numeric = float(value)
        if numeric < 0:
            return ""
        if numeric.is_integer():
            return f"{int(numeric)} years"
        return f"{numeric:.1f} years"
    except Exception:
        text = str(value).strip()
        if not text:
            return ""
        if "year" in text.lower() or "yr" in text.lower():
            return text
        return f"{text} years"


def _resume_pyresparser_autofill(resume_file_path):
    payload = _empty_resume_payload()
    if not resume_file_path or ResumeParser is None or not PYRESPARSER_ENABLED:
        return payload

    try:
        parsed = ResumeParser(resume_file_path).get_extracted_data() or {}
    except Exception as exc:
        logger.warning("pyresparser failed for %s: %s", resume_file_path, exc)
        return payload

    payload["full_name"] = (parsed.get("name") or "").strip()
    payload["email"] = (parsed.get("email") or "").strip()
    payload["contact_number"] = _normalize_contact_number(parsed.get("mobile_number"))
    payload["skills"] = _normalize_text_list(parsed.get("skills"))
    payload["experience"] = _format_experience(parsed.get("total_experience") or parsed.get("experience"))

    degree_value = _normalize_text_list(parsed.get("degree"))
    payload["highest_education_level"] = degree_value
    payload["degree_name"] = degree_value
    payload["institute_name"] = _normalize_text_list(parsed.get("college_name"))
    return payload


def _extract_resume_text(file_obj):
    if not file_obj:
        return ""
    try:
        file_obj.seek(0)
    except Exception:
        pass
    raw = file_obj.read()
    if not raw:
        return ""
    for encoding in ("utf-8", "latin-1", "utf-16"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _resume_regex_autofill(text):
    payload = _empty_resume_payload()
    if not text:
        return payload

    normalized = " ".join(text.split())

    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", normalized)
    if email_match:
        payload["email"] = email_match.group(0).strip()

    phone_match = re.search(r"(\+?\d[\d\-\s]{8,}\d)", normalized)
    if phone_match:
        payload["contact_number"] = re.sub(r"[^\d+]", "", phone_match.group(1))[:20]

    name_match = re.search(r"(?:name|candidate)\s*[:\-]\s*([A-Za-z][A-Za-z\s]{2,60})", normalized, flags=re.I)
    if name_match:
        payload["full_name"] = name_match.group(1).strip()

    exp_match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", normalized, flags=re.I)
    if exp_match:
        payload["experience"] = f"{exp_match.group(1)} years"

    skill_match = re.search(r"(?:skills?)\s*[:\-]\s*([A-Za-z0-9,\s\-\.\+#/]{3,200})", normalized, flags=re.I)
    if skill_match:
        payload["skills"] = skill_match.group(1).strip()[:250]

    edu_match = re.search(
        r"(b\.?tech|m\.?tech|b\.?e|mca|bca|mba|bsc|msc|phd|diploma|graduate|post graduate)",
        normalized,
        flags=re.I,
    )
    if edu_match:
        payload["highest_education_level"] = edu_match.group(1).upper().replace(".", "")

    return payload


def _merge_resume_payload(primary, fallback):
    merged = _empty_resume_payload()
    for key in merged.keys():
        primary_value = (primary or {}).get(key, "")
        fallback_value = (fallback or {}).get(key, "")
        merged[key] = str(primary_value or fallback_value or "").strip()
    return merged


def _apply_parsed_resume_to_candidate(candidate, parsed, overwrite=False):
    def _looks_like_gibberish(value):
        text = (value or "").strip()
        if not text:
            return True
        if len(text) > 1200:
            return True
        alpha = sum(ch.isalpha() for ch in text)
        total = len(text)
        if total == 0:
            return True
        if alpha / total < 0.5:
            return True
        if "endobj" in text.lower() or "stream" in text.lower():
            return True
        return False

    def _safe_set(attr, value):
        if not value:
            return
        if _looks_like_gibberish(value):
            return
        if not overwrite:
            current = getattr(candidate, attr, "") or ""
            if current:
                return
        setattr(candidate, attr, value)

    email_conflict = False
    if parsed.get("full_name"):
        cleaned = _clean_candidate_name(parsed["full_name"])
        if cleaned and (overwrite or not candidate.full_name):
            candidate.full_name = cleaned
    if parsed.get("email"):
        parsed_email = parsed["email"].strip().lower()
        current_email = (candidate.email or "").strip().lower()
        if parsed_email and re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", parsed_email) and parsed_email != current_email:
            exists_for_other = Candidate.objects.exclude(pk=candidate.pk).filter(email__iexact=parsed_email).exists()
            if exists_for_other:
                email_conflict = True
            else:
                candidate.email = parsed_email
    if parsed.get("contact_number"):
        phone = re.sub(r"[^\d+]", "", parsed["contact_number"])
        if 8 <= len(phone) <= 16:
            if overwrite or not candidate.contact_number:
                candidate.contact_number = phone
    if parsed.get("social_media_link"):
        link = parsed["social_media_link"]
        if any(domain in (link or "").lower() for domain in ["linkedin.com", "github.com", "gitlab.com", "behance.net"]):
            if overwrite or not candidate.social_media_link:
                candidate.social_media_link = link
    if parsed.get("skills"):
        _safe_set("skills", parsed["skills"])
    if parsed.get("experience"):
        _safe_set("experience", parsed["experience"])
    if parsed.get("employment_history"):
        _safe_set("employment_history", parsed["employment_history"])
    if parsed.get("references"):
        _safe_set("references", parsed["references"])
    if parsed.get("highest_education_level"):
        _safe_set("highest_education_level", parsed["highest_education_level"])
    if parsed.get("degree_name"):
        _safe_set("degree_name", parsed["degree_name"])
    elif parsed.get("highest_education_level"):
        _safe_set("degree_name", parsed["highest_education_level"])
    if parsed.get("institute_name"):
        _safe_set("institute_name", parsed["institute_name"])
    if parsed.get("year_of_passing"):
        _safe_set("year_of_passing", parsed["year_of_passing"])
    if parsed.get("percentage_cgpa"):
        _safe_set("percentage_cgpa", parsed["percentage_cgpa"])
    if parsed.get("certifications"):
        _safe_set("certifications", parsed["certifications"])
    return email_conflict


def _send_candidate_portal_link_email(request, full_name, email):
    portal_login_url = request.build_absolute_uri("/")
    company_name = getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS")

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    host = (getattr(email_config, "host", "") or "").strip() if email_config else ""
    smtp_enabled = bool(email_config and getattr(email_config, "smtp_enabled", False) and host)
    if email_config:
        from_email = (getattr(email_config, "from_email", "") or "").strip() or (getattr(email_config, "username", "") or "").strip()
    else:
        from_email = ""
    from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@ultimatix-ats.local")

    # Defensive import: avoid NameError if EmailTemplate isn't in module globals
    # due to partial reloads / circular imports during development.
    try:
        EmailTemplateModel = EmailTemplate
    except NameError:
        EmailTemplateModel = apps.get_model("app_settings", "EmailTemplate")

    # Prefer configurable templates from Settings -> Email Templates.
    template = (
        EmailTemplateModel.objects.filter(is_active=True, trigger__iexact="candidate_portal_registration").order_by("-updated_at").first()
        or EmailTemplateModel.objects.filter(is_active=True, trigger__iexact="candidate_portal_access").order_by("-updated_at").first()
        or EmailTemplateModel.objects.filter(is_active=True, name__iexact="Candidate Portal Access").order_by("-updated_at").first()
    )

    ctx = {
        "company_name": company_name,
        "candidate_name": full_name or "Candidate",
        "candidate_email": email or "",
        "portal_login_url": portal_login_url,
    }

    default_subject = f"{company_name} Candidate Portal Access"
    default_body_text = (
        f"Dear {full_name},\n\n"
        "Your registration is completed successfully.\n"
        "You can login to the Candidate Portal using your registered email.\n\n"
        f"Portal Link: {portal_login_url}\n"
        f"Login Email: {email}\n\n"
        "Use the password you set during registration.\n\n"
        f"Regards,\n{company_name}"
    )

    subject = default_subject
    body_rendered = ""
    if template:
        try:
            subject = (Template(str(template.subject or "")).render(Context(ctx, autoescape=True))).strip() or default_subject
        except Exception:
            subject = default_subject
        try:
            body_rendered = Template(str(template.body or "")).render(Context(ctx, autoescape=True))
        except Exception:
            body_rendered = ""

    # Fallback to old default if template missing or blank.
    if not body_rendered.strip():
        body_rendered = default_body_text

    looks_like_html = "<html" in body_rendered.lower() or "<body" in body_rendered.lower() or "<div" in body_rendered.lower() or "<p" in body_rendered.lower()
    body_text = body_rendered
    if looks_like_html:
        body_text = re.sub(r"<[^>]+>", "", body_rendered or "").strip() or default_body_text

    connection = None
    if smtp_enabled:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=int(getattr(email_config, "port", 587) or 587),
            username=(getattr(email_config, "username", "") or "").strip() or None,
            password=_normalize_smtp_password_shared(host, (getattr(email_config, "password", "") or "").strip()) or None,
            use_tls=bool(getattr(email_config, "use_tls", True)),
            fail_silently=False,
        )
    else:
        # Portal registration email must go to the candidate inbox; if SMTP isn't configured,
        # raise so the caller can show a clear warning.
        raise RuntimeError("SMTP is not configured. Enable SMTP and set Host/Username/Password/From Email in Settings -> Integration.")

    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email or None,
        to=[email],
        connection=connection,
    )
    if looks_like_html:
        message.attach_alternative(body_rendered, "text/html")
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.exception("candidate portal registration email failed to=%s err=%s", email, exc)
        raise RuntimeError(str(exc))


def candidate_portal_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name and role_name != "candidate":
        return redirect("candidate_portal:admin_access")

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to access candidate portal.")
        return redirect("/login/")

    candidate = Candidate.objects.prefetch_related("education_records").filter(email__iexact=login_email).first()
    if not candidate:
        _reset_login_session(request)
        messages.error(request, "Candidate profile not found. Please apply to a job first.")
        return redirect("/login/")

    if bool(request.session.get("candidate_resume_required")) and not bool(candidate.resume_path):
        return redirect("candidate_portal:resume_upload")

    CandidatePortalProfile.objects.update_or_create(
        candidate=candidate,
        defaults={
            "portal_email": candidate.email,
            "is_active": True,
            "last_login_at": timezone.now(),
        },
    )

    onboarding_invitation = (
        OnboardingInvitation.objects.select_related("offer_letter", "form_template")
        .filter(candidate=candidate)
        .order_by("-created_at")
        .first()
    )
    signature_request = None
    pending_sign_docs = []
    pending_signature_url = ""
    if onboarding_invitation:
        submission = OnboardingSubmission.objects.filter(invitation=onboarding_invitation).first()
        if submission:
            signature_request = getattr(submission, "signature_request", None)
            if signature_request and signature_request.token and signature_request.status == "pending":
                pending_sign_docs = list(signature_request.documents.filter(status="pending"))
                pending_signature_url = f"/candidate-portal/sign/{signature_request.token}/?as=candidate"
                try:
                    UiNotification.objects.get_or_create(
                        recipient_name=login_email,
                        source="signature",
                        link=pending_signature_url,
                        title="Signature Required",
                        defaults={
                            "message": "Please sign your onboarding document(s) to continue.",
                            "created_by": "system",
                        },
                    )
                except Exception:
                    pass

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "save_profile":
            candidate.full_name = request.POST.get("full_name", "").strip() or candidate.full_name
            candidate.contact_number = request.POST.get("contact_number", "").strip() or candidate.contact_number
            candidate.social_media_link = request.POST.get("social_media_link", "").strip()
            candidate.skills = request.POST.get("skills", "").strip()
            candidate.experience = request.POST.get("experience", "").strip()
            candidate.highest_education_level = request.POST.get("highest_education_level", "").strip()
            candidate.degree_name = request.POST.get("degree_name", "").strip() or candidate.highest_education_level
            candidate.institute_name = request.POST.get("institute_name", candidate.institute_name).strip()
            candidate.year_of_passing = request.POST.get("year_of_passing", candidate.year_of_passing).strip()
            candidate.percentage_cgpa = request.POST.get("percentage_cgpa", candidate.percentage_cgpa).strip()
            candidate.employment_history = request.POST.get("employment_history", "").strip()
            candidate.certifications = request.POST.get("certifications", "").strip()
            candidate.references = request.POST.get("references", "").strip()
            candidate.save()

            education_records_json = request.POST.get("education_records_json", "").strip()
            if education_records_json:
                try:
                    education_records = json.loads(education_records_json)
                except Exception:
                    education_records = []
                if education_records:
                    _save_candidate_education_records_shared(
                        candidate,
                        education_records,
                        fallback={
                            "highest_education_level": candidate.highest_education_level,
                            "degree_name": candidate.degree_name,
                            "institute_name": candidate.institute_name,
                            "year_of_passing": candidate.year_of_passing,
                            "percentage_cgpa": candidate.percentage_cgpa,
                        },
                    )
            messages.success(request, "Profile updated successfully.")
            return redirect("candidate_portal:index")

        if action == "upload_resume":
            resume_upload = request.FILES.get("resume_upload")
            if not resume_upload:
                messages.error(request, "Please choose a resume file.")
                return redirect("candidate_portal:index")
            if not _is_pdf_resume_upload(resume_upload):
                messages.error(request, "Resume must be uploaded in PDF format only.")
                return redirect("candidate_portal:index")

            resume_path = _save_resume_upload_versioned_shared(candidate, resume_upload)
            candidate.resume_path = resume_path
            parsed = _parse_resume_autofill_from_upload_shared(resume_upload)
            email_conflict = _apply_parsed_resume_to_candidate(candidate, parsed, overwrite=True)
            candidate.save()
            _save_candidate_education_records_shared(
                candidate,
                parsed.get("education_records", []),
                fallback=parsed,
            )
            request.session["candidate_resume_required"] = False
            messages.success(
                request,
                (
                    "Resume uploaded and profile auto-filled."
                    if not email_conflict
                    else "Resume uploaded and profile auto-filled (email kept unchanged due to existing profile)."
                ),
            )
            return redirect("candidate_portal:index")

    job_apps = list(
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate)
        .order_by("-applied_on")
    )
    stage_by_title = {}
    for item in CandidateEvaluation.objects.filter(candidate=candidate).order_by("-updated_at", "-created_at"):
        title_key = (item.posting_title or "").strip().lower()
        if title_key and title_key not in stage_by_title:
            stage_by_title[title_key] = item.status

    job_apps_data = []
    for item in job_apps:
        job_title_key = (item.job.title or "").strip().lower() if item.job else ""
        current_stage = item.stage or stage_by_title.get(job_title_key) or candidate.status
        job_apps_data.append({"application": item, "stage": current_stage})

    assessments_data = []
    try:
        assignments = list(
            CandidateAssessmentAssignment.objects.select_related("assessment_form", "submission")
            .filter(candidate=candidate)
            .order_by("-assigned_at")
        )
        for a in assignments:
            form = a.assessment_form
            submission = getattr(a, "submission", None)
            can_show_score = bool(getattr(form, "show_score_to_candidate", True))
            score_percent = None
            if submission and submission.max_score not in (None, 0) and can_show_score:
                try:
                    score_percent = round((float(submission.score or 0) / float(submission.max_score)) * 100.0, 1)
                except Exception:
                    score_percent = None

            assessments_data.append(
                {
                    "assignment": a,
                    "form": form,
                    "submission": submission,
                    "can_show_score": can_show_score,
                    "score_percent": score_percent,
                }
            )
    except Exception:
        logger.exception("Failed to load assessment history for candidate_id=%s", candidate.id)

    show_registration_success_popup = bool(request.session.pop("candidate_registration_success", False))
    candidate_portal_email_sent = bool(request.session.pop("candidate_portal_email_sent", False))
    return render(
        request,
        "candidate_portal/index.html",
        {
            "candidate": candidate,
            "job_apps_data": job_apps_data,
            "assessments_data": assessments_data,
            "resume_url": ("/candidate-portal/resume/" if candidate.resume_path else ""),
            "education_records": [
                {
                    "level": item.level,
                    "course": item.course,
                    "institute": item.institute,
                    "board_university": item.board_university,
                    "year_of_passing": item.year_of_passing,
                    "score": item.score,
                }
                for item in candidate.education_records.all()
            ],
            "show_resume_popup": not bool(candidate.resume_path),
            "onboarding_invitation": onboarding_invitation,
            "signature_request": signature_request,
            "pending_sign_docs": pending_sign_docs,
            "pending_signature_url": pending_signature_url,
            "show_registration_success_popup": show_registration_success_popup,
            "candidate_portal_email_sent": candidate_portal_email_sent,
        },
    )


def candidate_portal_resume_upload_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name and role_name != "candidate":
        return redirect("candidate_portal:admin_access")

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to upload your resume.")
        return redirect("/login/")

    candidate = Candidate.objects.filter(email__iexact=login_email).first()
    if not candidate:
        _reset_login_session(request)
        messages.error(request, "Candidate profile not found. Please apply to a job first.")
        return redirect("/login/")

    if request.method == "POST":
        resume_upload = request.FILES.get("resume_upload")
        if not resume_upload:
            messages.error(request, "Please choose a resume file.")
            return redirect("candidate_portal:resume_upload")
        if not _is_pdf_resume_upload(resume_upload):
            messages.error(request, "Resume must be uploaded in PDF format only.")
            return redirect("candidate_portal:resume_upload")

        resume_path = _save_resume_upload_versioned_shared(candidate, resume_upload)
        candidate.resume_path = resume_path
        parsed = _parse_resume_autofill_from_upload_shared(resume_upload)
        email_conflict = _apply_parsed_resume_to_candidate(candidate, parsed, overwrite=True)
        candidate.save()
        _save_candidate_education_records_shared(
            candidate,
            parsed.get("education_records", []),
            fallback=parsed,
        )
        request.session["candidate_resume_required"] = False
        messages.success(
            request,
            (
                "Resume uploaded and profile auto-filled."
                if not email_conflict
                else "Resume uploaded and profile auto-filled (email kept unchanged due to existing profile)."
            ),
        )
        return redirect("candidate_portal:index")

    return render(
        request,
        "candidate_portal/resume_upload.html",
        {
            "candidate": candidate,
            "next_url": "/candidate-portal/",
        },
    )


def candidate_portal_resume_download_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name and role_name != "candidate":
        return redirect("candidate_portal:admin_access")
    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to access candidate portal.")
        return redirect("/login/")
    candidate = Candidate.objects.filter(email__iexact=login_email).first()
    if not candidate or not candidate.resume_path:
        return redirect("candidate_portal:index")
    data = _read_storage_bytes_shared(candidate.resume_path)
    filename = os.path.basename(candidate.resume_path) or f"{candidate.candidate_id}_resume.pdf"
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def candidate_portal_admin_access_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if not role_name:
        messages.error(request, "Please login to continue.")
        return redirect("/login/")
    if role_name == "candidate":
        messages.error(request, "Access denied for candidate role.")
        return redirect("candidate_portal:index")

    profiles = CandidatePortalProfile.objects.select_related("candidate").prefetch_related("candidate__job_applications__job")
    rows = []
    for item in profiles.order_by("-last_login_at", "-updated_at"):
        candidate = item.candidate
        applied_jobs = sorted(
            list(candidate.job_applications.all()),
            key=lambda x: x.applied_on,
            reverse=True,
        )
        jobs = [f"{entry.job.job_id} - {entry.job.title}" for entry in applied_jobs if entry.job]
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "email": candidate.email,
                "portal_email": item.portal_email or candidate.email,
                "last_login_at": item.last_login_at,
                "is_active": item.is_active,
                "jobs": jobs,
            }
        )

    total_count = len(rows)
    active_count = sum(1 for item in rows if item["is_active"])
    recent_threshold = timezone.now() - timedelta(days=1)
    recent_access_count = sum(1 for item in rows if item["last_login_at"] and item["last_login_at"] >= recent_threshold)

    return render(
        request,
        "candidate_portal/admin_access.html",
        {
            "rows": rows,
            "total_count": total_count,
            "active_count": active_count,
            "inactive_count": total_count - active_count,
            "recent_access_count": recent_access_count,
        },
    )


def _map_candidate_status_to_stage(status):
    value = (status or "").strip().lower()
    if value in {"applied"}:
        return "Applied"
    if value in {"screened", "under review"}:
        return "Screened"
    if value in {"offer", "offered"}:
        return "Offer"
    if value in {"hired", "strong hire"}:
        return "Hired"
    if value in {"rejected"}:
        return "Rejected"
    if "interview" in value or value in {"in progress", "move to next round", "shortlist", "on-hold", "wait-list"}:
        return "Interview"
    return "Applied"


def candidate_application_pipeline_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name != "candidate":
        messages.error(request, "This application tracking page is available only for candidate users.")
        return redirect("/dashboard/")

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to access candidate portal.")
        return redirect("/login/")

    candidate = Candidate.objects.filter(email__iexact=login_email).first()
    if not candidate:
        _reset_login_session(request)
        messages.error(request, "Candidate profile not found. Please apply to a job first.")
        return redirect("/login/")

    default_stage_order = ["Applied", "Screened", "Interview", "Offer", "Hired", "Rejected"]
    selected_job_id = request.GET.get("job_id", "").strip()
    selected_job = JobRequisition.objects.filter(job_id=selected_job_id).first() if selected_job_id else None
    stage_order = default_stage_order.copy()
    if selected_job:
        configured = [item.strip() for item in (selected_job.stages or "").split(",") if item.strip()]
        if configured:
            stage_order = configured

    grouped = {stage: [] for stage in stage_order}
    covered_jobs = set()

    candidate_pipeline_entries = ApplicationPipelineCandidate.objects.filter(candidate=candidate).order_by("-last_updated")
    for item in candidate_pipeline_entries:
        if selected_job and (item.job_applied or "").strip().lower() != (selected_job.title or "").strip().lower():
            continue
        covered_jobs.add((item.job_applied or "").strip().lower())
        if item.stage not in grouped:
            grouped[item.stage] = []
            stage_order.append(item.stage)
        grouped[item.stage].append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "job_applied": item.job_applied or candidate.applied_position,
                "stage": item.stage,
                "last_updated": item.last_updated.strftime("%Y-%m-%d %H:%M"),
            }
        )

    job_apps = (
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate)
        .order_by("-applied_on")
    )
    for app in job_apps:
        job_title = (app.job.title or "").strip() if app.job else ""
        if selected_job and (job_title.lower() != (selected_job.title or "").strip().lower()):
            continue
        if job_title.lower() in covered_jobs:
            continue
        stage = app.stage or _map_candidate_status_to_stage(candidate.status)
        if stage not in grouped:
            grouped[stage] = []
            stage_order.append(stage)
        grouped[stage].append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "job_applied": job_title or candidate.applied_position,
                "stage": stage,
                "last_updated": app.applied_on.strftime("%Y-%m-%d %H:%M"),
            }
        )

    columns = [{"name": stage, "items": grouped.get(stage, [])} for stage in stage_order]
    position_options = list(
        JobRequisition.objects.filter(candidate_applications__candidate=candidate)
        .distinct()
        .order_by("-created_at")
        .values("job_id", "title", "stages")
    )
    return render(
        request,
        "candidate_portal/application_pipeline.html",
        {
            "columns": columns,
            "position_options": position_options,
            "selected_job_id": selected_job_id,
        },
    )


def candidate_applied_job_detail_view(request, job_id):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name != "candidate":
        messages.error(request, "This page is available only for candidate users.")
        return redirect("/dashboard/")

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to access candidate portal.")
        return redirect("/login/")

    candidate = Candidate.objects.filter(email__iexact=login_email).first()
    if not candidate:
        _reset_login_session(request)
        messages.error(request, "Candidate profile not found. Please apply to a job first.")
        return redirect("/login/")

    job = get_object_or_404(JobRequisition, job_id=job_id)
    application = (
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate, job=job)
        .first()
    )
    if not application:
        messages.error(request, "You have not applied for this job.")
        return redirect("candidate_portal:index")

    current_stage = application.stage or _map_candidate_status_to_stage(candidate.status)
    return render(
        request,
        "candidate_portal/applied_job_detail.html",
        {
            "job": job,
            "application": application,
            "current_stage": current_stage,
        },
    )


def public_careers_view(request):
    query = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    department = request.GET.get("department", "").strip()
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    login_email = (request.session.get("login_user_email") or "").strip().lower()
    candidate_logged_in = role_name == "candidate" and bool(
        login_email and Candidate.objects.filter(email__iexact=login_email).exists()
    )

    today = timezone.localdate()
    jobs_qs = (
        JobRequisition.objects.filter(status__iexact="Approved")
        .exclude(job_opening_status__iexact="Closed")
        .filter(Q(target_closure_date__isnull=True) | Q(target_closure_date__gte=today))
        .order_by("-created_at")
    )
    if query:
        jobs_qs = jobs_qs.filter(title__icontains=query)
    if location:
        jobs_qs = jobs_qs.filter(location__icontains=location)
    if department:
        jobs_qs = jobs_qs.filter(department__icontains=department)

    jobs = list(jobs_qs)
    locations = sorted(
        {item.strip() for item in JobRequisition.objects.exclude(location__exact="").values_list("location", flat=True)}
    )
    departments = sorted(
        {item.strip() for item in JobRequisition.objects.exclude(department__exact="").values_list("department", flat=True)}
    )

    return render(
        request,
        "candidate_portal/careers.html",
        {
            "jobs": jobs,
            "query": query,
            "selected_location": location,
            "selected_department": department,
            "locations": locations,
            "departments": departments,
            "open_positions": len(jobs),
            "candidate_logged_in": candidate_logged_in,
        },
    )


def public_job_detail_view(request, job_id):
    today = timezone.localdate()
    job = get_object_or_404(
        JobRequisition.objects.exclude(job_opening_status__iexact="Closed").filter(
            Q(target_closure_date__isnull=True) | Q(target_closure_date__gte=today)
        ),
        job_id=job_id,
        status__iexact="Approved",
    )
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "apply_job":
            full_name = request.POST.get("full_name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            contact_number = request.POST.get("contact_number", "").strip()
            password = request.POST.get("password", "").strip()
            confirm_password = request.POST.get("confirm_password", "").strip()
            if not full_name or not email or not contact_number or not password or not confirm_password:
                messages.error(request, "Full Name, Email, Contact Number, Password, and Confirm Password are required.")
                return render(
                    request,
                    "candidate_portal/public_job_detail.html",
                    {"job": job, "form_data": request.POST},
                )
            if password != confirm_password:
                messages.error(request, "Password and Confirm Password do not match.")
                return render(
                    request,
                    "candidate_portal/public_job_detail.html",
                    {"job": job, "form_data": request.POST},
                )

            candidate = Candidate.objects.filter(email__iexact=email).first()
            if candidate and CandidateJobApplication.objects.filter(candidate=candidate, job=job).exists():
                print(f"[CandidatePortalEmail] Skipped: duplicate application for {email} on {job.job_id}")
                messages.error(request, "You are already apply to this job. Please login.")
                return render(
                    request,
                    "candidate_portal/public_job_detail.html",
                    {"job": job, "form_data": {}},
                )

            if not candidate:
                candidate = Candidate.objects.create(
                    full_name=full_name,
                    email=email,
                    contact_number=contact_number,
                    status="Applied",
                    applied_position=job.title or "",
                    references=PORTAL_REFERENCE_LABEL,
                )
            else:
                candidate.full_name = full_name or candidate.full_name
                candidate.contact_number = contact_number or candidate.contact_number
                candidate.status = "Applied"
                existing_refs = [item.strip() for item in (candidate.references or "").split(",") if item.strip()]
                if PORTAL_REFERENCE_LABEL not in existing_refs:
                    existing_refs.append(PORTAL_REFERENCE_LABEL)
                candidate.references = ", ".join(existing_refs)
                existing_positions = [item.strip() for item in (candidate.applied_position or "").split(",") if item.strip()]
                if job.title and job.title not in existing_positions:
                    existing_positions.append(job.title)
                candidate.applied_position = ", ".join(existing_positions)
                candidate.save(
                    update_fields=["full_name", "contact_number", "status", "applied_position", "references", "updated_at"]
                )

            first_name, last_name = _split_name(full_name)
            user_row = UserMaster.objects.filter(email_id__iexact=email).first()
            if user_row:
                user_row.first_name = first_name or user_row.first_name
                user_row.last_name = last_name
                user_row.mobile_number = contact_number or user_row.mobile_number
                user_row.password = password
                user_row.role = "Candidate"
                user_row.allowed_modules = "candidate_portal"
                user_row.status = "Active"
                user_row.save()
            else:
                UserMaster.objects.create(
                    first_name=first_name or "Candidate",
                    last_name=last_name,
                    email_id=email,
                    mobile_number=contact_number,
                    username=email.split("@")[0],
                    password=password,
                    department="Candidate",
                    designation="Applicant",
                    role="Candidate",
                    team="",
                    reporting_manager="",
                    location="",
                    employee_code="",
                    status="Active",
                    allowed_modules="candidate_portal",
                    created_by="Candidate Self Registration",
                )

            _link, created = CandidateJobApplication.objects.get_or_create(candidate=candidate, job=job)
            if created:
                job.applications_received = CandidateJobApplication.objects.filter(job=job).count()
                job.save(update_fields=["applications_received", "updated_at"])
                messages.success(request, f"Registration and application submitted successfully for {job.title}.")
            else:
                messages.error(request, "You are already apply to this job. Please login.")

            try:
                _send_candidate_portal_link_email(request, full_name, email)
                print(f"[CandidatePortalEmail] Sent: {email} for job {job.job_id}")
                request.session["candidate_portal_email_sent"] = True
            except Exception as exc:
                print(f"[CandidatePortalEmail] Failed: {email} for job {job.job_id}")
                request.session["candidate_portal_email_sent"] = False
                messages.warning(
                    request,
                    f"Application submitted, but portal email could not be sent: {exc}",
                )

            request.session["login_user_name"] = full_name
            request.session["login_user_email"] = email
            request.session["login_user_role"] = "Candidate"
            request.session["candidate_resume_required"] = True
            request.session["candidate_registration_success"] = True
            return redirect("candidate_portal:resume_upload")

    return render(request, "candidate_portal/public_job_detail.html", {"job": job, "form_data": {}})


def candidate_resume_ocr_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request method."}, status=405)

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    candidate = Candidate.objects.filter(email__iexact=login_email).first() if login_email else None
    if not candidate:
        _reset_login_session(request)
        return JsonResponse({"ok": False, "message": "Candidate profile not found."}, status=404)

    resume_upload = request.FILES.get("resume_upload")
    if not resume_upload:
        return JsonResponse({"ok": False, "message": "Resume file is required."}, status=400)
    if not _is_pdf_resume_upload(resume_upload):
        return JsonResponse({"ok": False, "message": "Resume must be uploaded in PDF format only."}, status=400)

    resume_path = _save_resume_upload_versioned_shared(candidate, resume_upload)
    candidate.resume_path = resume_path
    parsed = _parse_resume_autofill_from_upload_shared(resume_upload)
    email_conflict = _apply_parsed_resume_to_candidate(candidate, parsed)
    try:
        candidate.save()
    except IntegrityError:
        return JsonResponse(
            {
                "ok": False,
                "message": "Resume parsed, but email conflicts with another candidate profile.",
            },
            status=409,
        )
    _save_candidate_education_records_shared(
        candidate,
        parsed.get("education_records", []),
        fallback=parsed,
    )

    request.session["candidate_resume_required"] = False

    return JsonResponse(
        {
            "ok": True,
            "message": (
                "Resume uploaded and profile auto-filled."
                if not email_conflict
                else "Resume uploaded and profile auto-filled (email kept unchanged due to existing profile)."
            ),
            "fields": {
                "full_name": candidate.full_name or "",
                "email": candidate.email or "",
                "contact_number": candidate.contact_number or "",
                "social_media_link": candidate.social_media_link or "",
                "skills": candidate.skills or "",
                "experience": candidate.experience or "",
                "highest_education_level": candidate.highest_education_level or "",
                "degree_name": candidate.degree_name or "",
                "institute_name": candidate.institute_name or "",
                "year_of_passing": candidate.year_of_passing or "",
                "percentage_cgpa": candidate.percentage_cgpa or "",
                "employment_history": candidate.employment_history or "",
                "certifications": candidate.certifications or "",
                "references": candidate.references or "",
                "education_records": parsed.get("education_records", []),
                "resume_url": f"{settings.MEDIA_URL}{candidate.resume_path}" if candidate.resume_path else "",
            },
        }
    )


def candidate_ai_chat_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request method."}, status=405)

    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name and role_name != "candidate":
        return JsonResponse({"ok": False, "message": "Unauthorized."}, status=403)

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    candidate = Candidate.objects.filter(email__iexact=login_email).first() if login_email else None
    if not candidate:
        _reset_login_session(request)
        return JsonResponse({"ok": False, "message": "Candidate profile not found."}, status=404)

    if not bool(getattr(settings, "OLLAMA_ENABLED", False)):
        return JsonResponse(
            {"ok": False, "message": "Ollama is disabled. Set OLLAMA_ENABLED=1 in .env."},
            status=503,
        )

    user_message = (request.POST.get("message") or "").strip()
    if not user_message:
        return JsonResponse({"ok": False, "message": "Message is required."}, status=400)

    system_message = (
        "You are a helpful assistant inside a recruitment candidate portal. "
        "Answer concisely and politely. "
        "Do not ask for passwords, OTPs, bank details, or other sensitive info. "
        "If asked about application status, suggest checking the portal tables or contacting HR."
    )

    result = ollama_chat(
        base_url=getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=getattr(settings, "OLLAMA_MODEL", "llama3.1"),
        user_message=user_message,
        system_message=system_message,
        timeout_seconds=int(getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 60) or 60),
    )
    if not result.ok:
        return JsonResponse({"ok": False, "message": f"Ollama error: {result.error}"}, status=502)

    return JsonResponse({"ok": True, "message": result.message})


def candidate_offer_response_view(request, token: str, decision: str):
    decision_key = (decision or "").strip().lower()
    if decision_key not in {"accept", "reject"}:
        return HttpResponse("Invalid action.", status=400)

    offer = OfferLetter.objects.select_related("candidate").filter(access_token=token).first()
    if not offer:
        return HttpResponse("Offer not found.", status=404)

    # Token-based access: force candidate session when link is opened in candidate mode.
    # Prevents accidentally landing in admin-access candidate portal pages.
    candidate_mode = (request.GET.get("as") or "").strip().lower() == "candidate"
    current_role = (request.session.get("login_user_role") or "").strip().lower()
    candidate = offer.candidate
    if candidate and (candidate_mode or not current_role or current_role == "candidate"):
        request.session["login_user_name"] = (candidate.full_name or "").strip()
        request.session["login_user_email"] = (candidate.email or "").strip()
        request.session["login_user_role"] = "Candidate"

    if offer.is_expired:
        if offer.status not in {"accepted", "rejected", "expired"}:
            offer.status = "expired"
            offer.save(update_fields=["status", "updated_at"])
        return render(request, "candidate_portal/offer_response.html", {"offer": offer, "decision": "expired"})

    new_status = "accepted" if decision_key == "accept" else "rejected"
    if offer.status not in {"accepted", "rejected"}:
        offer.status = new_status
        offer.responded_at = timezone.now()
        offer.response_note = f"Candidate {new_status} via email link"
        offer.save(update_fields=["status", "responded_at", "response_note", "updated_at"])

        OnboardingInvitation.objects.filter(offer_letter=offer).update(updated_at=timezone.now())

        try:
            _create_ui_notifications(
                recipient_emails=[offer.candidate.email],
                title=f"Offer {new_status.title()}",
                message=f"Your offer response was recorded as {new_status.title()}.",
                link="/candidate-portal/",
                source="offer",
            )
        except Exception:
            pass

        try:
            portal_home = _candidate_magic_portal_url(request, offer.candidate.email, "/candidate-portal/")
            if new_status == "accepted":
                _send_candidate_notification_email(
                    request=request,
                    to_email=offer.candidate.email,
                    subject=f"Thank you - Offer Accepted ({getattr(settings, 'ATS_COMPANY_NAME', 'Ultimatix ATS')})",
                    template_name="candidate_portal/emails/offer_accepted.html",
                    context={
                        "candidate": offer.candidate,
                        "portal_url": portal_home,
                    },
                )
            else:
                _send_candidate_notification_email(
                    request=request,
                    to_email=offer.candidate.email,
                    subject=f"Offer Response Recorded ({getattr(settings, 'ATS_COMPANY_NAME', 'Ultimatix ATS')})",
                    template_name="candidate_portal/emails/offer_rejected.html",
                    context={
                        "candidate": offer.candidate,
                        "portal_url": portal_home,
                    },
                )
        except Exception:
            logger.exception("Candidate notification failed for offer response. offer_id=%s", offer.id)

        try:
            job_title = ""
            if getattr(offer, "application", None) and getattr(offer.application, "job", None):
                job_title = offer.application.job.title or ""
            subject = f"Offer {new_status.title()} - {offer.candidate.full_name} ({offer.candidate.candidate_id})"
            body_html = (
                f"<p><strong>Candidate:</strong> {offer.candidate.full_name} ({offer.candidate.candidate_id})</p>"
                f"<p><strong>Email:</strong> {offer.candidate.email}</p>"
                f"<p><strong>Job:</strong> {job_title or offer.candidate.applied_position or '—'}</p>"
                f"<p><strong>Response:</strong> {new_status.title()}</p>"
                f"<p><strong>Responded At:</strong> {timezone.localtime(offer.responded_at).strftime('%Y-%m-%d %H:%M')}</p>"
            )
            action_url = request.build_absolute_uri("/onboarding/board/")
            _send_hr_notification_email(
                request=request,
                subject=subject,
                body_html=body_html,
                action_url=action_url,
                action_label="Open Onboarding Board",
            )

            _create_ui_notifications(
                recipient_emails=_hr_admin_recipient_emails(),
                title=subject,
                message=f"Candidate responded: {new_status.title()}",
                link="/onboarding/board/",
                source="offer",
            )
        except Exception:
            logger.exception("HR notification failed for offer response. offer_id=%s", offer.id)

    portal_url = _candidate_magic_portal_url(request, offer.candidate.email if offer.candidate else "", "/candidate-portal/")
    return render(
        request,
        "candidate_portal/offer_response.html",
        {"offer": offer, "decision": new_status, "portal_url": portal_url},
    )


def candidate_offer_detail_view(request, token: str):
    offer = OfferLetter.objects.select_related("candidate", "application__job").filter(access_token=token).first()
    if not offer:
        return HttpResponse("Offer not found.", status=404)

    candidate_mode = (request.GET.get("as") or "").strip().lower() == "candidate"
    current_role = (request.session.get("login_user_role") or "").strip().lower()
    candidate = offer.candidate
    if candidate and (candidate_mode or not current_role or current_role == "candidate"):
        request.session["login_user_name"] = (candidate.full_name or "").strip()
        request.session["login_user_email"] = (candidate.email or "").strip()
        request.session["login_user_role"] = "Candidate"
        CandidatePortalProfile.objects.get_or_create(candidate=candidate)

    if offer.is_expired:
        if offer.status not in {"accepted", "rejected", "expired"}:
            offer.status = "expired"
            offer.save(update_fields=["status", "updated_at"])
        offer_rendered_html = (offer.body_html or "") if offer else ""
        return render(
            request,
            "candidate_portal/offer_detail.html",
            {"offer": offer, "is_expired": True, "offer_rendered_html": offer_rendered_html},
        )

    suffix = "?as=candidate" if candidate_mode else ""
    accept_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/accept/{suffix}")
    reject_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/reject/{suffix}")

    job = offer.application.job if getattr(offer, "application", None) and getattr(offer.application, "job", None) else None
    company_name = getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS")
    ctx = {
        "company_name": company_name,
        "candidate_name": (offer.candidate.full_name or "").strip() if offer.candidate else "",
        "candidate_id": (offer.candidate.candidate_id or "").strip() if offer.candidate else "",
        "candidate_email": (offer.candidate.email or "").strip() if offer.candidate else "",
        "job_title": (getattr(job, "title", "") or "").strip(),
        "offer_id": str(getattr(offer, "id", "") or ""),
        "offer_date": timezone.localdate().strftime("%Y-%m-%d"),
        "department": (getattr(job, "department", "") or "").strip(),
        "work_location": (getattr(job, "location", "") or "").strip(),
        "employment_type": (getattr(job, "employment_type", "") or "").strip(),
        "reporting_manager": "",
        "joining_date": "",
        "ctc_annual": "",
        "base_pay": "",
        "benefits": "",
        "hr_email": "",
        "portal_url": _candidate_magic_portal_url(request, (offer.candidate.email or "") if offer.candidate else "", "/candidate-portal/"),
        "accept_url": accept_url,
        "reject_url": reject_url,
        "offer_view_url": request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/{suffix}"),
        "onboarding_url": "",
    }
    try:
        offer_rendered_html = Template(str(offer.body_html or "")).render(Context(ctx, autoescape=True))
    except Exception:
        offer_rendered_html = str(offer.body_html or "")
    return render(
        request,
        "candidate_portal/offer_detail.html",
        {
            "offer": offer,
            "is_expired": False,
            "accept_url": accept_url,
            "reject_url": reject_url,
            "offer_rendered_html": offer_rendered_html,
        },
    )


def _onboarding_field_defs():
    return {
        # Personal information (mirrors "JOINING KIT" Google Form)
        "full_name": {"label": "Name of the Candidate", "type": "text", "required": True},
        "father_or_husband_name": {"label": "Full Name of Father / Husband", "type": "text", "required": True},
        "mother_name": {"label": "Full Name of Mother", "type": "text", "required": True},
        "present_address": {"label": "Present Address", "type": "textarea", "required": True},
        "permanent_address": {"label": "Permanent Address", "type": "textarea", "required": True},
        "residence_contact_no": {"label": "Residence Contact Nos.", "type": "text", "required": True},
        "mobile_no": {"label": "Mobile No", "type": "tel", "required": True},
        "email": {"label": "Email Id", "type": "email", "required": True},
        "gender": {"label": "Gender", "type": "radio", "required": True, "choices": ["Male", "Female"]},
        "blood_group": {
            "label": "Blood Group",
            "type": "radio",
            "required": True,
            "choices": ["A positive (A+)", "A negative (A-)", "B positive (B+)", "B negative (B-)", "AB positive (AB+)", "AB negative (AB-)", "O positive (O+)", "O negative (O-)"],
        },
        "marital_status": {"label": "Marital Status", "type": "radio", "required": True, "choices": ["Single", "Married"]},
        "marriage_date": {"label": "Marriage Date", "type": "date", "required": False},
        "age": {"label": "Age", "type": "text", "required": True},
        "date_of_birth": {"label": "Date of Birth", "type": "date", "required": True},
        "identification_mark": {"label": "Identification Mark (If Any)", "type": "text", "required": True},
        "pan": {"label": "PAN No", "type": "text", "required": True},
        "aadhaar": {"label": "Aadhar No.", "type": "text", "required": True},
        "passport_no": {"label": "Passport No.", "type": "text", "required": False},
        "uan_number": {"label": "UAN Number", "type": "text", "required": False},
        "languages_known": {
            "label": "Languages Known: Please Tick (✓)",
            "type": "matrix",
            "required": True,
            "rows": ["English", "Hindi", "Gujarati"],
            "cols": ["Read", "Write", "Speak"],
        },
        "computer_skill": {"label": "Computer Skill", "type": "text", "required": True},
        "driving_license": {"label": "Driving License", "type": "radio", "required": True, "choices": ["Yes", "No"]},
        "two_wheeler": {"label": "Two Wheeler", "type": "radio", "required": True, "choices": ["Yes", "No"]},
        "total_work_experience": {"label": "Total Work Experience", "type": "text", "required": True},
        "previous_employment_details": {"label": "Previous Employment details", "type": "textarea", "required": True},
        "reason_for_joining": {"label": "Reason for Joining Orange Technolab Pvt LTD", "type": "textarea", "required": True},
        "professional_references": {
            "label": "Two Professional References (Name, Address & Phone Number)",
            "type": "textarea",
            "required": True,
        },
        "family_background": {
            "label": "Family Background (Sr. No, Name, Age, Occupation, Relationship, Dependents)",
            "type": "textarea",
            "required": True,
        },
        "emergency_contact_name": {"label": "Name of Contact Person in case of Emergency", "type": "text", "required": True},
        "emergency_contact_no": {"label": "Contact No. in case of Emergency", "type": "text", "required": True},
        "declaration_personal": {
            "label": "Declaration",
            "type": "checkbox",
            "required": True,
            "help": "I hereby declare that the above information is correct & as per best of my knowledge.",
        },

        # Bank account details
        "bank_name": {"label": "Bank Name", "type": "text", "required": True},
        "bank_account_name": {"label": "Name (as per bank Account)", "type": "text", "required": True},
        "bank_account_no": {"label": "Bank Account No.", "type": "text", "required": True},
        "bank_branch_address": {"label": "Bank Branch Address", "type": "text", "required": True},
        "micr_no": {"label": "Micr No. (9 Digit)", "type": "text", "required": True},
        "ifsc_code": {"label": "IFSC CODE (11Digit)", "type": "text", "required": True},
        "email_id_if_any": {"label": "Email id (if any)", "type": "email", "required": True},
        "sub_broker_mobile": {"label": "Mobile No. of Sub-broker/Dealer", "type": "text", "required": True},
        "nominee_details": {"label": "Nominee Details", "type": "textarea", "required": True},
        "declaration_bank": {
            "label": "Declaration (Bank)",
            "type": "checkbox",
            "required": True,
            "help": "I hereby declare that the above information is correct & as per best of my knowledge.",
        },
    }


def candidate_onboarding_register_view(request, token: str):
    invitation = OnboardingInvitation.objects.select_related("candidate", "offer_letter", "form_template").filter(token=token).first()
    if not invitation:
        return HttpResponse("Invalid onboarding link.", status=404)
    if invitation.is_expired:
        return HttpResponse("This onboarding link has expired.", status=410)

    candidate = invitation.candidate
    # This is a candidate-facing, token-authenticated flow. Force the session into candidate context
    # so the user is not redirected to admin-access candidate portal views.
    request.session["login_user_name"] = (candidate.full_name or "").strip()
    request.session["login_user_email"] = (candidate.email or "").strip()
    request.session["login_user_role"] = "Candidate"

    existing_user = UserMaster.objects.filter(email_id__iexact=candidate.email).first()

    if request.method == "POST":
        password = (request.POST.get("password") or "").strip()
        confirm_password = (request.POST.get("confirm_password") or "").strip()
        if not password or not confirm_password:
            messages.error(request, "Password and Confirm Password are required.")
            return redirect(request.path)
        if password != confirm_password:
            messages.error(request, "Password and Confirm Password do not match.")
            return redirect(request.path)

        first_name, last_name = _split_name(candidate.full_name or "")
        full_name = (candidate.full_name or "").strip() or f"{first_name} {last_name}".strip()

        if existing_user:
            existing_user.password = password
            existing_user.full_name = full_name
            existing_user.first_name = first_name or existing_user.first_name
            existing_user.last_name = last_name or existing_user.last_name
            existing_user.mobile_number = candidate.contact_number or existing_user.mobile_number
            existing_user.role = "Candidate"
            existing_user.allowed_modules = "candidate_portal"
            existing_user.save()
        else:
            UserMaster.objects.create(
                first_name=first_name or "Candidate",
                last_name=last_name or "",
                full_name=full_name,
                email_id=candidate.email,
                mobile_number=candidate.contact_number or "",
                username=candidate.email,
                password=password,
                role="Candidate",
                designation="Candidate",
                team="",
                reporting_manager="",
                location="",
                employee_code="",
                status="Active",
                allowed_modules="candidate_portal",
                created_by="Onboarding Invitation Registration",
            )

        CandidatePortalProfile.objects.get_or_create(candidate=candidate)

        request.session["login_user_name"] = full_name
        request.session["login_user_email"] = candidate.email
        request.session["login_user_role"] = "Candidate"

        if invitation.status == "pending":
            invitation.status = "registered"
            invitation.save(update_fields=["status", "updated_at"])

        return redirect(f"/candidate-portal/onboarding/{invitation.token}/form/")

    return render(
        request,
        "candidate_portal/onboarding_register.html",
        {"invitation": invitation, "candidate": candidate, "has_account": bool(existing_user)},
    )


def candidate_onboarding_form_view(request, token: str):
    invitation = OnboardingInvitation.objects.select_related("candidate", "offer_letter", "form_template").filter(token=token).first()
    if not invitation:
        return HttpResponse("Invalid onboarding link.", status=404)
    if invitation.is_expired:
        return HttpResponse("This onboarding link has expired.", status=410)

    candidate = invitation.candidate
    offer = invitation.offer_letter
    # Candidate-facing, token-authenticated flow: force candidate session context.
    request.session["login_user_name"] = (candidate.full_name or "").strip()
    request.session["login_user_email"] = (candidate.email or "").strip()
    request.session["login_user_role"] = "Candidate"
    CandidatePortalProfile.objects.get_or_create(candidate=candidate)

    if offer and offer.status != "accepted":
        accept_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/accept/?as=candidate")
        reject_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/reject/?as=candidate")
        offer_view_url = request.build_absolute_uri(f"/candidate-portal/offer/{offer.access_token}/?as=candidate")
        return render(
            request,
            "candidate_portal/onboarding_form_locked.html",
            {"candidate": candidate, "offer": offer, "accept_url": accept_url, "reject_url": reject_url, "offer_view_url": offer_view_url},
        )

    field_defs = _onboarding_field_defs()
    selected_fields = []
    document_requirements = []
    if invitation.form_template and invitation.form_template.is_active:
        selected_fields = list(invitation.form_template.selected_fields or [])
        document_requirements = list(invitation.form_template.document_requirements or [])
    if isinstance(getattr(invitation, "document_requirements_override", None), list) and invitation.document_requirements_override:
        document_requirements = list(invitation.document_requirements_override or [])
    if not selected_fields:
        selected_fields = [
            "full_name",
            "father_or_husband_name",
            "mother_name",
            "present_address",
            "permanent_address",
            "residence_contact_no",
            "mobile_no",
            "email",
            "gender",
            "blood_group",
            "marital_status",
            "marriage_date",
            "age",
            "date_of_birth",
            "identification_mark",
            "pan",
            "aadhaar",
            "passport_no",
            "uan_number",
            "languages_known",
            "computer_skill",
            "driving_license",
            "two_wheeler",
            "total_work_experience",
            "previous_employment_details",
            "reason_for_joining",
            "professional_references",
            "family_background",
            "emergency_contact_name",
            "emergency_contact_no",
            "declaration_personal",
            "bank_name",
            "bank_account_name",
            "bank_account_no",
            "bank_branch_address",
            "micr_no",
            "ifsc_code",
            "email_id_if_any",
            "sub_broker_mobile",
            "nominee_details",
            "declaration_bank",
        ]
    if not document_requirements:
        document_requirements = [
            "passport_photo",
            "residency_proof",
            "pan_card_copy",
            "aadhaar_card_copy_pdf",
            "passport_copy",
            "educational_qualification",
            "cancelled_cheque_copy",
        ]

    submission, _created = OnboardingSubmission.objects.get_or_create(invitation=invitation)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action != "submit_onboarding":
            messages.error(request, "Invalid action.")
            return redirect(request.path)

        form_data = {}
        for key in selected_fields:
            if key not in field_defs:
                continue
            fdef = field_defs[key]
            ftype = (fdef.get("type") or "text").strip().lower()
            if ftype == "checkbox":
                form_data[key] = bool(request.POST.get(key))
            elif ftype == "matrix":
                rows = list(fdef.get("rows") or [])
                cols = list(fdef.get("cols") or [])
                matrix = {}
                for r in rows:
                    row_key = str(r)
                    matrix[row_key] = {}
                    for c in cols:
                        col_key = str(c)
                        post_key = f"{key}__{row_key}__{col_key}"
                        matrix[row_key][col_key] = bool(request.POST.get(post_key))
                form_data[key] = matrix
            else:
                form_data[key] = (request.POST.get(key) or "").strip()

        submission.form_data = form_data
        submission.status = "submitted"
        submission.submitted_at = timezone.now()
        submission.save(update_fields=["form_data", "status", "submitted_at", "updated_at"])

        for doc_key in document_requirements:
            upload = request.FILES.get(f"doc_{doc_key}")
            if not upload:
                continue
            OnboardingDocument.objects.create(submission=submission, document_key=doc_key, file=upload)

        invitation.status = "submitted"
        invitation.save(update_fields=["status", "updated_at"])

        try:
            external_form_url = (getattr(settings, "ONBOARDING_DOCUMENT_EXTERNAL_FORM_URL", "") or "").strip()
            _send_candidate_notification_email(
                request=request,
                to_email=candidate.email,
                subject=f"Documents Submitted Successfully ({getattr(settings, 'ATS_COMPANY_NAME', 'Ultimatix ATS')})",
                template_name="candidate_portal/emails/onboarding_submitted.html",
                context={
                    "candidate": candidate,
                    "portal_url": _candidate_magic_portal_url(request, candidate.email, "/candidate-portal/onboarding-documents/"),
                    "external_form_url": external_form_url,
                },
            )
        except Exception:
            logger.exception("Candidate notification failed for onboarding submission. submission_id=%s", submission.id)

        try:
            subject = f"Onboarding Documents Submitted - {candidate.full_name} ({candidate.candidate_id})"
            body_html = (
                f"<p><strong>Candidate:</strong> {candidate.full_name} ({candidate.candidate_id})</p>"
                f"<p><strong>Email:</strong> {candidate.email}</p>"
                f"<p><strong>Status:</strong> Documents Submitted</p>"
                f"<p><strong>Submitted At:</strong> {timezone.localtime(submission.submitted_at).strftime('%Y-%m-%d %H:%M')}</p>"
            )
            if external_form_url:
                body_html += f"<p><strong>Form link:</strong> <a href=\"{external_form_url}\" target=\"_blank\" rel=\"noopener noreferrer\">{external_form_url}</a></p>"
            action_url = request.build_absolute_uri(f"/onboarding/approvals/{submission.id}/")
            _send_hr_notification_email(
                request=request,
                subject=subject,
                body_html=body_html,
                action_url=action_url,
                action_label="Review Submission",
            )
            _create_ui_notifications(
                recipient_emails=_hr_admin_recipient_emails(),
                title=subject,
                message="Documents submitted and ready for review.",
                link=f"/onboarding/approvals/{submission.id}/",
                source="onboarding",
            )
        except Exception:
            logger.exception("HR notification failed for onboarding submission. submission_id=%s", submission.id)

        messages.success(request, "Onboarding form and documents submitted successfully.")
        return redirect("/candidate-portal/onboarding-documents/")

    existing_docs = list(submission.documents.all())
    field_rows = []
    for key in selected_fields:
        if key not in field_defs:
            continue
        fdef = field_defs[key]
        ftype = (fdef.get("type") or "text").strip().lower()
        value = (submission.form_data or {}).get(key, "")
        matrix_checked = []
        if ftype == "matrix" and isinstance(value, dict):
            try:
                for r in list(fdef.get("rows") or []):
                    for c in list(fdef.get("cols") or []):
                        if bool(value.get(str(r), {}).get(str(c))):
                            matrix_checked.append(f"{r}__{c}")
            except Exception:
                matrix_checked = []
        field_rows.append(
            {
                "key": key,
                "label": fdef.get("label", key),
                "type": fdef.get("type", "text"),
                "required": bool(fdef.get("required")),
                "choices": list(fdef.get("choices") or []),
                "rows": list(fdef.get("rows") or []),
                "cols": list(fdef.get("cols") or []),
                "help": (fdef.get("help") or "").strip(),
                "value": value,
                "matrix_checked": matrix_checked,
            }
        )

    doc_labels = {
        "passport_photo": "Affix Recent Passport Size Photograph (Blue Background only)",
        "residency_proof": "Please attach residency proof",
        "pan_card_copy": "Attach Copy of PAN Card",
        "aadhaar_card_copy_pdf": "Attach full copy of Aadhar Card with front and back (In PDF only)",
        "passport_copy": "Attach Copy of Passport",
        "educational_qualification": "Educational Qualification",
        "cancelled_cheque_copy": "Attach copy of cancelled cheque",
    }
    document_rows = [{"key": k, "label": doc_labels.get(k, (str(k).replace("_", " ").strip() or k))} for k in document_requirements]
    return render(
        request,
        "candidate_portal/onboarding_form.html",
        {
            "invitation": invitation,
            "candidate": candidate,
            "offer": offer,
            "submission": submission,
            "field_rows": field_rows,
            "document_requirements": document_requirements,
            "document_rows": document_rows,
            "existing_docs": existing_docs,
        },
    )


def candidate_onboarding_documents_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name and role_name != "candidate":
        return redirect("candidate_portal:admin_access")

    login_email = (request.session.get("login_user_email") or "").strip().lower()
    if not login_email:
        messages.error(request, "Please login to access candidate portal.")
        return redirect("/login/")

    candidate = Candidate.objects.filter(email__iexact=login_email).first()
    if not candidate:
        _reset_login_session(request)
        messages.error(request, "Candidate profile not found.")
        return redirect("/login/")

    invitation = (
        OnboardingInvitation.objects.select_related("offer_letter", "form_template")
        .filter(candidate=candidate)
        .order_by("-created_at")
        .first()
    )

    document_requirements = []
    try:
        if invitation and isinstance(getattr(invitation, "document_requirements_override", None), list) and invitation.document_requirements_override:
            document_requirements = list(invitation.document_requirements_override or [])
        elif invitation and invitation.form_template and isinstance(getattr(invitation.form_template, "document_requirements", None), list):
            document_requirements = list(invitation.form_template.document_requirements or [])
    except Exception:
        document_requirements = []

    last_doc_request = None
    try:
        last_doc_request = (
            UiNotification.objects.filter(recipient_name__iexact=candidate.email, title__iexact="Onboarding Documents Requested")
            .order_by("-created_at")
            .first()
        )
    except Exception:
        last_doc_request = None

    submission = (
        OnboardingSubmission.objects.select_related("invitation")
        .filter(invitation__candidate=candidate)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if not submission and invitation:
        submission = OnboardingSubmission.objects.filter(invitation=invitation).first()

    documents = list(submission.documents.all()) if submission else []
    upload_url = f"/candidate-portal/onboarding/{invitation.token}/form/" if invitation else ""

    return render(
        request,
        "candidate_portal/onboarding_documents.html",
        {
            "candidate": candidate,
            "invitation": invitation,
            "submission": submission,
            "documents": documents,
            "upload_url": upload_url,
            "document_requirements": document_requirements,
            "last_doc_request": last_doc_request,
        },
    )


def candidate_magic_login_view(request, token: str):
    """
    Candidate-only magic link for email flows (e.g., stage update emails).
    Verifies a signed token, sets candidate session, then redirects into Candidate Portal.
    """

    signer = signing.TimestampSigner(salt="candidate_portal_magic")
    try:
        email = signer.unsign(token, max_age=7 * 24 * 60 * 60)
    except signing.SignatureExpired:
        return HttpResponse("This link has expired. Please login again.", status=410)
    except signing.BadSignature:
        return HttpResponse("Invalid link.", status=400)

    email = (email or "").strip()
    if not email:
        return HttpResponse("Invalid link.", status=400)

    candidate = Candidate.objects.filter(email__iexact=email).first()
    if not candidate:
        return HttpResponse("Candidate profile not found.", status=404)

    request.session["login_user_name"] = (candidate.full_name or "").strip()
    request.session["login_user_email"] = (candidate.email or "").strip()
    request.session["login_user_role"] = "Candidate"
    CandidatePortalProfile.objects.get_or_create(candidate=candidate)

    next_url = (request.GET.get("next") or "").strip()
    if next_url and next_url.startswith("/candidate-portal/"):
        return redirect(next_url)
    return redirect("/candidate-portal/application-pipeline/")


def candidate_onboarding_signature_view(request, token: str):
    signature_request = (
        OnboardingSignatureRequest.objects.select_related("submission__invitation__candidate")
        .filter(token=token)
        .first()
    )
    if not signature_request:
        return HttpResponse("Invalid signature link.", status=404)

    submission = signature_request.submission
    candidate = submission.invitation.candidate

    # Candidate-only, token-authenticated flow: force candidate session context.
    request.session["login_user_name"] = (candidate.full_name or "").strip()
    request.session["login_user_email"] = (candidate.email or "").strip()
    request.session["login_user_role"] = "Candidate"
    CandidatePortalProfile.objects.get_or_create(candidate=candidate)

    if signature_request.status in {"final_approved"}:
        return render(
            request,
            "candidate_portal/onboarding_signature.html",
            {"candidate": candidate, "submission": submission, "signature_request": signature_request, "already_signed": True},
        )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action != "submit_signature":
            messages.error(request, "Invalid action.")
            return redirect(request.path)

        signature_data = (request.POST.get("signature_data") or "").strip()
        if not signature_data.startswith("data:image/"):
            messages.error(request, "Signature is required.")
            return redirect(request.path)

        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT')

        doc_id = (request.POST.get("doc_id") or "").strip()
        target_doc = None
        if doc_id.isdigit():
            target_doc = OnboardingSignDocument.objects.filter(id=int(doc_id), signature_request=signature_request).first()

        # If multiple docs exist, candidate must sign the selected one.
        docs = list(signature_request.documents.all())
        if docs and not target_doc:
            messages.error(request, "Please select a document to sign.")
            return redirect(request.path)

        if not docs and getattr(signature_request, "document_pdf", None) and not target_doc:
            # legacy fallback: treat request as single doc
            target_doc = None

        if signature_request.status == "pending":
            # Determine which PDF to sign.
            pdf_file = None
            page_number = 1
            pos_x = signature_request.position_x
            pos_y = signature_request.position_y
            blk_w = signature_request.width
            blk_h = signature_request.height
            if target_doc:
                pdf_file = target_doc.document_pdf
                page_number = target_doc.page_number
                pos_x = target_doc.position_x
                pos_y = target_doc.position_y
                blk_w = target_doc.width
                blk_h = target_doc.height
            else:
                pdf_file = getattr(signature_request, "document_pdf", None)
                page_number = getattr(signature_request, "page_number", 1)

            signed_ok = False
            signature_request.signature_data = signature_data

            if pdf_file:
                signed_ok = False
                try:
                    import base64
                    import io
                    import os
                    import tempfile

                    from django.core.files.base import ContentFile
                    from django.core.files.storage import default_storage

                    try:
                        from pypdf import PdfReader, PdfWriter
                    except Exception:
                        try:
                            from PyPDF2 import PdfReader, PdfWriter
                        except Exception:
                            PdfReader = None
                            PdfWriter = None

                    from reportlab.pdfgen import canvas
                    from reportlab.lib.utils import ImageReader

                    if PdfReader and PdfWriter:
                        raw = signature_data.split(",", 1)[1] if "," in signature_data else ""
                        img_bytes = base64.b64decode(raw)

                        # Save signature image to a temp file for reportlab.
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                            tmp_img.write(img_bytes)
                            tmp_img_path = tmp_img.name

                        reader = PdfReader(pdf_file.open("rb"))
                        writer = PdfWriter()
                        for page_index, page in enumerate(reader.pages):
                            writer.add_page(page)

                        target_index = max(0, int(page_number or 1) - 1)
                        if target_index >= len(writer.pages):
                            target_index = 0

                        page = writer.pages[target_index]
                        page_width = float(page.mediabox.width)
                        page_height = float(page.mediabox.height)

                        x = (float(pos_x or 70.0) / 100.0) * page_width
                        y = page_height - ((float(pos_y or 80.0) / 100.0) * page_height) - float(blk_h or 70.0)
                        w = float(blk_w or 180.0)
                        h = float(blk_h or 70.0)

                        packet = io.BytesIO()
                        c = canvas.Canvas(packet, pagesize=(page_width, page_height))
                        c.drawImage(ImageReader(tmp_img_path), x, y, width=w, height=h, mask="auto")
                        c.save()
                        packet.seek(0)

                        overlay = PdfReader(packet)
                        if overlay.pages:
                            page.merge_page(overlay.pages[0])

                        out = io.BytesIO()
                        writer.write(out)
                        out.seek(0)
                        content = out.read()

                        # Save into media storage.
                        suffix = f"{target_doc.id}_" if target_doc else ""
                        safe_name = f"onboarding/signatures/signed/{candidate.candidate_id}_{submission.id}_{suffix}signed.pdf"
                        saved_path = default_storage.save(safe_name, ContentFile(content))
                        if target_doc:
                            target_doc.signed_pdf.name = saved_path
                        else:
                            signature_request.signed_pdf.name = saved_path
                        signed_ok = True

                        if signed_ok:
                            # Log DOCUMENT_SIGNED
                            OnboardingAuditLog.objects.create(
                                candidate=candidate,
                                action="DOCUMENT_SIGNED",
                                details={
                                    "document_id": target_doc.id if target_doc else None,
                                    "document_title": target_doc.title if target_doc else "Onboarding Document"
                                },
                                ip_address=ip_address,
                                user_agent=user_agent
                            )
                            
                            # Generate Certificate
                            try:
                                generate_signing_certificate(signature_request, doc=target_doc, ip_address=ip_address, user_agent=user_agent)
                            except Exception:
                                logger.exception("Failed to generate signing certificate for submission_id=%s", submission.id)

                        try:
                            os.unlink(tmp_img_path)
                        except Exception:
                            pass
                except Exception:
                    logger.exception("Failed to generate signed PDF. submission_id=%s", submission.id)

                if not signed_ok:
                    messages.error(
                        request,
                        "Could not generate the signed PDF. Please try again or contact HR.",
                    )
                    signature_request.signature_data = ""
                    signature_request.save(update_fields=["signature_data", "updated_at"])
                    return redirect(request.path)

            now_ts = timezone.now()
            if target_doc:
                target_doc.status = "signed"
                target_doc.signed_at = now_ts
                target_doc.save(update_fields=["signed_pdf", "status", "signed_at", "updated_at"])

            # If all docs are signed (or legacy single-doc), mark request signed.
            remaining = list(signature_request.documents.filter(status="pending"))
            if not remaining:
                signature_request.status = "signed"
                signature_request.signed_at = now_ts
                signature_request.rejection_reason = ""
                signature_request.save(update_fields=["signature_data", "signed_pdf", "status", "signed_at", "rejection_reason", "updated_at"])

            # Notify HR/Admin (email + in-app bell) that signature is completed.
            try:
                subject = f"Signature Completed - {candidate.full_name} ({candidate.candidate_id})"
                body_html = (
                    f"<p><strong>Candidate:</strong> {candidate.full_name} ({candidate.candidate_id})</p>"
                    f"<p><strong>Email:</strong> {candidate.email}</p>"
                    f"<p><strong>Status:</strong> Signed</p>"
                )
                action_url = request.build_absolute_uri(f"/onboarding/approvals/{submission.id}/")
                _send_hr_notification_email(
                    request=request,
                    subject=subject,
                    body_html=body_html,
                    action_url=action_url,
                    action_label="Review & Final Approve",
                )
                _create_ui_notifications(
                    recipient_emails=_hr_admin_recipient_emails(),
                    title=subject,
                    message="Candidate completed signing. Final approval pending.",
                    link=f"/onboarding/approvals/{submission.id}/",
                    source="signature",
                )
            except Exception:
                logger.exception("HR notification failed for signature completion. submission_id=%s", submission.id)

            messages.success(request, "Signature submitted successfully.")
        return redirect(request.path)

    return render(
        request,
        "candidate_portal/onboarding_signature.html",
        {
            "candidate": candidate,
            "submission": submission,
            "signature_request": signature_request,
            "already_signed": signature_request.status != "pending" and not signature_request.documents.filter(status="pending").exists(),
            "sign_documents": list(signature_request.documents.all()),
            "sign_documents_json": [
                {
                    "id": d.id,
                    "title": d.title,
                    "document_pdf": d.document_pdf.url if getattr(d, "document_pdf", None) else "",
                    "signed_pdf": d.signed_pdf.url if getattr(d, "signed_pdf", None) else "",
                    "page_number": d.page_number,
                    "position_x": float(d.position_x or 0),
                    "position_y": float(d.position_y or 0),
                    "width": float(d.width or 0),
                    "height": float(d.height or 0),
                    "status": d.status,
                }
                for d in signature_request.documents.all()
            ],
        },
    )
