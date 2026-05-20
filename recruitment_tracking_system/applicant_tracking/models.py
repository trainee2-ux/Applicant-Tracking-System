import uuid
from django.db import models
from django.utils import timezone
import json

from candidate_management.models import Candidate
from app_settings.models import AssessmentForm


class ApplicationPipelineCandidate(models.Model):
    STAGE_CHOICES = [
        ("Applied", "Applied"),
        ("Screened", "Screened"),
        ("Interview", "Interview"),
        ("Offer", "Offer"),
        ("Hired", "Hired"),
        ("Rejected", "Rejected"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="pipeline_entries")
    job_applied = models.CharField(max_length=180, blank=True)
    stage = models.CharField(max_length=40, choices=STAGE_CHOICES, default="Applied")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_updated"]
        unique_together = [("candidate", "job_applied")]


class InPersonInterview(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="in_person_interviews")
    manpower_requisition_id = models.CharField(max_length=50, blank=True)
    interview_process_name = models.CharField(max_length=100, blank=True)
    posting_title = models.CharField(max_length=180, blank=True)
    interviewer_name = models.CharField(max_length=150)
    client_name = models.CharField(max_length=150, blank=True)
    date = models.DateField()
    from_time = models.TimeField()
    to_time = models.TimeField()
    location = models.CharField(max_length=200, blank=True)
    interview_owner = models.CharField(max_length=150, blank=True)
    schedule_comments = models.TextField(blank=True)
    assessment_name = models.CharField(max_length=180, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    calendar_event_id = models.CharField(max_length=120, blank=True)
    calendar_sync_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.manpower_requisition_id:
            self.manpower_requisition_id = f"MPR{self.pk:04d}"
            super().save(update_fields=["manpower_requisition_id"])


class VideoInterviewSchedule(models.Model):
    PROVIDER_CHOICES = [
        ("google_meet", "Google Meet"),
        ("microsoft_teams", "Microsoft Teams"),
        ("zoom", "Zoom"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="video_interviews")
    manpower_requisition_id = models.CharField(max_length=50, blank=True)
    interview_process_name = models.CharField(max_length=100, blank=True)
    posting_title = models.CharField(max_length=180, blank=True)
    interviewer_name = models.CharField(max_length=150)
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES)
    meeting_link = models.CharField(max_length=255)
    host_link = models.CharField(max_length=255, blank=True)
    external_meeting_id = models.CharField(max_length=120, blank=True)
    provider_payload = models.TextField(blank=True)
    email_delivery_status = models.CharField(max_length=20, default="Pending")
    email_delivery_error = models.TextField(blank=True)
    email_sent_at = models.DateTimeField(blank=True, null=True)
    date = models.DateField()
    from_time = models.TimeField()
    to_time = models.TimeField()
    interview_owner = models.CharField(max_length=150, blank=True)
    schedule_comments = models.TextField(blank=True)
    cc_emails = models.TextField(blank=True)
    calendar_event_id = models.CharField(max_length=120, blank=True)
    calendar_sync_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def set_provider_payload(self, payload):
        self.provider_payload = json.dumps(payload or {})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.manpower_requisition_id:
            self.manpower_requisition_id = f"MPR{self.pk:04d}"
            super().save(update_fields=["manpower_requisition_id"])


class LoginInterviewSchedule(models.Model):
    """
    "Log In Interview" schedule type.
    Stores the schedule plus access instructions/link for logging in to an external system/portal.
    """

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="login_interviews")
    manpower_requisition_id = models.CharField(max_length=50, blank=True)
    interview_process_name = models.CharField(max_length=100, blank=True)
    posting_title = models.CharField(max_length=180, blank=True)
    interviewer_name = models.CharField(max_length=150)
    client_name = models.CharField(max_length=150, blank=True)
    login_url = models.CharField(max_length=255, blank=True)
    access_notes = models.TextField(blank=True)
    date = models.DateField()
    from_time = models.TimeField()
    to_time = models.TimeField()
    interview_owner = models.CharField(max_length=150, blank=True)
    schedule_comments = models.TextField(blank=True)
    assessment_name = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.manpower_requisition_id:
            self.manpower_requisition_id = f"MPR{self.pk:04d}"
            super().save(update_fields=["manpower_requisition_id"])


class CandidateAssessmentAssignment(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Completed", "Completed"),
        ("Expired", "Expired"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="assessment_assignments")
    assessment_form = models.ForeignKey(AssessmentForm, on_delete=models.CASCADE, related_name="candidate_assignments")
    assigned_by = models.CharField(max_length=150, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(blank=True, null=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    completed_at = models.DateTimeField(blank=True, null=True)

    source_type = models.CharField(max_length=40, blank=True, help_text="Optional: interview schedule source type")
    source_id = models.PositiveIntegerField(blank=True, null=True, help_text="Optional: interview schedule record id")

    last_opened_at = models.DateTimeField(blank=True, null=True)
    last_opened_ip = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-assigned_at"]

    def mark_opened(self, *, ip_address: str = ""):
        self.last_opened_at = timezone.now()
        self.last_opened_ip = (ip_address or "").strip()[:64]
        self.save(update_fields=["last_opened_at", "last_opened_ip"])

    def mark_completed(self):
        self.status = "Completed"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def __str__(self):
        return f"{self.candidate.full_name} - {self.assessment_form.name} ({self.status})"


class CandidateAssessmentSubmission(models.Model):
    assignment = models.OneToOneField(CandidateAssessmentAssignment, on_delete=models.CASCADE, related_name="submission")
    answers = models.JSONField(default=dict, blank=True)
    score = models.FloatField(default=0)
    max_score = models.FloatField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"Submission for {self.assignment_id} ({self.score})"
