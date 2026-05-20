from django.contrib import messages
from django.db.models import Sum
from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render

from app_settings.models import RoleMaster, UserMaster
from app_settings.notifications import create_notifications, normalize_recipients
from task_management.models import TaskRecord
from .models import RecruitmentTeamMaster


def recruitment_teams_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "save_team").strip()
        if action == "delete_team":
            team = get_object_or_404(RecruitmentTeamMaster, pk=request.POST.get("team_pk"))
            team.delete()
            messages.success(request, "Team deleted.")
            return redirect("recruitment_teams:index")

        team_name = request.POST.get("team_name", "").strip()
        team_lead = request.POST.get("team_lead", "").strip()
        team_members = request.POST.getlist("team_members")
        team_roles = request.POST.getlist("team_roles")
        department = request.POST.get("department", "").strip()
        team_email = request.POST.get("team_email", "").strip()
        status = request.POST.get("status", "").strip()
        team_pk = request.POST.get("team_pk", "").strip()

        if not team_name or not team_lead or not team_members or not department or not status:
            messages.error(request, "Team Name, Team Lead, Team Members, Department, and Status are required.")
            return redirect("recruitment_teams:index")

        try:
            if team_pk:
                team = get_object_or_404(RecruitmentTeamMaster, pk=team_pk)
                previous_members = {name.lower() for name in normalize_recipients([team.team_lead, team.team_members])}
                team.team_name = team_name
                team.team_lead = team_lead
                team.team_members = ",".join(team_members)
                team.team_roles = ",".join(team_roles)
                team.department = department
                team.team_email = team_email
                team.status = status
                team.save()
                messages.success(request, "Team updated successfully.")
                new_members_raw = normalize_recipients([team_lead, team.team_members])
                new_members = {name.lower() for name in new_members_raw}
                added = [name for name in new_members_raw if name.lower() not in previous_members]
                if added:
                    create_notifications(
                        added,
                        title="Team assignment",
                        message=f"You were added to team {team.team_name}.",
                        link="/recruitment-teams/",
                        source="team",
                        created_by=request.session.get("login_user_name", ""),
                    )
            else:
                team = RecruitmentTeamMaster.objects.create(
                    team_name=team_name,
                    team_lead=team_lead,
                    team_members=",".join(team_members),
                    team_roles=",".join(team_roles),
                    department=department,
                    team_email=team_email,
                    status=status,
                )
                messages.success(request, "Team created successfully.")
                members = normalize_recipients([team_lead, team.team_members])
                if members:
                    create_notifications(
                        members,
                        title="Team assignment",
                        message=f"You were added to team {team.team_name}.",
                        link="/recruitment-teams/",
                        source="team",
                        created_by=request.session.get("login_user_name", ""),
                    )
        except IntegrityError:
            messages.error(request, "Team Name already exists.")
        return redirect("recruitment_teams:index")

    last_team = RecruitmentTeamMaster.objects.order_by("-id").first()
    next_id = (last_team.id + 1) if last_team else 1
    next_team_id = f"TEAM{next_id:04d}"
    edit_id = request.GET.get("edit", "").strip()
    selected_team = None
    if edit_id:
        selected_team = RecruitmentTeamMaster.objects.filter(pk=edit_id).first()
        if selected_team:
            selected_team.selected_members = [
                item.strip() for item in selected_team.team_members.split(",") if item.strip()
            ]
            selected_team.selected_roles = [
                item.strip() for item in (selected_team.team_roles or "").split(",") if item.strip()
            ]

    team_dashboard_rows = []
    for team in RecruitmentTeamMaster.objects.all():
        members = [item.strip() for item in (team.team_members or "").split(",") if item.strip()]
        if team.team_lead:
            members.append(team.team_lead.strip())
        members = list({name for name in members if name})
        if members:
            team_tasks = TaskRecord.objects.filter(owner__in=members)
        else:
            team_tasks = TaskRecord.objects.none()
        pending_count = team_tasks.exclude(status__iexact="Completed").count()
        completed_count = team_tasks.filter(status__iexact="Completed").count()
        total_minutes = (
            team_tasks.filter(status__iexact="Completed").aggregate(total=Sum("duration_minutes")).get("total") or 0
        )
        total_hours = round(total_minutes / 60.0, 2)
        total_tasks = pending_count + completed_count
        productivity = f"{round((completed_count / total_tasks) * 100, 1)}%" if total_tasks else "-"
        team_dashboard_rows.append(
            {
                "team_name": team.team_name,
                "pending": pending_count,
                "completed": completed_count,
                "total_hours": total_hours,
                "productivity": productivity,
            }
        )

    context = {
        "next_team_id": next_team_id,
        "team_lead_options": list(
            UserMaster.objects.filter(status="Active")
            .exclude(full_name__exact="")
            .exclude(role__iexact="candidate")
            .order_by("full_name")
            .values_list("full_name", flat=True)
        ),
        "team_member_options": list(
            UserMaster.objects.filter(status="Active")
            .exclude(full_name__exact="")
            .exclude(role__iexact="candidate")
            .order_by("full_name")
            .values_list("full_name", flat=True)
        ),
        "role_options": (
            list(
                RoleMaster.objects.filter(status="Active")
                .exclude(role_name__exact="")
                .order_by("role_name")
                .values_list("role_name", flat=True)
            )
            or list(
                UserMaster.objects.filter(status="Active")
                .exclude(role__exact="")
                .order_by("role")
                .values_list("role", flat=True)
                .distinct()
            )
        ),
        "department_options": ["HR", "Tech", "Finance", "Operations"],
        "records": RecruitmentTeamMaster.objects.all(),
        "selected_team": selected_team,
        "team_dashboard_rows": team_dashboard_rows,
    }
    return render(request, "recruitment_teams/index.html", context)
