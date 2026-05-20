from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0007_onboardingauditlog_performed_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardinginvitation",
            name="document_requirements_override",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

