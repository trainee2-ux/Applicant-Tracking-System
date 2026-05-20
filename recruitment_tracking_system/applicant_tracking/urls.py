from django.urls import path

from .views import (
    applicant_tracking_view,
    application_pipeline_view,
    in_person_interview_view,
    in_person_interview_delete_confirm_view,
    interview_scheduling_view,
    login_interview_delete_confirm_view,
    login_interview_view,
    assessment_assignments_view,
    video_interview_delete_confirm_view,
    video_interview_view,
)

app_name = "applicant_tracking"

urlpatterns = [
    path("", applicant_tracking_view, name="index"),
    path("application-pipeline/", application_pipeline_view, name="application_pipeline"),
    path("interview-scheduling/", interview_scheduling_view, name="interview_scheduling"),
    path("interview-scheduling/in-person/", in_person_interview_view, name="in_person_interview"),
    path("interview-scheduling/in-person/delete/<int:record_id>/", in_person_interview_delete_confirm_view, name="in_person_interview_delete_confirm"),
    path("interview-scheduling/video/", video_interview_view, name="video_interview"),
    path("interview-scheduling/video/delete/<int:record_id>/", video_interview_delete_confirm_view, name="video_interview_delete_confirm"),
    path("interview-scheduling/login/", login_interview_view, name="login_interview"),
    path("interview-scheduling/login/delete/<int:record_id>/", login_interview_delete_confirm_view, name="login_interview_delete_confirm"),
    path("interview-scheduling/assessments/", assessment_assignments_view, name="assessment_assignments"),
]
