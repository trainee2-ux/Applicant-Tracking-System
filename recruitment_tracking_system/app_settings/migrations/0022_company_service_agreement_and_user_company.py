from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app_settings", "0021_google_oauth_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyinfo",
            name="agreement_status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("completed", "Completed")],
                default="completed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyinfo",
            name="service_from",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companyinfo",
            name="service_to",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companyinfo",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("inactive", "Inactive"),
                    ("suspended", "Suspended"),
                    ("expired", "Expired"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="usermaster",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members",
                to="app_settings.companyinfo",
            ),
        ),
    ]

