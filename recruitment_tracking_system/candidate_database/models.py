from django.db import models
from candidate_management.models import Candidate


class CandidateDatabaseNote(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="database_notes")
    note = models.TextField()
    created_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Note for {self.candidate.candidate_id}"
