from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app_settings", "0021_google_oauth_token"),
        ("onboarding", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingformtemplate",
            name="offer_email_template",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="onboarding_form_templates",
                to="app_settings.emailtemplate",
            ),
        ),
    ]
