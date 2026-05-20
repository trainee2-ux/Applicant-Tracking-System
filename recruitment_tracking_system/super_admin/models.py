from django.db import models
from django.utils import timezone

from app_settings.models import CompanyInfo


class Plan(models.Model):
    BILLING_CYCLE_CHOICES = [
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
        ("custom", "Custom"),
    ]

    name = models.CharField(max_length=120, unique=True)
    duration_days = models.PositiveIntegerField(default=30)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default="monthly")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def effective_duration_days(self) -> int:
        cycle = (self.billing_cycle or "").strip().lower()
        if cycle == "monthly":
            return 30
        if cycle == "yearly":
            return 365
        return int(self.duration_days or 30)


class CompanySubscription(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    company = models.ForeignKey(CompanyInfo, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="pending")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billing_cycle = models.CharField(max_length=20, default="monthly")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-end_date", "-created_at"]

    def __str__(self):
        return f"{self.company.company_name} - {self.plan.name} ({self.status})"

    def mark_expired_if_needed(self, today=None):
        if today is None:
            today = timezone.localdate()
        if self.status == "active" and self.end_date and today > self.end_date:
            self.status = "expired"
            self.save(update_fields=["status"])
            return True
        return False


class BillingEvent(models.Model):
    """
    Simple audit trail for super admin billing actions (payment status updates, extensions, cancellations).
    """

    company = models.ForeignKey(CompanyInfo, on_delete=models.CASCADE, related_name="billing_events")
    subscription = models.ForeignKey(
        CompanySubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billing_events",
    )
    action = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company.company_name}: {self.action}"
