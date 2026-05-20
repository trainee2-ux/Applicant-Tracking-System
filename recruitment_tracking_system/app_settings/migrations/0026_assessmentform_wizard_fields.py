from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0025_taskslaprioritysetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentform",
            name="department",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="difficulty_level",
            field=models.CharField(blank=True, choices=[("Easy", "Easy"), ("Medium", "Medium"), ("Hard", "Hard")], max_length=20),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="time_limit_minutes",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="passing_score_percent",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="instructions",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="shuffle_questions",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="show_score_to_candidate",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="allow_multiple_attempts",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="assessmentform",
            name="is_published",
            field=models.BooleanField(default=False),
        ),
    ]

