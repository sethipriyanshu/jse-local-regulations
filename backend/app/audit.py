from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    session: Session, actor: str, action: str, entity: str, entity_id: int | None,
    before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the session; the caller commits with its own change."""
    session.add(AuditLog(actor=actor[:128], action=action, entity=entity, entity_id=entity_id,
                         before=before, after=after))


def actor_for(is_admin: bool, name: str | None) -> str:
    """No login in the MVP (PLAN.md D4): admins are "admin", users give a free-text name."""
    if is_admin:
        return "admin" if not name else f"admin ({name.strip()[:100]})"
    return (name or "").strip()[:128] or "anonymous"
