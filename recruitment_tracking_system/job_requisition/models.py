from django.db import models


class JobRequisition(models.Model):
    job_id = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=180)
    department = models.CharField(max_length=120, blank=True)
    location = models.CharField(max_length=180, blank=True)
    skills_required = models.TextField(blank=True)
    stages = models.TextField(blank=True)
    experience_range = models.CharField(max_length=80, blank=True)
    job_description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    benefits = models.TextField(blank=True)
    hiring_manager = models.CharField(max_length=150, blank=True)
    openings = models.PositiveIntegerField(default=1)
    applications_received = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=40, default="Pending")
    job_opening_status = models.CharField(max_length=20, default="Open")
    date_of_opening = models.DateField(null=True, blank=True)
    target_closure_date = models.DateField(null=True, blank=True)
    public_url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class JobApproval(models.Model):
    job = models.ForeignKey(JobRequisition, on_delete=models.CASCADE, related_name="approvals")
    submitted_by = models.CharField(max_length=150, blank=True)
    approved_by = models.CharField(max_length=150, blank=True)
    approval_status = models.CharField(max_length=40, default="Pending")
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
