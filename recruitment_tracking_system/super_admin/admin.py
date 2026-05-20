from django.contrib import admin

from .models import BillingEvent, CompanySubscription, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "billing_cycle", "duration_days", "amount", "is_active", "created_at")
    list_filter = ("billing_cycle", "is_active")
    search_fields = ("name",)


@admin.register(CompanySubscription)
class CompanySubscriptionAdmin(admin.ModelAdmin):
    list_display = ("company", "plan", "start_date", "end_date", "status", "payment_status", "amount", "billing_cycle")
    list_filter = ("status", "payment_status", "billing_cycle", "plan")
    search_fields = ("company__company_name", "plan__name")
    autocomplete_fields = ()


@admin.register(BillingEvent)
class BillingEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company", "action", "created_by")
    list_filter = ("action",)
    search_fields = ("company__company_name", "action", "created_by", "notes")

