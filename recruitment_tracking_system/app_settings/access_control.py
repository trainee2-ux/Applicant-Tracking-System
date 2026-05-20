from app_settings.models import PortalRoleAccess, RolePermissionSetup


LEGACY_MODULE_KEYS = ["candidate_db", "job_posting", "interview", "bgv", "timesheet", "admin"]

APP_MODULE_KEYS = [
    "dashboard",
    "candidate_management",
    "job_requisition",
    "applicant_tracking",
    "background_verification",
    "interview_recording",
    "interview_evaluation",
    "candidate_portal",
    "recruitment_teams",
    "task_management",
    "candidate_database",
    "onboarding",
    "settings",
]

MODULE_LABEL_BY_KEY = {
    "dashboard": "Dashboard",
    "candidate_management": "Candidate Management",
    "job_requisition": "Requisition Management",
    "applicant_tracking": "Applicant Tracking",
    "background_verification": "Background Verification",
    "interview_recording": "Interview Recording",
    "interview_evaluation": "Interview Evaluation",
    "candidate_portal": "Candidate Portal",
    "recruitment_teams": "Recruitment Teams",
    "task_management": "Task Management",
    "candidate_database": "Candidate Database",
    "onboarding": "Onboarding",
    "settings": "Settings",
}

DEFAULT_ROLE_MATRIX = {
    "Super Admin": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "full", "timesheet": "full", "admin": "full"},
    "Admin": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "full", "timesheet": "full", "admin": "full"},
    "HR Manager": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "approve", "timesheet": "limited", "admin": "limited"},
    "Recruiter": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "view", "timesheet": "fill", "admin": "no"},
    "Team Lead": {"candidate_db": "full", "job_posting": "view", "interview": "view", "bgv": "view", "timesheet": "approve", "admin": "no"},
    "Interviewer": {"candidate_db": "limited", "job_posting": "no", "interview": "assigned_only", "bgv": "no", "timesheet": "no", "admin": "no"},
    "BGV Verifier": {"candidate_db": "view", "job_posting": "no", "interview": "no", "bgv": "full", "timesheet": "no", "admin": "no"},
    "Hiring Manager": {"candidate_db": "view", "job_posting": "approve", "interview": "feedback", "bgv": "view", "timesheet": "no", "admin": "no"},
    "Auditor": {"candidate_db": "read_only", "job_posting": "read_only", "interview": "read_only", "bgv": "read_only", "timesheet": "read_only", "admin": "no"},
    "Candidate": {"candidate_db": "self_only", "job_posting": "no", "interview": "self_only", "bgv": "self_only", "timesheet": "no", "admin": "no"},
}


def role_access_map(role_name):
    role = (role_name or "").strip() or "Admin"
    rows = PortalRoleAccess.objects.filter(role_name__iexact=role)
    if rows.exists():
        data = {key: "no" for key in LEGACY_MODULE_KEYS}
        for row in rows:
            data[row.module_key] = row.access_level
        return data
    return DEFAULT_ROLE_MATRIX.get(role, DEFAULT_ROLE_MATRIX["Admin"]).copy()


def _legacy_level_by_app_module(role_name, module_key):
    normalized_role = (role_name or "").strip().lower()

    # Candidate must be restricted to own portal only.
    if normalized_role == "candidate":
        return "view" if module_key == "candidate_portal" else "no"

    legacy = role_access_map(role_name)
    if module_key in {"candidate_management", "candidate_database"}:
        return legacy.get("candidate_db", "no")
    if module_key == "job_requisition":
        return legacy.get("job_posting", "no")
    if module_key in {"applicant_tracking", "interview_recording", "interview_evaluation"}:
        return legacy.get("interview", "no")
    if module_key == "background_verification":
        return legacy.get("bgv", "no")
    if module_key == "task_management":
        return legacy.get("timesheet", "no")
    if module_key in {"settings", "recruitment_teams"}:
        return legacy.get("admin", "no")
    if module_key == "dashboard":
        return legacy.get("admin", "no")
    if module_key == "onboarding":
        return legacy.get("admin", "no")
    if module_key == "candidate_portal":
        return "view"
    return "no"


def _permission_rows(role_name, module_key):
    role = (role_name or "").strip() or "Admin"
    module_label = MODULE_LABEL_BY_KEY.get(module_key, "")
    if not module_label:
        return RolePermissionSetup.objects.none()
    return RolePermissionSetup.objects.filter(role__iexact=role, module=module_label)


def can_view_module(role_name, module_key):
    normalized_role = (role_name or "").strip().lower()
    if normalized_role == "candidate":
        return module_key == "candidate_portal"

    rows = _permission_rows(role_name, module_key)
    if rows.exists():
        return rows.filter(full_access=True).exists() or rows.filter(view_permission=True).exists() or rows.filter(
            create_permission=True
        ).exists() or rows.filter(edit_permission=True).exists() or rows.filter(delete_permission=True).exists() or rows.filter(
            approve_permission=True
        ).exists() or rows.filter(assign_permission=True).exists()
    return _legacy_level_by_app_module(role_name, module_key) not in {"no"}


def has_action_permission(role_name, module_key, action_key):
    action = (action_key or "view").strip().lower()
    normalized_role = (role_name or "").strip().lower()

    # Hard stop: candidate can only access own candidate portal actions.
    if normalized_role == "candidate":
        if module_key != "candidate_portal":
            return False
        return action in {"view", "create", "edit"}

    rows = _permission_rows(role_name, module_key)
    if rows.exists():
        if rows.filter(full_access=True).exists():
            return True
        field_name = {
            "view": "view_permission",
            "create": "create_permission",
            "edit": "edit_permission",
            "delete": "delete_permission",
            "approve": "approve_permission",
            "export": "export_permission",
            "download": "download_permission",
            "assign": "assign_permission",
        }.get(action, "view_permission")
        return rows.filter(**{field_name: True}).exists()

    legacy = _legacy_level_by_app_module(role_name, module_key)
    if action == "view":
        return legacy not in {"no"}
    if legacy == "full":
        return True
    if action == "approve":
        return legacy in {"approve", "view/approve", "full"}
    if action == "create":
        return legacy in {"fill", "feedback", "full"}
    if action == "edit":
        return legacy in {"fill", "full"}
    if action == "delete":
        return legacy == "full"
    return legacy not in {"no"}


def nav_access_map(role_name):
    return {module_key: can_view_module(role_name, module_key) for module_key in APP_MODULE_KEYS}
