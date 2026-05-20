import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from candidate_management.models import Candidate, CandidateJobApplication


class OfferLetter(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="offer_letters")
    application = models.ForeignKey(
        CandidateJobApplication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offer_letters",
    )

    subject = models.CharField(max_length=255, default="Offer Letter")
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    access_token = models.CharField(max_length=80, unique=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    sent_to_email = models.EmailField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.CharField(max_length=255, blank=True)

    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Offer: {self.candidate.candidate_id} ({self.status})"

    def ensure_token(self, *, ttl_days: int = 14) -> None:
        if not self.access_token:
            self.access_token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=ttl_days)

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() > self.expires_at)


class OnboardingFormTemplate(models.Model):
    """
    A lightweight form-builder: HR selects a set of fields and document requirements.
    The candidate submission is stored against the generated invitation.
    """

    name = models.CharField(max_length=150, unique=True)
    description = models.CharField(max_length=255, blank=True)
    selected_fields = models.JSONField(default=list, blank=True)
    document_requirements = models.JSONField(default=list, blank=True)
    offer_email_template = models.ForeignKey(
        "app_settings.EmailTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_form_templates",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class OnboardingInvitation(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("registered", "Registered"),
        ("submitted", "Documents Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="onboarding_invitations")
    offer_letter = models.ForeignKey(
        OfferLetter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations",
    )
    form_template = models.ForeignKey(
        OnboardingFormTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations",
    )

    token = models.CharField(max_length=80, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    expires_at = models.DateTimeField(null=True, blank=True)
    document_requirements_override = models.JSONField(default=list, blank=True)

    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite: {self.candidate.candidate_id} ({self.status})"

    def ensure_token(self, *, ttl_days: int = 30) -> None:
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=ttl_days)

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() > self.expires_at)


class OnboardingSubmission(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    invitation = models.OneToOneField(
        OnboardingInvitation,
        on_delete=models.CASCADE,
        related_name="submission",
    )
    form_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=150, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Submission: {self.invitation.candidate.candidate_id} ({self.status})"


class OnboardingDocument(models.Model):
    submission = models.ForeignKey(OnboardingSubmission, on_delete=models.CASCADE, related_name="documents")
    document_key = models.CharField(max_length=120)
    file = models.FileField(upload_to="onboarding/documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.submission.invitation.candidate.candidate_id} - {self.document_key}"


class EmployeeCodeAssignment(models.Model):
    candidate = models.OneToOneField(Candidate, on_delete=models.CASCADE, related_name="employee_assignment")
    submission = models.OneToOneField(
        OnboardingSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_assignment",
    )
    employee_code = models.CharField(max_length=40, unique=True)
    assigned_by = models.CharField(max_length=150, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"EmployeeCode: {self.candidate.candidate_id} -> {self.employee_code}"


class OnboardingSignatureRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Signature"),
        ("signed", "Signed"),
        ("final_approved", "Final Approved"),
        ("rejected", "Rejected"),
    ]

    submission = models.OneToOneField(
        OnboardingSubmission,
        on_delete=models.CASCADE,
        related_name="signature_request",
    )
    token = models.CharField(max_length=80, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    signature_data = models.TextField(blank=True, help_text="Base64 data URL for the signature image")
    # NOTE: legacy single-document fields kept for backward compatibility.
    document_pdf = models.FileField(upload_to="onboarding/signatures/", blank=True)
    signed_pdf = models.FileField(upload_to="onboarding/signatures/signed/", blank=True)
    page_number = models.IntegerField(default=1)
    position_x = models.FloatField(default=70.0, help_text="X position as percentage of page width")
    position_y = models.FloatField(default=80.0, help_text="Y position as percentage of page height")
    width = models.FloatField(default=180.0, help_text="Width in pixels")
    height = models.FloatField(default=70.0, help_text="Height in pixels")
    signed_at = models.DateTimeField(null=True, blank=True)

    final_approved_by = models.CharField(max_length=150, blank=True)
    final_approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"SignatureRequest: {self.submission.invitation.candidate.candidate_id} ({self.status})"

    def ensure_token(self) -> None:
        if not self.token:
            self.token = secrets.token_urlsafe(32)


class OnboardingSignDocument(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Signature"),
        ("signed", "Signed"),
    ]

    signature_request = models.ForeignKey(
        OnboardingSignatureRequest,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=150, default="Document")
    document_pdf = models.FileField(upload_to="onboarding/signatures/")
    signed_pdf = models.FileField(upload_to="onboarding/signatures/signed/", blank=True)

    # Signature placement (percent-based like dmsystem).
    page_number = models.IntegerField(default=1)
    position_x = models.FloatField(default=70.0, help_text="X position as percentage of page width")
    position_y = models.FloatField(default=80.0, help_text="Y position as percentage of page height")
    width = models.FloatField(default=180.0, help_text="Width in pixels")
    height = models.FloatField(default=70.0, help_text="Height in pixels")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    signed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.signature_request.submission.invitation.candidate.candidate_id} - {self.title} ({self.status})"

class OnboardingAuditLog(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="onboarding_audit_logs", null=True, blank=True)
    performed_by = models.ForeignKey("app_settings.UserMaster", on_delete=models.SET_NULL, null=True, blank=True, related_name="onboarding_actions")
    action = models.CharField(max_length=150)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.candidate.full_name} - {self.action} ({self.timestamp})"


class OnboardingSigningCertificate(models.Model):
    signature_request = models.ForeignKey(OnboardingSignatureRequest, on_delete=models.CASCADE, related_name="certificates")
    document = models.ForeignKey(OnboardingSignDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="certificates")
    certificate_pdf = models.FileField(upload_to="onboarding/certificates/")
    verification_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Certificate: {self.signature_request.submission.invitation.candidate.full_name}"
