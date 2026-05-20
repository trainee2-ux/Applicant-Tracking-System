from django.urls import path

from .views import recruitment_teams_view

app_name = "recruitment_teams"

urlpatterns = [
    path("", recruitment_teams_view, name="index"),
]
