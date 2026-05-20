# Generated manually on 2026-03-03

from django.db import migrations


LEGACY_MATRIX = {
    "Super Admin": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "full", "timesheet": "full", "admin": "full"},
    "Admin": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "full", "timesheet": "full", "admin": "full"},
    "HR Manager": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "view/approve", "timesheet": "limited", "admin": "limited"},
    "Recruiter": {"candidate_db": "full", "job_posting": "full", "interview": "full", "bgv": "view", "timesheet": "fill", "admin": "no"},
    "Team Lead": {"candidate_db": "full", "job_posting": "view", "interview": "view", "bgv": "view", "timesheet": "approve", "admin": "no"},
    "Interviewer": {"candidate_db": "limited", "job_posting": "no", "interview": "assigned_only", "bgv": "no", "timesheet": "no", "admin": "no"},
    "BGV Verifier": {"candidate_db": "view", "job_posting": "no", "interview": "no", "bgv": "full", "timesheet": "no", "admin": "no"},
    "Hiring Manager": {"candidate_db": "view", "job_posting": "approve", "interview": "feedback", "bgv": "view", "timesheet": "no", "admin": "no"},
    "Auditor": {"candidate_db": "read_only", "job_posting": "read_only", "interview": "read_only", "bgv": "read_only", "timesheet": "read_only", "admin": "no"},
    "Candidate": {"candidate_db": "self_only", "job_posting": "no", "interview": "self_only", "bgv": "self_only", "timesheet": "no", "admin": "no"},
}

MODULE_SUBMODULE_MAP = {
    "Dashboard": ["Overview", "Analytics", "Calendar", "Charts"],
    "Candidate Management": ["Registration", "Candidate List", "Profile", "Evaluation"],
    "Requisition Management": ["Job Posting Form", "Position Dashboard", "Approval Workflow", "Public Job URL"],
    "Applicant Tracking": ["Application Pipeline", "Interview Scheduling", "In Person Interview", "Video Interview"],
    "Background Verification": ["Submission", "Verification Dashboard", "Report", "Alerts"],
    "Interview Recording": ["Recording Dashboard", "Panel Dashboard"],
    "Interview Evaluation": ["Interview Panel", "Evaluation", "Aggregates"],
    "Candidate Portal": ["Public Jobs", "Candidate Applications", "Profile"],
    "Recruitment Teams": ["Team Dashboard", "Team Mapping", "Task Assign"],
    "Task Management": ["Task Board", "Task Assignment", "Task Status"],
    "Candidate Database": ["Candidate Records", "Filters", "Export"],
    "Settings": ["Assessment Form", "Masters", "User Master", "Permission Management", "Integration"],
}


def _access_for_module(legacy_access, module_label, role_name):
    if module_label in {"Candidate Management", "Candidate Database"}:
        return legacy_access.get("candidate_db", "no")
    if module_label == "Requisition Management":
        return legacy_access.get("job_posting", "no")
    if module_label in {"Applicant Tracking", "Interview Recording", "Interview Evaluation"}:
        return legacy_access.get("interview", "no")
    if module_label == "Background Verification":
        return legacy_access.get("bgv", "no")
    if module_label == "Task Management":
        return legacy_access.get("timesheet", "no")
    if module_label in {"Settings", "Recruitment Teams"}:
        return legacy_access.get("admin", "no")
    if module_label == "Dashboard":
        return "view"
    if module_label == "Candidate Portal":
        return "self_only" if role_name == "Candidate" else "view"
    return "no"


def _flags(access):
    level = (access or "").strip().lower()
    if level == "full":
        return {
            "create_permission": True,
            "view_permission": True,
            "edit_permission": True,
            "delete_permission": True,
            "approve_permission": True,
            "export_permission": True,
            "download_permission": True,
            "assign_permission": True,
            "full_access": True,
        }
    if level in {"no", ""}:
        return {
            "create_permission": False,
            "view_permission": False,
            "edit_permission": False,
            "delete_permission": False,
            "approve_permission": False,
            "export_permission": False,
            "download_permission": False,
            "assign_permission": False,
            "full_access": False,
        }
    if level in {"view", "read_only", "limited", "self_only", "assigned_only"}:
        return {
            "create_permission": False,
            "view_permission": True,
            "edit_permission": False,
            "delete_permission": False,
            "approve_permission": False,
            "export_permission": level == "read_only",
            "download_permission": level == "read_only",
            "assign_permission": level == "assigned_only",
            "full_access": False,
        }
    if level in {"approve", "view/approve"}:
        return {
            "create_permission": False,
            "view_permission": True,
            "edit_permission": False,
            "delete_permission": False,
            "approve_permission": True,
            "export_permission": False,
            "download_permission": False,
            "assign_permission": False,
            "full_access": False,
        }
    if level == "fill":
        return {
            "create_permission": True,
            "view_permission": True,
            "edit_permission": True,
            "delete_permission": False,
            "approve_permission": False,
            "export_permission": False,
            "download_permission": False,
            "assign_permission": False,
            "full_access": False,
        }
    if level == "feedback":
        return {
            "create_permission": True,
            "view_permission": True,
            "edit_permission": False,
            "delete_permission": False,
            "approve_permission": False,
            "export_permission": False,
            "download_permission": False,
            "assign_permission": False,
            "full_access": False,
        }
    return {
        "create_permission": False,
        "view_permission": True,
        "edit_permission": False,
        "delete_permission": False,
        "approve_permission": False,
        "export_permission": False,
        "download_permission": False,
        "assign_permission": False,
        "full_access": False,
    }


def seed_new_permission_setup(apps, schema_editor):
    RolePermissionSetup = apps.get_model("app_settings", "RolePermissionSetup")
    RolePermissionSetup.objects.all().delete()
    for role_name, legacy_access in LEGACY_MATRIX.items():
        for module_label, submodules in MODULE_SUBMODULE_MAP.items():
            level = _access_for_module(legacy_access, module_label, role_name)
            payload = _flags(level)
            for sub_module in submodules:
                RolePermissionSetup.objects.create(
                    role=role_name,
                    module=module_label,
                    sub_module=sub_module,
                    **payload,
                )


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0014_seed_role_permission_setup"),
    ]

    operations = [
        migrations.RunPython(seed_new_permission_setup, migrations.RunPython.noop),
    ]
