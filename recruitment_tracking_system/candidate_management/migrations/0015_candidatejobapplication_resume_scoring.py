from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0014_profilephotoversion"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_match_score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_experience_level",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_experience_years",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_skills_matched",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
