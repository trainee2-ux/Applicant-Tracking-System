import json
import uuid
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class MeetingServiceError(Exception):
    pass


def _http_json(url, method="GET", headers=None, payload=None, timeout=20):
    body = None
    request_headers = headers or {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)
        raise MeetingServiceError(f"Provider API HTTP {exc.code}: {error_body}")
    except URLError as exc:
        raise MeetingServiceError(f"Provider API network error: {exc.reason}")


def _parse_credentials(setting):
    raw = (setting.credential_json or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeetingServiceError(f"{setting.provider_label}: credential JSON is invalid ({exc}).")
    if isinstance(parsed, dict) and isinstance(parsed.get("web"), dict):
        web_cfg = parsed.get("web", {})
        normalized = {
            "client_id": web_cfg.get("client_id", ""),
            "client_secret": web_cfg.get("client_secret", ""),
            "token_url": web_cfg.get("token_uri", "") or "https://oauth2.googleapis.com/token",
        }
        if parsed.get("refresh_token"):
            normalized["refresh_token"] = parsed.get("refresh_token")
        if parsed.get("access_token"):
            normalized["access_token"] = parsed.get("access_token")
        return normalized
    return parsed


def _save_credentials(setting, credentials):
    setting.credential_json = json.dumps(credentials)
    setting.save(update_fields=["credential_json", "updated_at"])


def _http_form(url, payload, headers=None, timeout=20):
    request_headers = headers or {}
    request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    body = urlencode(payload).encode("utf-8")
    request = Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)
        raise MeetingServiceError(f"Provider token API HTTP {exc.code}: {error_body}")
    except URLError as exc:
        raise MeetingServiceError(f"Provider token API network error: {exc.reason}")


def _resolve_google_access_token(setting, credentials):
    token = (credentials.get("access_token") or "").strip()
    if token:
        return token, credentials, False

    refresh_token = (credentials.get("refresh_token") or "").strip()
    client_id = (credentials.get("client_id") or "").strip()
    client_secret = (credentials.get("client_secret") or "").strip()
    token_url = (credentials.get("token_url") or "https://oauth2.googleapis.com/token").strip()
    if not all([refresh_token, client_id, client_secret]):
        raise MeetingServiceError(
            "Google Meet: provide access_token, or refresh_token + client_id + client_secret in credential JSON."
        )

    token_data = _http_form(
        token_url,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    new_token = (token_data.get("access_token") or "").strip()
    if not new_token:
        raise MeetingServiceError("Google Meet: could not refresh access token.")
    credentials["access_token"] = new_token
    return new_token, credentials, True


def _resolve_teams_access_token(setting, credentials):
    token = (credentials.get("access_token") or "").strip()
    if token:
        return token, credentials, False

    refresh_token = (credentials.get("refresh_token") or "").strip()
    client_id = (credentials.get("client_id") or "").strip()
    client_secret = (credentials.get("client_secret") or "").strip()
    token_url = (credentials.get("token_url") or "").strip()
    scope = (credentials.get("scope") or "https://graph.microsoft.com/.default").strip()
    if not all([refresh_token, client_id, client_secret, token_url]):
        raise MeetingServiceError(
            "Microsoft Teams: provide access_token, or refresh_token + client_id + client_secret + token_url in credential JSON."
        )

    token_data = _http_form(
        token_url,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
    )
    new_token = (token_data.get("access_token") or "").strip()
    if not new_token:
        raise MeetingServiceError("Microsoft Teams: could not refresh access token.")
    credentials["access_token"] = new_token
    if token_data.get("refresh_token"):
        credentials["refresh_token"] = token_data.get("refresh_token")
    return new_token, credentials, True


def _resolve_zoom_access_token(setting, credentials):
    token = (credentials.get("access_token") or "").strip()
    if token:
        return token, credentials, False

    account_id = (credentials.get("account_id") or "").strip()
    client_id = (credentials.get("client_id") or "").strip()
    client_secret = (credentials.get("client_secret") or "").strip()
    token_url = (credentials.get("token_url") or "https://zoom.us/oauth/token").strip()
    if not all([account_id, client_id, client_secret]):
        raise MeetingServiceError(
            "Zoom: provide access_token, or account_id + client_id + client_secret in credential JSON."
        )

    basic = f"{client_id}:{client_secret}".encode("utf-8")
    import base64
    auth_header = base64.b64encode(basic).decode("utf-8")
    token_data = _http_form(
        token_url,
        {"grant_type": "account_credentials", "account_id": account_id},
        headers={"Authorization": f"Basic {auth_header}"},
    )
    new_token = (token_data.get("access_token") or "").strip()
    if not new_token:
        raise MeetingServiceError("Zoom: could not fetch access token.")
    credentials["access_token"] = new_token
    return new_token, credentials, True


def _google_create(setting, title, start_dt, end_dt, attendee_emails):
    creds = _parse_credentials(setting)
    try:
        access_token, updated_creds, updated = _resolve_google_access_token(setting, creds)
        if updated:
            _save_credentials(setting, updated_creds)
    except MeetingServiceError:
        # Fallback mode when only browser URL is available and no token is configured.
        fallback_link = (setting.meeting_url or "").strip()
        if not fallback_link or fallback_link.lower() == "primary":
            fallback_link = "https://meet.new"
        if not fallback_link.lower().startswith(("http://", "https://")):
            fallback_link = f"https://{fallback_link}"
        return {
            "meeting_link": fallback_link,
            "host_link": fallback_link,
            "external_meeting_id": "",
            "provider_payload": {"mode": "google_browser_fallback"},
        }

    calendar_id = (setting.meeting_url or "").strip() or "primary"
    calendar_id_safe = quote(calendar_id, safe="")
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id_safe}/events?conferenceDataVersion=1&sendUpdates=all"
    payload = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
        "attendees": [{"email": email} for email in attendee_emails if email],
        "conferenceData": {
            "createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    data = _http_json(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        payload=payload,
    )
    join_url = (data.get("hangoutLink") or "").strip()
    if not join_url:
        entry_points = (((data.get("conferenceData") or {}).get("entryPoints")) or [])
        video_point = next((point for point in entry_points if point.get("entryPointType") == "video"), {})
        join_url = (video_point.get("uri") or "").strip()
    if not join_url:
        raise MeetingServiceError("Google Meet: API did not return a join URL.")
    return {
        "meeting_link": join_url,
        "host_link": join_url,
        "external_meeting_id": str(data.get("id", "")),
        "provider_payload": data,
    }


def _teams_create(setting, title, start_dt, end_dt, attendee_emails):
    creds = _parse_credentials(setting)
    access_token, updated_creds, updated = _resolve_teams_access_token(setting, creds)
    if updated:
        _save_credentials(setting, updated_creds)

    organizer_user = (setting.meeting_url or setting.organizer_email or "").strip()
    if not organizer_user:
        raise MeetingServiceError("Microsoft Teams: organizer user id/email is required in Meeting Target or Organizer Email/User.")

    organizer_user_safe = quote(organizer_user, safe="")
    url = f"https://graph.microsoft.com/v1.0/users/{organizer_user_safe}/events"
    payload = {
        "subject": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
        "attendees": [
            {"emailAddress": {"address": email}, "type": "required"}
            for email in attendee_emails
            if email
        ],
    }
    data = _http_json(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        payload=payload,
    )
    online_meeting = data.get("onlineMeeting") or {}
    join_url = (online_meeting.get("joinUrl") or data.get("webLink") or "").strip()
    if not join_url:
        raise MeetingServiceError("Microsoft Teams: API did not return a join URL.")
    return {
        "meeting_link": join_url,
        "host_link": join_url,
        "external_meeting_id": str(data.get("id", "")),
        "provider_payload": data,
    }


def _zoom_create(setting, title, start_dt, end_dt):
    creds = _parse_credentials(setting)
    access_token, updated_creds, updated = _resolve_zoom_access_token(setting, creds)
    if updated:
        _save_credentials(setting, updated_creds)

    user_id = (setting.meeting_url or "").strip() or "me"
    user_id_safe = quote(user_id, safe="")
    duration = max(15, int((end_dt - start_dt).total_seconds() // 60))
    url = f"https://api.zoom.us/v2/users/{user_id_safe}/meetings"
    payload = {
        "topic": title,
        "type": 2,
        "start_time": start_dt.isoformat(),
        "duration": duration,
        "timezone": "UTC",
        "settings": {"join_before_host": False},
    }
    data = _http_json(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
        payload=payload,
    )
    join_url = (data.get("join_url") or "").strip()
    if not join_url:
        raise MeetingServiceError("Zoom: API did not return join_url.")
    return {
        "meeting_link": join_url,
        "host_link": (data.get("start_url") or join_url).strip(),
        "external_meeting_id": str(data.get("id", "")),
        "provider_payload": data,
    }


def create_provider_meeting(setting, candidate, posting_title, date_value, from_time_value, to_time_value):
    start_dt = datetime.fromisoformat(f"{date_value}T{from_time_value}")
    end_dt = datetime.fromisoformat(f"{date_value}T{to_time_value}")
    title = f"Interview - {candidate.full_name} - {posting_title or 'ATS'}"
    attendee_emails = [candidate.email]
    if setting.organizer_email:
        attendee_emails.append(setting.organizer_email)

    if setting.provider_key == "google_meet":
        return _google_create(setting, title, start_dt, end_dt, attendee_emails)
    if setting.provider_key == "microsoft_teams":
        return _teams_create(setting, title, start_dt, end_dt, attendee_emails)
    if setting.provider_key == "zoom":
        return _zoom_create(setting, title, start_dt, end_dt)
    raise MeetingServiceError(f"Unsupported provider: {setting.provider_key}")
