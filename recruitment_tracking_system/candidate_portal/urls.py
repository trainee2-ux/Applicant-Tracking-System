from django.urls import path

from .views import (
    candidate_applied_job_detail_view,
    candidate_portal_admin_access_view,
    candidate_application_pipeline_view,
    candidate_portal_view,
    candidate_portal_resume_upload_view,
    candidate_resume_ocr_view,
    candidate_portal_resume_download_view,
    candidate_onboarding_documents_view,
    candidate_offer_detail_view,
    candidate_offer_response_view,
    candidate_onboarding_form_view,
    candidate_onboarding_register_view,
    candidate_magic_login_view,
    candidate_assessment_form_view,
    candidate_onboarding_signature_view,
    candidate_ai_chat_view,
    public_careers_view,
    public_job_detail_view,
)

app_name = "candidate_portal"

urlpatterns = [
    path("", candidate_portal_view, name="index"),
    path("admin-access/", candidate_portal_admin_access_view, name="admin_access"),
    path("application-pipeline/", candidate_application_pipeline_view, name="application_pipeline"),
    path("applied-jobs/<str:job_id>/", candidate_applied_job_detail_view, name="applied_job_detail"),
    path("careers/", public_careers_view, name="careers"),
    path("jobs/<str:job_id>/", public_job_detail_view, name="public_job_detail"),
    path("resume-upload/", candidate_portal_resume_upload_view, name="resume_upload"),
    path("resume-ocr/", candidate_resume_ocr_view, name="resume_ocr"),
    path("resume/", candidate_portal_resume_download_view, name="resume_download"),
    path("onboarding-documents/", candidate_onboarding_documents_view, name="onboarding_documents"),
    path("offer/<str:token>/", candidate_offer_detail_view, name="offer_detail"),
    path("offer/<str:token>/<str:decision>/", candidate_offer_response_view, name="offer_response"),
    path("onboarding/<str:token>/", candidate_onboarding_register_view, name="onboarding_register"),
    path("onboarding/<str:token>/form/", candidate_onboarding_form_view, name="onboarding_form"),
    path("sign/<str:token>/", candidate_onboarding_signature_view, name="onboarding_signature"),
    path("assessment/<uuid:token>/", candidate_assessment_form_view, name="assessment_form"),
    path("magic/<str:token>/", candidate_magic_login_view, name="magic_login"),
    path("ai-chat/", candidate_ai_chat_view, name="ai_chat"),
]
