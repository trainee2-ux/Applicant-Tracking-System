from django.test import TestCase
from django.urls import reverse
from django.conf import settings
from django.test import override_settings

from app_settings.models import UiNotification
from app_settings.models import AssessmentForm
from candidate_management.models import Candidate
from applicant_tracking.models import CandidateAssessmentAssignment, CandidateAssessmentSubmission
from onboarding.models import OnboardingFormTemplate, OnboardingInvitation, OfferLetter


@override_settings(
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]
)
class CandidateOnboardingDocumentsViewTests(TestCase):
    def test_onboarding_documents_shows_document_requirements(self):
        candidate = Candidate.objects.create(
            full_name="Test Candidate",
            email="test.candidate@example.com",
            contact_number="9999999999",
        )
        form_template = OnboardingFormTemplate.objects.create(
            name="Test Form",
            document_requirements=["PAN Card", "Aadhaar Card"],
            is_active=True,
        )
        offer = OfferLetter.objects.create(candidate=candidate, status="accepted")
        invite = OnboardingInvitation.objects.create(candidate=candidate, offer_letter=offer, form_template=form_template, status="registered")
        invite.ensure_token()
        invite.save()

        UiNotification.objects.create(
            recipient_name=candidate.email,
            title="Onboarding Documents Requested",
            message="Please upload your onboarding documents.",
            link="/candidate-portal/",
            source="onboarding",
            created_by="HR",
        )

        session = self.client.session
        session["login_user_email"] = candidate.email
        session["login_user_name"] = candidate.full_name
        session["login_user_role"] = "candidate"
        session.save()

        res = self.client.get(reverse("candidate_portal:onboarding_documents"), follow=True)
        self.assertEqual(res.status_code, 200, msg=f"Unexpected redirect chain: {res.redirect_chain}")
        self.assertContains(res, "Documents Requested")
        self.assertContains(res, "PAN Card")


@override_settings(
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]
)
class CandidatePortalAssessmentHistoryTests(TestCase):
    def test_portal_index_shows_completed_assessment_result(self):
        candidate = Candidate.objects.create(
            full_name="Test Candidate",
            email="test.candidate@example.com",
            contact_number="9999999999",
        )
        form = AssessmentForm.objects.create(
            name="Python Basics",
            form_type="assessment",
            show_score_to_candidate=True,
            is_published=True,
        )
        assignment = CandidateAssessmentAssignment.objects.create(
            candidate=candidate,
            assessment_form=form,
            status="Completed",
        )
        CandidateAssessmentSubmission.objects.create(
            assignment=assignment,
            answers={"q1": "a"},
            score=7,
            max_score=10,
        )

        session = self.client.session
        session["login_user_email"] = candidate.email
        session["login_user_name"] = candidate.full_name
        session["login_user_role"] = "candidate"
        session.save()

        res = self.client.get(reverse("candidate_portal:index"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Assessments")
        self.assertContains(res, "Python Basics")
        self.assertContains(res, "Completed")
        self.assertContains(res, "7")
