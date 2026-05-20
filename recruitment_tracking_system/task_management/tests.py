from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from app_settings.models import CompanyInfo, UserMaster
from super_admin.models import CompanySubscription, Plan
from task_management.models import TaskRecord
from app_settings.models import UiNotification


class TaskSubmitToManagerTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        plan = Plan.objects.create(name="Standard", duration_days=30, amount=0, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=0,
            billing_cycle="monthly",
        )
        self.user = UserMaster.objects.create(
            first_name="A",
            last_name="User",
            email_id="user@example.com",
            mobile_number="123",
            password="pw",
            department="IT",
            role="Admin",
            allowed_modules="",
            created_by="seed",
            company=self.company,
            reporting_manager="Manager One",
        )
        self.task = TaskRecord.objects.create(
            owner="A User",
            subject="Test Task",
            status="Completed",
            priority="Medium",
            completed_at=timezone.now(),
        )

        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = "A User"
        session.save()

    def test_submit_completed_task_sets_submission_fields(self):
        resp = self.client.post("/task-management/", {"action": "submit_to_manager", "task_id": self.task.id})
        self.assertEqual(resp.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.submission_status, "submitted")
        self.assertEqual(self.task.submitted_to, "Manager One")
        self.assertIsNotNone(self.task.submitted_at)

    def test_repeat_creates_next_task_on_completion_transition(self):
        # Move task back to in progress, then complete via dropdown update to trigger repeat.
        self.task.status = "In Progress"
        self.task.repeat_enabled = True
        self.task.repeat_type = "daily"
        self.task.repeat_start_date = timezone.localdate()
        self.task.save()

        resp = self.client.post(
            "/task-management/",
            {"action": "update_task_dropdown", "task_id": self.task.id, "field_name": "status", "field_value": "Completed"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TaskRecord.objects.count(), 2)
        next_task = TaskRecord.objects.exclude(id=self.task.id).first()
        self.assertEqual(next_task.status, "Open")

    def test_reminder_dispatch_creates_popup_notification(self):
        from task_management.reminder_dispatch import dispatch_due_task_reminders

        self.task.status = "Open"
        self.task.reminder_enabled = True
        self.task.reminder_start_date = timezone.localdate()
        self.task.reminder_type = "daily"
        self.task.reminder_notify_mode = "popup"
        self.task.save()

        sent = dispatch_due_task_reminders(limit=5)
        self.assertGreaterEqual(sent, 1)
        self.assertTrue(UiNotification.objects.filter(title__iexact="Task reminder").exists())
