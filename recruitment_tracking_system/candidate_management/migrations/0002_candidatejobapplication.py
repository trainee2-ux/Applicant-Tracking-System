# Generated manually for multi-job applications
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_requisition", "0002_jobrequisition_stages"),
        ("candidate_management", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CandidateJobApplication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("applied_on", models.DateTimeField(auto_now_add=True)),
                (
                    "candidate",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="job_applications",
                        to="candidate_management.candidate",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="candidate_applications",
                        to="job_requisition.jobrequisition",
                    ),
                ),
            ],
            options={
                "ordering": ["-applied_on"],
                "unique_together": {("candidate", "job")},
            },
        ),
    ]
