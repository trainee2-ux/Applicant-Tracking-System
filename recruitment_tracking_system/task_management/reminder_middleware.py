from django.utils.deprecation import MiddlewareMixin

from super_admin.utils import is_platform_superadmin

from .reminder_dispatch import dispatch_due_task_reminders


class TaskReminderMiddleware(MiddlewareMixin):
    """
    Lightweight reminder dispatcher (no celery required).
    On each authenticated request (company users), dispatches any due reminders once per day.
    """

    def process_request(self, request):
        if is_platform_superadmin(request):
            return None
        login_email = (request.session.get("login_user_email") or "").strip()
        if not login_email:
            return None
        # Avoid work on static/media.
        path = (request.path or "").lower()
        if path.startswith("/static/") or path.startswith("/media/"):
            return None
        dispatch_due_task_reminders(limit=10)
        return None

