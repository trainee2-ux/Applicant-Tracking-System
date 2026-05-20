from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0004_onboardingsignaturerequest_pdf_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="OnboardingSignDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(default="Document", max_length=150)),
                ("document_pdf", models.FileField(upload_to="onboarding/signatures/")),
                ("signed_pdf", models.FileField(blank=True, upload_to="onboarding/signatures/signed/")),
                ("page_number", models.IntegerField(default=1)),
                ("position_x", models.FloatField(default=70.0, help_text="X position as percentage of page width")),
                ("position_y", models.FloatField(default=80.0, help_text="Y position as percentage of page height")),
                ("width", models.FloatField(default=180.0, help_text="Width in pixels")),
                ("height", models.FloatField(default=70.0, help_text="Height in pixels")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending Signature"), ("signed", "Signed")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "signature_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="onboarding.onboardingsignaturerequest",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at"]},
        ),
    ]

