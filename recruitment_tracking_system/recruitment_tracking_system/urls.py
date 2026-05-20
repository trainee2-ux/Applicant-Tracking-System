from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import global_search_view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", global_search_view, name="global_search"),
    path("", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("candidate-management/", include("candidate_management.urls")),
    path("candidate-database/", include("candidate_database.urls")),
    path("job-requisition/", include("job_requisition.urls")),
    path("applicant-tracking/", include("applicant_tracking.urls")),
    path("interview-recording/", include("interview_recording.urls")),
    path("interview-evaluation/", include("interview_evaluation.urls")),
    path("background-verification/", include("background_verification.urls")),
    path("task-management/", include("task_management.urls")),
    path("onboarding/", include("onboarding.urls")),
    path("settings/", include("app_settings.urls")),
    path("recruitment-teams/", include("recruitment_teams.urls")),
    path("candidate-portal/", include("candidate_portal.urls")),
    path("proctoring/", include("proctoring.urls")),
    path("super-admin/", include("super_admin.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
