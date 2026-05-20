from django.contrib import admin
# pyrefly: ignore [missing-import]
from .models import ProctoringSession, ProctoringViolationLog, ProctoringSnapshot


class ViolationInline(admin.TabularInline):
    model = ProctoringViolationLog
    extra = 0
    readonly_fields = ("violation_type", "timestamp", "meta")
    can_delete = False


class SnapshotInline(admin.TabularInline):
    model = ProctoringSnapshot
    extra = 0
    readonly_fields = ("timestamp", "face_count", "flagged")
    exclude = ("image_data",)
    can_delete = False


@admin.register(ProctoringSession)
class ProctoringSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_token", "candidate_name", "candidate_email",
        "context", "status", "warnings_count", "max_warnings",
        "started_at", "ended_at",
    )
    list_filter = ("status", "context")
    search_fields = ("candidate_name", "candidate_email", "reference_id")
    readonly_fields = (
        "session_token", "started_at", "ended_at",
        "ip_address", "user_agent",
    )
    inlines = [ViolationInline, SnapshotInline]
    ordering = ("-started_at",)


@admin.register(ProctoringViolationLog)
class ProctoringViolationLogAdmin(admin.ModelAdmin):
    list_display = ("session", "violation_type", "timestamp")
    list_filter = ("violation_type",)
    search_fields = ("session__candidate_name", "session__candidate_email")
    readonly_fields = ("session", "violation_type", "timestamp", "meta")


@admin.register(ProctoringSnapshot)
class ProctoringSnapshotAdmin(admin.ModelAdmin):
    list_display = ("session", "face_count", "flagged", "timestamp")
    list_filter = ("flagged",)
    readonly_fields = ("session", "timestamp", "face_count", "flagged")
    exclude = ("image_data",)
