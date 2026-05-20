import json
from urllib import error, request as urllib_request

from django.contrib import messages
from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import get_valid_filename

from candidate_management.models import Candidate

from .models import BackgroundVerificationRecord


def background_verification_view(request):
    return render(request, "background_verification/index.html")


ID_PROOF_OPTIONS = ["Aadhaar Card", "PAN Card", "Passport", "Driving License", "Voter ID", "Other"]
ADDRESS_PROOF_OPTIONS = ["Utility Bill", "Rental Agreement", "Passport", "Bank Statement", "Aadhaar Card", "Other"]
EDUCATION_PROOF_OPTIONS = ["Degree Certificate", "Provisional Certificate", "Marksheet", "Transcript", "Other"]
EMPLOYMENT_PROOF_OPTIONS = ["Experience Letter", "Relieving Letter", "Salary Slip", "Offer Letter", "Other"]
RISK_THRESHOLD = 70


def _is_pdf_file(file_obj):
    if not file_obj:
        return True
    filename = (file_obj.name or "").lower()
    if not filename.endswith(".pdf"):
        return False
    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type and content_type not in {"application/pdf", "application/x-pdf", "application/octet-stream"}:
        return False
    return True


def _save_bgv_upload(file_obj, bucket):
    if not file_obj:
        return ""
    safe_name = get_valid_filename(file_obj.name)
    return default_storage.save(f"bgv/{bucket}/{safe_name}", file_obj)


def _pack_document_value(doc_type, file_path):
    doc_type = (doc_type or "").strip()
    file_path = (file_path or "").strip()
    if doc_type and file_path:
        return f"{doc_type}||{file_path}"
    if doc_type:
        return doc_type
    if file_path:
        return f"Uploaded||{file_path}"
    return ""


def _unpack_document_value(value):
    raw = (value or "").strip()
    if not raw:
        return "", ""
    if "||" in raw:
        doc_type, file_path = raw.split("||", 1)
        return doc_type.strip(), file_path.strip()
    return raw, ""


def _file_url(file_path):
    return f"{settings.MEDIA_URL}{file_path}" if file_path else ""


def _read_storage_bytes(file_path):
    if not file_path:
        return b""
    with default_storage.open(file_path, "rb") as handle:
        return handle.read()


def _extract_pdf_text(data):
    if not data:
        return ""
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    text_parts = []
    for page in doc:
        page_text = page.get_text("text")
        if page_text:
            text_parts.append(page_text)
    extracted = "\n".join(text_parts).strip()
    if extracted:
        return extracted
    return _ocr_pdf_pages(doc)


def _ocr_pdf_pages(doc, max_pages=2):
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    tesseract_cmd = (getattr(settings, "TESSERACT_CMD", "") or "").strip()
    if tesseract_cmd:
        try:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        except Exception:
            pass
    text_parts = []
    for index, page in enumerate(doc):
        if index >= max_pages:
            break
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            mode = "RGB"
            image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            ocr_text = pytesseract.image_to_string(image)
            if ocr_text:
                text_parts.append(ocr_text)
        except Exception:
            continue
    return "\n".join(text_parts).strip()


def _extract_text_from_file(file_path):
    if not file_path:
        return ""
    try:
        data = _read_storage_bytes(file_path)
    except Exception:
        return ""
    lower_path = (file_path or "").lower()
    if lower_path.endswith(".pdf"):
        extracted = _extract_pdf_text(data)
        if extracted:
            return extracted
    try:
        return data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _extract_first_json_object(raw_text):
    if not raw_text:
        return {}
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    snippet = raw_text[start : end + 1]
    try:
        return json.loads(snippet)
    except (TypeError, ValueError):
        return {}


def _normalize_gemini_field(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = (item.get("text") or "").strip()
                if not text:
                    text = json.dumps(item, ensure_ascii=False)
            else:
                text = str(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        for key in ("items", "bullet_points", "points"):
            if isinstance(value.get(key), list):
                return _normalize_gemini_field(value.get(key))
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _build_bgv_ocr_summary(record):
    doc_fields = [
        ("ID Proof", record.id_proof),
        ("Address Proof", record.address_proof),
        ("Education", record.education_certificates),
        ("Employment", record.employment_proof),
    ]
    summaries = []
    for label, packed in doc_fields:
        _, file_path = _unpack_document_value(packed)
        text = _extract_text_from_file(file_path)
        if not text:
            continue
        text = text.replace("\x00", " ").strip()
        if len(text) > 1500:
            text = text[:1500] + "..."
        summaries.append(f"{label}:\n{text}")
    if record.reference_contacts:
        summaries.append(f"References:\n{record.reference_contacts.strip()}")
    if record.comments:
        summaries.append(f"Verifier Notes:\n{record.comments.strip()}")
    if record.discrepancies and record.discrepancies.strip() != "-":
        summaries.append(f"Known Discrepancies:\n{record.discrepancies.strip()}")
    return "\n\n".join(summaries).strip()


def _gemini_bgv_risk_score(summary_text, candidate_label):
    gemini_api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    gemini_model = (getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash").strip()
    if not gemini_api_key:
        return {"ok": False, "message": "Gemini API key is missing. Set GEMINI_API_KEY in environment."}

    prompt = (
        "You are a background verification risk analyst.\n"
        "Analyze the evidence and notes below for inconsistencies, missing info, or red flags.\n"
        "Return VALID JSON ONLY, no markdown, no extra text.\n"
        "Required keys: risk_score (INTEGER 0-100), risk_level (Low/Medium/High), reason (1-2 sentences).\n"
        "If evidence is insufficient, return risk_score 20, risk_level Low, and explain that evidence is limited.\n\n"
        f"Candidate: {candidate_label}\n\n"
        f"Evidence:\n{summary_text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
        },
    }

    fallback_models = [
        gemini_model,
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    seen = set()
    ordered_models = []
    for model_name in fallback_models:
        if model_name and model_name not in seen:
            ordered_models.append(model_name)
            seen.add(model_name)

    body = None
    last_error = ""
    for model_name in ordered_models:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            f"?key={gemini_api_key}"
        )
        try:
            req = urllib_request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                detail = str(exc)
            last_error = f"{model_name}: {detail[:280]}"
            continue
        except Exception as exc:
            last_error = f"{model_name}: {str(exc)}"
            continue

    if not body:
        return {"ok": False, "message": f"Gemini request failed: {last_error}"}

    text_parts = []
    for candidate in body.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            if part.get("text"):
                text_parts.append(part["text"])
    raw_text = "\n".join(text_parts).strip()
    structured = _extract_first_json_object(raw_text)

    risk_score = structured.get("risk_score")
    risk_level = _normalize_gemini_field(structured.get("risk_level"))
    reason = _normalize_gemini_field(structured.get("reason"))
    if risk_score is None:
        try:
            import re
            match = re.search(r"risk_score\"?\s*[:=]\s*([0-9]{1,3})", raw_text)
            if not match:
                match = re.search(r"\bscore\b\s*[:=]\s*([0-9]{1,3})", raw_text, re.IGNORECASE)
            if match:
                risk_score = int(match.group(1))
        except Exception:
            pass
    return {"ok": True, "risk_score": risk_score, "risk_level": risk_level, "reason": reason}


def _normalize_risk_level(score, provided_level=""):
    level = (provided_level or "").strip().title()
    if level in {"Low", "Medium", "High"}:
        return level
    if score is None:
        return "Unknown"
    if score >= RISK_THRESHOLD:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _run_bgv_risk_scoring(record):
    summary = _build_bgv_ocr_summary(record)
    record.ocr_summary = summary
    if not summary:
        record.risk_score = None
        record.risk_level = "Unknown"
        record.risk_reason = "OCR text not available for risk scoring."
        record.save(update_fields=["ocr_summary", "risk_score", "risk_level", "risk_reason", "updated_at"])
        return

    result = _gemini_bgv_risk_score(summary, record.candidate.candidate_id)
    if not result.get("ok"):
        record.risk_score = None
        record.risk_level = "Unknown"
        record.risk_reason = result.get("message") or "Risk scoring unavailable."
        record.save(update_fields=["ocr_summary", "risk_score", "risk_level", "risk_reason", "updated_at"])
        return

    raw_score = result.get("risk_score")
    try:
        score_val = int(raw_score)
    except (TypeError, ValueError):
        score_val = None
    if score_val is not None:
        score_val = max(0, min(100, score_val))
    if score_val is None:
        score_val = 20
        level = "Low"
        reason = ""
    else:
        level = _normalize_risk_level(score_val, result.get("risk_level"))
        reason = result.get("reason") or ""

    record.risk_score = score_val
    record.risk_level = level
    record.risk_reason = reason
    if score_val is not None and score_val >= RISK_THRESHOLD:
        record.score_status = "Risky"
    record.save(update_fields=["ocr_summary", "risk_score", "risk_level", "risk_reason", "score_status", "updated_at"])


def bgv_submission_view(request):
    candidates = list(Candidate.objects.order_by("candidate_id"))
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = BackgroundVerificationRecord.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None

    if request.method == "POST":
        action = request.POST.get("action", "create_submission").strip()
        record_id = request.POST.get("record_id", "").strip()
        candidate_id = request.POST.get("candidate_id", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_id).first()
        if not candidate:
            messages.error(request, "Valid Candidate ID is required.")
            rows = []
            for row in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-created_at"):
                rows.append(
                    {
                        "id": row.id,
                        "candidate_id": row.candidate.candidate_id,
                        "id_proof": row.id_proof,
                        "address_proof": row.address_proof,
                        "education_certificates": row.education_certificates,
                        "employment_proof": row.employment_proof,
                        "reference_contacts": row.reference_contacts or "-",
                    }
                )
            return render(
                request,
                "background_verification/submission.html",
                {
                    "rows": _submission_rows(),
                    "candidates": candidates,
                    "form_data": request.POST,
                    "form_mode": "edit" if record_id else "create",
                    "id_proof_options": ID_PROOF_OPTIONS,
                    "address_proof_options": ADDRESS_PROOF_OPTIONS,
                    "education_proof_options": EDUCATION_PROOF_OPTIONS,
                    "employment_proof_options": EMPLOYMENT_PROOF_OPTIONS,
                },
            )

        id_proof_type = request.POST.get("id_proof_type", "").strip()
        address_proof_type = request.POST.get("address_proof_type", "").strip()
        education_certificates_type = request.POST.get("education_certificates_type", "").strip()
        employment_proof_type = request.POST.get("employment_proof_type", "").strip()

        id_proof_file = request.FILES.get("id_proof_file")
        address_proof_file = request.FILES.get("address_proof_file")
        education_certificates_file = request.FILES.get("education_certificates_file")
        employment_proof_file = request.FILES.get("employment_proof_file")

        upload_files = [id_proof_file, address_proof_file, education_certificates_file, employment_proof_file]
        if any(file_obj and not _is_pdf_file(file_obj) for file_obj in upload_files):
            messages.error(request, "Only PDF files are allowed for all document uploads.")
            return render(
                request,
                "background_verification/submission.html",
                {
                    "rows": _submission_rows(),
                    "candidates": candidates,
                    "form_data": request.POST,
                    "form_mode": "edit" if record_id else "create",
                    "id_proof_options": ID_PROOF_OPTIONS,
                    "address_proof_options": ADDRESS_PROOF_OPTIONS,
                    "education_proof_options": EDUCATION_PROOF_OPTIONS,
                    "employment_proof_options": EMPLOYMENT_PROOF_OPTIONS,
                },
            )

        if action == "update_submission" and record_id:
            record = get_object_or_404(BackgroundVerificationRecord, id=record_id)
            record.candidate = candidate
            record.comments = request.POST.get("comments", "").strip()
            record.discrepancies = request.POST.get("discrepancies", "").strip() or "-"

            current_id_type, current_id_file = _unpack_document_value(record.id_proof)
            current_address_type, current_address_file = _unpack_document_value(record.address_proof)
            current_edu_type, current_edu_file = _unpack_document_value(record.education_certificates)
            current_emp_type, current_emp_file = _unpack_document_value(record.employment_proof)

            id_file_path = _save_bgv_upload(id_proof_file, "id_proof") if id_proof_file else current_id_file
            address_file_path = _save_bgv_upload(address_proof_file, "address_proof") if address_proof_file else current_address_file
            edu_file_path = _save_bgv_upload(education_certificates_file, "education_certificates") if education_certificates_file else current_edu_file
            emp_file_path = _save_bgv_upload(employment_proof_file, "employment_proof") if employment_proof_file else current_emp_file

            record.id_proof = _pack_document_value(id_proof_type or current_id_type, id_file_path)
            record.address_proof = _pack_document_value(address_proof_type or current_address_type, address_file_path)
            record.education_certificates = _pack_document_value(education_certificates_type or current_edu_type, edu_file_path)
            record.employment_proof = _pack_document_value(employment_proof_type or current_emp_type, emp_file_path)
            record.reference_contacts = request.POST.get("reference_contacts", "").strip()
            record.save()
            _run_bgv_risk_scoring(record)
            messages.success(request, f"BGV submission updated for {record.candidate.candidate_id}.")
        else:
            id_file_path = _save_bgv_upload(id_proof_file, "id_proof")
            address_file_path = _save_bgv_upload(address_proof_file, "address_proof")
            edu_file_path = _save_bgv_upload(education_certificates_file, "education_certificates")
            emp_file_path = _save_bgv_upload(employment_proof_file, "employment_proof")
            record = BackgroundVerificationRecord.objects.create(
                candidate=candidate,
                document_type="Submission",
                status="Pending",
                comments=request.POST.get("comments", "").strip(),
                id_proof=_pack_document_value(id_proof_type, id_file_path),
                address_proof=_pack_document_value(address_proof_type, address_file_path),
                education_certificates=_pack_document_value(education_certificates_type, edu_file_path),
                employment_proof=_pack_document_value(employment_proof_type, emp_file_path),
                reference_contacts=request.POST.get("reference_contacts", "").strip(),
                verification_summary="Submission received",
                score_status="Pending",
                discrepancies=request.POST.get("discrepancies", "").strip() or "-",
            )
            _run_bgv_risk_scoring(record)
            messages.success(request, f"BGV submission saved for {record.candidate.candidate_id}.")
        return redirect("background_verification:submission")

    rows = _submission_rows()
    form_data = {}
    form_mode = "create"
    if edit_record:
        id_type, id_file = _unpack_document_value(edit_record.id_proof)
        address_type, address_file = _unpack_document_value(edit_record.address_proof)
        edu_type, edu_file = _unpack_document_value(edit_record.education_certificates)
        emp_type, emp_file = _unpack_document_value(edit_record.employment_proof)
        form_mode = "edit"
        form_data = {
            "record_id": str(edit_record.id),
            "candidate_id": edit_record.candidate.candidate_id,
            "id_proof_type": id_type,
            "address_proof_type": address_type,
            "education_certificates_type": edu_type,
            "employment_proof_type": emp_type,
            "id_proof_file_name": id_file.split("/")[-1] if id_file else "",
            "address_proof_file_name": address_file.split("/")[-1] if address_file else "",
            "education_certificates_file_name": edu_file.split("/")[-1] if edu_file else "",
            "employment_proof_file_name": emp_file.split("/")[-1] if emp_file else "",
            "reference_contacts": edit_record.reference_contacts,
            "comments": edit_record.comments,
            "discrepancies": edit_record.discrepancies,
        }
    return render(
        request,
        "background_verification/submission.html",
        {
            "rows": rows,
            "candidates": candidates,
            "form_data": form_data,
            "form_mode": form_mode,
            "id_proof_options": ID_PROOF_OPTIONS,
            "address_proof_options": ADDRESS_PROOF_OPTIONS,
            "education_proof_options": EDUCATION_PROOF_OPTIONS,
            "employment_proof_options": EMPLOYMENT_PROOF_OPTIONS,
        },
    )


def _submission_rows():
    rows = []
    for row in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-created_at"):
        id_type, id_file = _unpack_document_value(row.id_proof)
        address_type, address_file = _unpack_document_value(row.address_proof)
        edu_type, edu_file = _unpack_document_value(row.education_certificates)
        emp_type, emp_file = _unpack_document_value(row.employment_proof)
        rows.append(
            {
                "id": row.id,
                "candidate_id": row.candidate.candidate_id,
                "id_proof": id_type or "-",
                "id_proof_file_name": id_file.split("/")[-1] if id_file else "-",
                "id_proof_file_url": _file_url(id_file),
                "address_proof": address_type or "-",
                "address_proof_file_name": address_file.split("/")[-1] if address_file else "-",
                "address_proof_file_url": _file_url(address_file),
                "education_certificates": edu_type or "-",
                "education_certificates_file_name": edu_file.split("/")[-1] if edu_file else "-",
                "education_certificates_file_url": _file_url(edu_file),
                "employment_proof": emp_type or "-",
                "employment_proof_file_name": emp_file.split("/")[-1] if emp_file else "-",
                "employment_proof_file_url": _file_url(emp_file),
                "reference_contacts": row.reference_contacts or "-",
            }
        )
    return rows


def bgv_submission_delete_confirm_view(request, record_id):
    record = get_object_or_404(BackgroundVerificationRecord.objects.select_related("candidate"), id=record_id)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "confirm_delete":
            candidate_id = record.candidate.candidate_id
            record.delete()
            messages.success(request, f"BGV submission deleted for {candidate_id}.")
        return redirect("background_verification:submission")

    return render(request, "background_verification/submission_delete_confirm.html", {"record": record})


def bgv_verification_dashboard_view(request):
    if request.method == "POST" and request.POST.get("action") == "update_bgv_status":
        record = get_object_or_404(BackgroundVerificationRecord, id=request.POST.get("record_id"))
        new_status = request.POST.get("status", "").strip()
        if new_status:
            record.status = new_status
            record.score_status = new_status
            record.save(update_fields=["status", "score_status", "updated_at"])
            messages.success(request, "BGV status updated.")
        return redirect("background_verification:verification_dashboard")

    rows = []
    for row in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-updated_at"):
        rows.append(
            {
                "id": row.id,
                "candidate_id": row.candidate.candidate_id,
                "document_type": row.document_type,
                "verifier_assigned": row.verifier_assigned,
                "status": row.status,
                "comments": row.comments,
                "risk_score": row.risk_score if row.risk_score is not None else "-",
                "risk_level": row.risk_level or "-",
            }
        )
    status_options = sorted({"Pending", "In Progress", "Completed", "Rejected", *[row["status"] for row in rows if row["status"]]})
    return render(
        request,
        "background_verification/verification_dashboard.html",
        {"rows": rows, "status_options": status_options},
    )


def bgv_report_view(request):
    rows = []
    has_reason = False
    for row in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-updated_at"):
        reason = row.risk_reason or ""
        if reason.strip():
            has_reason = True
        rows.append(
            {
                "candidate_id": row.candidate.candidate_id,
                "verification_summary": row.verification_summary or "-",
                "score_status": row.score_status or row.status,
                "discrepancies": row.discrepancies or "-",
                "risk_score": row.risk_score if row.risk_score is not None else "-",
                "risk_level": row.risk_level or "-",
                "risk_reason": reason.strip() or "-",
            }
        )
    return render(request, "background_verification/report.html", {"rows": rows, "show_risk_reason": has_reason})
