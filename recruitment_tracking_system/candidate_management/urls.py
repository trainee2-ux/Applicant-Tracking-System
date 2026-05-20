from django.urls import path
from django.http import JsonResponse

from .views import (
    candidate_delete_confirm_view,
    candidate_management_view,
    candidate_resume_parse_view,
    candidate_registration_view,
    candidate_list_view,
    candidate_notes_view,
    candidate_profile_view,
    candidate_evaluation_view,
    candidate_resume_download_view,
    candidate_profile_photo_download_view,
    candidate_activity_dashboard_view,
)

app_name = "candidate_management"

urlpatterns = [
    path("", candidate_management_view, name="index"),
    path("registration/", candidate_registration_view, name="registration"),
    path("parse-resume/", candidate_resume_parse_view, name="parse_resume"),
    path("list/", candidate_list_view, name="list"),
    path("resume/<str:candidate_id>/", candidate_resume_download_view, name="resume_download"),
    path("profile-photo/<str:candidate_id>/", candidate_profile_photo_download_view, name="profile_photo_download"),
    path("delete/<str:candidate_id>/", candidate_delete_confirm_view, name="delete_confirm"),
    path("profile/", candidate_profile_view, name="profile"),
    path("notes/", candidate_notes_view, name="notes"),
    path("evaluation/", candidate_evaluation_view, name="evaluation"),
    path("activity/", candidate_activity_dashboard_view, name="activity"),
]
