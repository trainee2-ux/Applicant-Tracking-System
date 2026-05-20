from django.db import models
from candidate_management.models import Candidate


class CandidatePortalProfile(models.Model):
    candidate = models.OneToOneField(Candidate, on_delete=models.CASCADE, related_name="portal_profile")
    portal_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Portal profile: {self.candidate.candidate_id}"
