from django.urls import path
# pyrefly: ignore [missing-import]
from . import views

app_name = "proctoring"

urlpatterns = [
    path("start/", views.proctor_start_view, name="start"),
    path("violation/", views.proctor_violation_view, name="violation"),
    path("snapshot/", views.proctor_snapshot_view, name="snapshot"),
    path("complete/", views.proctor_complete_view, name="complete"),
    path("status/<uuid:session_token>/", views.proctor_status_view, name="status"),
    path("dashboard/", views.proctoring_dashboard_view, name="dashboard"),
]

