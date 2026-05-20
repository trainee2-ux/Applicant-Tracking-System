from django.urls import path

from .views import task_management_view, timesheet_report_view

app_name = "task_management"

urlpatterns = [
    path("", task_management_view, name="index"),
    path("timesheet-report/", timesheet_report_view, name="timesheet_report"),
]
