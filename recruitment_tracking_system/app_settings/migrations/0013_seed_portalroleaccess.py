# Generated manually on 2026-03-03

from django.db import migrations


ROLE_MATRIX = {
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


def seed_matrix(apps, schema_editor):
    PortalRoleAccess = apps.get_model("app_settings", "PortalRoleAccess")
    for role_name, module_map in ROLE_MATRIX.items():
        for module_key, access_level in module_map.items():
            PortalRoleAccess.objects.update_or_create(
                role_name=role_name,
                module_key=module_key,
                defaults={"access_level": access_level},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0012_portalroleaccess"),
    ]

    operations = [
        migrations.RunPython(seed_matrix, migrations.RunPython.noop),
    ]
