import uuid
from django.db import models


class ProctoringSession(models.Model):
    """
    One proctoring session per candidate assessment attempt
    (or per interviewer evaluation form load).
    """

    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("terminated", "Terminated – Too Many Violations"),
    ]

    CONTEXT_CHOICES = [
        ("assessment", "Candidate Assessment"),
        ("evaluation", "Interview Evaluation"),
    ]

    session_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    context = models.CharField(max_length=20, choices=CONTEXT_CHOICES, default="assessment")

    # Generic reference — store the assignment UUID or evaluation record id as a string
    reference_id = models.CharField(max_length=200, blank=True, help_text="Assessment token or evaluation ID")
    candidate_name = models.CharField(max_length=200, blank=True)
    candidate_email = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    warnings_count = models.PositiveIntegerField(default=0)
    max_warnings = models.PositiveIntegerField(default=3)

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Proctoring Session"
        verbose_name_plural = "Proctoring Sessions"

    def __str__(self):
        return f"[{self.context}] {self.candidate_name or self.reference_id} — {self.status}"

    @property
    def is_terminated(self):
        return self.status == "terminated"

    @property
    def violation_summary(self):
        counts = {}
        for v in self.violations.all():
            counts[v.violation_type] = counts.get(v.violation_type, 0) + 1
        return counts


class ProctoringViolationLog(models.Model):
    """
    Individual violation event captured during a proctoring session.
    """

    VIOLATION_TYPES = [
        ("tab_switch", "Tab Switch / Window Blur"),
        ("fullscreen_exit", "Exited Fullscreen"),
        ("devtools_open", "DevTools Opened"),
        ("copy_paste", "Copy/Paste Attempt"),
        ("right_click", "Right-Click Attempt"),
        ("multiple_faces", "Multiple Faces Detected"),
        ("no_face", "No Face Detected"),
        ("unknown", "Unknown"),
    ]

    session = models.ForeignKey(ProctoringSession, on_delete=models.CASCADE, related_name="violations")
    violation_type = models.CharField(max_length=40, choices=VIOLATION_TYPES, default="unknown")
    timestamp = models.DateTimeField(auto_now_add=True)
    meta = models.JSONField(default=dict, blank=True, help_text="Extra context (e.g. tab URL, window dimensions)")

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Violation Log"
        verbose_name_plural = "Violation Logs"

    def __str__(self):
        return f"{self.violation_type} @ {self.timestamp:%Y-%m-%d %H:%M:%S}"


class ProctoringSnapshot(models.Model):
    """
    Periodic webcam snapshot saved during a proctoring session.
    """

    session = models.ForeignKey(ProctoringSession, on_delete=models.CASCADE, related_name="snapshots")
    image_data = models.TextField(help_text="Base64-encoded JPEG snapshot")
    face_count = models.IntegerField(default=-1, help_text="-1 = not analysed, 0 = no face, 1 = ok, 2+ = multiple")
    flagged = models.BooleanField(default=False, help_text="True if face_count is 0 or >1")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Proctoring Snapshot"
        verbose_name_plural = "Proctoring Snapshots"

    def __str__(self):
        return f"Snapshot {self.pk} — faces={self.face_count} @ {self.timestamp:%H:%M:%S}"
