from dataclasses import dataclass

from django.http import JsonResponse
from django.shortcuts import redirect

from app_settings.models import CompanyInfo, UserMaster


def is_platform_superadmin(request) -> bool:
    user = getattr(request, "user", None)
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def is_superadmin_request(request) -> bool:
    # Super Admin module is for platform superusers only (separate from company roles/users).
    return is_platform_superadmin(request)


def superadmin_required(view_func):
    def _wrapped(request, *args, **kwargs):
        if not is_superadmin_request(request):
            if (request.headers.get("Accept") or "").lower().find("application/json") >= 0 or request.path.startswith(
                "/super-admin/api/"
            ):
                return JsonResponse({"success": False, "error": "Super Admin access required."}, status=403)
            return redirect("/dashboard/")
        return view_func(request, *args, **kwargs)

    return _wrapped


@dataclass(frozen=True)
class CurrentContext:
    user: UserMaster | None
    company: CompanyInfo | None
    role_name: str


def current_context_from_request(request) -> CurrentContext:
    role_name = (request.session.get("login_user_role") or "").strip()
    login_email = (request.session.get("login_user_email") or "").strip()
    user = None
    if login_email:
        user = UserMaster.objects.select_related("company").filter(email_id__iexact=login_email).first()
    company = getattr(user, "company", None) if user else None
    if company:
        company = company.get_root_company()
    else:
        company = CompanyInfo.objects.filter(parent_company__isnull=True).order_by("id").first()
    return CurrentContext(user=user, company=company, role_name=role_name)
