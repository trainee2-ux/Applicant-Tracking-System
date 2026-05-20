from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0026_assessmentform_wizard_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentfield",
            name="points",
            field=models.FloatField(default=1),
        ),
        migrations.AddField(
            model_name="assessmentfield",
            name="correct_answer",
            field=models.TextField(blank=True, help_text="Correct answer value(s). For multiple answers use comma-separated."),
        ),
    ]

