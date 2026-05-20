from django.test import TestCase
from django.urls import reverse

from candidate_management.models import Candidate
from onboarding.models import OfferLetter, OnboardingInvitation, OnboardingSubmission


class EmployeeCodeRouteTests(TestCase):
    def test_employee_code_route_accepts_candidate_id(self):
        candidate = Candidate.objects.create(
            full_name="Test Candidate",
            email="test.candidate@example.com",
            contact_number="9999999999",
        )
        invite = OnboardingInvitation.objects.create(candidate=candidate, status="approved")
        submission = OnboardingSubmission.objects.create(invitation=invite, status="approved")

        url = reverse("onboarding:employee_code_assign_by_candidate", kwargs={"candidate_id": candidate.candidate_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("onboarding:employee_code_assign", kwargs={"submission_id": submission.id}),
        )


class DocumentRequestViewTests(TestCase):
    def test_document_request_ajax_returns_onboarding_link(self):
        candidate = Candidate.objects.create(
            full_name="Test Candidate",
            email="test.candidate@example.com",
            contact_number="9999999999",
        )
        offer = OfferLetter.objects.create(candidate=candidate, status="accepted")
        invite = OnboardingInvitation.objects.create(candidate=candidate, offer_letter=offer, status="pending")
        invite.ensure_token()
        invite.save()

        url = reverse("onboarding:request_documents", kwargs={"candidate_id": candidate.candidate_id})
        response = self.client.get(url, {"ajax": "1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn(invite.token, payload.get("onboarding_url", ""))
