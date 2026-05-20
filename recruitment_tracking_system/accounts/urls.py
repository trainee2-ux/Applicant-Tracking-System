from django.urls import path

from .views import (
    subscription_expired_view,
    forgot_password_view,
    global_search_view,
    home_view,
    login_view,
    logout_view,
    my_profile_view,
    sso_callback_view,
    sso_login_view,
)

app_name = "accounts"

urlpatterns = [
    path("", home_view, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("subscription-expired/", subscription_expired_view, name="subscription_expired"),
    path("forgot-password/", forgot_password_view, name="forgot_password"),
    path("sso/login/", sso_login_view, name="sso_login"),
    path("sso/callback/", sso_callback_view, name="sso_callback"),
    path("profile/", my_profile_view, name="my_profile"),
    path("search/", global_search_view, name="global_search"),
]
