from datetime import datetime, timezone

from backend.app.db import get_session_factory
from backend.models import AuditLog


def log_fetch(
    *,
    actor: str,
    action: str,
    target_url: str,
    robots_allowed: bool | None,
    response_code: int | None = None,
    notes: str | None = None,
) -> None:
    note_parts: list[str] = []
    if response_code is not None:
        note_parts.append(f"response_code={response_code}")
    if notes is not None:
        note_parts.append(notes)
    record = AuditLog(
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        action=action,
        target_url=target_url,
        robots_allowed=robots_allowed,
        notes=" | ".join(note_parts) if note_parts else None,
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(record)
        session.commit()
