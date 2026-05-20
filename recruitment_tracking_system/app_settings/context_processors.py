from django.conf import settings
from app_settings.access_control import has_action_permission, nav_access_map
from app_settings.models import UiNotification
from task_management.models import TaskRecord
from super_admin.models import CompanySubscription
from super_admin.utils import current_context_from_request, is_platform_superadmin, is_superadmin_request


MODULE_BY_PATH_PREFIX = [
    ("/dashboard/", "dashboard"),
    ("/candidate-management/", "candidate_management"),
    ("/candidate-database/", "candidate_database"),
    ("/job-requisition/", "job_requisition"),
    ("/applicant-tracking/", "applicant_tracking"),
    ("/background-verification/", "background_verification"),
    ("/interview-recording/", "interview_recording"),
    ("/interview-evaluation/", "interview_evaluation"),
    ("/task-management/", "task_management"),
    ("/settings/", "settings"),
    ("/recruitment-teams/", "recruitment_teams"),
    ("/candidate-portal/", "candidate_portal"),
]


def _module_from_path(path):
    raw_path = (path or "").strip()
    for prefix, module_key in MODULE_BY_PATH_PREFIX:
        if raw_path.startswith(prefix):
            return module_key
    return ""


def role_access_context(request):
    careers_setting = getattr(settings, "CAREERS_URL", "/careers/") or "/careers/"
    careers_url = (
        careers_setting
        if str(careers_setting).lower().startswith(("http://", "https://"))
        else request.build_absolute_uri(careers_setting)
    )

    if is_platform_superadmin(request):
        # Platform superadmin should not see company ATS navigation or settings.
        return {
            "login_user_role": "Super Admin",
            "is_superadmin": True,
            "company_summary": None,
            "subscription_summary": None,
            "nav_access": {module_key: False for module_key in nav_access_map("Admin").keys()},
            "nav_task_override": False,
            "permission_alert": "",
            "current_module_key": "",
            "module_action_access": {"create": False, "edit": False, "delete": False},
            "ui_notifications": [],
            "ui_notification_unread": 0,
            "CAREERS_URL": careers_url,
        }

    role_name = request.session.get("login_user_role", "Admin")
    login_user_name = request.session.get("login_user_name", "")
    login_user_email = request.session.get("login_user_email", "")
    permission_alert = request.session.pop("permission_alert", "")
    current_module_key = _module_from_path(getattr(request, "path", ""))
    module_action_access = {
        "create": True,
        "edit": True,
        "delete": True,
    }
    if current_module_key:
        module_action_access = {
            "create": has_action_permission(role_name, current_module_key, "create"),
            "edit": has_action_permission(role_name, current_module_key, "edit"),
            "delete": has_action_permission(role_name, current_module_key, "delete"),
        }
    nav_access = nav_access_map(role_name)
    task_override = False
    if not nav_access.get("task_management") and login_user_name:
        task_override = TaskRecord.objects.filter(owner__iexact=login_user_name).exclude(status__iexact="Completed").exists()

    notifications = []
    unread_count = 0
    recipients = [name for name in [login_user_name, login_user_email] if name]
    if recipients:
        from django.db.models import Q

        lookup = Q()
        for entry in recipients:
            lookup |= Q(recipient_name__iexact=entry)
        notifications = list(
            UiNotification.objects.filter(lookup).order_by("-created_at")[:8]
        )
        unread_count = UiNotification.objects.filter(lookup, is_read=False).count()
    ctx = current_context_from_request(request)
    company_summary = None
    subscription_summary = None
    if ctx.company:
        company_summary = {
            "name": ctx.company.company_name,
            "agreement_status": ctx.company.agreement_status,
            "status": ctx.company.status,
            "service_to": ctx.company.service_to,
        }
        subscription = (
            CompanySubscription.objects.filter(company=ctx.company).order_by("-end_date", "-created_at").first()
        )
        if subscription:
            subscription_summary = {
                "end_date": subscription.end_date,
                "status": subscription.status,
                "payment_status": subscription.payment_status,
            }

    return {
        "login_user_role": role_name,
        "is_superadmin": is_superadmin_request(request),
        "company_summary": company_summary,
        "subscription_summary": subscription_summary,
        "nav_access": nav_access,
        "nav_task_override": task_override,
        "permission_alert": permission_alert,
        "current_module_key": current_module_key,
        "module_action_access": module_action_access,
        "ui_notifications": notifications,
        "ui_notification_unread": unread_count,
        "CAREERS_URL": careers_url,
    }
