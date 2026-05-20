from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0007_candidateevaluation_assessment_feedback_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidatejobapplication",
            name="stage",
            field=models.CharField(default="Applied", max_length=40),
        ),
    ]
