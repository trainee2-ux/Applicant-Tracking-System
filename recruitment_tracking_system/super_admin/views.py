from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from app_settings.models import CompanyInfo

from .models import BillingEvent, CompanySubscription, Plan
from .utils import current_context_from_request, is_superadmin_request, superadmin_required


def _as_decimal(raw, default="0"):
    try:
        value = (raw or "").strip()
        if not value:
            return Decimal(default)
        return Decimal(value)
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def _as_int(raw, default=0):
    try:
        return int(str(raw).strip())
    except Exception:
        return default


@superadmin_required
def dashboard_view(request):
    return render(
        request,
        "super_admin/dashboard.html",
        {
            "company_count": CompanyInfo.objects.filter(parent_company__isnull=True).count(),
            "active_companies": CompanyInfo.objects.filter(parent_company__isnull=True, status="active").count(),
            "pending_agreements": CompanyInfo.objects.filter(parent_company__isnull=True, agreement_status="pending").count(),
            "active_subscriptions": CompanySubscription.objects.filter(status="active").count(),
        },
    )


@superadmin_required
def companies_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            company_name = (request.POST.get("company_name") or "").strip()
            if not company_name:
                messages.error(request, "Company name is required.")
                return redirect("super_admin:companies")
            CompanyInfo.objects.create(company_name=company_name, agreement_status="pending", status="inactive")
            messages.success(request, "Company created.")
            return redirect("super_admin:companies")

        company_id = (request.POST.get("company_id") or "").strip()
        company = CompanyInfo.objects.filter(id=company_id).first()
        if not company:
            messages.error(request, "Company not found.")
            return redirect("super_admin:companies")

        if action == "update_status":
            status_value = (request.POST.get("status") or "").strip().lower()
            if status_value not in {"active", "inactive", "suspended", "expired"}:
                messages.error(request, "Invalid status.")
                return redirect("super_admin:companies")
            company.status = status_value
            company.save(update_fields=["status"])
            messages.success(request, "Company status updated.")
            return redirect("super_admin:companies")

        if action == "set_agreement_pending":
            company.agreement_status = "pending"
            company.save(update_fields=["agreement_status"])
            messages.success(request, "Agreement reset to pending.")
            return redirect("super_admin:companies")

    companies = CompanyInfo.objects.filter(parent_company__isnull=True).order_by("company_name")
    return render(request, "super_admin/companies.html", {"companies": companies})


@superadmin_required
def plans_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            name = (request.POST.get("name") or "").strip()
            billing_cycle = (request.POST.get("billing_cycle") or "monthly").strip().lower()
            amount = _as_decimal(request.POST.get("amount"), default="0")
            if not name:
                messages.error(request, "Plan name is required.")
                return redirect("super_admin:plans")
            if billing_cycle not in {"monthly", "yearly", "custom"}:
                billing_cycle = "monthly"
            duration_days = _as_int(request.POST.get("duration_days"), default=30)
            # Enforce standard durations for non-custom cycles.
            if billing_cycle == "monthly":
                duration_days = 30
            elif billing_cycle == "yearly":
                duration_days = 365
            Plan.objects.create(
                name=name,
                duration_days=max(duration_days, 1),
                billing_cycle=billing_cycle,
                amount=amount,
            )
            messages.success(request, "Plan created.")
            return redirect("super_admin:plans")

        if action == "toggle":
            plan_id = (request.POST.get("plan_id") or "").strip()
            plan = Plan.objects.filter(id=plan_id).first()
            if plan:
                plan.is_active = not plan.is_active
                plan.save(update_fields=["is_active"])
                messages.success(request, "Plan updated.")
            return redirect("super_admin:plans")

    return render(request, "super_admin/plans.html", {"plans": Plan.objects.order_by("name")})


@superadmin_required
def subscriptions_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "assign":
            company_id = (request.POST.get("company_id") or "").strip()
            plan_id = (request.POST.get("plan_id") or "").strip()
            company = get_object_or_404(CompanyInfo, id=company_id)
            plan = get_object_or_404(Plan, id=plan_id)
            if not plan.is_active:
                messages.error(request, "This plan is disabled. Enable it before assigning.")
                return redirect("super_admin:subscriptions")

            start_date = timezone.localdate()
            end_date = start_date + timedelta(days=plan.effective_duration_days())
            amount_raw = (request.POST.get("amount") or "").strip()
            amount = _as_decimal(amount_raw, default=str(plan.amount))
            # Billing cycle should match the plan. Allow override only for custom plans.
            billing_cycle = (plan.billing_cycle or "monthly").strip().lower()
            if billing_cycle == "custom":
                billing_cycle = (request.POST.get("billing_cycle") or "custom").strip().lower() or "custom"

            with transaction.atomic():
                # Ensure only one active subscription per company.
                CompanySubscription.objects.filter(company=company, status="active").update(status="cancelled")
                subscription = CompanySubscription.objects.create(
                    company=company,
                    plan=plan,
                    start_date=start_date,
                    end_date=end_date,
                    status="active",
                    payment_status="pending",
                    amount=amount,
                    billing_cycle=billing_cycle,
                )
                BillingEvent.objects.create(
                    company=company,
                    subscription=subscription,
                    action="subscription_assigned",
                    notes=f"Assigned plan {plan.name}",
                    created_by=(request.session.get("login_user_name") or "").strip(),
                )
                if company.agreement_status == "completed":
                    company.service_from = company.service_from or start_date
                    company.service_to = end_date
                    company.status = "active"
                    company.save(update_fields=["service_from", "service_to", "status"])

            messages.success(request, "Subscription assigned.")
            return redirect("super_admin:subscriptions")

    companies = CompanyInfo.objects.filter(parent_company__isnull=True).order_by("company_name")
    plans = Plan.objects.filter(is_active=True).order_by("name")
    subscriptions = CompanySubscription.objects.select_related("company", "plan").order_by("-created_at")[:200]
    return render(
        request,
        "super_admin/subscriptions.html",
        {"companies": companies, "plans": plans, "subscriptions": subscriptions},
    )


@superadmin_required
def billing_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        subscription_id = (request.POST.get("subscription_id") or "").strip()
        subscription = CompanySubscription.objects.select_related("company", "plan").filter(id=subscription_id).first()
        if not subscription:
            messages.error(request, "Subscription not found.")
            return redirect("super_admin:billing")

        actor = (request.session.get("login_user_name") or "").strip()
        if action == "set_payment_status":
            payment_status = (request.POST.get("payment_status") or "").strip().lower()
            if payment_status not in {"pending", "paid", "failed"}:
                messages.error(request, "Invalid payment status.")
                return redirect("super_admin:billing")
            subscription.payment_status = payment_status
            subscription.save(update_fields=["payment_status"])
            BillingEvent.objects.create(
                company=subscription.company,
                subscription=subscription,
                action="payment_status_updated",
                notes=f"Payment status set to {payment_status}",
                created_by=actor,
            )
            messages.success(request, "Payment status updated.")
            return redirect("super_admin:billing")

        if action == "extend":
            extend_days = _as_int(request.POST.get("extend_days"), default=0)
            if extend_days <= 0:
                messages.error(request, "Extension days must be > 0.")
                return redirect("super_admin:billing")
            subscription.end_date = subscription.end_date + timedelta(days=extend_days)
            subscription.status = "active"
            subscription.save(update_fields=["end_date", "status"])
            subscription.company.service_to = subscription.end_date
            subscription.company.status = "active"
            subscription.company.save(update_fields=["service_to", "status"])
            BillingEvent.objects.create(
                company=subscription.company,
                subscription=subscription,
                action="subscription_extended",
                notes=f"Extended by {extend_days} days",
                created_by=actor,
            )
            messages.success(request, "Subscription extended.")
            return redirect("super_admin:billing")

        if action == "cancel":
            subscription.status = "cancelled"
            subscription.save(update_fields=["status"])
            # If this was the latest subscription, mark company as expired to block access.
            latest = (
                CompanySubscription.objects.filter(company=subscription.company)
                .order_by("-end_date", "-created_at")
                .first()
            )
            if latest and latest.id == subscription.id:
                subscription.company.status = "expired"
                subscription.company.service_to = timezone.localdate()
                subscription.company.save(update_fields=["status", "service_to"])
            BillingEvent.objects.create(
                company=subscription.company,
                subscription=subscription,
                action="subscription_cancelled",
                notes="Cancelled by super admin",
                created_by=actor,
            )
            messages.success(request, "Subscription cancelled.")
            return redirect("super_admin:billing")

    subscriptions = CompanySubscription.objects.select_related("company", "plan").order_by("-created_at")[:200]
    events = BillingEvent.objects.select_related("company", "subscription").order_by("-created_at")[:50]
    from interview_recording.models import InterviewRecording

    recordings = InterviewRecording.objects.select_related("candidate").order_by("-created_at")[:20]
    return render(
        request,
        "super_admin/billing.html",
        {"subscriptions": subscriptions, "events": events, "recordings": recordings},
    )


@superadmin_required
def service_agreements_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        company_id = (request.POST.get("company_id") or "").strip()
        company = CompanyInfo.objects.filter(id=company_id).first()
        if not company:
            messages.error(request, "Company not found.")
            return redirect("super_admin:service_agreements")

        if action == "complete":
            today = timezone.localdate()
            subscription = CompanySubscription.objects.filter(company=company).order_by("-end_date", "-created_at").first()
            if not subscription:
                messages.error(request, "Cannot complete agreement: no subscription assigned to this company.")
                return redirect("super_admin:service_agreements")

            company.agreement_status = "completed"
            company.status = "active"
            company.service_from = today
            company.service_to = subscription.end_date
            company.save(update_fields=["agreement_status", "status", "service_from", "service_to"])
            BillingEvent.objects.create(
                company=company,
                subscription=subscription,
                action="service_agreement_completed",
                notes="Agreement completed via Super Admin",
                created_by=(request.session.get("login_user_name") or "").strip(),
            )
            messages.success(request, "Service agreement completed.")
            return redirect("super_admin:service_agreements")

    pending = CompanyInfo.objects.filter(parent_company__isnull=True, agreement_status="pending").order_by("company_name")
    completed = CompanyInfo.objects.filter(parent_company__isnull=True, agreement_status="completed").order_by("company_name")[:200]
    return render(
        request,
        "super_admin/service_agreements.html",
        {"pending_companies": pending, "completed_companies": completed},
    )


def access_blocked_view(request):
    reason = (request.GET.get("reason") or "").strip()
    detail = (request.GET.get("detail") or "").strip()
    return render(request, "super_admin/access_blocked.html", {"reason": reason, "detail": detail})


def service_agreement_view(request):
    if is_superadmin_request(request):
        return redirect("/super-admin/dashboard/")

    ctx = current_context_from_request(request)
    if not ctx.user or not ctx.company:
        messages.error(request, "Please login again.")
        return redirect("/login/")

    if ctx.company.agreement_status == "completed":
        return redirect("/dashboard/")

    subscription = (
        CompanySubscription.objects.filter(company=ctx.company)
        .select_related("plan")
        .order_by("-end_date", "-created_at")
        .first()
    )

    if request.method == "POST":
        if not subscription or subscription.status not in {"active"}:
            messages.error(request, "Service agreement cannot be completed: subscription is missing or inactive.")
            return redirect("super_admin:service_agreement")

        today = timezone.localdate()
        ctx.company.agreement_status = "completed"
        ctx.company.status = "active"
        ctx.company.service_from = today
        ctx.company.service_to = subscription.end_date
        ctx.company.save(update_fields=["agreement_status", "status", "service_from", "service_to"])
        messages.success(request, "Service agreement completed. Welcome!")
        return redirect("/dashboard/")

    return render(
        request,
        "super_admin/service_agreement.html",
        {
            "company": ctx.company,
            "subscription": subscription,
        },
    )
