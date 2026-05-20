from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from app_settings.models import CompanyInfo, UserMaster
from candidate_management.models import Candidate
from super_admin.models import CompanySubscription, Plan

from .models import LoginInterviewSchedule


class LoginInterviewFlowTests(TestCase):
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
            allowed_modules="applicant_tracking",
            created_by="seed",
        )
        self.interviewer = UserMaster.objects.create(
            first_name="Aman",
            last_name="Interviewer",
            email_id="aman@testco.com",
            mobile_number="8888888888",
            password="pass",
            department="Tech",
            role="Interviewer",
            status="Active",
            company=self.company,
            allowed_modules="applicant_tracking",
            created_by="seed",
        )
        self.candidate = Candidate.objects.create(
            full_name="Candidate One",
            email="cand1@testco.com",
            contact_number="7777777777",
            applied_position="Python Developer",
        )

        session = self.client.session
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session["login_user_role"] = "Admin"
        session.save()

    def test_interview_scheduling_page_has_login_card_url(self):
        resp = self.client.get("/applicant-tracking/interview-scheduling/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "/applicant-tracking/interview-scheduling/login/")

    def test_can_create_login_interview(self):
        today = timezone.localdate()
        resp = self.client.post(
            "/applicant-tracking/interview-scheduling/login/?create=1",
            data={
                "candidate_name": self.candidate.candidate_id,
                "posting_title": "Python Developer",
                "interviewer_name": self.interviewer.full_name,
                "interview_process_name": "HR Round",
                "client_name": "",
                "login_url": "https://example.com/login",
                "access_notes": "Use provided creds",
                "date": today.isoformat(),
                "from_time": "10:00",
                "to_time": "10:30",
                "interview_owner": self.user.full_name,
                "schedule_comments": "",
                "assessment_name": "",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(LoginInterviewSchedule.objects.filter(candidate=self.candidate).exists())
