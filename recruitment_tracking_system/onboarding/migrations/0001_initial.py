from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("candidate_management", "0016_candidatejobapplication_resume_scoring_details"),
    ]

    operations = [
        migrations.CreateModel(
            name="OnboardingFormTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("selected_fields", models.JSONField(blank=True, default=list)),
                ("document_requirements", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="OfferLetter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(default="Offer Letter", max_length=255)),
                ("body_html", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("sent", "Sent"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("expired", "Expired")], default="draft", max_length=20)),
                ("access_token", models.CharField(blank=True, max_length=80, unique=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("sent_to_email", models.EmailField(blank=True, max_length=254)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("response_note", models.CharField(blank=True, max_length=255)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="offer_letters", to="candidate_management.candidatejobapplication")),
                ("candidate", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="offer_letters", to="candidate_management.candidate")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="OnboardingInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(blank=True, max_length=80, unique=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("registered", "Registered"), ("submitted", "Documents Submitted"), ("approved", "Approved"), ("rejected", "Rejected"), ("expired", "Expired")], default="pending", max_length=20)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("candidate", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="onboarding_invitations", to="candidate_management.candidate")),
                ("form_template", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invitations", to="onboarding.onboardingformtemplate")),
                ("offer_letter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invitations", to="onboarding.offerletter")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="OnboardingSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("form_data", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected")], default="draft", max_length=20)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.CharField(blank=True, max_length=150)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("invitation", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="submission", to="onboarding.onboardinginvitation")),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="OnboardingDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_key", models.CharField(max_length=120)),
                ("file", models.FileField(upload_to="onboarding/documents/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="onboarding.onboardingsubmission")),
            ],
            options={
                "ordering": ["-uploaded_at"],
            },
        ),
        migrations.CreateModel(
            name="EmployeeCodeAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_code", models.CharField(max_length=40, unique=True)),
                ("assigned_by", models.CharField(blank=True, max_length=150)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("candidate", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="employee_assignment", to="candidate_management.candidate")),
                ("submission", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="employee_assignment", to="onboarding.onboardingsubmission")),
            ],
            options={
                "ordering": ["-assigned_at"],
            },
        ),
    ]

