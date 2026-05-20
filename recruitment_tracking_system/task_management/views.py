from datetime import time, timedelta
import re

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage, get_connection
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from app_settings.models import EmailDeliveryConfig, RoleMaster, UserMaster
from app_settings.models import TaskSlaPrioritySetting
from app_settings.notifications import create_notifications
from candidate_management.models import Candidate
from recruitment_teams.models import RecruitmentTeamMaster
from job_requisition.models import JobRequisition

from .models import TaskRecord, TaskTimesheetEntry

_TASK_ID_RE = re.compile(r"^TASK(\d+)$", re.IGNORECASE)

PRIORITY_SLA_HOURS = {
    "urgent": (1, 4),
    "high": (2, 10),
    "medium": (6, 20),
    "low": (8, 30),
}


def _sla_hours_for_priority(priority: str):
    key = (priority or "").strip().lower() or "medium"
    row = TaskSlaPrioritySetting.objects.filter(priority=key).only("first_response_hours", "resolution_hours").first()
    if row and row.first_response_hours and row.resolution_hours:
        return int(row.first_response_hours), int(row.resolution_hours)
    return PRIORITY_SLA_HOURS.get(key, PRIORITY_SLA_HOURS["medium"])


ONBOARDING_SUBTASK_TEMPLATE = [
    # Before Start Date
    {"section": "Before Start Date", "task": "Send offer letter and collect signed acceptance"},
    {"section": "Before Start Date", "task": "Initiate background check and reference verification"},
    {"section": "Before Start Date", "task": "Collect tax forms (W-4, I-9 documentation)"},
    {"section": "Before Start Date", "task": "Set up payroll and direct deposit"},
    {"section": "Before Start Date", "task": "Enroll employee in benefits (health, dental, 401k)"},
    {"section": "Before Start Date", "task": "Share start date, location, and first-day logistics"},
    {"section": "Before Start Date", "task": "Send pre-boarding welcome package"},
    {"section": "Before Start Date", "task": "Prepare desk, badge, and work area"},
    {"section": "Before Start Date", "task": "Provision laptop, phone, and necessary hardware"},
    {"section": "Before Start Date", "task": "Create accounts: email, Slack, SSO, HRIS"},
    {"section": "Before Start Date", "task": "Grant access to required systems and tools"},
    # Day 1
    {"section": "Day 1", "task": "Welcome meeting with HR — policies, benefits overview"},
    {"section": "Day 1", "task": "Collect signed NDA and company policy acknowledgement"},
    {"section": "Day 1", "task": "Office tour and introductions to key contacts"},
    {"section": "Day 1", "task": "Review 30/60/90-day expectations and goals"},
    {"section": "Day 1", "task": "Meet the team — schedule 1:1s for first week"},
    {"section": "Day 1", "task": "Set up laptop, test accounts, and VPN access"},
    {"section": "Day 1", "task": "Complete IT security and acceptable use training"},
    {"section": "Day 1", "task": "Update employee profile in HRIS"},
    # First Week
    {"section": "First Week", "task": "Complete mandatory compliance training (harassment, safety)"},
    {"section": "First Week", "task": "Assign onboarding buddy or mentor"},
    {"section": "First Week", "task": "Share team org chart, key processes, and workflows"},
    {"section": "First Week", "task": "Review role-specific tools and software"},
    {"section": "First Week", "task": "Schedule check-in at end of week 1"},
    {"section": "First Week", "task": "Add employee to relevant Slack channels and mailing lists"},
    {"section": "First Week", "task": "Complete role-specific onboarding modules"},
    {"section": "First Week", "task": "Review company handbook and culture guide"},
    {"section": "First Week", "task": "Set up password manager and 2FA for all systems"},
    # First 30 Days
    {"section": "First 30 Days", "task": "Confirm I-9 documentation is complete and filed"},
    {"section": "First 30 Days", "task": "Verify benefits elections are processed"},
    {"section": "First 30 Days", "task": "Conduct formal 30-day performance check-in"},
    {"section": "First 30 Days", "task": "Set OKRs or performance goals for the quarter"},
    {"section": "First 30 Days", "task": "Confirm all system access is correctly scoped"},
    {"section": "First 30 Days", "task": "Remove temporary or provisional access levels"},
    {"section": "First 30 Days", "task": "Submit any outstanding paperwork to HR"},
    {"section": "First 30 Days", "task": "Share feedback on onboarding experience"},
]


def _assign_subtask_task_id(*, subtask: TaskRecord, parent: TaskRecord) -> None:
    if not parent or not (parent.task_id or "").strip():
        return
    if not subtask:
        return
    prefix = f"{parent.task_id}."
    max_suffix = 0
    for existing in TaskRecord.objects.filter(parent_task=parent).exclude(id=subtask.id).only("task_id"):
        value = (existing.task_id or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):].strip()
        if suffix.isdigit():
            max_suffix = max(max_suffix, int(suffix))
    subtask.task_id = f"{parent.task_id}.{max_suffix + 1}"
    subtask.save(update_fields=["task_id", "updated_at"])


def _start_datetime_for_task(task: TaskRecord):
    if task.start_date:
        dt = timezone.datetime.combine(task.start_date, time(9, 0))
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return task.created_at or timezone.now()


def _apply_status_timestamps(task):
    status = (task.status or "").strip().lower()
    now = timezone.now()

    if task.started_at is None and task.start_date:
        task.started_at = _start_datetime_for_task(task)

    if status == "in progress" and task.started_at is None:
        task.started_at = now

    if status == "completed":
        if task.started_at is None:
            task.started_at = task.created_at or now
        if task.completed_at is None:
            task.completed_at = now
        seconds = (task.completed_at - task.started_at).total_seconds()
        task.duration_minutes = max(1, int(seconds // 60))
    else:
        task.completed_at = None
        task.duration_minutes = 0


def _apply_sla_fields(task: TaskRecord):
    if not getattr(task, "sla_enabled", True):
        task.sla_first_response_hours = None
        task.sla_resolution_hours = None
        task.sla_first_response_due_at = None
        task.sla_resolution_due_at = None
        return

    resp_h, res_h = _sla_hours_for_priority(task.priority or "medium")
    task.sla_first_response_hours = resp_h
    task.sla_resolution_hours = res_h
    start_at = _start_datetime_for_task(task)
    task.sla_first_response_due_at = start_at + timedelta(hours=resp_h)
    task.sla_resolution_due_at = start_at + timedelta(hours=res_h)


def _parse_date(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _normalize_smtp_password(host: str, password: str) -> str:
    host_value = (host or "").strip().lower()
    pwd = (password or "").strip()
    if host_value in {"smtp.gmail.com", "smtp.googlemail.com"}:
        return pwd.replace(" ", "")
    return pwd


def _send_task_notification_email(*, to_email: str, subject: str, body: str) -> str:
    if not to_email:
        return "Missing recipient email."

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    if email_config and email_config.smtp_enabled:
        if not email_config.host:
            return "SMTP is enabled but host is empty in Integration settings."
        smtp_password = _normalize_smtp_password(email_config.host, email_config.password or "")
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=email_config.host,
            port=email_config.port or 587,
            username=email_config.username or "",
            password=smtp_password,
            use_tls=email_config.use_tls,
        )
        from_email = email_config.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    else:
        connection = get_connection()
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")

    try:
        message = EmailMessage(
            subject=subject[:180],
            body=body,
            from_email=from_email,
            to=[to_email],
            connection=connection,
        )
        message.send(fail_silently=False)
        return ""
    except Exception as exc:
        return str(exc)


def _advance_due_date(base_date, repeat_type: str):
    if not base_date:
        base_date = timezone.localdate()
    key = (repeat_type or "").strip().lower()
    if key in {"none", ""}:
        return None
    if key == "daily":
        return base_date + timedelta(days=1)
    if key == "weekly":
        return base_date + timedelta(days=7)
    if key == "monthly":
        return base_date + timedelta(days=30)
    if key == "yearly":
        return base_date + timedelta(days=365)
    return None


def _create_repeat_task_if_needed(*, task: TaskRecord, created_by: str) -> TaskRecord | None:
    if not task.repeat_enabled:
        return None
    repeat_type = (task.repeat_type or "").strip().lower()
    next_due = _advance_due_date(task.due_date or task.repeat_start_date or timezone.localdate(), repeat_type)
    if not next_due:
        return None
    if task.repeat_end_date and next_due > task.repeat_end_date:
        return None

    # Create next occurrence as a new task record.
    next_task = TaskRecord.objects.create(
        owner=task.owner,
        team=task.team,
        job_id=task.job_id,
        subject=task.subject,
        due_date=next_due,
        target_type=task.target_type,
        contact_name=task.contact_name,
        candidate=task.candidate,
        parent_task=task.parent_task,
        status="Open",
        priority=task.priority,
        description=task.description,
        send_notification_email=task.send_notification_email,
        repeat_enabled=task.repeat_enabled,
        repeat_start_date=task.repeat_start_date,
        repeat_end_date=task.repeat_end_date,
        repeat_type=task.repeat_type,
        reminder_enabled=task.reminder_enabled,
    )
    if next_task.parent_task_id:
        _assign_subtask_task_id(subtask=next_task, parent=next_task.parent_task)
    if task.owner:
        create_notifications(
            task.owner,
            title="Task created (recurring)",
            message=f"{task.subject} ({next_task.task_id})",
            link=f"/task-management/?edit={next_task.id}",
            source="task",
            created_by=created_by,
        )
    return next_task


def _format_duration(minutes):
    total = max(0, int(minutes or 0))
    hours = total // 60
    mins = total % 60
    return f"{hours}h {mins:02d}m"


def _task_owner_options():
    manager_role_names = set(
        RoleMaster.objects.filter(status="Active", role_level__in=["Admin", "Manager"])
        .values_list("role_name", flat=True)
    )
    users = UserMaster.objects.filter(status="Active").exclude(full_name__exact="")
    if manager_role_names:
        users = users.filter(role__in=manager_role_names)
    else:
        users = users.exclude(role__iexact="candidate")
    rows = users.order_by("full_name", "role").values("full_name", "role").distinct()
    return [
        {
            "value": row["full_name"],
            "role": row.get("role") or "",
            "label": row["full_name"],
        }
        for row in rows
    ]


def _task_owner_role_map(owner_options):
    return {row["value"]: row["role"] for row in owner_options}


def _is_admin(role_name):
    if not role_name:
        return False
    normalized = role_name.strip().lower()
    if normalized in {"admin", "super admin", "administrator"}:
        return True
    return RoleMaster.objects.filter(
        status="Active",
        role_name__iexact=role_name,
        role_level="Admin",
    ).exists()


def _owners_for_user(owner_options, full_name):
    name = (full_name or "").strip().lower()
    if not name:
        return []
    return [row["value"] for row in owner_options if (row.get("value") or "").strip().lower() == name]


def _timesheet_context(request):
    role_name = (request.session.get("login_user_role") or "").strip()
    login_user_name = (request.session.get("login_user_name") or "").strip()
    owner_options = _task_owner_options()
    owner_role_map = _task_owner_role_map(owner_options)
    report_from = request.GET.get("report_from", "").strip()
    report_to = request.GET.get("report_to", "").strip()
    report_owner = request.GET.get("report_owner", "").strip()

    timesheet_qs = TaskRecord.objects.filter(completed_at__isnull=False).order_by("-completed_at")
    if not _is_admin(role_name):
        owners = _owners_for_user(owner_options, login_user_name)
        if owners:
            timesheet_qs = timesheet_qs.filter(owner__in=owners)
        else:
            timesheet_qs = timesheet_qs.none()
    if report_from:
        timesheet_qs = timesheet_qs.filter(completed_at__date__gte=report_from)
    if report_to:
        timesheet_qs = timesheet_qs.filter(completed_at__date__lte=report_to)
    if report_owner:
        timesheet_qs = timesheet_qs.filter(owner=report_owner)

    timesheet_rows = [
        {
            "owner": row.owner,
            "owner_role": owner_role_map.get(row.owner, "-"),
            "subject": row.subject,
            "status": row.status,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "duration": _format_duration(row.duration_minutes),
            "duration_minutes": row.duration_minutes,
        }
        for row in timesheet_qs
    ]
    summary_minutes = timesheet_qs.aggregate(total=Sum("duration_minutes")).get("total") or 0

    return {
        "timesheet_rows": timesheet_rows,
        "timesheet_total_duration": _format_duration(summary_minutes),
        "timesheet_total_tasks": len(timesheet_rows),
        "report_from": report_from,
        "report_to": report_to,
        "report_owner": report_owner,
        "task_owners": owner_options,
    }


def task_management_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action in {"submit_to_manager", "approve_task", "reject_task"}:
            task = get_object_or_404(TaskRecord, id=request.POST.get("task_id"))
            role_name = (request.session.get("login_user_role") or "").strip()
            login_user_name = (request.session.get("login_user_name") or "").strip()
            login_email = (request.session.get("login_user_email") or "").strip()
            user_row = UserMaster.objects.filter(email_id__iexact=login_email).first() if login_email else None

            def _can_act_as_owner():
                return _is_admin(role_name) or (login_user_name and (task.owner or "").strip().lower() == login_user_name.lower())

            def _can_act_as_manager():
                return _is_admin(role_name) or (
                    login_user_name and (task.submitted_to or "").strip().lower() == login_user_name.lower()
                )

            if action == "submit_to_manager":
                if not _can_act_as_owner():
                    messages.error(request, "You can only submit your own tasks.")
                    return redirect("task_management:index")
                if (task.status or "").strip().lower() != "completed":
                    messages.error(request, "Only completed tasks can be submitted to manager.")
                    return redirect("task_management:index")

                manager_name = (user_row.reporting_manager or "").strip() if user_row else ""
                if not manager_name:
                    messages.error(request, "Reporting manager is not configured for your profile.")
                    return redirect("task_management:index")

                task.submission_status = "submitted"
                task.submitted_to = manager_name
                task.submitted_at = timezone.now()
                task.approved_by = ""
                task.approved_at = None
                task.rejection_reason = ""
                task.save(
                    update_fields=[
                        "submission_status",
                        "submitted_to",
                        "submitted_at",
                        "approved_by",
                        "approved_at",
                        "rejection_reason",
                        "updated_at",
                    ]
                )
                create_notifications(
                    manager_name,
                    title="Task submitted for approval",
                    message=f"{task.subject} ({task.task_id})",
                    link=f"/task-management/?edit={task.id}",
                    source="task",
                    created_by=login_user_name,
                )
                messages.success(request, "Task submitted to manager.")
                return redirect("task_management:index")

            if action == "approve_task":
                if not _can_act_as_manager():
                    messages.error(request, "Only the assigned manager can approve this task.")
                    return redirect("task_management:index")
                if task.submission_status != "submitted":
                    messages.error(request, "Only submitted tasks can be approved.")
                    return redirect("task_management:index")
                task.submission_status = "approved"
                task.approved_by = login_user_name or (task.submitted_to or "")
                task.approved_at = timezone.now()
                task.rejection_reason = ""
                task.save(update_fields=["submission_status", "approved_by", "approved_at", "rejection_reason", "updated_at"])
                messages.success(request, "Task approved.")
                return redirect("task_management:index")

            if action == "reject_task":
                if not _can_act_as_manager():
                    messages.error(request, "Only the assigned manager can reject this task.")
                    return redirect("task_management:index")
                if task.submission_status != "submitted":
                    messages.error(request, "Only submitted tasks can be rejected.")
                    return redirect("task_management:index")
                reason = (request.POST.get("rejection_reason") or "").strip()
                task.submission_status = "rejected"
                task.approved_by = login_user_name or (task.submitted_to or "")
                task.approved_at = timezone.now()
                task.rejection_reason = reason
                task.save(update_fields=["submission_status", "approved_by", "approved_at", "rejection_reason", "updated_at"])
                messages.success(request, "Task rejected.")
                return redirect("task_management:index")

        if action == "toggle_task_done":
            task = get_object_or_404(TaskRecord, id=request.POST.get("task_id"))
            role_name = (request.session.get("login_user_role") or "").strip()
            login_user_name = (request.session.get("login_user_name") or "").strip()

            if not _is_admin(role_name):
                if not login_user_name or (task.owner or "").strip().lower() != login_user_name.lower():
                    messages.error(request, "You can only update your own tasks.")
                    return redirect("task_management:index")

            done = (request.POST.get("done") or "").strip().lower() in {"1", "true", "yes", "on"}
            previous_status = (task.status or "").strip().lower()
            task.status = "Completed" if done else "Open"
            _apply_status_timestamps(task)
            task.save(update_fields=["status", "started_at", "completed_at", "duration_minutes", "updated_at"])
            if previous_status != "completed" and done:
                _create_repeat_task_if_needed(task=task, created_by=(login_user_name or "").strip())
            messages.success(request, "Task updated.")
            return redirect("task_management:index")

        if action == "update_task_dropdown":
            task = get_object_or_404(TaskRecord, id=request.POST.get("task_id"))
            previous_status = (task.status or "").strip()
            field_name = request.POST.get("field_name", "").strip()
            field_value = request.POST.get("field_value", "").strip()
            if field_name in {"status", "priority"} and field_value:
                setattr(task, field_name, field_value)
                if field_name == "status":
                    _apply_status_timestamps(task)
                    task.save(update_fields=[field_name, "started_at", "completed_at", "duration_minutes", "updated_at"])
                    if previous_status.strip().lower() != "completed" and field_value.strip().lower() == "completed":
                        _create_repeat_task_if_needed(task=task, created_by=(request.session.get("login_user_name") or "").strip())
                else:
                    task.save(update_fields=[field_name, "updated_at"])
                messages.success(request, "Task updated.")
            return redirect("task_management:index")
        if action == "delete_task":
            task = get_object_or_404(TaskRecord, id=request.POST.get("task_id"))
            task.delete()
            messages.success(request, "Task deleted.")
            return redirect("task_management:index")
        if action == "save_task":
            task_id = request.POST.get("task_id", "").strip()
            team_id = request.POST.get("team_id", "").strip()
            candidate_ref = request.POST.get("candidate", "").strip()
            candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(full_name=candidate_ref).first()
            team = RecruitmentTeamMaster.objects.filter(id=team_id).first() if team_id else None
            parent_task_id = (request.POST.get("parent_task_id") or "").strip()
            parent_task = TaskRecord.objects.filter(id=parent_task_id).first() if parent_task_id else None
            owner_name = request.POST.get("task_owner", "").strip()
            role_name = (request.session.get("login_user_role") or "").strip()
            login_user_name = (request.session.get("login_user_name") or "").strip()
            if not owner_name and login_user_name:
                owner_name = login_user_name
            if team:
                team_members = [item.strip() for item in (team.team_members or "").split(",") if item.strip()]
                if team.team_lead:
                    team_members.append(team.team_lead.strip())
                team_members = {name for name in team_members if name}
                if owner_name and owner_name not in team_members:
                    messages.error(request, "Assigned member must belong to the selected team.")
                    return redirect("task_management:index")

            if parent_task and not _is_admin(role_name):
                owner_options = _task_owner_options()
                allowed = set(_owners_for_user(owner_options, login_user_name) or [])
                if login_user_name:
                    allowed.add(login_user_name)
                if parent_task.owner not in allowed:
                    messages.error(request, "You don't have access to use that parent task.")
                    return redirect("task_management:index")

            if task_id and parent_task and str(parent_task.id) == str(task_id):
                messages.error(request, "A task cannot be set as its own parent.")
                return redirect("task_management:index")

            if parent_task:
                # Subtasks inherit the same target (candidate/contact) as the parent.
                if parent_task.candidate_id:
                    candidate = parent_task.candidate
                if (parent_task.contact_name or "").strip() and not parent_task.candidate_id:
                    candidate = None

            subtask_subjects = [s.strip() for s in request.POST.getlist("subtask_subject") if (s or "").strip()]
            subtask_due_dates_raw = request.POST.getlist("subtask_due_date")
            subtask_due_dates = [_parse_date(v) for v in subtask_due_dates_raw]
            subtask_owners_raw = request.POST.getlist("subtask_owner")
            subtask_owners = [(v or "").strip() for v in subtask_owners_raw]
            subtask_groups_raw = request.POST.getlist("subtask_group")
            subtask_groups = [(v or "").strip() for v in subtask_groups_raw]
            subtask_statuses = [(v or "").strip() for v in request.POST.getlist("subtask_status")]
            subtask_priorities = [(v or "").strip() for v in request.POST.getlist("subtask_priority")]

            team_member_set = None
            if team:
                members = [item.strip() for item in (team.team_members or "").split(",") if item.strip()]
                if team.team_lead:
                    members.append(team.team_lead.strip())
                team_member_set = {name for name in members if name}

            if team_member_set is not None:
                for owner_value in subtask_owners:
                    if not owner_value:
                        continue
                    if owner_value not in team_member_set:
                        messages.error(request, "Subtask assigned member must belong to the selected team.")
                        return redirect("task_management:index")

            payload = {
                "owner": owner_name,
                "team": team,
                "job_id": request.POST.get("job_id", "").strip(),
                "subject": request.POST.get("subject", "").strip(),
                "start_date": _parse_date(request.POST.get("start_date")),
                "due_date": _parse_date(request.POST.get("due_date")),
                "target_type": request.POST.get("target_type", "").strip(),
                "contact_name": request.POST.get("contact_name", "").strip(),
                "candidate": candidate,
                "parent_task": parent_task,
                "status": request.POST.get("status", "").strip() or "Open",
                "priority": request.POST.get("priority", "").strip() or "Medium",
                "description": request.POST.get("description", "").strip(),
                "sla_enabled": request.POST.get("sla_enabled") == "on",
                "send_notification_email": request.POST.get("send_notification_email") == "on",
                "repeat_enabled": request.POST.get("repeat_enabled") == "on",
                "repeat_start_date": _parse_date(request.POST.get("repeat_start_date")),
                "repeat_end_date": _parse_date(request.POST.get("repeat_end_date")),
                "repeat_type": (request.POST.get("repeat_type") or "").strip().lower(),
                "reminder_enabled": request.POST.get("reminder_enabled") == "on",
                "reminder_start_date": _parse_date(request.POST.get("reminder_start_date")),
                "reminder_type": (request.POST.get("reminder_type") or "").strip().lower(),
                "reminder_notify_mode": (request.POST.get("reminder_notify_mode") or "").strip().lower(),
            }
            # Normalize target fields.
            if parent_task:
                if parent_task.candidate_id:
                    payload["target_type"] = "candidate"
                    payload["candidate"] = parent_task.candidate
                    payload["contact_name"] = ""
                else:
                    payload["target_type"] = "contact"
                    payload["candidate"] = None
                    payload["contact_name"] = parent_task.contact_name

            if (payload["target_type"] or "").strip().lower() == "candidate":
                payload["contact_name"] = ""
            elif (payload["target_type"] or "").strip().lower() == "contact":
                payload["candidate"] = None
            else:
                payload["candidate"] = None
                payload["contact_name"] = ""
            if payload["repeat_type"] in {"none"}:
                payload["repeat_type"] = ""
            if not payload["repeat_enabled"]:
                payload["repeat_start_date"] = None
                payload["repeat_end_date"] = None
                payload["repeat_type"] = ""
            if payload["repeat_enabled"] and not payload["repeat_type"]:
                messages.error(request, "Repeat type is required when repeat is enabled.")
                return redirect("task_management:index")
            if payload["repeat_start_date"] and payload["repeat_end_date"] and payload["repeat_end_date"] < payload["repeat_start_date"]:
                messages.error(request, "Repeat end date must be after start date.")
                return redirect("task_management:index")
            if payload["reminder_type"] in {"none"}:
                payload["reminder_type"] = ""
            if not payload["reminder_enabled"]:
                payload["reminder_start_date"] = None
                payload["reminder_type"] = ""
                payload["reminder_notify_mode"] = ""
            if payload["reminder_enabled"] and not payload["reminder_start_date"]:
                messages.error(request, "Reminder start date is required when reminder is enabled.")
                return redirect("task_management:index")
            if payload["reminder_enabled"] and not payload["reminder_type"]:
                messages.error(request, "Reminder repeat type is required when reminder is enabled.")
                return redirect("task_management:index")
            if payload["reminder_enabled"] and payload["reminder_notify_mode"] not in {"popup", "email", "both"}:
                payload["reminder_notify_mode"] = "popup"
            if task_id:
                task = get_object_or_404(TaskRecord, id=task_id)
                previous_owner = task.owner
                previous_status = (task.status or "").strip().lower()
                for key, value in payload.items():
                    setattr(task, key, value)
                _apply_sla_fields(task)
                _apply_status_timestamps(task)
                task.save()
                messages.success(request, "Task updated.")
                if subtask_subjects and task.parent_task_id is None:
                    for idx, subject in enumerate(subtask_subjects):
                        due = subtask_due_dates[idx] if idx < len(subtask_due_dates) else None
                        sub_owner = subtask_owners[idx] if idx < len(subtask_owners) else ""
                        if not sub_owner:
                            sub_owner = task.owner
                        group = subtask_groups[idx] if idx < len(subtask_groups) else ""
                        sub_status = subtask_statuses[idx] if idx < len(subtask_statuses) else "Open"
                        sub_priority = subtask_priorities[idx] if idx < len(subtask_priorities) else task.priority
                        created = TaskRecord.objects.create(
                            owner=sub_owner,
                            team=task.team,
                            job_id=task.job_id,
                            subject=subject,
                            due_date=due,
                            target_type=task.target_type,
                            contact_name=task.contact_name,
                            candidate=task.candidate,
                            parent_task=task,
                            subtask_group=group,
                            status=sub_status or "Open",
                            priority=sub_priority or task.priority,
                            description="",
                        )
                        _apply_status_timestamps(created)
                        created.save(update_fields=["started_at", "completed_at", "duration_minutes", "updated_at"])
                        _assign_subtask_task_id(subtask=created, parent=task)
                if payload["owner"] and payload["owner"] != previous_owner:
                    create_notifications(
                        payload["owner"],
                        title="Task assigned",
                        message=f"{payload['subject']}",
                        link=f"/task-management/?edit={task.id}",
                        source="task",
                        created_by=request.session.get("login_user_name", ""),
                    )
                if payload["send_notification_email"] and payload["owner"] and payload["owner"] != previous_owner:
                    owner_row = UserMaster.objects.filter(full_name__iexact=payload["owner"]).first()
                    if owner_row and (owner_row.email_id or "").strip():
                        err = _send_task_notification_email(
                            to_email=owner_row.email_id.strip(),
                            subject="Task assigned",
                            body=f"You have been assigned a task: {payload['subject']}\nDue date: {payload['due_date'] or '-'}\nLink: /task-management/?edit={task.id}",
                        )
                        if err:
                            messages.warning(request, f"Email notification failed: {err}")
                if previous_status != "completed" and (task.status or "").strip().lower() == "completed":
                    _create_repeat_task_if_needed(task=task, created_by=(request.session.get("login_user_name") or "").strip())
            else:
                task = TaskRecord(**payload)
                _apply_sla_fields(task)
                _apply_status_timestamps(task)
                task.save()
                messages.success(request, f"Task created: {task.task_id}")
                if task.parent_task_id:
                    _assign_subtask_task_id(subtask=task, parent=task.parent_task)
                if subtask_subjects and task.parent_task_id is None:
                    for idx, subject in enumerate(subtask_subjects):
                        due = subtask_due_dates[idx] if idx < len(subtask_due_dates) else None
                        sub_owner = subtask_owners[idx] if idx < len(subtask_owners) else ""
                        if not sub_owner:
                            sub_owner = task.owner
                        group = subtask_groups[idx] if idx < len(subtask_groups) else ""
                        sub_status = subtask_statuses[idx] if idx < len(subtask_statuses) else "Open"
                        sub_priority = subtask_priorities[idx] if idx < len(subtask_priorities) else task.priority
                        created = TaskRecord.objects.create(
                            owner=sub_owner,
                            team=task.team,
                            job_id=task.job_id,
                            subject=subject,
                            due_date=due,
                            target_type=task.target_type,
                            contact_name=task.contact_name,
                            candidate=task.candidate,
                            parent_task=task,
                            subtask_group=group,
                            status=sub_status or "Open",
                            priority=sub_priority or task.priority,
                            description="",
                        )
                        _apply_status_timestamps(created)
                        created.save(update_fields=["started_at", "completed_at", "duration_minutes", "updated_at"])
                        _assign_subtask_task_id(subtask=created, parent=task)
                # If task_id generation was skipped for any reason, ensure it's set.
                if not (task.task_id or "").strip():
                    task.task_id = f"TASK{task.pk:05d}"
                    task.save(update_fields=["task_id", "updated_at"])
                if payload["owner"]:
                    create_notifications(
                        payload["owner"],
                        title="Task assigned",
                        message=f"{payload['subject']}",
                        link=f"/task-management/?edit={task.id}",
                        source="task",
                        created_by=request.session.get("login_user_name", ""),
                    )
                if payload["send_notification_email"] and payload["owner"]:
                    owner_row = UserMaster.objects.filter(full_name__iexact=payload["owner"]).first()
                    if owner_row and (owner_row.email_id or "").strip():
                        err = _send_task_notification_email(
                            to_email=owner_row.email_id.strip(),
                            subject="Task assigned",
                            body=f"You have been assigned a task: {payload['subject']}\nDue date: {payload['due_date'] or '-'}\nLink: /task-management/?edit={task.id}",
                        )
                        if err:
                            messages.warning(request, f"Email notification failed: {err}")
                if (task.status or "").strip().lower() == "completed":
                    _create_repeat_task_if_needed(task=task, created_by=(request.session.get("login_user_name") or "").strip())
                # After create, redirect to edit view so the generated Task ID is visible immediately.
                # After update by a task owner, redirect back to the dashboard (avoid reopening subtask panel).
                if not task_id:
                    return redirect(f"/task-management/?edit={task.id}")
                if not _is_admin(role_name):
                    return redirect("task_management:index")
                return redirect(f"/task-management/?edit={task.id}")
            return redirect("task_management:index")

    role_name = (request.session.get("login_user_role") or "").strip()
    login_user_name = (request.session.get("login_user_name") or "").strip()
    owner_options = _task_owner_options()
    owner_role_map = _task_owner_role_map(owner_options)
    tasks_qs = TaskRecord.objects.select_related("candidate", "parent_task", "team").order_by("-created_at")
    if not _is_admin(role_name):
        owners = _owners_for_user(owner_options, login_user_name)
        if owners:
            tasks_qs = tasks_qs.filter(owner__in=owners)
        else:
            tasks_qs = tasks_qs.none()

    edit_id = request.GET.get("edit", "").strip()
    selected_task = None
    if edit_id:
        # Fetch selected task from full table to ensure the redirected "edit" view
        # can display the generated Task ID immediately after create/update.
        selected_task = TaskRecord.objects.select_related("candidate", "parent_task", "team").filter(id=edit_id).first()
        if selected_task and not _is_admin(role_name):
            allowed = set(_owners_for_user(owner_options, login_user_name) or [])
            if login_user_name:
                allowed.add(login_user_name)
            if (selected_task.owner or "") not in allowed:
                selected_task = None
    initial_parent_id = (request.GET.get("parent") or "").strip()
    initial_parent_task = tasks_qs.filter(id=initial_parent_id).first() if initial_parent_id else None
    task_rows = list(tasks_qs)
    visible_by_id = {row.id: row for row in task_rows}
    children_by_parent = {}
    roots = []
    for row in task_rows:
        if row.parent_task_id and row.parent_task_id in visible_by_id:
            children_by_parent.setdefault(row.parent_task_id, []).append(row)
        else:
            roots.append(row)

    for parent_id, items in children_by_parent.items():
        items.sort(key=lambda r: (r.created_at, r.id))

    def _row_dict(
        *,
        row: TaskRecord,
        level: int = 0,
        parent_display: str = "",
        parent_id: int | None = None,
        root_id: int | None = None,
        has_children: bool = False,
    ):
        return {
            "id": row.id,
            "task_id": row.task_id,
            "owner": row.owner,
            "owner_role": owner_role_map.get(row.owner, "-"),
            "team": row.team.team_name if row.team else "-",
            "job_id": row.job_id,
            "subject": row.subject,
            "due_date": row.due_date,
            "status": row.status,
            "priority": row.priority,
            "candidate": row.candidate.full_name if row.candidate else row.contact_name,
            "duration": _format_duration(row.duration_minutes),
            "submission_status": row.submission_status,
            "submitted_to": row.submitted_to,
            "level": level,
            "indent": min(level * 14, 42),
            "parent_task": parent_display,
            "parent_id": parent_id,
            "root_id": root_id or row.id,
            "has_children": has_children,
            "subtask_group": (row.subtask_group or "").strip(),
            "is_group_header": False,
            "group_title": "",
        }

    tasks = []
    visited = set()

    def _group_header_dict(*, title: str, level: int, parent_id: int | None, root_id: int):
        return {
            "id": f"grp-{root_id}-{parent_id or root_id}-{title.lower().replace(' ', '-')}",
            "task_id": "",
            "owner": "",
            "owner_role": "",
            "team": "",
            "job_id": "",
            "subject": "",
            "due_date": None,
            "status": "",
            "priority": "",
            "candidate": "",
            "duration": "",
            "submission_status": "",
            "submitted_to": "",
            "level": level,
            "indent": min(level * 14, 42),
            "parent_task": "",
            "parent_id": parent_id,
            "root_id": root_id,
            "has_children": False,
            "subtask_group": "",
            "is_group_header": True,
            "group_title": title,
        }

    def _flatten(node: TaskRecord, level: int, parent_task_code: str = "", parent_id: int | None = None, root_id: int | None = None):
        if node.id in visited:
            return
        visited.add(node.id)
        node_children = children_by_parent.get(node.id, [])
        tasks.append(
            _row_dict(
                row=node,
                level=level,
                parent_display=parent_task_code,
                parent_id=parent_id,
                root_id=root_id or node.id,
                has_children=bool(node_children),
            )
        )
        if not node_children:
            return

        # For subtasks, insert group headers (e.g. "Before Start Date") then tasks.
        grouped = {}
        group_order = []
        for child in node_children:
            group = (child.subtask_group or "").strip() or "Tasks"
            if group not in grouped:
                grouped[group] = []
                group_order.append(group)
            grouped[group].append(child)

        for group in group_order:
            children_in_group = grouped[group]
            if level + 1 > 0:
                tasks.append(
                    _group_header_dict(
                        title=group,
                        level=level + 1,
                        parent_id=node.id,
                        root_id=(root_id or node.id),
                    )
                )
            for child in children_in_group:
                _flatten(
                    child,
                    level + 1,
                    parent_task_code=(node.task_id or parent_task_code),
                    parent_id=node.id,
                    root_id=(root_id or node.id),
                )

    roots.sort(key=lambda r: (r.created_at, r.id), reverse=True)
    for root in roots:
        _flatten(root, 0, "", None, root.id)

    # Next parent task id should be continuous, regardless of subtasks.
    # Use parent_sequence when available; fall back to parsing TASKxxxxx from existing task_id.
    parent_rows = TaskRecord.objects.filter(parent_task__isnull=True).values_list("parent_sequence", "task_id")
    max_parent_seq = 0
    for parent_sequence, task_id in parent_rows:
        if parent_sequence:
            max_parent_seq = max(max_parent_seq, int(parent_sequence))
            continue
        raw = (task_id or "").strip()
        match = _TASK_ID_RE.match(raw)
        if match:
            max_parent_seq = max(max_parent_seq, int(match.group(1)))
    next_task_id_preview = f"TASK{max_parent_seq + 1:05d}"
    next_subtask_id_preview = ""
    if initial_parent_task and (initial_parent_task.task_id or "").strip():
        prefix = f"{initial_parent_task.task_id}."
        max_suffix = 0
        for existing in TaskRecord.objects.filter(parent_task=initial_parent_task).only("task_id"):
            value = (existing.task_id or "").strip()
            if not value.startswith(prefix):
                continue
            suffix = value[len(prefix):].strip()
            if suffix.isdigit():
                max_suffix = max(max_suffix, int(suffix))
        next_subtask_id_preview = f"{initial_parent_task.task_id}.{max_suffix + 1}"

    parent_task_options = []
    for row in task_rows:
        if row.parent_task_id is not None:
            continue
        if row.candidate_id is None:
            continue
        parent_task_options.append(
            {
                "id": row.id,
                "task_id": row.task_id,
                "subject": row.subject,
                "candidate_id": row.candidate.candidate_id if row.candidate else "",
                "candidate_name": row.candidate.full_name if row.candidate else "",
            }
        )
    context = {
        "task_owners": owner_options,
        "contacts": ["HR Team", "Client Contact", "Vendor Contact"],
        "team_options": list(
            RecruitmentTeamMaster.objects.order_by("team_name").values("id", "team_name", "team_members", "team_lead")
        ),
        "job_options": list(
            JobRequisition.objects.order_by("-created_at").values("job_id", "title")
        ),
        "candidates": [
            {"id": row.candidate_id, "name": row.full_name}
            for row in Candidate.objects.order_by("candidate_id")
        ],
        "statuses": ["Open", "In Progress", "Completed", "Deferred"],
        "priorities": ["Low", "Medium", "High", "Urgent"],
        "repeat_types": ["None", "Daily", "Weekly", "Monthly", "Yearly"],
        "tasks": tasks,
        "selected_task": selected_task,
        "parent_task_options": parent_task_options,
        "initial_parent_task": initial_parent_task,
        "next_task_id_preview": next_task_id_preview,
        "next_subtask_id_preview": next_subtask_id_preview,
        "onboarding_subtask_template": ONBOARDING_SUBTASK_TEMPLATE,
        "sla_priority_map": {
            key: {"resp": resp, "res": res}
            for key, (resp, res) in PRIORITY_SLA_HOURS.items()
        },
    }

    # Override SLA map from settings (if configured).
    for row in TaskSlaPrioritySetting.objects.all().only("priority", "first_response_hours", "resolution_hours"):
        if row.first_response_hours and row.resolution_hours:
            context["sla_priority_map"][row.priority] = {"resp": int(row.first_response_hours), "res": int(row.resolution_hours)}
    return render(request, "task_management/index.html", context)


def timesheet_report_view(request):
    if request.method == "POST":
        messages.error(request, "Timesheet entry creation is disabled.")
        return redirect("task_management:timesheet_report")

    context = {}
    context.update(_timesheet_context(request))
    context["timesheet_tasks"] = TaskRecord.objects.order_by("-created_at")
    context["timesheet_entries"] = TaskTimesheetEntry.objects.select_related("task").order_by("-entry_date", "-created_at")[:200]
    return render(request, "task_management/timesheet_report.html", context)
