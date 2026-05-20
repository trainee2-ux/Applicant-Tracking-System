from django.db import models


class RecruitmentTeamMaster(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
    ]

    team_id = models.CharField(max_length=20, unique=True, blank=True)
    team_name = models.CharField(max_length=150, unique=True)
    team_lead = models.CharField(max_length=120)
    team_members = models.TextField(help_text="Comma separated users")
    team_roles = models.TextField(blank=True, help_text="Comma separated roles")
    department = models.CharField(max_length=80)
    team_email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active")
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.team_id:
            self.team_id = f"TEAM{self.pk:04d}"
            super().save(update_fields=["team_id"])

    def __str__(self):
        return self.team_name
