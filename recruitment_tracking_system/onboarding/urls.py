from django.urls import path
from .views import (
    onboarding_board_view,
    onboarding_candidate_view,
    onboarding_dashboard_view,
    onboarding_finalized_board_view,
    onboarding_approvals_view,
    onboarding_employee_code_assign_view,
    onboarding_employee_code_assign_by_candidate_view,
    onboarding_offer_reports_view,
    onboarding_submission_action_view,
    onboarding_submission_detail_view,
    onboarding_offer_create_view,
    onboarding_document_request_view,
    onboarding_signature_block_place_view,
    onboarding_audit_logs_view,
    onboarding_certificate_view,
    onboarding_certificate_regenerate_view,
    onboarding_certificate_download_view,
)

app_name = "onboarding"

urlpatterns = [
    path("", onboarding_dashboard_view, name="dashboard"),
    path("board/", onboarding_board_view, name="board"),
    path("finalized-board/", onboarding_finalized_board_view, name="finalized_board"),
    path("candidates/", onboarding_candidate_view, name="candidates"),
    path("offers/create/<str:candidate_id>/", onboarding_offer_create_view, name="offer_create"),
    path("request-documents/<str:candidate_id>/", onboarding_document_request_view, name="request_documents"),
    path("approvals/", onboarding_approvals_view, name="approvals"),
    path("approvals/<int:submission_id>/", onboarding_submission_detail_view, name="approval_detail"),
    path("approvals/<int:submission_id>/action/", onboarding_submission_action_view, name="approval_action"),
    path("approvals/<int:submission_id>/signature-block/", onboarding_signature_block_place_view, name="signature_block_place"),
    path("employee-code/<int:submission_id>/", onboarding_employee_code_assign_view, name="employee_code_assign"),
    path("employee-code/<str:candidate_id>/", onboarding_employee_code_assign_by_candidate_view, name="employee_code_assign_by_candidate"),
    path("reports/offers/", onboarding_offer_reports_view, name="offer_reports"),
    path("audit-logs/", onboarding_audit_logs_view, name="audit_logs"),
    path("certificate/<int:cert_id>/", onboarding_certificate_view, name="certificate_view"),
    path("certificate/<int:cert_id>/regenerate/", onboarding_certificate_regenerate_view, name="certificate_regenerate"),
    path("certificate/download/<int:cert_id>/", onboarding_certificate_download_view, name="certificate_download"),
]
