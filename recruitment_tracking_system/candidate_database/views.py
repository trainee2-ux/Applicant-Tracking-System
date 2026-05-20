from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from background_verification.models import BackgroundVerificationRecord
from candidate_management.models import Candidate, CandidateJobApplication


def candidate_database_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "delete_candidate":
            candidate = get_object_or_404(Candidate, candidate_id=request.POST.get("candidate_id", "").strip())
            candidate.delete()
            messages.success(request, "Candidate deleted.")
            return redirect("candidate_database:index")

    bgv_map = {
        item.candidate.candidate_id: item
        for item in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-updated_at")
    }
    all_rows = []
    candidates = Candidate.objects.prefetch_related(
        "evaluations",
        "job_applications__job",
    ).order_by("-created_at")
    for candidate in candidates:
        latest_eval = candidate.evaluations.first()
        bgv = bgv_map.get(candidate.candidate_id)
        applied_positions = [item.job.title for item in candidate.job_applications.all() if item.job and item.job.title]
        job_applied = ", ".join(dict.fromkeys(applied_positions)) if applied_positions else candidate.applied_position
        all_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.full_name,
                "email": candidate.email,
                "phone": candidate.contact_number,
                "aadhaar": candidate.aadhaar,
                "pan": candidate.pan,
                "pf": "",
                "esic": "",
                "skills": candidate.skills,
                "job_applied": job_applied,
                "status": (latest_eval.status if latest_eval else candidate.status),
                "personal_info": f"{candidate.full_name} / {candidate.email}",
                "experience": candidate.experience,
                "bgv_status": (bgv.status if bgv else "-"),
                "interview_scores": (str(latest_eval.overall_rating) if latest_eval else "-"),
                "resume_url": (f"/media/{candidate.resume_path}" if candidate.resume_path else ""),
                "resume_name": (candidate.resume_path.split("/")[-1] if candidate.resume_path else ""),
                "profile_photo_url": (f"/media/{candidate.profile_photo_path}" if candidate.profile_photo_path else ""),
            }
        )
    search_fields = ["name", "email", "phone", "aadhaar", "pan", "pf", "esic", "skills", "job_applied", "status"]
    filters = {field: request.GET.get(field, "").strip() for field in search_fields}
    search_by = request.GET.get("search_by", "").strip()
    q = request.GET.get("q", "").strip().lower()

    rows = all_rows

    if q:
        if search_by in search_fields:
            rows = [row for row in rows if q in str(row.get(search_by, "")).lower()]
        else:
            rows = [
                row
                for row in rows
                if any(q in str(row.get(field, "")).lower() for field in search_fields)
            ]

    for field, value in filters.items():
        if value:
            rows = [row for row in rows if value.lower() in str(row.get(field, "")).lower()]

    context = {"filters": filters, "rows": rows, "search_by": search_by, "query": request.GET.get("q", "")}
    return render(request, "candidate_database/index.html", context)
