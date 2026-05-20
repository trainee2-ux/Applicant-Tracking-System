from django.contrib import admin

from .models import (
    EmployeeCodeAssignment,
    OfferLetter,
    OnboardingDocument,
    OnboardingFormTemplate,
    OnboardingInvitation,
    OnboardingSubmission,
)


@admin.register(OnboardingFormTemplate)
class OnboardingFormTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "offer_email_template", "is_active", "updated_at", "created_by")
    search_fields = ("name",)


@admin.register(OfferLetter)
class OfferLetterAdmin(admin.ModelAdmin):
    list_display = ("candidate", "status", "sent_to_email", "sent_at", "responded_at")
    search_fields = ("candidate__candidate_id", "candidate__full_name", "candidate__email", "status")


@admin.register(OnboardingInvitation)
class OnboardingInvitationAdmin(admin.ModelAdmin):
    list_display = ("candidate", "status", "expires_at", "created_at")
    search_fields = ("candidate__candidate_id", "candidate__full_name", "candidate__email", "status")


@admin.register(OnboardingSubmission)
class OnboardingSubmissionAdmin(admin.ModelAdmin):
    list_display = ("invitation", "status", "submitted_at", "approved_by", "approved_at")
    search_fields = ("invitation__candidate__candidate_id", "invitation__candidate__full_name", "status")


@admin.register(OnboardingDocument)
class OnboardingDocumentAdmin(admin.ModelAdmin):
    list_display = ("submission", "document_key", "uploaded_at")


@admin.register(EmployeeCodeAssignment)
class EmployeeCodeAssignmentAdmin(admin.ModelAdmin):
    list_display = ("candidate", "employee_code", "assigned_by", "assigned_at")
    search_fields = ("candidate__candidate_id", "employee_code")
