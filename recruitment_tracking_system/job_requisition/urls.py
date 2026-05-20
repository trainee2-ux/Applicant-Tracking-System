from django.urls import path

from .views import (
    job_approval_delete_confirm_view,
    job_delete_confirm_view,
    job_requisition_view,
    job_dashboard_view,
    job_position_dashboard_view,
    job_content_suggestion_view,
    job_posting_form_view,
    job_approval_workflow_view,
    job_approval_form_view,
)

app_name = "job_requisition"

urlpatterns = [
    path("", job_requisition_view, name="index"),
    path("job-position-dashboard/", job_position_dashboard_view, name="job_position_dashboard"),
    path("dashboard/", job_dashboard_view, name="dashboard"),
    path("posting-form/", job_posting_form_view, name="posting_form"),
    path("posting-form/suggest-content/", job_content_suggestion_view, name="suggest_content"),
    path("delete/<str:job_id>/", job_delete_confirm_view, name="delete_confirm"),
    path("job-approval/", job_approval_workflow_view, name="approval_workflow"),
    path("job-approval/delete/<str:job_id>/", job_approval_delete_confirm_view, name="approval_delete_confirm"),
    path("job-approval/form/", job_approval_form_view, name="approval_form"),
]
