from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0015_candidatejobapplication_resume_scoring"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_skills_required",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_skill_score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_experience_score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_education_score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_text_similarity",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_match_status",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_skills_matched_list",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_skills_missing_list",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_education_required",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="candidatejobapplication",
            name="resume_education_candidate",
            field=models.CharField(blank=True, max_length=60),
        ),
    ]
