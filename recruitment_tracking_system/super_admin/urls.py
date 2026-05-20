from django.urls import path

from .auth_views import superadmin_login_view, superadmin_logout_view
from .views import (
    access_blocked_view,
    billing_view,
    companies_view,
    dashboard_view,
    plans_view,
    service_agreement_view,
    service_agreements_view,
    subscriptions_view,
)

app_name = "super_admin"

urlpatterns = [
    path("login/", superadmin_login_view, name="login"),
    path("logout/", superadmin_logout_view, name="logout"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("companies/", companies_view, name="companies"),
    path("plans/", plans_view, name="plans"),
    path("subscriptions/", subscriptions_view, name="subscriptions"),
    path("billing/", billing_view, name="billing"),
    path("service-agreements/", service_agreements_view, name="service_agreements"),
    path("access-blocked/", access_blocked_view, name="access_blocked"),
    path("service-agreement/", service_agreement_view, name="service_agreement"),
]
