from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.shortcuts import redirect, render


def superadmin_login_view(request):
    """
    Platform Super Admin login using Django's built-in auth user (is_superuser=True).
    This is intentionally separate from company user login (/login/).
    """

    if getattr(request, "user", None) and request.user.is_authenticated and request.user.is_superuser:
        request.session["login_user_role"] = "Super Admin"
        request.session["login_user_name"] = request.user.get_username()
        request.session["login_user_email"] = (getattr(request.user, "email", "") or "").strip()
        return redirect("/super-admin/dashboard/")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()
        user = authenticate(request, username=username, password=password)
        if not user or not user.is_superuser:
            messages.error(request, "Invalid Super Admin credentials.")
            return render(request, "super_admin/login.html", {})

        django_login(request, user)
        request.session["login_user_role"] = "Super Admin"
        request.session["login_user_name"] = user.get_username()
        request.session["login_user_email"] = (getattr(user, "email", "") or "").strip()
        return redirect("/super-admin/dashboard/")

    return render(request, "super_admin/login.html", {})


def superadmin_logout_view(request):
    django_logout(request)
    request.session.flush()
    return redirect("/super-admin/login/")

