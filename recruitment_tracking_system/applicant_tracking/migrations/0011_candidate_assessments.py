from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0016_candidatejobapplication_resume_scoring_details"),
        ("app_settings", "0025_taskslaprioritysetting"),
        ("applicant_tracking", "0010_logininterviewschedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="CandidateAssessmentAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_by", models.CharField(blank=True, max_length=150)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("token", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("Pending", "Pending"), ("Completed", "Completed"), ("Expired", "Expired")],
                        default="Pending",
                        max_length=20,
                    ),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("source_type", models.CharField(blank=True, help_text="Optional: interview schedule source type", max_length=40)),
                ("source_id", models.PositiveIntegerField(blank=True, help_text="Optional: interview schedule record id", null=True)),
                ("last_opened_at", models.DateTimeField(blank=True, null=True)),
                ("last_opened_ip", models.CharField(blank=True, max_length=64)),
                (
                    "assessment_form",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="candidate_assignments", to="app_settings.assessmentform"),
                ),
                (
                    "candidate",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assessment_assignments", to="candidate_management.candidate"),
                ),
            ],
            options={
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.CreateModel(
            name="CandidateAssessmentSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("answers", models.JSONField(blank=True, default=dict)),
                ("score", models.FloatField(default=0)),
                ("max_score", models.FloatField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assignment",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="submission", to="applicant_tracking.candidateassessmentassignment"),
                ),
            ],
            options={
                "ordering": ["-submitted_at"],
            },
        ),
    ]
