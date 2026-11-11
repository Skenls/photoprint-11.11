from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from .db import get_db

COOKIE_NAME = "magi_session"
SESSION_TTL = 8 * 3600
READ_ALL_ROLES = {"director", "analyst"}


def _secret() -> str:
    return os.getenv("MAGI_SECRET", "magi-demo-secret-change-me")


def check_password(password: str) -> bool:
    expected = os.getenv("MAGI_PASSWORD", "demo")
    return hmac.compare_digest(password, expected)


def create_session(user_id: int) -> str:
    expires = int(time.time()) + SESSION_TTL
    payload = f"{user_id}.{expires}"
    signature = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session(token: str | None) -> int | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id, expires, signature = parts
    payload = f"{user_id}.{expires}"
    expected = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        if int(expires) < int(time.time()):
            return None
        return int(user_id)
    except ValueError:
        return None


def cookie_kwargs() -> dict:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": os.getenv("MAGI_SECURE_COOKIE", "0") == "1",
        "max_age": SESSION_TTL,
        "path": "/",
    }


async def current_user(request: Request) -> dict:
    user_id = read_session(request.cookies.get(COOKIE_NAME))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Нужно войти в систему")
    with get_db() as conn:
        row = conn.execute("SELECT id, name, email, role, team, title FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    return dict(row)


def require_roles(*roles: str):
    async def check(request: Request) -> dict:
        user = await current_user(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return check


def require_teams(*teams: str):
    """Роль+команда: директор и аналитик всегда допущены; руководитель — только своя команда."""
    async def check(request: Request) -> dict:
        user = await current_user(request)
        if user["role"] in READ_ALL_ROLES:
            return user
        if user["role"] == "head" and user["team"] in teams:
            return user
        raise HTTPException(status_code=403, detail="Раздел закрыт для вашего подразделения")

    return check


def client_scope(user: dict, alias: str = "c") -> tuple[str, list]:
    if user["role"] in READ_ALL_ROLES:
        return "1=1", []
    if user["role"] == "head":
        return f"{alias}.team = ?", [user["team"]]
    return (
        f"({alias}.owner_id = ? OR {alias}.id IN "
        f"(SELECT cv2.client_id FROM conversations cv2 WHERE cv2.assignee_id = ?))",
        [user["id"], user["id"]],
    )


def conversation_scope(user: dict, alias: str = "cv") -> tuple[str, list]:
    if user["role"] in READ_ALL_ROLES:
        return "1=1", []
    if user["role"] == "head":
        return f"{alias}.team = ?", [user["team"]]
    return f"{alias}.assignee_id = ?", [user["id"]]


def can_access_conversation(user: dict, conversation: dict) -> bool:
    if user["role"] in READ_ALL_ROLES:
        return True
    if user["role"] == "head":
        return conversation["team"] == user["team"]
    return conversation["assignee_id"] == user["id"]


def require_client_service():
    """Клиентский сервис: директор/аналитик всегда; руководитель и оператор — только своего отдела."""
    async def check(request: Request) -> dict:
        user = await current_user(request)
        if user["role"] in READ_ALL_ROLES:
            return user
        if user["role"] in ("head", "operator") and user["team"] == "Клиентский сервис":
            return user
        raise HTTPException(status_code=403, detail="Раздел закрыт для вашего подразделения")

    return check


def log_audit(conn, user: dict | None, action: str, entity: str, entity_id=None, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit (user_id, actor, action, entity, entity_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["id"] if user else None, user["name"] if user else "Система", action, entity,
         str(entity_id) if entity_id is not None else None, detail,
         datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")),
    )
