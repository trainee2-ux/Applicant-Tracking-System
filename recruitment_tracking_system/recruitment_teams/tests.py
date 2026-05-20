from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from app_settings.models import CompanyInfo, RoleMaster, UserMaster
from super_admin.models import CompanySubscription, Plan

from .models import RecruitmentTeamMaster


class RecruitmentTeamsRoleDropdownTests(TestCase):
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
            first_name="Test",
            last_name="Admin",
            email_id="admin@testco.com",
            mobile_number="9999999999",
            password="pass",
            department="HR",
            role="Admin",
            status="Active",
            company=self.company,
            allowed_modules="dashboard,settings,recruitment_teams",
            created_by="seed",
        )
        RoleMaster.objects.create(
            role_name="Recruiter",
            role_description="",
            role_level="User",
            status="Active",
            created_by="seed",
        )
        RoleMaster.objects.create(
            role_name="Interviewer",
            role_description="",
            role_level="User",
            status="Active",
            created_by="seed",
        )

        session = self.client.session
        session["login_user_email"] = self.user.email_id
        session["login_user_name"] = self.user.full_name
        session["login_user_role"] = "Admin"
        session.save()

    def test_page_renders_roles_section(self):
        resp = self.client.get("/recruitment-teams/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Roles")
        self.assertContains(resp, "Select Roles")

    def test_post_saves_selected_roles(self):
        resp = self.client.post(
            "/recruitment-teams/",
            data={
                "action": "save_team",
                "team_name": "Team A",
                "team_lead": self.user.full_name,
                "team_members": [self.user.full_name],
                "team_roles": ["Recruiter", "Interviewer"],
                "department": "HR",
                "team_email": "team@testco.com",
                "status": "Active",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        team = RecruitmentTeamMaster.objects.get(team_name="Team A")
        self.assertEqual(team.team_roles, "Recruiter,Interviewer")
