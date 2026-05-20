from django.urls import path

from .views import (
    background_verification_view,
    bgv_report_view,
    bgv_submission_delete_confirm_view,
    bgv_submission_view,
    bgv_verification_dashboard_view,
)

app_name = "background_verification"

urlpatterns = [
    path("", background_verification_view, name="index"),
    path("submission/", bgv_submission_view, name="submission"),
    path("submission/delete/<int:record_id>/", bgv_submission_delete_confirm_view, name="submission_delete_confirm"),
    path("verification-dashboard/", bgv_verification_dashboard_view, name="verification_dashboard"),
    path("report/", bgv_report_view, name="report"),
]
