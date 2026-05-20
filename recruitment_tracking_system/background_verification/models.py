from django.db import models
from django.core.files.storage import default_storage
from django.db.models.signals import post_delete
from django.dispatch import receiver

from candidate_management.models import Candidate


class BackgroundVerificationRecord(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="bgv_records")
    document_type = models.CharField(max_length=120)
    verifier_assigned = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=40, default="Pending")
    comments = models.TextField(blank=True)
    verification_summary = models.TextField(blank=True)
    score_status = models.CharField(max_length=60, blank=True)
    discrepancies = models.TextField(blank=True)
    risk_score = models.IntegerField(null=True, blank=True)
    risk_level = models.CharField(max_length=20, blank=True)
    risk_reason = models.TextField(blank=True)
    ocr_summary = models.TextField(blank=True)
    id_proof = models.CharField(max_length=255, blank=True)
    address_proof = models.CharField(max_length=255, blank=True)
    education_certificates = models.CharField(max_length=255, blank=True)
    employment_proof = models.CharField(max_length=255, blank=True)
    reference_contacts = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


def _extract_file_path(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "||" in raw:
        _, file_path = raw.split("||", 1)
        return (file_path or "").strip()
    return ""


@receiver(post_delete, sender=BackgroundVerificationRecord)
def _cleanup_bgv_files(sender, instance, **kwargs):
    file_fields = [
        instance.id_proof,
        instance.address_proof,
        instance.education_certificates,
        instance.employment_proof,
    ]
    for packed in file_fields:
        file_path = _extract_file_path(packed)
        if not file_path:
            continue
        try:
            if default_storage.exists(file_path):
                default_storage.delete(file_path)
        except Exception:
            continue
