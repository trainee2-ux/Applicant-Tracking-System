from django.db import models
from django.contrib.auth import get_user_model


class DashboardPreference(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, related_name="dashboard_preference")
    default_module = models.CharField(max_length=120, blank=True)
    pinned_widgets = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Dashboard preference: {self.user.username}"
