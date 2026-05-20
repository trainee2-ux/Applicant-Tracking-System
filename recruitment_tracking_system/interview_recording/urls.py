from django.urls import path

from .views import (
    auto_recording_ingest_view,
    interview_panel_dashboard_view,
    interview_recording_dashboard_view,
    interview_recording_view,
    panel_delete_confirm_view,
    recording_delete_confirm_view,
)

app_name = "interview_recording"

urlpatterns = [
    path("", interview_recording_view, name="index"),
    path("panel/", interview_panel_dashboard_view, name="panel_dashboard"),
    path("panel/delete/<int:record_id>/", panel_delete_confirm_view, name="panel_delete_confirm"),
    path("recording/", interview_recording_dashboard_view, name="recording_dashboard"),
    path("recording/delete/<int:record_id>/", recording_delete_confirm_view, name="recording_delete_confirm"),
    path("api/auto-recording/", auto_recording_ingest_view, name="auto_recording_ingest"),
]
