from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0002_onboardingformtemplate_offer_email_template"),
    ]

    operations = [
        migrations.CreateModel(
            name="OnboardingSignatureRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(blank=True, max_length=80, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending Signature"),
                            ("signed", "Signed"),
                            ("final_approved", "Final Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("signature_data", models.TextField(blank=True, help_text="Base64 data URL for the signature image")),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("final_approved_by", models.CharField(blank=True, max_length=150)),
                ("final_approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "submission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="signature_request",
                        to="onboarding.onboardingsubmission",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at"]},
        ),
    ]

