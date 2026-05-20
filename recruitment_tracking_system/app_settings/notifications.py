from __future__ import annotations

from typing import Iterable, List

from .models import UiNotification


def _split_names(value: str) -> List[str]:
    parts = []
    for chunk in (value or "").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts


def normalize_recipients(value: Iterable[str] | str) -> List[str]:
    if isinstance(value, str):
        items = _split_names(value)
    else:
        items = []
        for entry in value:
            items.extend(_split_names(str(entry)))
    seen = set()
    result = []
    for name in items:
        key = name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(name.strip())
    return result


def create_notifications(
    recipients: Iterable[str] | str,
    title: str,
    message: str = "",
    link: str = "",
    source: str = "",
    created_by: str = "",
) -> int:
    names = normalize_recipients(recipients)
    if not names or not title:
        return 0
    rows = [
        UiNotification(
            recipient_name=name,
            title=title[:180],
            message=(message or "")[:1000],
            link=(link or "")[:255],
            source=(source or "")[:60],
            created_by=(created_by or "")[:150],
        )
        for name in names
    ]
    UiNotification.objects.bulk_create(rows)
    return len(rows)
