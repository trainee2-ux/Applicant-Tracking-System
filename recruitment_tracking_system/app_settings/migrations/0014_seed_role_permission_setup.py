# Generated manually on 2026-03-03

from django.db import migrations


ROLE_MATRIX = {
    "Super Admin": {"Candidate DB": "Full", "Job Posting": "Full", "Interview": "Full", "BGV": "Full", "Timesheet": "Full", "Admin": "Full"},
    "Admin": {"Candidate DB": "Full", "Job Posting": "Full", "Interview": "Full", "BGV": "Full", "Timesheet": "Full", "Admin": "Full"},
    "HR Manager": {"Candidate DB": "Full", "Job Posting": "Full", "Interview": "Full", "BGV": "View/Approve", "Timesheet": "Limited", "Admin": "Limited"},
    "Recruiter": {"Candidate DB": "Full", "Job Posting": "Full", "Interview": "Full", "BGV": "View", "Timesheet": "Fill", "Admin": "No"},
    "Team Lead": {"Candidate DB": "Full", "Job Posting": "View", "Interview": "View", "BGV": "View", "Timesheet": "Approve", "Admin": "No"},
    "Interviewer": {"Candidate DB": "Limited", "Job Posting": "No", "Interview": "Assigned only", "BGV": "No", "Timesheet": "No", "Admin": "No"},
    "BGV Verifier": {"Candidate DB": "View", "Job Posting": "No", "Interview": "No", "BGV": "Full", "Timesheet": "No", "Admin": "No"},
    "Hiring Manager": {"Candidate DB": "View", "Job Posting": "Approve", "Interview": "Feedback", "BGV": "View", "Timesheet": "No", "Admin": "No"},
    "Auditor": {"Candidate DB": "Read Only", "Job Posting": "Read Only", "Interview": "Read Only", "BGV": "Read Only", "Timesheet": "Read Only", "Admin": "No"},
    "Candidate": {"Candidate DB": "Self only", "Job Posting": "No", "Interview": "Self only", "BGV": "Self only", "Timesheet": "No", "Admin": "No"},
}


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
    if level in {"view", "read only", "limited", "self only", "assigned only"}:
        return {
            "create_permission": False,
            "view_permission": True,
            "edit_permission": False,
            "delete_permission": False,
            "approve_permission": False,
            "export_permission": level == "read only",
            "download_permission": level == "read only",
            "assign_permission": level == "assigned only",
            "full_access": False,
        }
    if level == "approve":
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
    if level == "view/approve":
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


def seed_permission_setup(apps, schema_editor):
    RolePermissionSetup = apps.get_model("app_settings", "RolePermissionSetup")
    for role_name, module_map in ROLE_MATRIX.items():
        for module_name, access_level in module_map.items():
            payload = _flags(access_level)
            RolePermissionSetup.objects.update_or_create(
                role=role_name,
                module=module_name,
                sub_module="General",
                defaults=payload,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0013_seed_portalroleaccess"),
    ]

    operations = [
        migrations.RunPython(seed_permission_setup, migrations.RunPython.noop),
    ]
