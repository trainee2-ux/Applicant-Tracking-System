import os
import json
import logging
import re
import tempfile
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage, EmailMultiAlternatives, send_mail, get_connection
from django.core import signing
from django.template.loader import render_to_string
from django.template import Template, Context
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.db.models import Avg, Prefetch
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.utils import timezone
from app_settings.constants import INTERVIEW_ROUND_OPTIONS
from app_settings.models import City, Country, EducationLevel, State
from app_settings.models import AssessmentForm, EmailDeliveryConfig, EmailTemplate, UserMaster
from interview_evaluation.models import InterviewEvaluationSubmission
from applicant_tracking.models import InPersonInterview, VideoInterviewSchedule
from job_requisition.models import JobRequisition

from .models import (
    Candidate,
    CandidateActivity,
    CandidateEducation,
    CandidateEvaluation,
    CandidateJobApplication,
    CandidateNote,
    ProfilePhotoVersion,
    ResumeVersion,
)


def _normalize_smtp_password(host: str, password: str) -> str:
    cleaned_host = (host or "").strip().lower()
    cleaned_password = (password or "").strip()
    if not cleaned_password:
        return ""
    if cleaned_host in {"smtp.gmail.com", "smtp.googlemail.com"}:
        if " " in cleaned_password:
            compact = cleaned_password.replace(" ", "")
            if len(compact) == 16:
                return compact
    return cleaned_password
from .resume_scoring import score_resume_against_job
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None

    class InvalidToken(Exception):
        pass

try:
    from pyresparser import ResumeParser
except Exception:
    ResumeParser = None

try:
    import fitz
except Exception:
    fitz = None

try:
    from pypdf import PdfReader
except Exception:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        PdfReader = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

try:
    from PIL import Image
except Exception:
    Image = None

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


STATUS_OPTIONS = [
    "Applied",
    "Screened",
    "In Progress",
    "Under Review",
    "Technical Interview",
    "Shortlist",
    "Move to Next Round",
    "On-Hold",
    "Hired",
    "Rejected",
]

EVALUATION_BASE_STATUSES = [
    "Hired",
    "On-Hold",
    "Strong Hire",
    "Shortlist",
    "Wait-List",
    "Move to Next Round",
]


def _candidate_management_access_guard(request):
    login_role = (request.session.get("login_user_role") or "").strip().lower()
    if login_role == "candidate":
        messages.error(request, "Access denied. Candidates can view only their own Candidate Portal data.")
        return redirect("candidate_portal:index")
    return None


def _notify_candidate_status_change(request, candidate, previous_status):
    previous = (previous_status or "").strip()
    current = (candidate.status or "").strip()
    if not current or previous.lower() == current.lower():
        return

    try:
        _send_candidate_stage_update_email(
            request=request,
            candidate=candidate,
            job_title=candidate.applied_position or "",
            previous_stage=previous,
            new_stage=current,
        )
    except Exception as exc:
        logger.exception("Candidate stage update email failed for %s: %s", candidate.candidate_id, exc)


def _send_candidate_stage_update_email(*, request, candidate, job_title: str, previous_stage: str, new_stage: str) -> None:
    """
    Send a single branded stage update email to the candidate (HTML + text fallback).
    """

    if not candidate or not (candidate.email or "").strip():
        return
    if not new_stage or (previous_stage or "").strip().lower() == (new_stage or "").strip().lower():
        return

    def _render_template(text, context):
        if not text:
            return ""
        try:
            return Template(str(text)).render(Context(context or {}, autoescape=True))
        except Exception:
            rendered = str(text)
            for key, value in (context or {}).items():
                pattern = r"{{\s*" + re.escape(str(key)) + r"\s*}}"
                rendered = re.sub(pattern, str(value or ""), rendered, flags=re.IGNORECASE)
            return rendered

    def _looks_like_full_html(value: str) -> bool:
        snippet = (value or "").strip().lower()
        if not snippet:
            return False
        return "<!doctype" in snippet[:400] or "<html" in snippet[:400] or "<head" in snippet[:800]

    def _normalize_trigger(value: str) -> str:
        cleaned = (value or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    company_name = getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS")

    stage_key = _normalize_trigger(new_stage).replace(" ", "_")
    stage_trigger = f"candidate_stage:{stage_key}" if stage_key else ""

    template = None
    if stage_trigger:
        template = EmailTemplate.objects.filter(is_active=True, trigger__iexact=stage_trigger).order_by("-updated_at").first()
    if not template:
        template = EmailTemplate.objects.filter(is_active=True, trigger__iexact="candidate_stage_update").order_by("-updated_at").first()
    if not template:
        template = EmailTemplate.objects.filter(is_active=True, name__iexact="Stage Update").first()
    signer = signing.TimestampSigner(salt="candidate_portal_magic")
    token = signer.sign(candidate.email)
    portal_url = request.build_absolute_uri(f"/candidate-portal/magic/{token}/") if request else "/candidate-portal/"

    context = {
        "candidate_name": candidate.full_name or "",
        "candidate_email": candidate.email or "",
        "candidate_id": candidate.candidate_id or "",
        "job_title": job_title or "",
        "previous_stage": previous_stage or "",
        "current_status": new_stage or "",
        "new_stage": new_stage or "",
        "stage": new_stage or "",
        "company_name": company_name,
        "today": timezone.localdate().isoformat(),
        "portal_url": portal_url,
    }

    subject = _render_template(template.subject, context) if template else f"Application Stage Update - {new_stage}"
    inner_html = _render_template(template.body, context) if template else (
        f"<p>Hi {candidate.full_name},</p>"
        "<p>Your application stage has been updated.</p>"
        f"<p><strong>Job Applied:</strong> {job_title}<br>"
        f"<strong>Previous Stage:</strong> {previous_stage}<br>"
        f"<strong>New Stage:</strong> {new_stage}</p>"
        f"<p>Regards,<br>{company_name}</p>"
    )

    if template and _looks_like_full_html(template.body):
        body_html = inner_html
    else:
        body_html = render_to_string(
            "applicant_tracking/emails/stage_update.html",
            {
                "candidate": candidate,
                "job_title": job_title,
                "previous_stage": previous_stage,
                "new_stage": new_stage,
                "body_html": inner_html,
                "company_name": company_name,
                "portal_url": portal_url,
            },
        )
    body_text = re.sub(r"<[^>]+>", "", inner_html).strip() or (
        f"Hi {candidate.full_name},\n\nYour application stage updated to {new_stage}."
    )

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    if not (email_config and email_config.smtp_enabled and email_config.host):
        logger.warning("stage update email skipped: smtp not configured or host empty")
        return

    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=email_config.host,
        port=email_config.port or 587,
        username=email_config.username or "",
        password=_normalize_smtp_password(email_config.host, email_config.password or ""),
        use_tls=email_config.use_tls,
    )
    from_email = (email_config.from_email or "").strip() or (email_config.username or "").strip() or settings.DEFAULT_FROM_EMAIL

    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email,
        to=[candidate.email],
        connection=connection,
    )
    message.attach_alternative(body_html, "text/html")
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.exception("stage update email send failed candidate=%s err=%s", getattr(candidate, "candidate_id", ""), exc)
        raise


def _is_pdf_upload(file_obj):
    if not file_obj:
        return True
    filename = (file_obj.name or "").lower()
    if not filename.endswith(".pdf"):
        return False
    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type and content_type not in {"application/pdf", "application/x-pdf", "application/octet-stream"}:
        return False
    return True


def _save_resume_upload(file_obj):
    if not file_obj:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    return default_storage.save(f"resumes/{safe_name}", file_obj)


def _get_fernet():
    if Fernet is None:
        return None
    key = (getattr(settings, "FILE_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def _encrypt_bytes(data):
    fernet = _get_fernet()
    if not fernet:
        return data
    return fernet.encrypt(data)


def _decrypt_bytes(data):
    fernet = _get_fernet()
    if not fernet:
        return data
    try:
        return fernet.decrypt(data)
    except InvalidToken:
        return data


def _save_encrypted_upload(file_obj, storage_path):
    if not file_obj:
        return ""
    data = file_obj.read()
    file_obj.seek(0)
    encrypted = _encrypt_bytes(data)
    return default_storage.save(storage_path, ContentFile(encrypted))


def _read_storage_bytes(storage_path):
    if not storage_path:
        return b""
    with default_storage.open(storage_path, "rb") as handle:
        data = handle.read()
    return _decrypt_bytes(data)


def _register_resume_version(candidate, resume_path):
    if not candidate or not resume_path:
        return
    if ResumeVersion.objects.filter(candidate=candidate, file_path=resume_path).exists():
        return
    latest = ResumeVersion.objects.filter(candidate=candidate).order_by("-version").first()
    next_version = (latest.version + 1) if latest else 1
    ResumeVersion.objects.create(
        candidate=candidate,
        version=next_version,
        file_path=resume_path,
    )


def _save_resume_upload_versioned(candidate, file_obj):
    if not file_obj or not candidate:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    latest = ResumeVersion.objects.filter(candidate=candidate).order_by("-version").first()
    next_version = (latest.version + 1) if latest else 1
    prefix = candidate.candidate_id or f"cand{candidate.id}"
    versioned_name = f"{prefix}_v{next_version}_{safe_name}"
    path = _save_encrypted_upload(file_obj, f"resumes/{versioned_name}")
    ResumeVersion.objects.create(
        candidate=candidate,
        version=next_version,
        file_path=path,
    )
    return path


def _save_profile_photo_upload_versioned(candidate, file_obj):
    if not file_obj or not candidate:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    latest = ProfilePhotoVersion.objects.filter(candidate=candidate).order_by("-version").first()
    next_version = (latest.version + 1) if latest else 1
    prefix = candidate.candidate_id or f"cand{candidate.id}"
    versioned_name = f"{prefix}_photo_v{next_version}_{safe_name}"
    path = _save_encrypted_upload(file_obj, f"profile_photos/{versioned_name}")
    ProfilePhotoVersion.objects.create(
        candidate=candidate,
        version=next_version,
        file_path=path,
    )
    return path


def _empty_resume_payload():
    return {
        "full_name": "",
        "email": "",
        "contact_number": "",
        "social_media_link": "",
        "skills": "",
        "experience": "",
        "employment_history": "",
        "references": "",
        "highest_education_level": "",
        "education_details": "",
        "education_records": [],
        "degree_name": "",
        "institute_name": "",
        "year_of_passing": "",
        "percentage_cgpa": "",
        "certifications": "",
    }


def _normalize_contact_number(value):
    if not value:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit() or ch == "+")
    return digits[:20]


def _normalize_text_list(value):
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
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


def _resume_storage_path(resume_path):
    if not resume_path:
        return ""
    try:
        return default_storage.path(resume_path)
    except Exception:
        media_root = getattr(settings, "MEDIA_ROOT", "") or ""
        if not media_root:
            return ""
        return os.path.join(media_root, resume_path)


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
    filename = (getattr(file_obj, "name", "") or "").lower()
    is_pdf = filename.endswith(".pdf")
    if is_pdf:
        return ""
    for encoding in ("utf-8", "latin-1", "utf-16"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _extract_resume_text_from_path(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""
    is_pdf = file_path.lower().endswith(".pdf")

    if fitz is not None:
        try:
            doc = fitz.open(file_path)
            try:
                parts = [page.get_text("text") for page in doc]
            finally:
                doc.close()
            text = "\n".join(parts).strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("PyMuPDF text extraction failed for %s: %s", file_path, exc)

    if PdfReader is not None:
        try:
            with open(file_path, "rb") as handle:
                reader = PdfReader(handle)
                parts = []
                for page in reader.pages:
                    page_text = page.extract_text() or ""
                    if page_text:
                        parts.append(page_text)
            text = "\n".join(parts).strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("pypdf text extraction failed for %s: %s", file_path, exc)

    if is_pdf:
        ocr_text = _extract_text_via_ocr(file_path, max_pages=2)
        if ocr_text:
            return ocr_text
        return ""

    try:
        with open(file_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    for encoding in ("utf-8", "latin-1", "utf-16"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _normalize_spaces(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


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


def _extract_resume_text_from_storage(resume_path):
    if not resume_path:
        return ""
    try:
        data = _read_storage_bytes(resume_path)
    except Exception:
        return ""
    if not data:
        return ""
    suffix = os.path.splitext(resume_path)[-1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(data)
        temp_path = handle.name
    try:
        return _extract_resume_text_from_path(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _extract_text_via_ocr(file_path, max_pages=2):
    if not file_path or not os.path.exists(file_path):
        return ""
    if pytesseract is None:
        return ""
    tesseract_cmd = getattr(settings, "TESSERACT_CMD", "") or ""
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    poppler_path = getattr(settings, "POPPLER_PATH", "") or os.environ.get("POPPLER_PATH", "")
    try:
        if convert_from_path is not None:
            images = convert_from_path(
                file_path,
                dpi=200,
                first_page=1,
                last_page=max_pages,
                poppler_path=poppler_path or None,
            )
        else:
            images = []
    except Exception as exc:
        logger.warning("OCR image conversion failed for %s: %s", file_path, exc)
        images = []

    if not images and fitz is not None and Image is not None:
        try:
            doc = fitz.open(file_path)
            images = []
            for page_index in range(min(max_pages, doc.page_count)):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                images.append(img)
            doc.close()
        except Exception as exc:
            logger.warning("OCR fallback render failed for %s: %s", file_path, exc)

    if not images:
        return ""

    parts = []
    for img in images:
        try:
            parts.append(pytesseract.image_to_string(img))
        except Exception as exc:
            logger.warning("OCR text extraction failed for %s: %s", file_path, exc)
    return "\n".join([part for part in parts if part]).strip()


def _pick_highest_degree_name(value):
    text = _normalize_spaces(str(value or ""))
    if not text:
        return ""

    tokens = [item.strip() for item in re.split(r"[,/|;\n]+", text) if item.strip()]
    if not tokens:
        tokens = [text]

    ranking_rules = [
        (90, ("phd", "doctor", "doctorate")),
        (80, ("m.tech", "mtech", "master", "mba", "mca", "m.sc", "msc", "m.e", "me ")),
        (70, ("b.tech", "btech", "b.e", "be ", "bachelor", "b.sc", "bsc", "bca")),
        (60, ("diploma", "polytechnic", "iti")),
        (50, ("12th", "xii", "hsc", "higher secondary")),
        (40, ("10th", "x", "ssc", "secondary")),
    ]

    best_token = tokens[0]
    best_rank = -1
    for token in tokens:
        token_lower = token.lower()
        rank = 0
        for score, keywords in ranking_rules:
            if any(keyword in token_lower for keyword in keywords):
                rank = score
                break
        if rank > best_rank:
            best_rank = rank
            best_token = token

    return _normalize_spaces(best_token)


def _normalize_custom_tags(raw_value):
    tags = []
    seen = set()
    for part in re.split(r"[,\n;]+", raw_value or ""):
        token = _normalize_spaces(part.strip().strip("#"))
        if not token:
            continue
        token = token[:40]
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(token)
    return tags


def _extract_section_block(text, headings, stop_headings, max_lines=18):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""

    heading_set = [item.lower() for item in headings]
    stop_set = [item.lower() for item in stop_headings]
    start_index = -1
    start_remainder = ""

    for idx, line in enumerate(lines):
        lower = line.lower().strip(" :-")
        if any(lower.startswith(item) for item in heading_set):
            start_index = idx
            if ":" in line:
                start_remainder = line.split(":", 1)[1].strip()
            break
    if start_index == -1:
        return ""

    collected = []
    if start_remainder:
        collected.append(start_remainder)

    for idx in range(start_index + 1, min(len(lines), start_index + 1 + max_lines)):
        line = lines[idx].strip()
        lower = line.lower().strip(" :-")
        if any(lower.startswith(item) for item in stop_set):
            break
        if len(line) < 4 and line.endswith(":"):
            break
        if line.isupper() and len(line.split()) <= 4:
            break
        collected.append(line)

    return _normalize_spaces("\n".join(collected))


def _split_items(value):
    if not value:
        return []
    parts = re.split(r"[\n,;/|•]+", value)
    cleaned = []
    for item in parts:
        token = _normalize_spaces(item.strip(" -:."))
        if not token:
            continue
        if len(token) <= 1:
            continue
        cleaned.append(token)
    return cleaned


def _dedupe_preserve(items):
    seen = set()
    output = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _extract_social_media_link(text):
    if not text:
        return ""
    social_domains = [
        "linkedin.com",
        "github.com",
        "gitlab.com",
        "behance.net",
        "dribbble.com",
        "twitter.com",
        "instagram.com",
        "facebook.com",
    ]
    found = []
    for url in re.findall(r"https?://[^\s<>'\"()]+", text, flags=re.I):
        clean = url.rstrip(".,);")
        if any(domain in clean.lower() for domain in social_domains):
            found.append(clean)
    for bare in re.findall(
        r"\b(?:www\.)?(?:linkedin\.com|github\.com|gitlab\.com|behance\.net|dribbble\.com|twitter\.com|instagram\.com|facebook\.com)/[^\s<>'\"()]+",
        text,
        flags=re.I,
    ):
        clean = bare.rstrip(".,);")
        if not clean.lower().startswith(("http://", "https://")):
            clean = f"https://{clean}"
        found.append(clean)
    if not found:
        linked_id_match = re.search(r"\blinked\s*(?:in)?\s*id\s*[:\-]\s*([A-Za-z0-9\-\._\s]{3,80})", text, flags=re.I)
        if linked_id_match:
            handle = linked_id_match.group(1).strip()
            handle = re.sub(r"[^A-Za-z0-9\-\s_\.]", "", handle)
            handle = re.sub(r"[\s_]+", "-", handle).strip("-").lower()
            handle = re.sub(r"-(?:be|b-e|b-tech|btech|mtech|me|mba)$", "", handle)
            handle = handle.strip("-")
            if handle:
                return f"https://www.linkedin.com/in/{handle}"
        return ""

    # Prefer LinkedIn when multiple social links are present.
    for link in found:
        if "linkedin.com" in link.lower():
            return link
    return found[0]


def _looks_like_placeholder(text):
    lower = (text or "").lower()
    placeholders = [
        "lorem ipsum",
        "dolor sit amet",
        "really great",
        "example.com",
        "yourname",
        "your name",
        "sample",
        "template",
    ]
    return any(token in lower for token in placeholders)


def _looks_like_address(text):
    lower = (text or "").lower()
    address_tokens = [
        "street",
        "st.",
        "st ",
        "road",
        "rd",
        "avenue",
        "ave",
        "city",
        "state",
        "zip",
        "pincode",
        "pin",
        "india",
    ]
    if any(token in lower for token in address_tokens):
        return True
    if re.search(r"\d", text or ""):
        return True
    return False


def _pick_best_email(text):
    if not text:
        return ""
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    blocked_domains = {"example.com", "test.com", "reallygreatsite.com"}
    for email in emails:
        domain = email.split("@", 1)[-1].lower()
        if domain in blocked_domains:
            continue
        return email
    return emails[0] if emails else ""


def _pick_best_phone(text):
    if not text:
        return ""
    candidates = re.findall(r"(\+?\d[\d\-\s]{8,}\d)", text)
    cleaned = [_normalize_contact_number(item) for item in candidates]
    cleaned = [item for item in cleaned if 8 <= len(item) <= 16]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def _pick_best_name(lines):
    for line in lines[:10]:
        cleaned = _clean_candidate_name(line)
        if cleaned and not _looks_like_placeholder(cleaned):
            return cleaned
    return ""


def _extract_skills_from_lines(text):
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    start_idx = None
    for idx, line in enumerate(lines):
        lower = line.lower()
        if lower in {"skills", "skill set", "technical skills", "core skills"} or lower.startswith("skills"):
            start_idx = idx + 1
            break
    if start_idx is None:
        return ""
    stop_words = {"education", "experience", "employment", "projects", "certifications", "contact", "references"}
    items = []
    for line in lines[start_idx:start_idx + 20]:
        lower = line.lower()
        if any(word in lower for word in stop_words):
            break
        if len(line) > 60:
            parts = re.split(r"[,\|/]", line)
        else:
            parts = [line]
        for part in parts:
            token = _normalize_spaces(part.strip(" -:•"))
            if not token or _looks_like_placeholder(token):
                continue
            if _looks_like_address(token):
                continue
            if len(token) > 40:
                continue
            items.append(token)
    items = _dedupe_preserve(items)
    return ", ".join(items[:35])


def _extract_education_records(text):
    if not text:
        return []

    patterns = [
        ("10th", r"\b(10th|ssc|matric(?:ulation)?)\b", 1),
        ("12th", r"\b(12th|hsc|intermediate|higher secondary)\b", 2),
        ("Diploma", r"\b(diploma|polytechnic)\b", 3),
        ("BCA", r"\b(bca|bachelor of computer applications)\b", 4),
        ("BSc", r"\b(bsc|b\.?\s?sc|bachelor of science)\b", 4),
        ("BE", r"\b(?:b\.\s*e\.?|b e|bachelor of engineering)\b", 5),
        ("BTech", r"\b(b\.?\s?tech|bachelor of technology)\b", 5),
        ("MCA", r"\b(mca|master of computer applications)\b", 6),
        ("MSc", r"\b(msc|m\.?\s?sc|master of science)\b", 6),
        ("ME", r"\b(?:m\.\s*e\.?|m e|master of engineering)\b", 7),
        ("MTech", r"\b(m\.?\s?tech|master of technology)\b", 7),
        ("MBA", r"\b(mba|master of business administration)\b", 7),
        ("PhD", r"\b(phd|ph\.?d|doctorate)\b", 8),
    ]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    section_breakers = (
        "summary",
        "objective",
        "projects",
        "experience",
        "work experience",
        "technical skills",
        "skills",
        "certification",
        "certifications",
        "languages",
        "hobbies",
        "references",
    )
    institute_tokens = ("school", "college", "university", "institute", "polytechnic")
    board_tokens = ("board", "university")
    parsed = []

    for idx, line in enumerate(lines):
        clean = _normalize_spaces(line)
        lower = clean.lower()
        matched = None
        for label, pattern, rank in patterns:
            if re.search(pattern, lower, flags=re.I):
                matched = (label, rank)
                break
        if not matched:
            continue

        level, rank = matched
        chunk = [clean]
        for next_idx in range(idx + 1, min(len(lines), idx + 7)):
            next_line = _normalize_spaces(lines[next_idx])
            next_lower = next_line.lower()
            if any(next_lower.startswith(item) for item in section_breakers):
                break
            if any(re.search(pattern, next_lower, flags=re.I) for _, pattern, _ in patterns):
                break
            chunk.append(next_line)

        chunk_text = " | ".join(chunk)
        years = re.findall(r"\b(19\d{2}|20\d{2})\b", chunk_text)
        score_match = re.search(r"\b(\d{1,2}(?:\.\d{1,2})?)\s*%", chunk_text)
        if not score_match:
            score_match = re.search(r"\b(?:cgpa|gpa)\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", chunk_text, flags=re.I)

        institute = ""
        board_university = ""
        for token_line in chunk:
            token_lower = token_line.lower()
            if not institute and any(token in token_lower for token in institute_tokens):
                institute = token_line
            if not board_university and any(token in token_lower for token in board_tokens):
                board_university = token_line

        course = clean
        if course.lower() == level.lower():
            course = ""

        parsed.append(
            {
                "level": level,
                "rank": rank,
                "course": course[:180],
                "institute": institute[:255],
                "board_university": board_university[:255],
                "year_of_passing": (sorted(years)[-1] if years else "")[:20],
                "score": ((score_match.group(1) + "%") if score_match and "%" in score_match.group(0) else (score_match.group(1) if score_match else ""))[:60],
                "raw": chunk_text.lower(),
            }
        )

    if not parsed:
        return []

    best_by_level = {}
    for item in parsed:
        info = 0
        if item["institute"]:
            info += 2
        if item["year_of_passing"]:
            info += 2
        if item["score"]:
            info += 2
        if "linkedin" in item["raw"]:
            info -= 3
        prev = best_by_level.get(item["level"])
        if prev is None or info > prev[0]:
            best_by_level[item["level"]] = (info, item)

    records = [entry[1] for entry in best_by_level.values()]
    records.sort(key=lambda row: row["rank"])

    cleaned = []
    for seq, row in enumerate(records, start=1):
        cleaned.append(
            {
                "sequence": seq,
                "level": row["level"],
                "course": row["course"],
                "institute": row["institute"],
                "board_university": row["board_university"],
                "year_of_passing": row["year_of_passing"],
                "score": row["score"],
            }
        )
    return cleaned


def _extract_education_details(text):
    records = _extract_education_records(text)
    if not records:
        return "", "", "", "", ""

    highest = records[-1]["level"]
    sequence = ", ".join([item["level"] for item in records])
    year_candidates = [item["year_of_passing"] for item in records if item["year_of_passing"]]
    year_of_passing = sorted(year_candidates)[-1] if year_candidates else ""
    score_summary = ", ".join([f"{item['level']}: {item['score']}" for item in records if item["score"]])
    details = " || ".join(
        [
            " - ".join(
                [
                    token
                    for token in [
                        item["level"],
                        item["course"],
                        item["institute"],
                        item["board_university"],
                        item["year_of_passing"],
                        item["score"],
                    ]
                    if token
                ]
            )
            for item in records
        ]
    )
    return highest, sequence, year_of_passing, score_summary, details


def _extract_skills(text):
    skills_section = _extract_section_block(
        text,
        headings=["skills", "technical skills", "key skills", "technologies", "tech stack"],
        stop_headings=[
            "experience",
            "education",
            "projects",
            "certification",
            "achievements",
            "languages",
            "profile",
            "summary",
        ],
    )
    raw_items = _split_items(skills_section)
    items = []
    for item in raw_items:
        if ":" in item:
            label, value = item.split(":", 1)
            if len(value.strip()) >= 2:
                items.extend(_split_items(value))
            elif len(label.strip()) >= 2:
                items.append(label.strip())
        else:
            items.append(item)

    if not items:
        known = [
            "python",
            "django",
            "flask",
            "fastapi",
            "java",
            "spring",
            "javascript",
            "typescript",
            "react",
            "angular",
            "node",
            "sql",
            "mysql",
            "postgresql",
            "mongodb",
            "aws",
            "azure",
            "git",
            "html",
            "css",
            "excel",
            "power bi",
            "tableau",
        ]
        lower = text.lower()
        for skill in known:
            if re.search(rf"\b{re.escape(skill)}\b", lower):
                items.append(skill.title())

    items = _dedupe_preserve([_normalize_spaces(token.title()) for token in items])
    items = [item for item in items if not _looks_like_address(item)]
    return ", ".join(items[:35])


def _extract_certifications(text):
    cert_section = _extract_section_block(
        text,
        headings=["certifications", "certification", "licenses", "license"],
        stop_headings=["experience", "education", "projects", "skills", "achievements"],
    )
    cert_items = _dedupe_preserve(_split_items(cert_section))
    if cert_items:
        return ", ".join(cert_items)[:500]

    inline = re.findall(r"\b(?:certified|certificate in|certification in)\s+([A-Za-z0-9\-\+\s]{3,80})", text, flags=re.I)
    inline = _dedupe_preserve([_normalize_spaces(item) for item in inline])[:10]
    return ", ".join(inline)[:500]


def _extract_employment_history(text):
    history = _extract_section_block(
        text,
        headings=["experience", "work experience", "employment history", "professional experience"],
        stop_headings=["education", "projects", "skills", "certification", "achievements", "profile", "summary"],
        max_lines=25,
    )
    return history[:1500]


def _resume_regex_autofill(text):
    payload = _empty_resume_payload()
    if not text:
        return payload

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name_from_top = _pick_best_name(lines)
    if name_from_top:
        payload["full_name"] = name_from_top

    normalized = " ".join(text.split())

    email_pick = _pick_best_email(normalized)
    if email_pick and not _looks_like_placeholder(email_pick):
        payload["email"] = email_pick.strip()

    payload["social_media_link"] = _extract_social_media_link(text)

    phone_pick = _pick_best_phone(normalized)
    if phone_pick:
        payload["contact_number"] = phone_pick

    name_match = re.search(r"(?:name|candidate)\s*[:\-]\s*([A-Za-z][A-Za-z\s\.\-']{2,60})", normalized, flags=re.I)
    if name_match and not payload["full_name"]:
        cleaned = _clean_candidate_name(name_match.group(1).strip())
        if cleaned and not _looks_like_placeholder(cleaned):
            payload["full_name"] = cleaned

    exp_match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", normalized, flags=re.I)
    if exp_match:
        payload["experience"] = f"{exp_match.group(1)} years"

    skill_section = _extract_section_block(
        text,
        headings=["skills", "technical skills", "skill set", "core skills"],
        stop_headings=["education", "experience", "projects", "certification", "certifications"],
        max_lines=12,
    )
    skills_value = _extract_skills(skill_section or text)
    if not skills_value:
        skills_value = _extract_skills_from_lines(text)
    payload["skills"] = skills_value
    payload["certifications"] = _extract_certifications(text)
    payload["employment_history"] = _extract_employment_history(text)
    payload["education_records"] = _extract_education_records(text)

    highest, education_sequence, year_of_passing, score, education_details = _extract_education_details(text)
    payload["highest_education_level"] = highest
    payload["degree_name"] = education_sequence
    payload["education_details"] = education_details
    if education_details:
        payload["institute_name"] = education_details.split("||", 1)[0].strip()
    payload["year_of_passing"] = year_of_passing
    payload["percentage_cgpa"] = score

    if "reference available" in normalized.lower():
        payload["references"] = "References available upon request"

    return payload


def _merge_resume_payload(primary, fallback):
    merged = _empty_resume_payload()
    for key in merged.keys():
        if key == "education_records":
            primary_records = (primary or {}).get(key) or []
            fallback_records = (fallback or {}).get(key) or []
            merged[key] = primary_records if primary_records else fallback_records
            continue
        primary_value = (primary or {}).get(key, "")
        fallback_value = (fallback or {}).get(key, "")
        merged[key] = str(primary_value or fallback_value or "").strip()
    return merged


def _parse_resume_from_file_path(file_path):
    payload = _empty_resume_payload()
    if not file_path or ResumeParser is None or not PYRESPARSER_ENABLED:
        return payload

    try:
        parsed = ResumeParser(file_path).get_extracted_data() or {}
    except Exception as exc:
        logger.warning("pyresparser failed for %s: %s", file_path, exc)
        return payload

    degree_value = _normalize_text_list(parsed.get("degree"))
    highest_degree = _pick_highest_degree_name(degree_value)
    payload["full_name"] = (parsed.get("name") or "").strip()
    payload["email"] = (parsed.get("email") or "").strip()
    payload["contact_number"] = _normalize_contact_number(parsed.get("mobile_number"))
    payload["skills"] = _normalize_text_list(parsed.get("skills"))
    payload["experience"] = _format_experience(parsed.get("total_experience") or parsed.get("experience"))
    payload["highest_education_level"] = highest_degree or degree_value
    payload["degree_name"] = degree_value
    payload["education_details"] = degree_value
    payload["institute_name"] = _normalize_text_list(parsed.get("college_name"))
    return payload


def _parse_resume_autofill_from_upload(file_obj):
    payload = _empty_resume_payload()
    if not file_obj:
        return payload

    temp_path = ""
    try:
        suffix = os.path.splitext(file_obj.name or "")[-1] or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in file_obj.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        pyresparser_data = _parse_resume_from_file_path(temp_path)
        regex_data = _resume_regex_autofill(_extract_resume_text_from_path(temp_path))
        payload = _merge_resume_payload(pyresparser_data, regex_data)
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return payload


def _parse_resume_autofill(resume_path):
    if not resume_path:
        return _empty_resume_payload()
    temp_path = ""
    try:
        data = _read_storage_bytes(resume_path)
        suffix = os.path.splitext(resume_path)[-1] or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            temp_path = tmp.name
        pyresparser_data = _parse_resume_from_file_path(temp_path)
        regex_data = _resume_regex_autofill(_extract_resume_text_from_path(temp_path))
        return _merge_resume_payload(pyresparser_data, regex_data)
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _normalize_education_records(raw_records):
    normalized = []
    if not isinstance(raw_records, list):
        return normalized

    for idx, row in enumerate(raw_records, start=1):
        if not isinstance(row, dict):
            continue
        level = _normalize_spaces(str(row.get("level", "")))
        course = _normalize_spaces(str(row.get("course", "")))
        institute = _normalize_spaces(str(row.get("institute", "")))
        board_university = _normalize_spaces(str(row.get("board_university", "")))
        year_of_passing = _normalize_spaces(str(row.get("year_of_passing", "")))
        score = _normalize_spaces(str(row.get("score", "")))
        if not level and not course:
            continue
        normalized.append(
            {
                "sequence": idx,
                "level": (level or course)[:60],
                "course": course[:180],
                "institute": institute[:255],
                "board_university": board_university[:255],
                "year_of_passing": year_of_passing[:20],
                "score": score[:60],
            }
        )
    return normalized


def _save_candidate_education_records(candidate, records, fallback=None):
    records = _normalize_education_records(records)
    if not records and fallback:
        fallback_level = _normalize_spaces(fallback.get("highest_education_level", ""))
        fallback_course = _normalize_spaces(fallback.get("degree_name", ""))
        fallback_institute = _normalize_spaces(fallback.get("institute_name", ""))
        fallback_year = _normalize_spaces(fallback.get("year_of_passing", ""))
        fallback_score = _normalize_spaces(fallback.get("percentage_cgpa", ""))
        if fallback_level or fallback_course:
            records = [
                {
                    "sequence": 1,
                    "level": (fallback_level or fallback_course)[:60],
                    "course": fallback_course[:180],
                    "institute": fallback_institute[:255],
                    "board_university": "",
                    "year_of_passing": fallback_year[:20],
                    "score": fallback_score[:60],
                }
            ]

    CandidateEducation.objects.filter(candidate=candidate).delete()
    if not records:
        return

    CandidateEducation.objects.bulk_create(
        [
            CandidateEducation(
                candidate=candidate,
                sequence=item["sequence"],
                level=item["level"],
                course=item["course"],
                institute=item["institute"],
                board_university=item["board_university"],
                year_of_passing=item["year_of_passing"],
                score=item["score"],
            )
            for item in records
        ]
    )


def _is_profile_photo_upload(file_obj):
    if not file_obj:
        return True
    filename = (file_obj.name or "").lower()
    if not (filename.endswith(".jpg") or filename.endswith(".jpeg") or filename.endswith(".png")):
        return False
    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type and content_type not in {"image/jpeg", "image/jpg", "image/png", "application/octet-stream"}:
        return False
    return True


def _save_profile_photo_upload(file_obj):
    if not file_obj:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    return default_storage.save(f"profile_photos/{safe_name}", file_obj)


def _resume_url(resume_path, candidate_id=None):
    if not resume_path:
        return ""
    try:
        parsed = urlparse(resume_path)
        if parsed.scheme in {"http", "https"}:
            return resume_path
    except Exception:
        pass
    if candidate_id:
        return reverse("candidate_management:resume_download", args=[candidate_id])
    return f"{settings.MEDIA_URL}{resume_path}"


def _build_job_description(job):
    if not job:
        return ""
    parts = [
        (job.title or "").strip(),
        (job.skills_required or "").strip(),
        (job.experience_range or "").strip(),
        (job.job_description or "").strip(),
        (job.requirements or "").strip(),
        (job.benefits or "").strip(),
    ]
    return " ".join([part for part in parts if part]).strip()


def _profile_photo_url(profile_photo_path, candidate_id=None):
    if not profile_photo_path:
        return ""
    if candidate_id:
        return reverse("candidate_management:profile_photo_download", args=[candidate_id])
    return f"{settings.MEDIA_URL}{profile_photo_path}"


def candidate_resume_download_view(request, candidate_id):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    if not candidate.resume_path:
        return redirect("candidate_management:list")
    try:
        parsed = urlparse(candidate.resume_path)
        if parsed.scheme in {"http", "https"}:
            return redirect(candidate.resume_path)
    except Exception:
        pass
    try:
        data = _read_storage_bytes(candidate.resume_path)
    except OSError:
        messages.error(request, "Resume file path is invalid. Please re-upload the resume PDF.")
        return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
    except Exception:
        messages.error(request, "Unable to open resume. Please re-upload the resume PDF.")
        return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
    filename = os.path.basename(candidate.resume_path) or f"{candidate.candidate_id}_resume.pdf"
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def candidate_profile_photo_download_view(request, candidate_id):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    if not candidate.profile_photo_path:
        return redirect("candidate_management:list")
    data = _read_storage_bytes(candidate.profile_photo_path)
    filename = os.path.basename(candidate.profile_photo_path) or f"{candidate.candidate_id}_photo"
    mime, _ = mimetypes.guess_type(filename)
    response = HttpResponse(data, content_type=mime or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _next_candidate_id():
    latest = Candidate.objects.order_by("-id").first()
    next_num = (latest.id + 1) if latest else 1
    while True:
        candidate_id = f"CAND{next_num:04d}"
        if not Candidate.objects.filter(candidate_id=candidate_id).exists():
            return candidate_id
        next_num += 1


def _candidates_with_evaluations():
    return Candidate.objects.prefetch_related(
        Prefetch("evaluations", queryset=CandidateEvaluation.objects.order_by("-created_at")),
        Prefetch("job_applications", queryset=CandidateJobApplication.objects.select_related("job").order_by("-applied_on")),
    )


def _latest_status(candidate):
    latest_application = next(iter(candidate.job_applications.all()), None)
    if latest_application and latest_application.stage:
        return latest_application.stage
    latest_eval = next(iter(candidate.evaluations.all()), None)
    return (latest_eval.status if latest_eval else "") or candidate.status or "-"


def _serialize_candidate_applications(candidate):
    apps = []
    for item in candidate.job_applications.all():
        if not item.job:
            continue
        apps.append(
            {
                "job_id": item.job.job_id,
                "title": item.job.title or item.job.job_id,
                "stage": item.stage or "Applied",
            }
        )
    return apps


def _update_candidate_stage(request, candidate, new_status, job_id=""):
    if job_id:
        app = (
            CandidateJobApplication.objects.select_related("job")
            .filter(candidate=candidate, job__job_id=job_id)
            .first()
        )
        if not app:
            return False, f"Job {job_id} application not found for {candidate.candidate_id}."
        previous_stage = app.stage or ""
        app.stage = new_status
        app.save(update_fields=["stage"])
        try:
            job_label = f"{app.job.job_id} - {app.job.title}" if app.job else (job_id or "")
            _send_candidate_stage_update_email(
                request=request,
                candidate=candidate,
                job_title=job_label,
                previous_stage=previous_stage,
                new_stage=new_status,
            )
        except Exception as exc:
            return False, f"Stage updated but email failed: {exc}"
        return True, f"Stage updated for {candidate.candidate_id} ({app.job.job_id} - {app.job.title})."

    previous_status = candidate.status
    candidate.status = new_status
    candidate.save(update_fields=["status", "updated_at"])
    try:
        _send_candidate_stage_update_email(
            request=request,
            candidate=candidate,
            job_title=candidate.applied_position or "",
            previous_stage=previous_status,
            new_stage=new_status,
        )
    except Exception as exc:
        return False, f"Status updated but email failed: {exc}"

    # Keep applicant pipeline in sync when status is updated without specifying a job.
    # Prefer updating the job application whose stage matches the previous status; otherwise update the latest one.
    apps = list(
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate)
        .order_by("-applied_on")
    )
    updated_apps = []
    if apps:
        if len(apps) == 1:
            apps[0].stage = new_status
            apps[0].save(update_fields=["stage"])
            updated_apps = [apps[0]]
        else:
            matched = [app for app in apps if _normalized(app.stage) == _normalized(previous_status)]
            if matched:
                for app in matched:
                    app.stage = new_status
                    app.save(update_fields=["stage"])
                updated_apps = matched
            else:
                apps[0].stage = new_status
                apps[0].save(update_fields=["stage"])
                updated_apps = [apps[0]]

    if updated_apps:
        details = ", ".join(
            f"{app.job.job_id if app.job else ''}".strip() or "job"
            for app in updated_apps[:3]
        )
        more = "" if len(updated_apps) <= 3 else f" (+{len(updated_apps) - 3} more)"
        return True, f"Status updated for {candidate.candidate_id} and pipeline stage synced ({details}{more})."

    return True, f"Status updated for {candidate.candidate_id}."


def _evaluation_form_catalog():
    forms = AssessmentForm.objects.prefetch_related("fields").order_by("name")
    catalog = {"assessment": [], "feedback": [], "map": {}, "name_to_id": {}}
    for form in forms:
        fields = []
        for field in form.fields.all():
            fields.append(
                {
                    "field_name": field.field_name,
                    "label": field.label,
                    "field_type": field.field_type,
                    "required": field.required,
                    "options": [item.strip() for item in (field.options or "").split(",") if item.strip()],
                }
            )
        item = {
            "id": form.id,
            "name": form.name,
            "form_type": form.form_type,
            "fields": fields,
        }
        catalog["map"][str(form.id)] = item
        catalog["name_to_id"][form.name] = form.id
        if form.form_type == "feedback":
            catalog["feedback"].append({"id": form.id, "name": form.name})
        else:
            catalog["assessment"].append({"id": form.id, "name": form.name})
    return catalog


def candidate_management_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    if request.method == "POST" and request.POST.get("action") == "update_status":
        candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
        new_status = request.POST.get("status", "").strip()
        job_id = request.POST.get("job_id", "").strip()
        if new_status:
            ok, message = _update_candidate_stage(request, candidate, new_status, job_id=job_id)
            if ok:
                messages.success(request, message)
            else:
                messages.error(request, message)
        return redirect("candidate_management:index")

    entries = []
    status_options = set(STATUS_OPTIONS)
    for candidate in _candidates_with_evaluations():
        status = _latest_status(candidate)
        status_options.add(status)
        applications = _serialize_candidate_applications(candidate)
        for app in applications:
            status_options.add(app["stage"])
        entries.append(
            {
                "id": candidate.candidate_id,
                "name": candidate.full_name,
                "email": candidate.email,
                "degree": _pick_highest_degree_name(candidate.highest_education_level or candidate.degree_name) or "-",
                "year": candidate.year_of_passing or "-",
                "status": status,
                "references": candidate.references or "-",
                "applications": applications,
            }
        )

    return render(
        request,
        "candidate_management/index.html",
        {"entries": entries, "status_options": sorted(status_options)},
    )


def candidate_resume_parse_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request method."}, status=405)

    blocked = _candidate_management_access_guard(request)
    if blocked:
        return JsonResponse({"ok": False, "message": "Access denied."}, status=403)

    resume_upload = request.FILES.get("resume_upload")
    if not resume_upload:
        return JsonResponse({"ok": False, "message": "Resume file is required."}, status=400)
    if not _is_pdf_upload(resume_upload):
        return JsonResponse({"ok": False, "message": "Resume must be uploaded in PDF format only."}, status=400)

    parsed = _parse_resume_autofill_from_upload(resume_upload)
    if not any(parsed.values()):
        return JsonResponse(
            {
                "ok": False,
                "message": "No readable data found in this PDF. Upload a text-based resume PDF or OCR-scanned PDF.",
            },
            status=422,
        )
    return JsonResponse(
        {
            "ok": True,
            "message": "Resume parsed successfully.",
            "fields": {
                "full_name": parsed.get("full_name", ""),
                "email": parsed.get("email", ""),
                "contact_number": parsed.get("contact_number", ""),
                "social_media_link": parsed.get("social_media_link", ""),
                "skills": parsed.get("skills", ""),
                "experience": parsed.get("experience", ""),
                "employment_history": parsed.get("employment_history", ""),
                "references": parsed.get("references", ""),
                "highest_education_level": parsed.get("highest_education_level", ""),
                "education_details": parsed.get("education_details", ""),
                "education_records": parsed.get("education_records", []),
                "degree_name": parsed.get("degree_name", ""),
                "institute_name": parsed.get("institute_name", ""),
                "year_of_passing": parsed.get("year_of_passing", ""),
                "percentage_cgpa": parsed.get("percentage_cgpa", ""),
                "certifications": parsed.get("certifications", ""),
            },
        }
    )


def candidate_registration_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    country_options = list(Country.objects.order_by("name").values_list("name", flat=True))
    state_options = list(State.objects.order_by("name").values_list("name", flat=True))
    city_options = list(City.objects.order_by("name").values_list("name", flat=True))
    education_level_options = list(EducationLevel.objects.order_by("name").values_list("name", flat=True))
    position_options = list(JobRequisition.objects.order_by("-created_at").values("job_id", "title"))

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        contact_number = request.POST.get("contact_number", "").strip()
        candidate_id = request.POST.get("candidate_id", "").strip() or _next_candidate_id()
        resume_upload = request.FILES.get("resume_upload")
        profile_photo_upload = request.FILES.get("profile_photo_upload")
        selected_position_ids = [item.strip() for item in request.POST.getlist("applied_positions") if item.strip()]
        education_records_json = request.POST.get("education_records_json", "").strip()

        if resume_upload and not _is_pdf_upload(resume_upload):
            messages.error(request, "Resume must be uploaded in PDF format only.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )
        if profile_photo_upload and not _is_profile_photo_upload(profile_photo_upload):
            messages.error(request, "Profile photo must be JPG or PNG format only.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )

        resume_autofill = _parse_resume_autofill_from_upload(resume_upload) if resume_upload else _empty_resume_payload()
        full_name = full_name or resume_autofill.get("full_name", "").strip()
        email = email or resume_autofill.get("email", "").strip()
        contact_number = contact_number or resume_autofill.get("contact_number", "").strip()

        if not full_name or not email or not contact_number:
            messages.error(request, "Candidate Name, Email and Contact Number are required.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )

        if Candidate.objects.filter(candidate_id=candidate_id).exists():
            messages.error(request, f"Candidate ID {candidate_id} already exists.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )
        if Candidate.objects.filter(email__iexact=email).exists():
            messages.error(request, f"Email ID {email} already exists.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )

        resume_path = ""
        profile_photo_path = ""

        education_records = []
        if education_records_json:
            try:
                education_records = json.loads(education_records_json)
            except (TypeError, ValueError):
                education_records = []
        if not education_records:
            education_records = resume_autofill.get("education_records", [])

        highest_education_level = request.POST.get("highest_education_level", "").strip() or resume_autofill.get(
            "highest_education_level",
            "",
        )
        degree_name = (
            request.POST.get("degree_name", "").strip()
            or resume_autofill.get("education_details", "")
            or resume_autofill.get("degree_name", "")
        )
        institute_name = request.POST.get("institute_name", "").strip() or resume_autofill.get("institute_name", "")
        year_of_passing = request.POST.get("year_of_passing", "").strip() or resume_autofill.get("year_of_passing", "")
        percentage_cgpa = request.POST.get("percentage_cgpa", "").strip() or resume_autofill.get("percentage_cgpa", "")
        certifications = request.POST.get("certifications", "").strip() or resume_autofill.get("certifications", "")
        social_media_link = request.POST.get("social_media_link", "").strip() or resume_autofill.get("social_media_link", "")
        skills = request.POST.get("skills", "").strip() or resume_autofill.get("skills", "")
        experience = request.POST.get("experience", "").strip() or resume_autofill.get("experience", "")
        employment_history = request.POST.get("employment_history", "").strip() or resume_autofill.get("employment_history", "")
        references = request.POST.get("references", "").strip() or resume_autofill.get("references", "")

        try:
            candidate = Candidate.objects.create(
                candidate_id=candidate_id,
                candidate_code=candidate_id,
                full_name=full_name,
                email=email,
                contact_number=contact_number,
                date_of_birth=request.POST.get("date_of_birth") or None,
                gender=request.POST.get("gender", "").strip(),
                current_city=request.POST.get("current_city", "").strip(),
                country=request.POST.get("country", "").strip(),
                state=request.POST.get("state", "").strip(),
                pan=request.POST.get("pan", "").strip(),
                aadhaar=request.POST.get("aadhaar", "").strip(),
                pf=request.POST.get("pf", "").strip(),
                esic=request.POST.get("esic", "").strip(),
                social_media_link=social_media_link,
                address=request.POST.get("address", "").strip(),
                resume_path="",
                profile_photo_path="",
                highest_education_level=highest_education_level,
                degree_name=degree_name,
                institute_name=institute_name,
                year_of_passing=year_of_passing,
                percentage_cgpa=percentage_cgpa,
                certifications=certifications,
                skills=skills,
                experience=experience,
                employment_history=employment_history,
                references=references,
                status="Applied",
            )
            if resume_path:
                _register_resume_version(candidate, resume_path)
            if resume_upload:
                resume_path = _save_resume_upload_versioned(candidate, resume_upload)
                candidate.resume_path = resume_path
                candidate.save(update_fields=["resume_path", "updated_at"])
            if profile_photo_upload:
                profile_photo_path = _save_profile_photo_upload_versioned(candidate, profile_photo_upload)
                candidate.profile_photo_path = profile_photo_path
                candidate.save(update_fields=["profile_photo_path", "updated_at"])
            if resume_path and not any(resume_autofill.values()):
                resume_autofill = _parse_resume_autofill(resume_path)

            if selected_position_ids:
                resume_text = _extract_resume_text_from_storage(resume_path) if resume_path else ""
                selected_jobs = list(JobRequisition.objects.filter(job_id__in=selected_position_ids))
                for job in selected_jobs:
                    score_payload = None
                    job_description = _build_job_description(job)
                    if resume_text and job_description:
                        education_text = candidate.degree_name or candidate.highest_education_level or ""
                        score_payload = score_resume_against_job(resume_text, job_description, education_text)
                    defaults = {"stage": "Applied"}
                    if score_payload:
                        defaults.update(
                            {
                                "resume_match_score": score_payload["match_score"],
                                "resume_experience_level": score_payload["experience_level"],
                                "resume_experience_years": score_payload["experience_years"],
                                "resume_skills_matched": score_payload["skills_matched"],
                                "resume_skills_required": score_payload["skills_required"],
                                "resume_skill_score": score_payload["skills_score"],
                                "resume_experience_score": score_payload["experience_score"],
                                "resume_education_score": score_payload["education_score"],
                                "resume_text_similarity": score_payload["text_similarity"],
                                "resume_match_status": score_payload["match_status"],
                                "resume_skills_matched_list": ", ".join(score_payload["skills_matched_list"]),
                                "resume_skills_missing_list": ", ".join(score_payload["skills_missing_list"]),
                                "resume_education_required": score_payload["education_required"],
                                "resume_education_candidate": score_payload["education_candidate"],
                            }
                        )
                    app, created = CandidateJobApplication.objects.get_or_create(
                        candidate=candidate,
                        job=job,
                        defaults=defaults,
                    )
                    if not created and score_payload:
                        app.resume_match_score = score_payload["match_score"]
                        app.resume_experience_level = score_payload["experience_level"]
                        app.resume_experience_years = score_payload["experience_years"]
                        app.resume_skills_matched = score_payload["skills_matched"]
                        app.resume_skills_required = score_payload["skills_required"]
                        app.resume_skill_score = score_payload["skills_score"]
                        app.resume_experience_score = score_payload["experience_score"]
                        app.resume_education_score = score_payload["education_score"]
                        app.resume_text_similarity = score_payload["text_similarity"]
                        app.resume_match_status = score_payload["match_status"]
                        app.resume_skills_matched_list = ", ".join(score_payload["skills_matched_list"])
                        app.resume_skills_missing_list = ", ".join(score_payload["skills_missing_list"])
                        app.resume_education_required = score_payload["education_required"]
                        app.resume_education_candidate = score_payload["education_candidate"]
                        app.save(
                            update_fields=[
                                "resume_match_score",
                                "resume_experience_level",
                                "resume_experience_years",
                                "resume_skills_matched",
                                "resume_skills_required",
                                "resume_skill_score",
                                "resume_experience_score",
                                "resume_education_score",
                                "resume_text_similarity",
                                "resume_match_status",
                                "resume_skills_matched_list",
                                "resume_skills_missing_list",
                                "resume_education_required",
                                "resume_education_candidate",
                            ]
                        )
                selected_titles = [job.title for job in selected_jobs if job.title]
                if selected_titles:
                    candidate.applied_position = ", ".join(selected_titles)
                    candidate.save(update_fields=["applied_position", "updated_at"])
            _save_candidate_education_records(
                candidate,
                education_records,
                fallback={
                    "highest_education_level": highest_education_level,
                    "degree_name": degree_name,
                    "institute_name": institute_name,
                    "year_of_passing": year_of_passing,
                    "percentage_cgpa": percentage_cgpa,
                },
            )
        except IntegrityError:
            messages.error(request, f"Email ID {email} already exists.")
            return render(
                request,
                "candidate_management/registration.html",
                {
                    "generated_candidate_id": candidate_id,
                    "form_data": request.POST,
                    "country_options": country_options,
                    "state_options": state_options,
                    "city_options": city_options,
                    "education_level_options": education_level_options,
                    "position_options": position_options,
                },
            )
        messages.success(request, f"Candidate {candidate.candidate_id} created successfully.")
        return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")

    return render(
        request,
        "candidate_management/registration.html",
        {
            "generated_candidate_id": _next_candidate_id(),
            "form_data": {},
            "country_options": country_options,
            "state_options": state_options,
            "city_options": city_options,
            "education_level_options": education_level_options,
            "position_options": position_options,
        },
    )


def candidate_list_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "update_status":
            candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
            new_status = request.POST.get("status", "").strip()
            job_id = request.POST.get("job_id", "").strip()
            if new_status:
                ok, message = _update_candidate_stage(request, candidate, new_status, job_id=job_id)
                if ok:
                    messages.success(request, message)
                else:
                    messages.error(request, message)
        elif action == "delete_candidate":
            if request.POST.get("confirm_delete") != "1":
                messages.error(request, "Please confirm delete by clicking Yes.")
                return redirect("candidate_management:list")
            candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
            deleted_id = candidate.candidate_id
            candidate.delete()
            messages.success(request, f"Candidate {deleted_id} deleted.")
        return redirect("candidate_management:list")

    return render_candidate_list(request)


def candidate_delete_confirm_view(request, candidate_id):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "confirm_delete":
            deleted_id = candidate.candidate_id
            candidate.delete()
            messages.success(request, f"Candidate {deleted_id} deleted.")
        return redirect("candidate_management:list")

    return render(
        request,
        "candidate_management/delete_confirm.html",
        {"candidate": candidate},
    )


def render_candidate_list(request):
    candidates = list(_candidates_with_evaluations())
    records = []
    status_options = set(STATUS_OPTIONS)

    for candidate in candidates:
        applications = list(candidate.job_applications.all())
        if applications:
            for app in applications:
                stage = app.stage or candidate.status or "Applied"
                status_options.add(stage)
                job_title = (app.job.title or "").strip() if app.job else ""
                job_id = (app.job.job_id or "").strip() if app.job else ""
                position_label = f"{job_id} - {job_title}".strip(" -") or _candidate_applied_positions(candidate)
                resume_score = ""
                if app.resume_match_score is not None:
                    try:
                        resume_score = round(float(app.resume_match_score), 2)
                    except (TypeError, ValueError):
                        resume_score = ""
                records.append(
                    {
                        "id": candidate.candidate_id,
                        "name": candidate.full_name,
                        "email": candidate.email,
                        "phone": candidate.contact_number,
                        "aadhaar": candidate.aadhaar,
                        "pan": candidate.pan,
                        "pf": "",
                        "esic": "",
                        "skills": candidate.skills,
                        "experience": candidate.experience,
                        "position": position_label,
                        "job_title": job_title or position_label,
                        "status": stage,
                        "job_id": job_id,
                        "references": candidate.references or "-",
                        "resume_name": os.path.basename(candidate.resume_path) if candidate.resume_path else "",
                        "resume_url": _resume_url(candidate.resume_path, candidate.candidate_id),
                        "profile_photo_url": _profile_photo_url(candidate.profile_photo_path, candidate.candidate_id),
                        "resume_score": resume_score,
                    }
                )
        else:
            status = _latest_status(candidate)
            status_options.add(status)
            records.append(
                {
                    "id": candidate.candidate_id,
                    "name": candidate.full_name,
                    "email": candidate.email,
                    "phone": candidate.contact_number,
                    "aadhaar": candidate.aadhaar,
                    "pan": candidate.pan,
                    "pf": "",
                    "esic": "",
                    "skills": candidate.skills,
                    "experience": candidate.experience,
                    "position": _candidate_applied_positions(candidate),
                    "job_title": "",
                    "status": status,
                    "job_id": "",
                    "references": candidate.references or "-",
                    "resume_name": os.path.basename(candidate.resume_path) if candidate.resume_path else "",
                    "resume_url": _resume_url(candidate.resume_path, candidate.candidate_id),
                    "profile_photo_url": _profile_photo_url(candidate.profile_photo_path, candidate.candidate_id),
                    "resume_score": "",
                }
            )

    searchable_keys = [
        "name",
        "email",
        "phone",
        "position",
        "aadhaar",
        "pan",
        "pf",
        "esic",
        "skills",
        "experience",
        "status",
        "references",
    ]
    filters = {key: request.GET.get(key, "").strip() for key in searchable_keys}
    query = request.GET.get("q", "").strip().lower()
    filtered_records = records

    for key, value in filters.items():
        if value:
            filtered_records = [
                row for row in filtered_records if value.lower() in str(row.get(key, "")).lower()
            ]

    if query:
        filtered_records = [
            row
            for row in filtered_records
            if any(query in str(row.get(key, "")).lower() for key in searchable_keys)
        ]

    return render(
        request,
        "candidate_management/list.html",
        {
            "records": filtered_records,
            "status_options": sorted(status_options),
            "query": request.GET.get("q", ""),
            "filters": filters,
            "total_records": len(records),
            "matched_records": len(filtered_records),
            "applied_filters_count": sum(1 for value in filters.values() if value),
        },
    )


def candidate_profile_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    if request.method == "POST":
        candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
        action = (request.POST.get("action") or "update_profile").strip()
        if action == "recalculate_match":
            resume_text = _extract_resume_text_from_storage(candidate.resume_path) if candidate.resume_path else ""
            if not resume_text:
                messages.error(request, "Resume text could not be extracted. Please upload a text-based PDF.")
                return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
            education_text = candidate.degree_name or candidate.highest_education_level or ""
            for app in CandidateJobApplication.objects.select_related("job").filter(candidate=candidate):
                job_description = _build_job_description(app.job)
                if not job_description:
                    continue
                score_payload = score_resume_against_job(resume_text, job_description, education_text)
                if not score_payload:
                    continue
                app.resume_match_score = score_payload["match_score"]
                app.resume_experience_level = score_payload["experience_level"]
                app.resume_experience_years = score_payload["experience_years"]
                app.resume_skills_matched = score_payload["skills_matched"]
                app.resume_skills_required = score_payload["skills_required"]
                app.resume_skill_score = score_payload["skills_score"]
                app.resume_experience_score = score_payload["experience_score"]
                app.resume_education_score = score_payload["education_score"]
                app.resume_text_similarity = score_payload["text_similarity"]
                app.resume_match_status = score_payload["match_status"]
                app.resume_skills_matched_list = ", ".join(score_payload["skills_matched_list"])
                app.resume_skills_missing_list = ", ".join(score_payload["skills_missing_list"])
                app.resume_education_required = score_payload["education_required"]
                app.resume_education_candidate = score_payload["education_candidate"]
                app.save(
                    update_fields=[
                        "resume_match_score",
                        "resume_experience_level",
                        "resume_experience_years",
                        "resume_skills_matched",
                        "resume_skills_required",
                        "resume_skill_score",
                        "resume_experience_score",
                        "resume_education_score",
                        "resume_text_similarity",
                        "resume_match_status",
                        "resume_skills_matched_list",
                        "resume_skills_missing_list",
                        "resume_education_required",
                        "resume_education_candidate",
                    ]
                )
            messages.success(request, "JD match recalculated.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
        if action == "add_note":
            note_text = request.POST.get("note_text", "").strip()
            if not note_text:
                messages.error(request, "Note is required.")
                return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
            created_by = (
                request.session.get("login_user_name")
                or request.session.get("login_user_email")
                or "Recruiter/Admin"
            )
            CandidateNote.objects.create(
                candidate=candidate,
                note=note_text[:4000],
                created_by=_normalize_spaces(created_by)[:120],
            )
            messages.success(request, "Candidate note added.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")

        if action != "update_profile":
            messages.error(request, "Invalid action.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")

        email = request.POST.get("email", "").strip()
        profile_photo_upload = request.FILES.get("profile_photo_upload")
        if Candidate.objects.exclude(pk=candidate.pk).filter(email__iexact=email).exists():
            messages.error(request, f"Email ID {email} already exists.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
        if profile_photo_upload and not _is_profile_photo_upload(profile_photo_upload):
            messages.error(request, "Profile photo must be JPG or PNG format only.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
        candidate.full_name = request.POST.get("name", "").strip()
        candidate.email = email
        candidate.contact_number = request.POST.get("phone", "").strip()
        candidate.skills = request.POST.get("skills", "").strip()
        candidate.experience = request.POST.get("experience", "").strip()
        candidate.highest_education_level = request.POST.get("education", "").strip()
        candidate.degree_name = request.POST.get("education", "").strip()
        candidate.institute_name = request.POST.get("institute_name", candidate.institute_name).strip()
        candidate.year_of_passing = request.POST.get("year_of_passing", candidate.year_of_passing).strip()
        candidate.percentage_cgpa = request.POST.get("percentage_cgpa", candidate.percentage_cgpa).strip()
        candidate.social_media_link = request.POST.get("social_media_link", "").strip()
        candidate.employment_history = request.POST.get("employment_history", "").strip()
        candidate.certifications = request.POST.get("certificates", "").strip()
        candidate.references = request.POST.get("references", "").strip()
        candidate.custom_tags = ", ".join(_normalize_custom_tags(request.POST.get("custom_tags", "")))
        if profile_photo_upload:
            candidate.profile_photo_path = _save_profile_photo_upload_versioned(candidate, profile_photo_upload)
        try:
            candidate.save()
        except IntegrityError:
            messages.error(request, f"Email ID {email} already exists.")
            return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")
        messages.success(request, f"Candidate profile updated for {candidate.candidate_id}.")
        return redirect(f"/candidate-management/profile/?candidate_id={candidate.candidate_id}")

    candidate_id = request.GET.get("candidate_id", "").strip()
    candidate_qs = Candidate.objects.prefetch_related(
        "education_records",
        "notes",
        Prefetch("job_applications", queryset=CandidateJobApplication.objects.select_related("job").order_by("-applied_on")),
    ).order_by("-created_at")
    candidates = list(candidate_qs)
    selected = get_object_or_404(candidate_qs, candidate_id=candidate_id) if candidate_id else (candidates[0] if candidates else None)

    custom_tags = _normalize_custom_tags(selected.custom_tags if selected else "")
    job_matches = []
    if selected:
        for app in selected.job_applications.all():
            job = app.job
            job_matches.append(
                {
                    "job_id": job.job_id if job else "",
                    "job_title": job.title if job else "",
                    "match_score": app.resume_match_score,
                    "match_status": app.resume_match_status,
                    "skill_score": app.resume_skill_score,
                    "experience_score": app.resume_experience_score,
                    "education_score": app.resume_education_score,
                    "text_similarity": app.resume_text_similarity,
                    "skills_matched": app.resume_skills_matched_list,
                    "skills_missing": app.resume_skills_missing_list,
                    "skills_required": app.resume_skills_required,
                    "experience_level": app.resume_experience_level,
                    "experience_years": app.resume_experience_years,
                    "education_required": app.resume_education_required,
                    "education_candidate": app.resume_education_candidate,
                    "skills_required_text": (job.skills_required or "").strip() if job else "",
                }
            )

    profile = {
        "candidate_id": selected.candidate_id if selected else "",
        "name": selected.full_name if selected else "",
        "email": selected.email if selected else "",
        "phone": selected.contact_number if selected else "",
        "skills": selected.skills if selected else "",
        "experience": selected.experience if selected else "",
        "education": (selected.degree_name or selected.highest_education_level) if selected else "",
        "institute_name": selected.institute_name if selected else "",
        "year_of_passing": selected.year_of_passing if selected else "",
        "percentage_cgpa": selected.percentage_cgpa if selected else "",
        "social_media_link": selected.social_media_link if selected else "",
        "employment_history": selected.employment_history if selected else "",
        "certificates": selected.certifications if selected else "",
        "references": selected.references if selected else "",
        "custom_tags": custom_tags,
        "custom_tags_display": ", ".join(custom_tags),
        "resume_name": (os.path.basename(selected.resume_path) if selected and selected.resume_path else ""),
        "resume_url": (_resume_url(selected.resume_path, selected.candidate_id) if selected else ""),
        "profile_photo_url": (_profile_photo_url(selected.profile_photo_path, selected.candidate_id) if selected else ""),
        "education_records": (
            [
                {
                    "level": item.level,
                    "course": item.course,
                    "institute": item.institute,
                    "board_university": item.board_university,
                    "year_of_passing": item.year_of_passing,
                    "score": item.score,
                }
                for item in selected.education_records.all()
            ]
            if selected
            else []
        ),
        "notes": (
            [
                {"note": item.note, "created_by": item.created_by, "created_at": item.created_at}
                for item in selected.notes.all()[:5]
            ]
            if selected
            else []
        ),
        "job_matches": job_matches,
    }

    candidate_rows = [{"id": item.candidate_id, "name": item.full_name} for item in candidates]
    return render(
        request,
        "candidate_management/profile.html",
        {"profile": profile, "candidate_rows": candidate_rows},
    )


def candidate_notes_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    candidate_id = request.GET.get("candidate_id", "").strip()
    if request.method == "POST":
        candidate_id = request.POST.get("candidate_id", "").strip()
        action = (request.POST.get("action") or "").strip()
        candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
        if action == "add_note":
            note_text = request.POST.get("note_text", "").strip()
            if not note_text:
                messages.error(request, "Note is required.")
            else:
                created_by = (
                    request.session.get("login_user_name")
                    or request.session.get("login_user_email")
                    or "Recruiter/Admin"
                )
                
                # Mark scheduled activity as complete if supplied and link to note
                complete_activity_id = request.POST.get("complete_activity_id", "").strip()
                act_obj = None
                if complete_activity_id:
                    act_obj = CandidateActivity.objects.filter(id=complete_activity_id, candidate=candidate).first()

                CandidateNote.objects.create(
                    candidate=candidate,
                    activity=act_obj,
                    note=note_text[:4000],
                    created_by=_normalize_spaces(created_by)[:120],
                )
                
                if act_obj:
                    act_obj.status = "Done"
                    act_obj.completed_at = timezone.now()
                    act_obj.save(update_fields=["status", "completed_at", "updated_at"])
                    messages.success(request, f"Note added & Activity '{act_obj.title}' marked as Done!")
                else:
                    messages.success(request, "Candidate note added.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")
        if action == "update_note":
            note_id = request.POST.get("note_id", "").strip()
            note_obj = CandidateNote.objects.filter(id=note_id, candidate=candidate).first()
            if not note_obj:
                messages.error(request, "Note not found or already deleted.")
                return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")
            note_text = request.POST.get("note_text", "").strip()
            if not note_text:
                messages.error(request, "Note is required.")
            else:
                note_obj.note = note_text[:4000]
                note_obj.save(update_fields=["note", "updated_at"])
                messages.success(request, "Candidate note updated.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")
        if action == "delete_note":
            note_id = request.POST.get("note_id", "").strip()
            note_obj = CandidateNote.objects.filter(id=note_id, candidate=candidate).first()
            if not note_obj:
                messages.error(request, "Note not found or already deleted.")
                return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")
            note_obj.delete()
            messages.success(request, "Candidate note deleted successfully.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")

        # ── Activity actions ──────────────────────────────────────────
        if action == "add_activity":
            activity_type = request.POST.get("activity_type", "call").strip()
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            scheduled_date = request.POST.get("scheduled_date", "").strip()
            scheduled_time = request.POST.get("scheduled_time", "09:00").strip() or "09:00"
            scheduled_at = None
            if scheduled_date:
                try:
                    from datetime import datetime as _dt
                    scheduled_at = timezone.make_aware(_dt.strptime(f"{scheduled_date} {scheduled_time}", "%Y-%m-%d %H:%M"))
                except ValueError:
                    scheduled_at = None
            if not title:
                title = f"{activity_type.capitalize()} with {candidate.full_name}"
            created_by = (
                request.session.get("login_user_name")
                or request.session.get("login_user_email")
                or "Recruiter/Admin"
            )
            doc_file = request.FILES.get("document_file")
            act = CandidateActivity(
                candidate=candidate,
                activity_type=activity_type,
                title=title[:255],
                description=description[:4000],
                scheduled_at=scheduled_at,
                created_by=_normalize_spaces(created_by)[:120],
                status="Scheduled",
            )
            if doc_file:
                act.document = doc_file
            act.save()
            messages.success(request, f"Activity '{title}' scheduled successfully.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")

        if action == "update_activity_status":
            activity_id = request.POST.get("activity_id", "").strip()
            new_status = request.POST.get("status", "Done").strip()
            act_obj = CandidateActivity.objects.filter(id=activity_id, candidate=candidate).first()
            if act_obj:
                act_obj.status = new_status
                if new_status == "Done":
                    act_obj.completed_at = timezone.now()
                act_obj.save(update_fields=["status", "completed_at", "updated_at"])
                messages.success(request, f"Activity marked as {new_status}.")
            else:
                messages.error(request, "Activity not found.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")

        if action == "delete_activity":
            activity_id = request.POST.get("activity_id", "").strip()
            act_obj = CandidateActivity.objects.filter(id=activity_id, candidate=candidate).first()
            if act_obj:
                act_obj.delete()
                messages.success(request, "Activity deleted.")
            else:
                messages.error(request, "Activity not found.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")

        if action == "reschedule_activity":
            activity_id = request.POST.get("activity_id", "").strip()
            act_obj = CandidateActivity.objects.filter(id=activity_id, candidate=candidate).first()
            if act_obj:
                scheduled_date = request.POST.get("scheduled_date", "").strip()
                scheduled_time = request.POST.get("scheduled_time", "09:00").strip() or "09:00"
                scheduled_at = None
                if scheduled_date:
                    try:
                        from datetime import datetime as _dt
                        scheduled_at = timezone.make_aware(_dt.strptime(f"{scheduled_date} {scheduled_time}", "%Y-%m-%d %H:%M"))
                    except ValueError:
                        scheduled_at = None
                if scheduled_at:
                    act_obj.scheduled_at = scheduled_at
                    act_obj.status = "Scheduled"
                    act_obj.save(update_fields=["scheduled_at", "status", "updated_at"])
                    messages.success(request, f"Activity '{act_obj.title}' rescheduled successfully.")
                else:
                    messages.error(request, "Invalid date/time provided.")
            else:
                messages.error(request, "Activity not found.")
            return redirect(f"/candidate-management/notes/?candidate_id={candidate.candidate_id}")

    candidate_qs = Candidate.objects.prefetch_related(
        "notes",
        "activities",
        Prefetch("job_applications", queryset=CandidateJobApplication.objects.select_related("job").order_by("-applied_on")),
    ).order_by("-created_at")
    candidates = list(candidate_qs)
    selected = get_object_or_404(candidate_qs, candidate_id=candidate_id) if candidate_id else (candidates[0] if candidates else None)

    notes = (
        [
            {
                "id": item.id,
                "note": item.note,
                "created_by": item.created_by,
                "created_at": item.created_at,
                "activity_title": item.activity.title if item.activity else None,
                "activity_type": item.activity.activity_type if item.activity else None,
            }
            for item in selected.notes.select_related("activity").all()
        ]
        if selected
        else []
    )
    activities = list(selected.activities.order_by("scheduled_at", "-created_at")) if selected else []

    return render(
        request,
        "candidate_management/notes.html",
        {
            "candidate_rows": [
                {
                    "id": item.candidate_id,
                    "name": item.full_name,
                    "title": _candidate_applied_positions(item),
                }
                for item in candidates
            ],
            "selected_candidate": selected,
            "selected_candidate_title": _candidate_applied_positions(selected) if selected else "",
            "notes": notes,
            "activities": activities,
        },
    )


def candidate_activity_dashboard_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        activity_id = request.POST.get("activity_id", "").strip()
        act_obj = CandidateActivity.objects.filter(id=activity_id).first()
        if act_obj:
            if action == "mark_done":
                act_obj.status = "Done"
                act_obj.completed_at = timezone.now()
                act_obj.save(update_fields=["status", "completed_at", "updated_at"])
                messages.success(request, "Activity marked as done.")
            elif action == "delete_activity":
                act_obj.delete()
                messages.success(request, "Activity deleted.")
            elif action == "reschedule_activity":
                scheduled_date = request.POST.get("scheduled_date", "").strip()
                scheduled_time = request.POST.get("scheduled_time", "09:00").strip() or "09:00"
                scheduled_at = None
                if scheduled_date:
                    try:
                        from datetime import datetime as _dt
                        scheduled_at = timezone.make_aware(_dt.strptime(f"{scheduled_date} {scheduled_time}", "%Y-%m-%d %H:%M"))
                    except ValueError:
                        scheduled_at = None
                if scheduled_at:
                    act_obj.scheduled_at = scheduled_at
                    act_obj.status = "Scheduled"
                    act_obj.save(update_fields=["scheduled_at", "status", "updated_at"])
                    messages.success(request, f"Activity '{act_obj.title}' rescheduled successfully.")
                else:
                    messages.error(request, "Invalid date/time provided.")
        next_url = request.POST.get("next", "/candidate-management/activity/")
        return redirect(next_url)

    today = timezone.localdate()
    all_activities = (
        CandidateActivity.objects
        .select_related("candidate")
        .order_by("scheduled_at", "-created_at")
    )

    past_activities = []
    today_activities = []
    future_activities = []

    for act in all_activities:
        if act.scheduled_at:
            act_date = act.scheduled_at.date()
            if act_date < today:
                act.time_frame = "past"
                past_activities.append(act)
            elif act_date == today:
                act.time_frame = "today"
                today_activities.append(act)
            else:
                act.time_frame = "future"
                future_activities.append(act)
        else:
            act.time_frame = "today"
            today_activities.append(act)

    view_filter = request.GET.get("view", "").strip().lower()

    if view_filter in ("past", "today", "future"):
        if view_filter == "past":
            filtered = past_activities
            title = "Past Activities"
            color_class = "past"
        elif view_filter == "today":
            filtered = today_activities
            title = "Today's Activities"
            color_class = "today"
        else:
            filtered = future_activities
            title = "Upcoming Activities"
            color_class = "future"

        return render(
            request,
            "candidate_management/activity_detail.html",
            {
                "activities": filtered,
                "view_filter": view_filter,
                "title": title,
                "color_class": color_class,
                "today": today,
                "past_count": len(past_activities),
                "today_count": len(today_activities),
                "future_count": len(future_activities),
            }
        )

    return render(
        request,
        "candidate_management/activity_dashboard.html",
        {
            "past_count": len(past_activities),
            "today_count": len(today_activities),
            "future_count": len(future_activities),
            "today": today,
            "activities": list(all_activities),
        }
    )


def candidate_evaluation_view(request):
    blocked = _candidate_management_access_guard(request)
    if blocked:
        return blocked

    if request.method == "POST":
        action = request.POST.get("action", "save_evaluation").strip()
        if action == "delete_evaluation":
            evaluation = get_object_or_404(CandidateEvaluation, id=request.POST.get("evaluation_id"))
            evaluation.delete()
            messages.success(request, "Candidate evaluation deleted.")
            return redirect("candidate_management:evaluation")

        status = request.POST.get("status", "").strip()
        custom_status = request.POST.get("custom_status", "").strip()
        final_status = custom_status if status == "__custom__" and custom_status else status
        evaluation_id = request.POST.get("evaluation_id", "").strip()
        assessment_form_id = request.POST.get("assessment_form_id", "").strip()
        feedback_form_id = request.POST.get("feedback_form_id", "").strip()
        form_catalog = _evaluation_form_catalog()
        form_map = form_catalog["map"]

        def _collect_dynamic_form_data(form_id, expected_type, prefix):
            if not form_id:
                return "", ""
            form_cfg = form_map.get(str(form_id))
            if not form_cfg or form_cfg.get("form_type") != expected_type:
                return "", ""
            values = {}
            for field in form_cfg["fields"]:
                field_key = f"{prefix}{field['field_name']}"
                if field.get("field_type") == "checkbox":
                    selected_values = [item.strip() for item in request.POST.getlist(field_key) if item.strip()]
                    field_value = ", ".join(selected_values)
                else:
                    field_value = request.POST.get(field_key, "").strip()
                if field.get("required") and not field_value:
                    raise ValueError(f"{form_cfg['name']} - {field['label']} is required.")
                values[field["field_name"]] = field_value
            return form_cfg["name"], json.dumps(values)

        required_values = [
            request.POST.get("candidate_id", "").strip(),
            request.POST.get("candidate_name", "").strip(),
            request.POST.get("candidate_phone", "").strip(),
            request.POST.get("candidate_email", "").strip(),
            request.POST.get("posting_title", "").strip(),
            request.POST.get("interviewed_by", "").strip(),
            request.POST.get("interview_round", "").strip(),
            request.POST.get("technical_score", "").strip(),
            request.POST.get("communication_score", "").strip(),
            request.POST.get("cultural_fit_score", "").strip(),
            request.POST.get("overall_rating", "").strip(),
            final_status,
        ]
        if any(not item for item in required_values):
            messages.error(request, "Please fill all mandatory fields.")
            return render_candidate_evaluation(
                request,
                show_form=True,
                selected_candidate_id=request.POST.get("candidate_id", "").strip(),
                form_data=request.POST,
            )

        try:
            assessment_form_name, assessment_form_data = _collect_dynamic_form_data(
                assessment_form_id,
                "assessment",
                "assessment_field_",
            )
            feedback_form_name, feedback_form_data = _collect_dynamic_form_data(
                feedback_form_id,
                "feedback",
                "feedback_field_",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render_candidate_evaluation(
                request,
                show_form=True,
                selected_candidate_id=request.POST.get("candidate_id", "").strip(),
                form_data=request.POST,
            )

        candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
        payload = {
            "candidate": candidate,
            "candidate_code": candidate.candidate_id,
            "candidate_name": request.POST.get("candidate_name", "").strip(),
            "candidate_phone": request.POST.get("candidate_phone", "").strip(),
            "candidate_email": request.POST.get("candidate_email", "").strip(),
            "posting_title": request.POST.get("posting_title", "").strip(),
            "interviewed_by": request.POST.get("interviewed_by", "").strip(),
            "interview_round": request.POST.get("interview_round", "").strip(),
            "technical_score": request.POST.get("technical_score"),
            "communication_score": request.POST.get("communication_score"),
            "cultural_fit_score": request.POST.get("cultural_fit_score"),
            "overall_rating": request.POST.get("overall_rating"),
            "interviewer_comments": request.POST.get("interviewer_comments", "").strip(),
            "assessment_form_name": assessment_form_name,
            "assessment_form_data": assessment_form_data,
            "feedback_form_name": feedback_form_name,
            "feedback_form_data": feedback_form_data,
            "status": final_status,
        }

        if evaluation_id:
            evaluation = get_object_or_404(CandidateEvaluation, id=evaluation_id)
            for key, value in payload.items():
                setattr(evaluation, key, value)
            evaluation.save()
            messages.success(request, "Candidate evaluation updated.")
        else:
            CandidateEvaluation.objects.create(**payload)
            messages.success(request, "Candidate evaluation saved.")

        InterviewEvaluationSubmission.objects.update_or_create(
            candidate=candidate,
            interviewer_name=payload["interviewed_by"],
            interview_round=payload["interview_round"],
            defaults={
                "candidate_name": payload["candidate_name"],
                "technical_score": payload["technical_score"],
                "communication_score": payload["communication_score"],
                "cultural_fit_score": payload["cultural_fit_score"],
                "comments": payload["interviewer_comments"],
                "interview_round": payload["interview_round"],
                "assessment_form_name": assessment_form_name,
                "assessment_form_data": assessment_form_data,
                "feedback_form_name": feedback_form_name,
                "feedback_form_data": feedback_form_data,
            },
        )

        posting_title = (payload["posting_title"] or "").strip()
        if posting_title:
            candidate_app = (
                CandidateJobApplication.objects.select_related("job")
                .filter(candidate=candidate, job__title__iexact=posting_title)
                .order_by("-applied_on")
                .first()
            )
            if candidate_app and candidate_app.stage != final_status:
                candidate_app.stage = final_status
                candidate_app.save(update_fields=["stage"])

        previous_status = candidate.status
        candidate.status = final_status
        candidate.save(update_fields=["status", "updated_at"])
        _notify_candidate_status_change(request, candidate, previous_status)
        messages.info(request, "Candidate evaluation information sent to Interview Evaluation.")
        return redirect(f"/interview-evaluation/evaluation/?candidate_id={candidate.candidate_id}&candidate_name={candidate.full_name}")

    return render_candidate_evaluation(
        request,
        show_form=request.GET.get("create") == "1",
        selected_candidate_id=request.GET.get("candidate_id", "").strip(),
        edit_id=request.GET.get("edit_id", "").strip(),
    )


def render_candidate_evaluation(request, show_form=False, selected_candidate_id="", edit_id="", form_data=None):
    form_data = form_data or {}
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    candidate_qs = Candidate.objects.order_by("candidate_id")
    candidate_options = [
        {
            "id": item.candidate_id,
            "name": item.full_name,
            "email": item.email,
            "phone": item.contact_number,
            "posting_title": item.applied_position,
        }
        for item in candidate_qs
    ]
    option_map = {item["id"]: item for item in candidate_options}
    selected_candidate = option_map.get(selected_candidate_id) if selected_candidate_id else None
    form_catalog = _evaluation_form_catalog()
    name_to_id = form_catalog["name_to_id"]
    round_map = {}
    scheduled_items = []
    for item in InPersonInterview.objects.select_related("candidate").order_by("-created_at"):
        scheduled_items.append((item.created_at, item.candidate, item.interview_process_name))
    for item in VideoInterviewSchedule.objects.select_related("candidate").order_by("-created_at"):
        scheduled_items.append((item.created_at, item.candidate, item.interview_process_name))
    scheduled_items.sort(key=lambda row: row[0] or "")
    for _, candidate_ref, round_name in reversed(scheduled_items):
        candidate_id = candidate_ref.candidate_id if candidate_ref else ""
        if candidate_id and candidate_id not in round_map and round_name:
            round_map[candidate_id] = round_name

    evaluation_edit = None
    if edit_id:
        evaluation_edit = CandidateEvaluation.objects.filter(id=edit_id).first()
        if evaluation_edit:
            show_form = True
            selected_candidate = option_map.get(
                evaluation_edit.candidate.candidate_id if evaluation_edit.candidate else evaluation_edit.candidate_code
            )

    initial = {
        "candidate_id": (
            (evaluation_edit.candidate.candidate_id if evaluation_edit and evaluation_edit.candidate else None)
            or (evaluation_edit.candidate_code if evaluation_edit else None)
            or (selected_candidate or {}).get("id", "")
        ),
        "candidate_name": (evaluation_edit.candidate_name if evaluation_edit else (selected_candidate or {}).get("name", "")),
        "candidate_phone": (evaluation_edit.candidate_phone if evaluation_edit else (selected_candidate or {}).get("phone", "")),
        "candidate_email": (evaluation_edit.candidate_email if evaluation_edit else (selected_candidate or {}).get("email", "")),
        "posting_title": (
            evaluation_edit.posting_title if evaluation_edit else (selected_candidate or {}).get("posting_title", "")
        ),
        "interviewed_by": evaluation_edit.interviewed_by if evaluation_edit else "",
        "interview_round": evaluation_edit.interview_round if evaluation_edit else "",
        "technical_score": evaluation_edit.technical_score if evaluation_edit else "",
        "communication_score": evaluation_edit.communication_score if evaluation_edit else "",
        "cultural_fit_score": evaluation_edit.cultural_fit_score if evaluation_edit else "",
        "overall_rating": evaluation_edit.overall_rating if evaluation_edit else "",
        "interviewer_comments": evaluation_edit.interviewer_comments if evaluation_edit else "",
        "status": evaluation_edit.status if evaluation_edit else "",
        "custom_status": "",
        "evaluation_id": evaluation_edit.id if evaluation_edit else "",
        "assessment_form_id": (
            str(name_to_id.get(evaluation_edit.assessment_form_name, "")) if evaluation_edit else ""
        ),
        "feedback_form_id": (
            str(name_to_id.get(evaluation_edit.feedback_form_name, "")) if evaluation_edit else ""
        ),
        "assessment_form_values": {},
        "feedback_form_values": {},
    }

    if evaluation_edit and evaluation_edit.assessment_form_data:
        try:
            initial["assessment_form_values"] = json.loads(evaluation_edit.assessment_form_data)
        except (TypeError, ValueError):
            initial["assessment_form_values"] = {}
    if evaluation_edit and evaluation_edit.feedback_form_data:
        try:
            initial["feedback_form_values"] = json.loads(evaluation_edit.feedback_form_data)
        except (TypeError, ValueError):
            initial["feedback_form_values"] = {}

    if not initial["interview_round"]:
        selected_id = initial["candidate_id"]
        if selected_id and round_map.get(selected_id):
            initial["interview_round"] = round_map[selected_id]

    if form_data:
        initial["candidate_id"] = form_data.get("candidate_id", initial["candidate_id"])
        initial["candidate_name"] = form_data.get("candidate_name", initial["candidate_name"])
        initial["candidate_phone"] = form_data.get("candidate_phone", initial["candidate_phone"])
        initial["candidate_email"] = form_data.get("candidate_email", initial["candidate_email"])
        initial["posting_title"] = form_data.get("posting_title", initial["posting_title"])
        initial["interviewed_by"] = form_data.get("interviewed_by", initial["interviewed_by"])
        initial["interview_round"] = form_data.get("interview_round", initial["interview_round"])
        initial["technical_score"] = form_data.get("technical_score", initial["technical_score"])
        initial["communication_score"] = form_data.get("communication_score", initial["communication_score"])
        initial["cultural_fit_score"] = form_data.get("cultural_fit_score", initial["cultural_fit_score"])
        initial["overall_rating"] = form_data.get("overall_rating", initial["overall_rating"])
        initial["interviewer_comments"] = form_data.get("interviewer_comments", initial["interviewer_comments"])
        initial["status"] = form_data.get("status", initial["status"])
        initial["custom_status"] = form_data.get("custom_status", initial["custom_status"])
        initial["assessment_form_id"] = form_data.get("assessment_form_id", initial["assessment_form_id"])
        initial["feedback_form_id"] = form_data.get("feedback_form_id", initial["feedback_form_id"])

        assessment_values = {}
        feedback_values = {}
        for key, value in form_data.items():
            if key.startswith("assessment_field_"):
                assessment_values[key.replace("assessment_field_", "", 1)] = value
            elif key.startswith("feedback_field_"):
                feedback_values[key.replace("feedback_field_", "", 1)] = value
        initial["assessment_form_values"] = assessment_values
        initial["feedback_form_values"] = feedback_values

    if initial["status"] and initial["status"] not in EVALUATION_BASE_STATUSES:
        initial["custom_status"] = initial["status"]
        initial["status"] = "__custom__"

    records_qs = CandidateEvaluation.objects.order_by("-created_at")
    if current_user and not is_admin:
        records_qs = records_qs.filter(interviewed_by__iexact=current_user)
    records = []
    for row in records_qs:
        records.append(
            {
                "id": row.id,
                "candidate_id": row.candidate_code,
                "candidate_name": row.candidate_name,
                "interview_round": row.interview_round or "-",
                "technical_score": round(float(row.technical_score or 0), 2),
                "communication_score": round(float(row.communication_score or 0), 2),
                "cultural_fit_score": round(float(row.cultural_fit_score or 0), 2),
                "overall_rating": round(float(row.overall_rating or 0), 2),
                "interviewer_comments": row.interviewer_comments,
                "assessment_form_name": row.assessment_form_name or "-",
                "feedback_form_name": row.feedback_form_name or "-",
                "status": row.status,
            }
        )

    agg = records_qs.aggregate(
        avg_technical=Avg("technical_score"),
        avg_communication=Avg("communication_score"),
        avg_cultural=Avg("cultural_fit_score"),
        avg_overall=Avg("overall_rating"),
    )

    interviewer_options = _interviewer_options()
    return render(
        request,
        "candidate_management/evaluation.html",
        {
            "records": records,
            "show_form": show_form,
            "candidate_options": candidate_options,
            "interviewer_options": interviewer_options,
            "interviewer_name_list": [item["full_name"] for item in interviewer_options],
            "selected_candidate_id": selected_candidate_id,
            "initial_candidate_id": initial["candidate_id"],
            "initial_candidate_name": initial["candidate_name"],
            "initial_candidate_phone": initial["candidate_phone"],
            "initial_candidate_email": initial["candidate_email"],
            "initial_posting_title": initial["posting_title"],
            "initial_interviewed_by": initial["interviewed_by"],
            "initial_interview_round": initial["interview_round"],
            "initial_technical_score": initial["technical_score"],
            "initial_communication_score": initial["communication_score"],
            "initial_cultural_fit_score": initial["cultural_fit_score"],
            "initial_overall_rating": initial["overall_rating"],
            "initial_interviewer_comments": initial["interviewer_comments"],
            "initial_status": initial["status"],
            "initial_custom_status": initial["custom_status"],
            "initial_evaluation_id": initial["evaluation_id"],
            "initial_assessment_form_id": initial["assessment_form_id"],
            "initial_feedback_form_id": initial["feedback_form_id"],
            "initial_assessment_form_values": initial["assessment_form_values"],
            "initial_feedback_form_values": initial["feedback_form_values"],
            "avg_technical": round(float(agg["avg_technical"] or 0), 2),
            "avg_communication": round(float(agg["avg_communication"] or 0), 2),
            "avg_cultural": round(float(agg["avg_cultural"] or 0), 2),
            "avg_overall": round(float(agg["avg_overall"] or 0), 2),
            "assessment_form_options": form_catalog["assessment"],
            "feedback_form_options": form_catalog["feedback"],
            "evaluation_form_map": form_catalog["map"],
            "interview_round_options": INTERVIEW_ROUND_OPTIONS,
            "candidate_round_map": round_map,
        },
    )


def _candidate_applied_positions(candidate):
    titles = [item.job.title for item in candidate.job_applications.all() if item.job and item.job.title]
    if titles:
        return ", ".join(dict.fromkeys(titles))
    return candidate.applied_position or candidate.degree_name or "-"


def _interviewer_options():
    return list(
        UserMaster.objects.filter(status__iexact="Active")
        .exclude(role__iexact="Candidate")
        .order_by("full_name")
        .values("full_name")
    )


def _login_user_name(request):
    return (
        (request.session.get("login_user_name") or "").strip()
        or (request.session.get("login_user_email") or "").strip()
    )


def _is_admin_request(request):
    role = (request.session.get("login_user_role") or "").strip().lower()
    return role in {"admin", "super admin", "administrator"}



