import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, date, time

from django.utils.dateparse import parse_date, parse_time

from django.conf import settings

try:
    from google.oauth2 import service_account
    from google.oauth2 import credentials as oauth2_credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
except Exception:  # pragma: no cover - handled at runtime when deps missing
    service_account = None
    oauth2_credentials = None
    build = None
    Request = None

from app_settings.models import InterviewIntegrationSetting, UserMaster, GoogleOAuthToken

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_BAD_LOCAL_PROXY_RE = re.compile(r"(?i)(?:^|//)(?:localhost|127\\.0\\.0\\.1):9\\b")


def _has_bad_local_proxy_env() -> bool:
    for key in _PROXY_ENV_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value and _BAD_LOCAL_PROXY_RE.search(value):
            return True
    return False


@contextmanager
def _bypass_bad_local_proxy_env():
    """
    Work around environments where a broken local proxy (commonly 127.0.0.1:9)
    is injected via HTTP(S)_PROXY variables, which breaks outbound Google API calls.

    This only clears proxies when we detect the known-bad pattern; corporate proxies
    remain untouched.
    """

    if not _has_bad_local_proxy_env():
        yield
        return

    removed = {}
    for key in _PROXY_ENV_KEYS:
        if key in os.environ:
            removed[key] = os.environ.pop(key)
    try:
        yield
    finally:
        os.environ.update(removed)


@dataclass
class CalendarSyncResult:
    ok: bool
    event_id: str = ""
    error: str = ""
    skipped: bool = False


def _load_calendar_credentials(setting):
    if not setting or not (setting.credential_json or "").strip():
        return None, "Google Calendar credential JSON is empty."
    if service_account is None or oauth2_credentials is None or build is None:
        return None, "Google Calendar dependencies are missing. Install google-auth and google-api-python-client."

    try:
        payload = json.loads(setting.credential_json)
    except Exception as exc:
        return None, f"Invalid credential JSON: {exc}"

    if payload.get("type") == "service_account" or ("client_email" in payload and "private_key" in payload):
        try:
            creds = service_account.Credentials.from_service_account_info(payload, scopes=CALENDAR_SCOPES)
            if setting.organizer_email:
                creds = creds.with_subject(setting.organizer_email)
            return creds, ""
        except Exception as exc:
            return None, f"Service account credential load failed: {exc}"

    if payload.get("refresh_token") and payload.get("client_id") and payload.get("client_secret"):
        try:
            creds = oauth2_credentials.Credentials(
                token=payload.get("token"),
                refresh_token=payload.get("refresh_token"),
                token_uri=payload.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=payload.get("client_id"),
                client_secret=payload.get("client_secret"),
                scopes=CALENDAR_SCOPES,
            )
            return creds, ""
        except Exception as exc:
            return None, f"OAuth credential load failed: {exc}"

    return None, "Credential JSON must include a service account or OAuth refresh_token payload."


def _load_oauth_client_config(setting):
    if not setting or not (setting.credential_json or "").strip():
        return None, "Google OAuth client JSON is empty."
    try:
        payload = json.loads(setting.credential_json)
    except Exception as exc:
        return None, f"Invalid credential JSON: {exc}"

    if "installed" in payload:
        client = payload["installed"]
    elif "web" in payload:
        client = payload["web"]
    else:
        client = payload

    client_id = client.get("client_id")
    client_secret = client.get("client_secret")
    token_uri = client.get("token_uri", "https://oauth2.googleapis.com/token")
    if not client_id or not client_secret:
        return None, "Credential JSON must contain client_id and client_secret."

    return {"client_id": client_id, "client_secret": client_secret, "token_uri": token_uri}, ""


def _resolve_user_email(value):
    if not value:
        return ""
    cleaned = value.strip()
    if "@" in cleaned:
        return cleaned
    user = UserMaster.objects.filter(full_name__iexact=cleaned).first()
    if user and user.email_id:
        return user.email_id
    user = UserMaster.objects.filter(email_id__iexact=cleaned).first()
    if user and user.email_id:
        return user.email_id
    return ""


def _pick_user_token(interview, setting):
    for value in [getattr(interview, "interview_owner", ""), getattr(interview, "interviewer_name", "")]:
        email_value = _resolve_user_email(value)
        if not email_value:
            continue
        user = UserMaster.objects.filter(email_id__iexact=email_value).first()
        if not user:
            continue
        token = GoogleOAuthToken.objects.filter(user=user, provider="google_calendar").first()
        if token:
            return token
    organizer_email = (getattr(setting, "organizer_email", "") or "").strip()
    if organizer_email:
        organizer_user = UserMaster.objects.filter(email_id__iexact=organizer_email).first()
        if organizer_user:
            token = GoogleOAuthToken.objects.filter(user=organizer_user, provider="google_calendar").first()
            if token:
                return token
    return None


def _load_user_credentials(setting, token):
    if oauth2_credentials is None or build is None:
        return None, "Google Calendar dependencies are missing. Install google-auth and google-api-python-client."
    client_cfg, error = _load_oauth_client_config(setting)
    if not client_cfg:
        return None, error

    creds = oauth2_credentials.Credentials(
        token=token.access_token or None,
        refresh_token=token.refresh_token or None,
        token_uri=client_cfg["token_uri"],
        client_id=client_cfg["client_id"],
        client_secret=client_cfg["client_secret"],
        scopes=CALENDAR_SCOPES,
    )
    try:
        if creds.expired and creds.refresh_token:
            with _bypass_bad_local_proxy_env():
                creds.refresh(Request())
            token.access_token = creds.token or token.access_token
            token.expiry = creds.expiry
            token.scopes = " ".join(creds.scopes or []) if creds.scopes else token.scopes
            token.save(update_fields=["access_token", "expiry", "scopes", "updated_at"])
    except Exception as exc:
        return None, f"OAuth refresh failed: {exc}"
    return creds, ""


def _build_event_payload(interview, candidate, meeting_link="", is_video=False):
    tz = getattr(settings, "TIME_ZONE", "UTC")
    interview_date = interview.date
    if isinstance(interview_date, str):
        interview_date = parse_date(interview_date)
    interview_from = interview.from_time
    if isinstance(interview_from, str):
        interview_from = parse_time(interview_from)
    interview_to = interview.to_time
    if isinstance(interview_to, str):
        interview_to = parse_time(interview_to)
    if not isinstance(interview_date, date) or not isinstance(interview_from, time) or not isinstance(interview_to, time):
        raise ValueError("Interview date/time is invalid for calendar sync.")

    start_dt = datetime.combine(interview_date, interview_from)
    end_dt = datetime.combine(interview_date, interview_to)

    summary = f"Interview: {candidate.full_name or candidate.candidate_id} - {interview.posting_title or 'Interview'}"
    description_parts = []
    if interview.interview_process_name:
        description_parts.append(f"Process: {interview.interview_process_name}")
    if interview.interviewer_name:
        description_parts.append(f"Interviewer: {interview.interviewer_name}")
    if interview.schedule_comments:
        description_parts.append(f"Notes: {interview.schedule_comments}")
    if meeting_link:
        description_parts.append(f"Meeting Link: {meeting_link}")
    description = "\n".join(description_parts).strip()

    attendees = []
    candidate_email = (candidate.email or "").strip()
    if candidate_email:
        attendees.append({"email": candidate_email})

    interviewer_email = _resolve_user_email(interview.interviewer_name)
    owner_email = _resolve_user_email(getattr(interview, "interview_owner", ""))
    for email_value in [interviewer_email, owner_email]:
        if email_value and email_value.lower() != candidate_email.lower():
            if email_value.lower() not in {a["email"].lower() for a in attendees}:
                attendees.append({"email": email_value})

    payload = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        "attendees": attendees,
    }
    if not is_video and getattr(interview, "location", ""):
        payload["location"] = interview.location
    return payload


def sync_interview_calendar_event(interview, candidate, meeting_link="", is_video=False):
    setting = InterviewIntegrationSetting.objects.filter(
        provider_key="google_meet",
        is_enabled=True,
    ).first()
    if not setting:
        return CalendarSyncResult(ok=False, skipped=True, error="Google Calendar integration is not enabled.")

    user_token = _pick_user_token(interview, setting)
    if user_token:
        creds, error = _load_user_credentials(setting, user_token)
        calendar_id = "primary"
    else:
        creds, error = _load_calendar_credentials(setting)
        calendar_id = (setting.meeting_url or "").strip() or (setting.organizer_email or "").strip() or "primary"
    if not creds:
        return CalendarSyncResult(ok=False, error=error)
    event_payload = _build_event_payload(interview, candidate, meeting_link=meeting_link, is_video=is_video)

    try:
        with _bypass_bad_local_proxy_env():
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            if interview.calendar_event_id:
                event = (
                    service.events()
                    .update(
                        calendarId=calendar_id,
                        eventId=interview.calendar_event_id,
                        body=event_payload,
                        sendUpdates="all",
                    )
                    .execute()
                )
            else:
                event = (
                    service.events()
                    .insert(
                        calendarId=calendar_id,
                        body=event_payload,
                        sendUpdates="all",
                    )
                    .execute()
                )
        event_id = event.get("id", "")
        return CalendarSyncResult(ok=True, event_id=event_id)
    except Exception as exc:
        logger.exception("Google Calendar sync failed: %s", exc)
        error_text = str(exc)
        if _has_bad_local_proxy_env() and "proxy" in error_text.lower():
            error_text = (
                f"{error_text} (Detected a bad local proxy env like 127.0.0.1:9; "
                "clear HTTP_PROXY/HTTPS_PROXY in the server environment.)"
            )
        return CalendarSyncResult(ok=False, error=error_text)
