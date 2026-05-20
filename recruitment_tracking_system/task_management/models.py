from django.db import models

from candidate_management.models import Candidate
from recruitment_teams.models import RecruitmentTeamMaster


class TaskRecord(models.Model):
    SUBMISSION_STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    task_id = models.CharField(max_length=20, unique=True, blank=True)
    parent_sequence = models.PositiveIntegerField(null=True, blank=True, unique=True)
    owner = models.CharField(max_length=150)
    team = models.ForeignKey(RecruitmentTeamMaster, on_delete=models.SET_NULL, null=True, blank=True)
    job_id = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=220)
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    target_type = models.CharField(max_length=40, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subtasks",
    )
    subtask_group = models.CharField(max_length=120, blank=True)
    sla_enabled = models.BooleanField(default=True)
    sla_first_response_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    sla_resolution_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    sla_first_response_due_at = models.DateTimeField(null=True, blank=True)
    sla_resolution_due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=40, default="Open")
    priority = models.CharField(max_length=40, default="Medium")
    description = models.TextField(blank=True)
    send_notification_email = models.BooleanField(default=False)
    repeat_enabled = models.BooleanField(default=False)
    repeat_start_date = models.DateField(null=True, blank=True)
    repeat_end_date = models.DateField(null=True, blank=True)
    repeat_type = models.CharField(max_length=20, blank=True)
    reminder_enabled = models.BooleanField(default=False)
    reminder_start_date = models.DateField(null=True, blank=True)
    reminder_type = models.CharField(max_length=20, blank=True)
    reminder_notify_mode = models.CharField(max_length=20, blank=True)
    reminder_last_sent_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    proof_file = models.FileField(upload_to="task_proofs/", blank=True, null=True)
    proof_notes = models.TextField(blank=True)
    proof_submitted_at = models.DateTimeField(null=True, blank=True)
    submission_status = models.CharField(max_length=20, choices=SUBMISSION_STATUS_CHOICES, default="draft")
    submitted_to = models.CharField(max_length=150, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=150, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if (self.task_id or "").strip():
            # Keep parent_sequence in sync for legacy rows (created before parent_sequence existed).
            if self.parent_task_id is None and self.parent_sequence is None:
                value = (self.task_id or "").strip().upper()
                if value.startswith("TASK"):
                    suffix = value[4:]
                    if suffix.isdigit():
                        self.parent_sequence = int(suffix)
                        super().save(update_fields=["parent_sequence", "updated_at"])
            return

        if self.parent_task_id:
            # Subtask IDs are assigned in views to follow "<PARENT>.<N>" pattern.
            return

        # Parent tasks should use a continuous sequence that is not affected by subtasks.
        if self.parent_sequence is None:
            max_value = (
                TaskRecord.objects.filter(parent_task__isnull=True)
                .exclude(parent_sequence__isnull=True)
                .aggregate(models.Max("parent_sequence"))
                .get("parent_sequence__max")
                or 0
            )
            self.parent_sequence = max_value + 1
            super().save(update_fields=["parent_sequence", "updated_at"])

        self.task_id = f"TASK{self.parent_sequence:05d}"
        super().save(update_fields=["task_id", "updated_at"])


class TaskTimesheetEntry(models.Model):
    task = models.ForeignKey(TaskRecord, on_delete=models.CASCADE, related_name="timesheet_entries")
    user_name = models.CharField(max_length=150)
    entry_date = models.DateField()
    hours_worked = models.DecimalField(max_digits=5, decimal_places=2)
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
