from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from app_settings.models import AssessmentForm, CompanyInfo, UserMaster
from candidate_management.models import Candidate
from super_admin.models import CompanySubscription, Plan


class SubscriptionBillingPageTests(TestCase):
    def test_subscription_billing_page_renders_details(self):
        company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=company,
            plan=plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
            billing_cycle="monthly",
        )
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

        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = "user@example.com"
        session["login_user_name"] = "User"
        session.save()

        resp = self.client.get("/settings/subscription-billing/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Subscription")
        self.assertContains(resp, "Standard")


class AssessmentFillEmptyFormTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
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
        )
        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session.save()

    def test_post_to_empty_form_does_not_error(self):
        form = AssessmentForm.objects.create(name="Empty Form")
        resp = self.client.post(f"/settings/assessment-form/{form.id}/fill/", data={}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Assessment entry saved.")

        table = f"assessment_form_{form.id}"
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            count = cursor.fetchone()[0]
        self.assertEqual(count, 1)


class CompanyInfoCrudTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
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
        )
        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session.save()

    def test_can_edit_company_info(self):
        target = CompanyInfo.objects.create(company_name="Old Name", parent_company=self.company)
        resp = self.client.post(
            "/settings/company/info/",
            data={
                "action": "save",
                "company_id": str(target.id),
                "company_name": "New Name",
                "domain": "example.com",
                "website": "",
                "location": "",
                "strength": "",
                "industry": "",
                "social_link": "",
                "company_description": "",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.company_name, "New Name")
        self.assertEqual(target.domain, "example.com")

    def test_can_delete_company_info(self):
        target = CompanyInfo.objects.create(company_name="To Delete", parent_company=self.company)
        resp = self.client.post(
            "/settings/company/info/",
            data={
                "action": "delete",
                "company_id": str(target.id),
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CompanyInfo.objects.filter(id=target.id).exists())


class DataExportPayloadTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
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
        )
        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session.save()

    def test_payload_export_pdf_handles_short_rows(self):
        resp = self.client.post(
            "/settings/data-export/payload/",
            data={
                "export_format": "pdf",
                "source_path": "/settings/data-export/",
                "table_name": "test_export",
                "columns_json": '["A","B","C"]',
                "rows_json": '[["onlyA"]]',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")


class MastersCityPostTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
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
        )
        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session.save()

    def test_city_master_create_stays_on_masters(self):
        resp = self.client.post(
            "/settings/masters/city/",
            data={"action": "create", "name": "Mumbai", "code": "MUM"},
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/settings/masters/city/", resp["Location"])


class BulkUploadCandidateTests(TestCase):
    def setUp(self):
        self.company = CompanyInfo.objects.create(company_name="Acme", agreement_status="completed", status="active")
        self.plan = Plan.objects.create(name="Standard", duration_days=30, amount=100, billing_cycle="monthly")
        today = timezone.localdate()
        CompanySubscription.objects.create(
            company=self.company,
            plan=self.plan,
            start_date=today,
            end_date=today + timedelta(days=30),
            status="active",
            payment_status="paid",
            amount=100,
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
        )
        session = self.client.session
        session["login_user_role"] = "Admin"
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session.save()

    def test_bulk_upload_candidate_csv_creates_candidate(self):
        csv_payload = (
            "Full Name,Email,Contact Number\n"
            "Bulk User,bulk.user@example.com,9999999999\n"
        ).encode("utf-8")

        upload = SimpleUploadedFile("candidates.csv", csv_payload, content_type="text/csv")

        resp = self.client.post(
            "/settings/bulk-upload/",
            data={
                "entity": "candidate",
                "upsert_mode": "create_only",
                "upload_file": upload,
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/settings/bulk-upload/map/")

        resp = self.client.post(
            "/settings/bulk-upload/map/",
            data={
                "map__0": "full_name",
                "map__1": "email",
                "map__2": "contact_number",
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/settings/bulk-upload/run/")

        resp = self.client.post("/settings/bulk-upload/run/", data={}, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/settings/bulk-upload/")

        self.assertTrue(Candidate.objects.filter(email__iexact="bulk.user@example.com").exists())
