from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("candidate_management", "0010_candidateeducation"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidate",
            name="custom_tags",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="CandidateNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.TextField()),
                ("created_by", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "candidate",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="notes", to="candidate_management.candidate"),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
