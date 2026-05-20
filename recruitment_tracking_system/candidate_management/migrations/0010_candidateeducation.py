from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0009_alter_candidate_education_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CandidateEducation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField(default=0)),
                ("level", models.CharField(max_length=60)),
                ("course", models.CharField(blank=True, max_length=180)),
                ("institute", models.CharField(blank=True, max_length=255)),
                ("board_university", models.CharField(blank=True, max_length=255)),
                ("year_of_passing", models.CharField(blank=True, max_length=20)),
                ("score", models.CharField(blank=True, max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "candidate",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="education_records",
                        to="candidate_management.candidate",
                    ),
                ),
            ],
            options={
                "ordering": ["sequence", "id"],
            },
        ),
    ]

