from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.utils import timezone

from app_settings.models import EmailDeliveryConfig, UserMaster
from app_settings.notifications import create_notifications
from recruitment_teams.models import RecruitmentTeamMaster

from .models import TaskRecord


def _normalize_smtp_password(host: str, password: str) -> str:
    host_value = (host or "").strip().lower()
    pwd = (password or "").strip()
    if host_value in {"smtp.gmail.com", "smtp.googlemail.com"}:
        return pwd.replace(" ", "")
    return pwd


def _send_email(*, to_email: str, subject: str, body: str) -> str:
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


def _advance_date(base_date, repeat_type: str):
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


def _resolve_recipients(task: TaskRecord) -> list[tuple[str, str]]:
    """
    Returns list of (display_name, email) recipients for a task reminder.
    - If task has team: all team members + lead (if present) that can be resolved to UserMaster emails.
    - Else: task owner.
    """

    names: list[str] = []
    if task.team_id:
        team = RecruitmentTeamMaster.objects.filter(id=task.team_id).first()
        if team:
            names.extend([n.strip() for n in (team.team_members or "").split(",") if n.strip()])
            if (team.team_lead or "").strip():
                names.append(team.team_lead.strip())
    else:
        if (task.owner or "").strip():
            names.append(task.owner.strip())

    seen = set()
    result: list[tuple[str, str]] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        user = UserMaster.objects.filter(full_name__iexact=name).first()
        email = (user.email_id if user else "").strip() if user else ""
        result.append((name, email))
    return result


def dispatch_due_task_reminders(*, limit: int = 25) -> int:
    """
    Sends reminders that are due *today* (or earlier) and not already sent today.
    Creates UiNotification (portal pop-up) and optionally sends emails.

    This function is safe to call frequently (once-per-request) due to once-per-day gating.
    """

    today = timezone.localdate()
    now = timezone.now()
    qs = (
        TaskRecord.objects.filter(reminder_enabled=True)
        .exclude(status__iexact="Completed")
        .filter(reminder_start_date__isnull=False, reminder_start_date__lte=today)
        .order_by("reminder_last_sent_at", "id")
    )

    sent = 0
    for task in qs[: max(1, int(limit))]:
        last = task.reminder_last_sent_at
        if last and last.date() >= today:
            continue

        notify_mode = (task.reminder_notify_mode or "").strip().lower() or "popup"
        recipients = _resolve_recipients(task)

        # Always create portal notifications (popup) when enabled.
        create_notifications(
            [name for name, _email in recipients if name],
            title="Task reminder",
            message=f"{task.subject} ({task.task_id})",
            link=f"/task-management/?edit={task.id}",
            source="task",
            created_by="system",
        )

        if notify_mode in {"email", "both"}:
            for display_name, email in recipients:
                if not email:
                    continue
                _send_email(
                    to_email=email,
                    subject="Task reminder",
                    body=f"Reminder for task: {task.subject}\nTask ID: {task.task_id}\nDue: {task.due_date or '-'}\nLink: /task-management/?edit={task.id}",
                )

        with transaction.atomic():
            task.reminder_last_sent_at = now
            task.save(update_fields=["reminder_last_sent_at", "updated_at"])

        # Reschedule next reminder based on reminder_type.
        next_date = _advance_date(task.reminder_start_date, task.reminder_type)
        if next_date:
            task.reminder_start_date = next_date
            task.save(update_fields=["reminder_start_date", "updated_at"])

        sent += 1

    return sent

