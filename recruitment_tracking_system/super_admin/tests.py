from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from app_settings.models import CompanyInfo, UserMaster

from .models import CompanySubscription, Plan


class SuperAdminAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=0, billing_cycle="monthly")

    def _login_session(self, role: str, email: str, name: str = "Test User"):
        session = self.client.session
        session["login_user_role"] = role
        session["login_user_email"] = email
        session["login_user_name"] = name
        session.save()

    def test_superadmin_can_access_super_admin_pages(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username="platform_admin", email="platform@example.com", password="pw")
        self.client.force_login(admin)
        resp = self.client.get("/super-admin/dashboard/")
        self.assertEqual(resp.status_code, 200)

    def test_normal_user_blocked_from_super_admin_pages(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        UserMaster.objects.create(
            first_name="A",
            last_name="User",
            email_id="user@example.com",
            mobile_number="123",
            password="pw",
            department="IT",
            role="Admin",
            allowed_modules="",
            created_by="seed",
            company=company,
        )
        self._login_session("Admin", "user@example.com")
        resp = self.client.get("/super-admin/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/super-admin/login/", resp.headers.get("Location", ""))

    def test_pending_agreement_blocks_company_user(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="pending", status="inactive")
        start = timezone.localdate()
        CompanySubscription.objects.create(
            company=company,
            plan=self.plan,
            start_date=start,
            end_date=start + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=0,
            billing_cycle="monthly",
        )
        UserMaster.objects.create(
            first_name="A",
            last_name="User",
            email_id="user2@example.com",
            mobile_number="123",
            password="pw",
            department="IT",
            role="Admin",
            allowed_modules="",
            created_by="seed",
            company=company,
        )
        self._login_session("Admin", "user2@example.com")
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/super-admin/service-agreement/", resp.headers.get("Location", ""))

    def test_completed_agreement_allows_company_user(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        start = timezone.localdate()
        CompanySubscription.objects.create(
            company=company,
            plan=self.plan,
            start_date=start,
            end_date=start + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=0,
            billing_cycle="monthly",
        )
        UserMaster.objects.create(
            first_name="A",
            last_name="User",
            email_id="user3@example.com",
            mobile_number="123",
            password="pw",
            department="IT",
            role="Admin",
            allowed_modules="",
            created_by="seed",
            company=company,
        )
        self._login_session("Admin", "user3@example.com")
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 200)

    def test_expired_subscription_blocks_company_user(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=company,
            plan=self.plan,
            start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=1),
            status="active",
            payment_status="paid",
            amount=0,
            billing_cycle="monthly",
        )
        UserMaster.objects.create(
            first_name="A",
            last_name="User",
            email_id="user4@example.com",
            mobile_number="123",
            password="pw",
            department="IT",
            role="Admin",
            allowed_modules="",
            created_by="seed",
            company=company,
        )
        self._login_session("Admin", "user4@example.com")
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/subscription-expired/", resp.headers.get("Location", ""))

    def test_superadmin_bypasses_company_expiry(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="expired")
        User = get_user_model()
        admin = User.objects.create_superuser(username="platform_admin2", email="platform2@example.com", password="pw")
        self.client.force_login(admin)
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/super-admin/dashboard/", resp.headers.get("Location", ""))


class PlanBillingCycleTests(TestCase):
    def test_effective_duration_days_monthly_yearly_custom(self):
        from super_admin.models import Plan

        monthly = Plan.objects.create(name="M", billing_cycle="monthly", duration_days=999, amount=0)
        yearly = Plan.objects.create(name="Y", billing_cycle="yearly", duration_days=10, amount=0)
        custom = Plan.objects.create(name="C", billing_cycle="custom", duration_days=45, amount=0)

        self.assertEqual(monthly.effective_duration_days(), 30)
        self.assertEqual(yearly.effective_duration_days(), 365)
        self.assertEqual(custom.effective_duration_days(), 45)


class SubscriptionFlowTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="platform_admin_subs", password="pw", email="x@example.com")
        self.client.force_login(self.admin)

    def test_assign_cancels_previous_active_subscription(self):
        today = timezone.localdate()
        old = CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
            billing_cycle="monthly",
        )

        resp = self.client.post(
            "/super-admin/subscriptions/",
            {"action": "assign", "company_id": self.company.id, "plan_id": self.plan.id, "amount": "100"},
        )
        self.assertEqual(resp.status_code, 302)
        old.refresh_from_db()
        self.assertEqual(old.status, "cancelled")

        latest = CompanySubscription.objects.filter(company=self.company).order_by("-created_at").first()
        self.assertEqual(latest.status, "active")
        self.assertEqual(latest.billing_cycle, "monthly")

    def test_cancel_latest_marks_company_expired(self):
        today = timezone.localdate()
        sub = CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
            billing_cycle="monthly",
        )

        resp = self.client.post("/super-admin/billing/", {"action": "cancel", "subscription_id": sub.id})
        self.assertEqual(resp.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "expired")
