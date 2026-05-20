from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0003_onboardingsignaturerequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="document_pdf",
            field=models.FileField(blank=True, upload_to="onboarding/signatures/"),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="signed_pdf",
            field=models.FileField(blank=True, upload_to="onboarding/signatures/signed/"),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="page_number",
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="position_x",
            field=models.FloatField(default=70.0, help_text="X position as percentage of page width"),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="position_y",
            field=models.FloatField(default=80.0, help_text="Y position as percentage of page height"),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="width",
            field=models.FloatField(default=180.0, help_text="Width in pixels"),
        ),
        migrations.AddField(
            model_name="onboardingsignaturerequest",
            name="height",
            field=models.FloatField(default=70.0, help_text="Height in pixels"),
        ),
    ]

