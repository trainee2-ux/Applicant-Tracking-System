from django.db import models
from django.utils import timezone


class AssessmentForm(models.Model):
    FORM_TYPES = [
        ("assessment", "Assessment Form"),
        ("feedback", "Feedback Form"),
    ]

    DIFFICULTY_CHOICES = [
        ("Easy", "Easy"),
        ("Medium", "Medium"),
        ("Hard", "Hard"),
    ]

    name = models.CharField(max_length=120, unique=True)
    form_type = models.CharField(max_length=20, choices=FORM_TYPES, default="assessment")
    description = models.CharField(max_length=255, blank=True)
    department = models.CharField(max_length=120, blank=True)
    difficulty_level = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, blank=True)
    time_limit_minutes = models.PositiveIntegerField(blank=True, null=True)
    passing_score_percent = models.PositiveIntegerField(blank=True, null=True)

    instructions = models.TextField(blank=True)
    shuffle_questions = models.BooleanField(default=False)
    show_score_to_candidate = models.BooleanField(default=True)
    allow_multiple_attempts = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AssessmentField(models.Model):
    FIELD_TYPES = [
        ("text", "Text"),
        ("number", "Number"),
        ("date", "Date"),
        ("email", "Email"),
        ("tel", "Phone"),
        ("url", "URL"),
        ("time", "Time"),
        ("datetime", "Date & Time"),
        ("textarea", "Long Text"),
        ("select", "Dropdown"),
        ("radio", "Radio"),
        ("checkbox", "Checkbox"),
    ]

    form = models.ForeignKey(AssessmentForm, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=120)
    field_name = models.SlugField(max_length=80)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default="text")
    required = models.BooleanField(default=False)
    options = models.TextField(blank=True, help_text="Comma-separated options for dropdown")
    points = models.FloatField(default=1)
    correct_answer = models.TextField(blank=True, help_text="Correct answer value(s). For multiple answers use comma-separated.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("form", "field_name")]
        ordering = ["id"]

    def __str__(self):
        return f"{self.form.name} - {self.label}"


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class State(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class City(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EducationLevel(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=30, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CompanyInfo(models.Model):
    AGREEMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("suspended", "Suspended"),
        ("expired", "Expired"),
    ]

    company_name = models.CharField(max_length=150)
    logo = models.ImageField(upload_to="company/logo/", blank=True, null=True)
    domain = models.CharField(max_length=120, blank=True)
    website = models.CharField(max_length=180, blank=True)
    location = models.CharField(max_length=180, blank=True)
    strength = models.CharField(max_length=80, blank=True)
    industry = models.CharField(max_length=120, blank=True)
    social_link = models.CharField(max_length=255, blank=True)
    company_description = models.TextField(blank=True)
    parent_company = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sub_companies",
    )
    agreement_status = models.CharField(
        max_length=20,
        choices=AGREEMENT_STATUS_CHOICES,
        default="completed",
    )
    service_from = models.DateField(null=True, blank=True)
    service_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.company_name

    def get_root_company(self):
        company = self
        # Guard against accidental cycles by limiting hops.
        for _ in range(20):
            if not company.parent_company_id:
                return company
            company = company.parent_company
        return self

    def mark_expired_if_needed(self, today=None):
        if today is None:
            today = timezone.localdate()
        if self.service_to and today > self.service_to and self.status != "expired":
            self.status = "expired"
            self.save(update_fields=["status"])
            return True
        return False


class RoleMaster(models.Model):
    ROLE_LEVEL_CHOICES = [
        ("Admin", "Admin"),
        ("Manager", "Manager"),
        ("User", "User"),
    ]
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
    ]

    role_id = models.CharField(max_length=20, unique=True, blank=True)
    role_name = models.CharField(max_length=120, unique=True)
    role_description = models.TextField(blank=True)
    role_level = models.CharField(max_length=20, choices=ROLE_LEVEL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active")
    created_by = models.CharField(max_length=120)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.role_id:
            self.role_id = f"ROLE{self.pk:04d}"
            super().save(update_fields=["role_id"])

    def __str__(self):
        return self.role_name


class UserMaster(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
        ("Suspended", "Suspended"),
    ]

    user_id = models.CharField(max_length=20, unique=True, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    full_name = models.CharField(max_length=180, blank=True)
    email_id = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=20)
    username = models.CharField(max_length=80, blank=True)
    password = models.CharField(max_length=255)
    department = models.CharField(max_length=80)
    designation = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=120)
    team = models.CharField(max_length=120, blank=True)
    reporting_manager = models.CharField(max_length=120, blank=True)
    location = models.CharField(max_length=120, blank=True)
    employee_code = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active")
    company = models.ForeignKey(
        CompanyInfo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    date_of_joining = models.DateField(blank=True, null=True)
    profile_photo = models.ImageField(upload_to="users/profile/", blank=True, null=True)
    allowed_modules = models.TextField(help_text="Comma separated modules")
    ip_restriction_enabled = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    created_by = models.CharField(max_length=120)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]

    def save(self, *args, **kwargs):
        self.full_name = f"{self.first_name} {self.last_name}".strip()
        super().save(*args, **kwargs)
        updates = {}
        if not self.user_id:
            updates["user_id"] = f"USR{self.pk:04d}"
        if not self.employee_code:
            updates["employee_code"] = f"EMP{self.pk:04d}"
        if updates:
            for key, value in updates.items():
                setattr(self, key, value)
            super().save(update_fields=list(updates.keys()))

    def __str__(self):
        return self.full_name or self.email_id


class UserMasterAudit(models.Model):
    user = models.ForeignKey(UserMaster, on_delete=models.CASCADE, related_name="audit_logs")
    action = models.CharField(max_length=120)
    details = models.TextField(blank=True)
    changed_by = models.CharField(max_length=120)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.user.user_id} - {self.action}"


class RolePermissionSetup(models.Model):
    role = models.CharField(max_length=120)
    module = models.CharField(max_length=80)
    sub_module = models.CharField(max_length=120)
    create_permission = models.BooleanField(default=False)
    view_permission = models.BooleanField(default=False)
    edit_permission = models.BooleanField(default=False)
    delete_permission = models.BooleanField(default=False)
    approve_permission = models.BooleanField(default=False)
    export_permission = models.BooleanField(default=False)
    download_permission = models.BooleanField(default=False)
    assign_permission = models.BooleanField(default=False)
    full_access = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.role} - {self.module} - {self.sub_module}"


class InterviewIntegrationSetting(models.Model):
    provider_key = models.CharField(max_length=30, unique=True)
    provider_label = models.CharField(max_length=80)
    is_enabled = models.BooleanField(default=False)
    meeting_url = models.CharField(max_length=255, blank=True)
    organizer_email = models.CharField(max_length=150, blank=True)
    credential_json = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider_label"]

    def __str__(self):
        return self.provider_label


class GoogleOAuthToken(models.Model):
    user = models.ForeignKey(UserMaster, on_delete=models.CASCADE, related_name="google_oauth_tokens")
    provider = models.CharField(max_length=40, default="google_calendar")
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_uri = models.CharField(max_length=255, blank=True)
    scopes = models.TextField(blank=True)
    expiry = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "provider")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.full_name or self.user.email_id} ({self.provider})"


class EmailDeliveryConfig(models.Model):
    smtp_enabled = models.BooleanField(default=False)
    host = models.CharField(max_length=150, blank=True)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, blank=True)
    use_tls = models.BooleanField(default=True)
    from_email = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return "Email Delivery Configuration"


class EmailTemplate(models.Model):
    name = models.CharField(max_length=150, unique=True)
    module = models.CharField(max_length=120, blank=True)
    trigger = models.CharField(max_length=120, blank=True)
    to_emails = models.CharField(max_length=255, blank=True)
    cc_emails = models.CharField(max_length=255, blank=True)
    bcc_emails = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class EmailPlaceholder(models.Model):
    key = models.CharField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    example = models.CharField(max_length=180, blank=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key


class UiNotification(models.Model):
    recipient_name = models.CharField(max_length=150)
    title = models.CharField(max_length=180)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=60, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient_name}: {self.title}"


class PortalRoleAccess(models.Model):
    MODULE_CHOICES = [
        ("candidate_db", "Candidate DB"),
        ("job_posting", "Job Posting"),
        ("interview", "Interview"),
        ("bgv", "BGV"),
        ("timesheet", "Timesheet"),
        ("admin", "Admin"),
    ]
    ACCESS_CHOICES = [
        ("no", "No"),
        ("self_only", "Self only"),
        ("assigned_only", "Assigned only"),
        ("view", "View"),
        ("approve", "Approve"),
        ("fill", "Fill"),
        ("feedback", "Feedback"),
        ("limited", "Limited"),
        ("read_only", "Read Only"),
        ("full", "Full"),
    ]

    role_name = models.CharField(max_length=120)
    module_key = models.CharField(max_length=40, choices=MODULE_CHOICES)
    access_level = models.CharField(max_length=40, choices=ACCESS_CHOICES, default="no")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role_name", "module_key"]
        unique_together = [("role_name", "module_key")]

    def __str__(self):
        return f"{self.role_name} - {self.module_key}: {self.access_level}"


class TaskSlaPrioritySetting(models.Model):
    PRIORITY_CHOICES = [
        ("urgent", "Urgent"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, unique=True)
    first_response_hours = models.PositiveSmallIntegerField(default=6)
    resolution_hours = models.PositiveSmallIntegerField(default=20)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"SLA: {self.priority}"


class GlobalAuditLog(models.Model):
    MODULE_CHOICES = [
        ("onboarding", "Onboarding"),
        ("job_requisition", "Job Requisition"),
        ("applicant_tracking", "Applicant Tracking"),
        ("assessment", "Assessment Builder"),
        ("candidate_management", "Candidate Management"),
        ("app_settings", "Settings"),
        ("interview", "Interview Evaluation"),
    ]
    
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    action = models.CharField(max_length=150)
    performed_by = models.ForeignKey(UserMaster, on_delete=models.SET_NULL, null=True, blank=True, related_name="global_audit_entries")
    candidate = models.ForeignKey("candidate_management.Candidate", on_delete=models.CASCADE, null=True, blank=True, related_name="global_audit_logs")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.module} - {self.action} by {self.performed_by}"

