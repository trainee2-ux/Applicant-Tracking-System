from django.urls import path

from .views import (
    assessment_result_view,
    interview_evaluation_detail_view,
    interview_evaluation_panel_delete_confirm_view,
    interview_evaluation_panel_view,
    interview_evaluation_submission_delete_confirm_view,
    interview_evaluation_view,
)

app_name = "interview_evaluation"

urlpatterns = [
    path("", interview_evaluation_view, name="index"),
    path("panel/", interview_evaluation_panel_view, name="panel"),
    path("panel/delete/<int:record_id>/", interview_evaluation_panel_delete_confirm_view, name="panel_delete_confirm"),
    path("evaluation/", interview_evaluation_detail_view, name="evaluation"),
    path("assessment-result/", assessment_result_view, name="assessment_result"),
    path("evaluation/delete/<int:record_id>/", interview_evaluation_submission_delete_confirm_view, name="evaluation_delete_confirm"),
]
