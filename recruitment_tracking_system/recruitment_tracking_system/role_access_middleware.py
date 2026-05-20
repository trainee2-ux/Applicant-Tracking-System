from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.messages.api import MessageFailure

from app_settings.access_control import can_view_module, has_action_permission
from app_settings.models import UserMaster
from task_management.models import TaskRecord


class RoleAccessMiddleware:
    MODULE_BY_PREFIX = [
        ("/dashboard/", "dashboard"),
        ("/candidate-management/", "candidate_management"),
        ("/candidate-database/", "candidate_database"),
        ("/job-requisition/", "job_requisition"),
        ("/applicant-tracking/", "applicant_tracking"),
        ("/interview-recording/", "interview_recording"),
        ("/interview-evaluation/", "interview_evaluation"),
        ("/background-verification/", "background_verification"),
        ("/task-management/", "task_management"),
        ("/onboarding/", "onboarding"),
        ("/settings/", "settings"),
        ("/recruitment-teams/", "recruitment_teams"),
        ("/candidate-portal/", "candidate_portal"),
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/media/") or path.startswith("/admin/"):
            return self.get_response(request)
        if path in {"/", "/login/", "/logout/", "/forgot-password/", "/sso/login/", "/sso/callback/"}:
            return self.get_response(request)

        # Allow unauthenticated candidate links (token-based email flows and public pages)
        # to reach their views so they can establish a Candidate session.
        if path.startswith(
            (
                "/candidate-portal/magic/",
                "/candidate-portal/onboarding/",
                "/candidate-portal/offer/",
                "/candidate-portal/sign/",
                "/candidate-portal/assessment/",
                "/candidate-portal/resume/",
                "/candidate-portal/careers/",
                "/candidate-portal/jobs/",
            )
        ):
            return self.get_response(request)

        login_email = (request.session.get("login_user_email") or "").strip()
        role_name = (request.session.get("login_user_role") or "").strip().lower()
        # Candidate sessions are established via tokenized links and rely on Candidate records,
        # not necessarily a UserMaster row at the time of first access.
        if role_name != "candidate" and login_email and not UserMaster.objects.filter(email_id__iexact=login_email).exists():
            request.session.flush()
            return redirect("/login/")

        module_key = None
        for prefix, module in self.MODULE_BY_PREFIX:
            if path.startswith(prefix):
                module_key = module
                break

        if module_key:
            role_name = request.session.get("login_user_role", "Admin")
            login_user_name = (request.session.get("login_user_name") or "").strip()
            has_task_override = False
            if module_key == "task_management" and login_user_name:
                has_task_override = TaskRecord.objects.filter(
                    owner__iexact=login_user_name,
                ).exclude(status__iexact="Completed").exists()

            if not can_view_module(role_name, module_key) and not has_task_override:
                self._notify(request, "You do not have permission to access this module.")
                fallback = "/candidate-portal/" if str(role_name).strip().lower() == "candidate" else "/dashboard/"
                return redirect(fallback)

            # Enforce action-level permissions for non-GET requests.
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                action_key = self._infer_action(request)
                if not has_action_permission(role_name, module_key, action_key):
                    if module_key == "task_management" and login_user_name and action_key in {"edit", "view"}:
                        task_id = (request.POST.get("task_id") or "").strip()
                        if task_id and TaskRecord.objects.filter(id=task_id, owner__iexact=login_user_name).exists():
                            return self.get_response(request)
                    self._notify(request, f"You do not have permission to {action_key}.")
                    fallback_url = request.META.get("HTTP_REFERER") or request.path or (
                        "/candidate-portal/" if str(role_name).strip().lower() == "candidate" else "/dashboard/"
                    )
                    return redirect(fallback_url)

        return self.get_response(request)

    @staticmethod
    def _infer_action(request):
        action_name = (request.POST.get("action", "") or "").strip().lower()
        if not action_name:
            if request.method == "POST":
                return "view"
            if request.method == "DELETE":
                return "delete"
            if request.method in {"PUT", "PATCH"}:
                return "edit"
            return "view"
        if "export" in action_name:
            return "export"
        if "download" in action_name:
            return "download"
        if "delete" in action_name:
            return "delete"
        if "approve" in action_name:
            return "approve"
        if "update" in action_name or "edit" in action_name or "modify" in action_name:
            return "edit"
        if "create" in action_name or "save" in action_name or "add" in action_name or "submit" in action_name:
            return "create"
        if request.method == "DELETE":
            return "delete"
        if request.method in {"PUT", "PATCH"}:
            return "edit"
        if request.method == "POST":
            return "view"
        return "view"

    @staticmethod
    def _notify(request, message_text):
        try:
            messages.error(request, message_text)
        except MessageFailure:
            request.session["permission_alert"] = message_text
