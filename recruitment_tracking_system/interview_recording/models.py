from django.db import models

from candidate_management.models import Candidate


class InterviewPanelSchedule(models.Model):
    MODE_CHOICES = [("In Person", "In Person"), ("Video", "Video")]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="panel_schedules")
    interviewers = models.CharField(max_length=250)
    date = models.DateField()
    time = models.TimeField()
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    video_link = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class InterviewRecording(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="recordings")
    interviewer = models.CharField(max_length=150)
    video_file_name = models.CharField(max_length=255)
    video_file_path = models.CharField(max_length=500, blank=True)
    transcript = models.TextField(blank=True)
    anonymized_transcript = models.TextField(blank=True)
    pii_redacted = models.BooleanField(default=False)
    sentiment_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    dominant_emotion = models.CharField(max_length=50, blank=True)
    emotion_summary = models.TextField(blank=True)
    emotion_error = models.TextField(blank=True)
    emotion_processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
