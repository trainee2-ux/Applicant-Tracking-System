from django.db import models

from candidate_management.models import Candidate


class InterviewEvaluationSubmission(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="interview_submissions")
    candidate_name = models.CharField(max_length=150, blank=True)
    interviewer_name = models.CharField(max_length=150)
    interview_round = models.CharField(max_length=80, blank=True)
    technical_score = models.DecimalField(max_digits=5, decimal_places=2)
    communication_score = models.DecimalField(max_digits=5, decimal_places=2)
    cultural_fit_score = models.DecimalField(max_digits=5, decimal_places=2)
    comments = models.TextField(blank=True)
    assessment_form_name = models.CharField(max_length=120, blank=True)
    assessment_form_data = models.TextField(blank=True)
    feedback_form_name = models.CharField(max_length=120, blank=True)
    feedback_form_data = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
