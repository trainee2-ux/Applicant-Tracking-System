import json
from urllib import error, request as urllib_request

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone

from app_settings.models import City, Country, UserMaster, GlobalAuditLog
from app_settings.utils import log_action

from .models import JobApproval, JobRequisition


def _manager_related_user_names():
    keywords = ("manager", "lead", "recruiter", "admin")
    names = set()
    users = UserMaster.objects.exclude(full_name__exact="").filter(status="Active")
    for user in users:
        role = (user.role or "").strip().lower()
        designation = (user.designation or "").strip().lower()
        if role == "candidate":
            continue
        if any(token in role for token in keywords) or any(token in designation for token in keywords):
            names.add((user.full_name or "").strip())
    return sorted([item for item in names if item])


def _next_job_id():
    latest = JobRequisition.objects.order_by("-id").first()
    seq = (latest.id + 1) if latest else 1
    return f"MPR{seq:04d}"


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


def _build_public_job_url(request, job_id):
    path = reverse("candidate_portal:public_job_detail", args=[job_id])
    return request.build_absolute_uri(path) if request else path


def _parse_posted_date(value):
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        return parse_date(cleaned)
    return None


def _is_job_publicly_open(job):
    if (job.status or "").strip().lower() != "approved":
        return False
    if (job.job_opening_status or "").strip().lower() == "closed":
        return False
    target_closure_date = _parse_posted_date(getattr(job, "target_closure_date", None))
    if target_closure_date and target_closure_date < timezone.localdate():
        return False
    return True


def _get_current_user(request):
    email = (request.session.get("login_user_email") or "").strip()
    return UserMaster.objects.filter(email_id__iexact=email).first()


def _sync_job_approval_status(job, new_status, current_user="Administrator", request=None):
    job.status = new_status
    if _is_job_publicly_open(job):
        job.public_url = _build_public_job_url(request, job.job_id)
    else:
        job.public_url = ""
    job.save(update_fields=["status", "public_url", "updated_at"])
    approval, _ = JobApproval.objects.get_or_create(job=job, defaults={"submitted_by": "Administrator"})
    approval.approval_status = new_status
    if new_status.lower() == "approved":
        approval.approved_by = current_user
    approval.save(update_fields=["approval_status", "approved_by", "updated_at"])
    
    if request:
        log_action(
            module="job_requisition",
            action=f"JOB_STATUS_{new_status.upper()}",
            user=_get_current_user(request),
            details={"job_id": job.job_id, "status": new_status},
            request=request
        )


def job_requisition_view(request):
    jobs = JobRequisition.objects.all().order_by("-created_at")
    
    # Recent Requisitions
    recent_jobs = jobs[:5]
    
    # Stats
    total_openings = sum(j.openings for j in jobs)
    pending_count = jobs.filter(status="Pending").count()
    approved_count = jobs.filter(status="Approved").count()
    
    dept_counts = {}
    for job in jobs:
        dept = (job.department or "Other").strip()
        if not dept:
            dept = "Other"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
        
    sorted_depts = sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:4]
    dept_labels = [k for k, v in sorted_depts]
    dept_data = [v for k, v in sorted_depts]
    
    if not dept_labels:
        dept_labels = ["Engineering", "Sales", "Support", "HR"]
        dept_data = [0, 0, 0, 0]

    status_counts = {"Pending": 0, "Approved": 0, "Rejected": 0}
    for job in jobs:
        status = (job.status or "Pending").capitalize()
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["Pending"] += 1

    status_data = [status_counts["Pending"], status_counts["Approved"], status_counts["Rejected"]]

    context = {
        "dept_labels": json.dumps(dept_labels),
        "dept_data": json.dumps(dept_data),
        "status_data": json.dumps(status_data),
        "recent_jobs": recent_jobs,
        "total_openings": total_openings,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "total_requisitions": jobs.count(),
    }
    return render(request, "job_requisition/index.html", context)


def job_dashboard_view(request):
    rows = [
        {
            "job_id": item.job_id,
            "title": item.title,
            "department": item.department,
            "openings": item.openings,
            "applications_received": item.applications_received,
            "status": item.status,
            "public_url": item.public_url,
        }
        for item in JobRequisition.objects.order_by("-created_at")
    ]
    return render(request, "job_requisition/dashboard.html", {"rows": rows})


def job_position_dashboard_view(request):
    approval_map = {}
    for item in JobApproval.objects.select_related("job").order_by("-updated_at"):
        if item.job.job_id not in approval_map:
            approval_map[item.job.job_id] = item
    rows = [
        {
            "job_id": item.job_id,
            "job_title": item.title,
            "department": item.department,
            "location": item.location,
            "skills_required": item.skills_required,
            "experience_range": item.experience_range,
            "job_description": item.job_description,
            "hiring_manager": item.hiring_manager,
            "approval_status": (approval_map.get(item.job_id).approval_status if approval_map.get(item.job_id) else item.status),
            "approved_by": (approval_map.get(item.job_id).approved_by if approval_map.get(item.job_id) else ""),
            "public_url": item.public_url,
        }
        for item in JobRequisition.objects.order_by("-created_at")
    ]
    return render(
        request,
        "job_requisition/position_dashboard.html",
        {"rows": rows},
    )


def job_delete_confirm_view(request, job_id):
    job = get_object_or_404(JobRequisition, job_id=job_id)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "confirm_delete":
            deleted_job_id = job.job_id
            job.delete()
            log_action(
                module="job_requisition",
                action="JOB_DELETED",
                user=_get_current_user(request),
                details={"job_id": deleted_job_id},
                request=request
            )
            messages.success(request, f"Job {deleted_job_id} deleted successfully.")
        return redirect("job_requisition:job_position_dashboard")

    return render(request, "job_requisition/delete_confirm.html", {"job": job})


def job_posting_form_view(request):
    manager_related_names = _manager_related_user_names()
    city_options = list(City.objects.order_by("name").values("name", "code"))
    country_options = list(Country.objects.order_by("name").values_list("name", flat=True))
    industry_options = sorted(
        {val for val in JobRequisition.objects.exclude(department__exact="").values_list("department", flat=True)}
        | {val for val in UserMaster.objects.exclude(department__exact="").values_list("department", flat=True)}
        | {"IT", "Banking", "Healthcare"}
    )
    default_skills = {"Django", "Python", "SQL", "JavaScript"}
    db_skills = set()
    for row in JobRequisition.objects.exclude(skills_required__exact="").values_list("skills_required", flat=True):
        db_skills.update([item.strip() for item in (row or "").split(",") if item.strip()])
    skill_options = sorted(default_skills | db_skills)
    default_stage_options = {
        "Applied",
        "Screening",
        "Shortlisted",
        "Interview",
        "Technical Round",
        "HR Round",
        "Offer",
        "Hired",
        "Rejected",
    }
    db_stages = set()
    for row in JobRequisition.objects.exclude(stages__exact="").values_list("stages", flat=True):
        db_stages.update([item.strip() for item in (row or "").split(",") if item.strip()])
    stage_options = sorted(default_stage_options | db_stages)

    edit_job_id = request.GET.get("job_id", "").strip()
    edit_job = JobRequisition.objects.filter(job_id=edit_job_id).first() if edit_job_id else None

    if request.method == "POST":
        form_mode = request.POST.get("form_mode", "create").strip()
        edit_job_id = request.POST.get("job_id", "").strip()
        posting_title = request.POST.get("posting_title", "").strip()
        department = request.POST.get("industry", "").strip()
        location = request.POST.get("city", "").strip()
        openings = request.POST.get("number_of_opening", "").strip() or "1"
        selected_skills = [item.strip() for item in request.POST.getlist("required_skills") if item.strip()]
        selected_stages = [item.strip() for item in request.POST.getlist("stages") if item.strip()]
        if not posting_title:
            messages.error(request, "Posting Title is required.")
            return render(
                request,
                "job_requisition/posting_form.html",
                {
                    "form_data": request.POST,
                    "form_mode": form_mode,
                    "edit_job_id": edit_job_id,
                    "contact_options": manager_related_names,
                    "manager_options": manager_related_names,
                    "recruiter_options": manager_related_names,
                    "city_options": city_options,
                    "country_options": country_options,
                    "industry_options": industry_options,
                    "skill_options": skill_options,
                    "stage_options": stage_options,
                },
            )
        normalized_openings = max(int(openings), 1)
        if form_mode == "edit" and edit_job_id:
            job = get_object_or_404(JobRequisition, job_id=edit_job_id)
            job.title = posting_title
            job.department = department
            job.location = location
            job.skills_required = ", ".join(selected_skills)
            job.stages = ", ".join(selected_stages)
            job.experience_range = request.POST.get("work_experience", "").strip()
            job.job_description = request.POST.get("description", "").strip()
            job.requirements = request.POST.get("requirements", "").strip()
            job.benefits = request.POST.get("benefits", "").strip()
            job.hiring_manager = request.POST.get("account_manager", "").strip()
            job.openings = normalized_openings
            job.job_opening_status = request.POST.get("job_opening_status", "").strip() or "Open"
            job.date_of_opening = _parse_posted_date(request.POST.get("date_of_opening", ""))
            job.target_closure_date = _parse_posted_date(request.POST.get("target_closure_date", ""))
            if _is_job_publicly_open(job):
                job.public_url = _build_public_job_url(request, job.job_id)
            else:
                job.public_url = ""
            job.save()
            log_action(
                module="job_requisition",
                action="JOB_UPDATED",
                user=_get_current_user(request),
                details={"job_id": job.job_id, "title": job.title},
                request=request
            )
            JobApproval.objects.update_or_create(
                job=job,
                defaults={"approval_status": job.status, "submitted_by": "Administrator"},
            )
            messages.success(request, f"Job requisition {job.job_id} updated.")
            return redirect("job_requisition:job_position_dashboard")

        job = JobRequisition.objects.create(
            job_id=_next_job_id(),
            title=posting_title,
            department=department,
            location=location,
            skills_required=", ".join(selected_skills),
            stages=", ".join(selected_stages),
            experience_range=request.POST.get("work_experience", "").strip(),
            job_description=request.POST.get("description", "").strip(),
            requirements=request.POST.get("requirements", "").strip(),
            benefits=request.POST.get("benefits", "").strip(),
            hiring_manager=request.POST.get("account_manager", "").strip(),
            openings=normalized_openings,
            status="Pending",
            job_opening_status=request.POST.get("job_opening_status", "").strip() or "Open",
            date_of_opening=_parse_posted_date(request.POST.get("date_of_opening", "")),
            target_closure_date=_parse_posted_date(request.POST.get("target_closure_date", "")),
        )
        if _is_job_publicly_open(job):
            job.public_url = _build_public_job_url(request, job.job_id)
            job.save(update_fields=["public_url", "updated_at"])
        JobApproval.objects.get_or_create(job=job, defaults={"approval_status": job.status, "submitted_by": "Administrator"})
        request.session["job_approval_prefill"] = {
            "manpower_requisition_id": job.job_id,
            "posting_title": request.POST.get("posting_title", "").strip(),
            "client_name": request.POST.get("client_name", "").strip(),
            "contact_name": request.POST.get("contact_name", "").strip(),
            "account_manager": request.POST.get("account_manager", "").strip(),
            "assigned_recruiter": request.POST.get("assigned_recruiter", "").strip(),
            "date_of_opening": request.POST.get("date_of_opening", "").strip(),
            "target_closure_date": request.POST.get("target_closure_date", "").strip(),
            "job_opening_status": request.POST.get("job_opening_status", "").strip(),
            "job_type": request.POST.get("job_type", "").strip(),
            "work_experience": request.POST.get("work_experience", "").strip(),
            "industry": request.POST.get("industry", "").strip(),
            "salary_from": request.POST.get("salary_from", "").strip(),
            "salary_to": request.POST.get("salary_to", "").strip(),
            "currency_type": request.POST.get("currency_type", "").strip(),
            "required_skills": selected_skills,
            "stages": selected_stages,
            "number_of_opening": request.POST.get("number_of_opening", "").strip(),
            "budget_for_position": request.POST.get("budget_for_position", "").strip(),
            "city": request.POST.get("city", "").strip(),
            "country": request.POST.get("country", "").strip(),
            "pincode": request.POST.get("pincode", "").strip(),
            "description": request.POST.get("description", "").strip(),
            "requirements": request.POST.get("requirements", "").strip(),
            "benefits": request.POST.get("benefits", "").strip(),
            "approval_status": request.POST.get("job_opening_status", "").strip() or "Pending",
        }
        messages.success(request, f"Job requisition {job.job_id} created.")
        log_action(
            module="job_requisition",
            action="JOB_CREATED",
            user=_get_current_user(request),
            details={"job_id": job.job_id, "title": job.title},
            request=request
        )
        return redirect(f"{reverse('job_requisition:approval_form')}?job_id={job.job_id}")

    form_data = {}
    form_mode = "create"
    if edit_job:
        form_mode = "edit"
        form_data = {
            "manpower_requisition_id": edit_job.job_id,
            "posting_title": edit_job.title,
            "industry": edit_job.department,
            "city": edit_job.location,
            "required_skills": [item.strip() for item in (edit_job.skills_required or "").split(",") if item.strip()],
            "stages": [item.strip() for item in (edit_job.stages or "").split(",") if item.strip()],
            "work_experience": edit_job.experience_range,
            "description": edit_job.job_description,
            "requirements": edit_job.requirements,
            "benefits": edit_job.benefits,
            "account_manager": edit_job.hiring_manager,
            "number_of_opening": str(edit_job.openings),
            "job_opening_status": edit_job.job_opening_status,
            "date_of_opening": edit_job.date_of_opening.isoformat() if edit_job.date_of_opening else "",
            "target_closure_date": (
                edit_job.target_closure_date.isoformat() if edit_job.target_closure_date else ""
            ),
        }

    return render(
        request,
        "job_requisition/posting_form.html",
        {
            "form_data": form_data,
            "form_mode": form_mode,
            "edit_job_id": edit_job.job_id if edit_job else "",
            "next_manpower_requisition_id": _next_job_id(),
            "contact_options": manager_related_names,
            "manager_options": manager_related_names,
            "recruiter_options": manager_related_names,
            "city_options": city_options,
            "country_options": country_options,
            "industry_options": industry_options,
            "skill_options": skill_options,
            "stage_options": stage_options,
        },
    )


def job_content_suggestion_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request method."}, status=405)

    posting_title = request.POST.get("posting_title", "").strip()
    if not posting_title:
        return JsonResponse({"ok": False, "message": "Posting title is required."}, status=400)
    target_field = request.POST.get("target_field", "").strip().lower()
    valid_targets = {"description", "requirements", "benefits"}
    if target_field and target_field not in valid_targets:
        return JsonResponse({"ok": False, "message": "Invalid target field."}, status=400)

    gemini_api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    gemini_model = (getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash").strip()
    if not gemini_api_key:
        return JsonResponse(
            {"ok": False, "message": "Gemini API key is missing. Set GEMINI_API_KEY in environment."},
            status=400,
        )

    industry = request.POST.get("industry", "").strip()
    experience = request.POST.get("work_experience", "").strip()
    skills = request.POST.get("required_skills", "").strip()

    requested_targets = [target_field] if target_field else ["description", "requirements", "benefits"]
    prompt = (
        "Generate job posting content in valid JSON only, without markdown.\n"
        f"Return only these keys: {', '.join(requested_targets)}.\n"
        "Write concise, professional content suitable for ATS posting form.\n\n"
        f"Posting title: {posting_title}\n"
        f"Industry: {industry or 'General'}\n"
        f"Experience: {experience or 'Not specified'}\n"
        f"Key skills: {skills or 'Not specified'}\n"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }

    fallback_models = [
        gemini_model,
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash-latest",
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
        return JsonResponse({"ok": False, "message": f"Gemini request failed: {last_error}"}, status=502)

    text_parts = []
    for candidate in body.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            if part.get("text"):
                text_parts.append(part["text"])
    raw_text = "\n".join(text_parts).strip()
    structured = _extract_first_json_object(raw_text)

    description = (structured.get("description") or "").strip() if "description" in requested_targets else ""
    requirements = (structured.get("requirements") or "").strip() if "requirements" in requested_targets else ""
    benefits = (structured.get("benefits") or "").strip() if "benefits" in requested_targets else ""

    if not any([description, requirements, benefits]):
        return JsonResponse(
            {"ok": False, "message": "Could not parse Gemini response into required fields."},
            status=502,
        )

    fields = {}
    if "description" in requested_targets:
        fields["description"] = description
    if "requirements" in requested_targets:
        fields["requirements"] = requirements
    if "benefits" in requested_targets:
        fields["benefits"] = benefits

    return JsonResponse({"ok": True, "fields": fields})


def job_approval_workflow_view(request):
    if request.method == "POST" and request.POST.get("action") == "update_approval_status":
        job = get_object_or_404(JobRequisition, job_id=request.POST.get("job_id", "").strip())
        new_status = request.POST.get("approval_status", "").strip()
        if new_status:
            current_user = request.session.get("login_user_name", "Administrator")
            _sync_job_approval_status(job, new_status, current_user=current_user, request=request)
            messages.success(request, f"Approval status updated for {job.job_id}.")
        return redirect("job_requisition:approval_workflow")

    rows = []
    for item in JobApproval.objects.select_related("job").order_by("-created_at"):
        rows.append(
            {
                "job_id": item.job.job_id,
                "submitted_by": item.submitted_by,
                "approved_by": item.approved_by or "-",
                "approval_status": item.approval_status,
                "comments": item.comments,
                "public_url": item.job.public_url,
            }
        )
    options = sorted({"Pending", "In Progress", "Approved", "Rejected", "On Hold", *[r["approval_status"] for r in rows]})
    return render(
        request,
        "job_requisition/approval_dashboard.html",
        {"rows": rows, "approval_status_options": options},
    )


def job_approval_form_view(request):
    if request.method == "POST":
        job_id = request.POST.get("manpower_requisition_id", "").strip()
        approval_status = request.POST.get("approval_status", "").strip() or "Pending"
        comments = request.POST.get("comment", "").strip()
        current_user = request.session.get("login_user_name", "Administrator")
        job = JobRequisition.objects.filter(job_id=job_id).first()
        if not job:
            messages.error(request, "Valid Job ID is required.")
            return render(request, "job_requisition/job_approval.html")
        approval, _ = JobApproval.objects.get_or_create(job=job, defaults={"submitted_by": "Administrator"})
        approval.approval_status = approval_status
        approval.comments = comments
        if approval_status.lower() == "approved":
            approval.approved_by = request.POST.get("account_manager", "").strip() or current_user
        approval.save()
        job.job_opening_status = request.POST.get("job_opening_status", "").strip() or job.job_opening_status or "Open"
        job.date_of_opening = _parse_posted_date(request.POST.get("date_of_opening", "")) or job.date_of_opening
        job.target_closure_date = _parse_posted_date(request.POST.get("target_closure_date", "")) or job.target_closure_date
        job.save(update_fields=["job_opening_status", "date_of_opening", "target_closure_date", "updated_at"])
        _sync_job_approval_status(job, approval_status, current_user=current_user, request=request)
        messages.success(request, f"Approval captured for {job.job_id}.")
        return redirect("job_requisition:approval_workflow")

    job_id = request.GET.get("job_id", "").strip()
    prefill = request.session.pop("job_approval_prefill", {})
    form_data = {}

    if job_id:
        job = JobRequisition.objects.filter(job_id=job_id).first()
        approval = JobApproval.objects.filter(job=job).first() if job else None
        if job:
            form_data.update(
                {
                    "manpower_requisition_id": job.job_id,
                    "posting_title": job.title,
                    "account_manager": job.hiring_manager,
                    "work_experience": job.experience_range,
                    "industry": job.department,
                    "city": job.location,
                    "description": job.job_description,
                    "requirements": job.requirements,
                    "benefits": job.benefits,
                    "required_skills": [item.strip() for item in (job.skills_required or "").split(",") if item.strip()],
                    "number_of_opening": str(job.openings),
                    "approval_status": job.status,
                    "job_opening_status": job.job_opening_status,
                    "date_of_opening": job.date_of_opening.isoformat() if job.date_of_opening else "",
                    "target_closure_date": job.target_closure_date.isoformat() if job.target_closure_date else "",
                    "comment": (approval.comments if approval else ""),
                }
            )
            if approval and approval.approved_by:
                form_data["account_manager"] = approval.approved_by

    if prefill and (not job_id or prefill.get("manpower_requisition_id") == job_id):
        form_data.update(prefill)

    return render(request, "job_requisition/job_approval.html", {"form_data": form_data})


def job_approval_delete_confirm_view(request, job_id):
    job = get_object_or_404(JobRequisition, job_id=job_id)
    approval = JobApproval.objects.filter(job=job).first()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "confirm_delete" and approval:
            approval.delete()
            messages.success(request, f"Approval record deleted for {job.job_id}.")
        return redirect("job_requisition:approval_workflow")

    return render(
        request,
        "job_requisition/approval_delete_confirm.html",
        {"job": job, "approval": approval},
    )
