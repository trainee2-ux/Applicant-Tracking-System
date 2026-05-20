from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from app_settings.models import City, CompanyInfo, UserMaster
from super_admin.models import CompanySubscription, Plan


class JobPostingCityCodeTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.company = CompanyInfo.objects.create(
            company_name="TestCo",
            agreement_status="completed",
            status="active",
            service_from=today,
            service_to=today + timedelta(days=60),
        )
        self.plan = Plan.objects.create(name="Standard", billing_cycle="monthly", duration_days=30, amount=1000)
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=1000,
            billing_cycle="monthly",
        )
        self.user = UserMaster.objects.create(
            first_name="Neha",
            last_name="Sharma",
            email_id="neha@testco.com",
            mobile_number="9999999999",
            password="pass",
            department="HR",
            role="Admin",
            status="Active",
            company=self.company,
            allowed_modules="job_requisition",
            created_by="seed",
        )
        City.objects.create(name="Mumbai", code="400001")
        session = self.client.session
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session["login_user_role"] = "Admin"
        session.save()

    def test_city_options_include_data_code(self):
        resp = self.client.get("/job-requisition/posting-form/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-code="400001"')
