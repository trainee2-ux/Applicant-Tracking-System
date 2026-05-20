from django.urls import path

from .views import candidate_database_view

app_name = "candidate_database"

urlpatterns = [
    path("", candidate_database_view, name="index"),
]
