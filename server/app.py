from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .magi import (
    mask_text,
    masked_client,
    provider_info,
    reply as magi_reply,
    rules_map_from_db,
    summary_for_manager,
)
from .auth import (
    COOKIE_NAME,
    can_access_conversation,
    check_password,
    client_scope,
    conversation_scope,
    cookie_kwargs,
    create_session,
    current_user,
    log_audit,
    require_client_service,
    require_roles,
    require_teams,
)
from .db import get_db

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="Magi CRM", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "MAGI_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHANNELS = ["site", "telegram", "email", "instagram"]
STATUSES = ["new", "qualified", "customer", "sleeping"]
CHANNEL_LABELS = {"site": "Сайт", "telegram": "Telegram", "email": "Почта", "instagram": "Instagram"}
STATUS_LABELS = {"new": "Новый", "qualified": "В работе", "customer": "Клиент", "sleeping": "Спящий"}
DELAY_CAUSE_LABELS = {"delivery": "Доставка", "moderation": "Модерация", "production": "Производство"}
MANAGEMENT_ROLES = ("director", "head", "analyst")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _settings(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    raw = {r["key"]: r["value"] for r in rows}
    return {
        "magi_enabled": raw.get("magi_enabled", "1") == "1",
        "confidence_threshold": float(raw.get("confidence_threshold", "0.55")),
        "auto_channels": [c for c in raw.get("auto_channels", ",".join(CHANNELS)).split(",") if c],
    }


def _rules(conn) -> dict[str, dict]:
    return rules_map_from_db(conn.execute("SELECT key, config, enabled FROM rules").fetchall())


def _topic_name(conn, key: str | None) -> str:
    if not key:
        return "Другое"
    row = conn.execute("SELECT name FROM topics WHERE key = ?", (key,)).fetchone()
    return row["name"] if row else "Другое"


def _conversation(conn, conversation_id: int) -> dict:
    row = conn.execute(
        "SELECT cv.*, c.name AS client_name, c.ltv, c.city, c.phone, c.tags, u.name AS assignee_name "
        "FROM conversations cv JOIN clients c ON c.id = cv.client_id "
        "LEFT JOIN users u ON u.id = cv.assignee_id WHERE cv.id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    return dict(row)


def _client(conn, client_id: int) -> dict:
    row = conn.execute(
        "SELECT c.*, u.name AS owner_name FROM clients c LEFT JOIN users u ON u.id = c.owner_id WHERE c.id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return dict(row)


def _orders(conn, client_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC", (client_id,)
    ).fetchall()]


def _kb(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM kb ORDER BY id").fetchall()]


def _messages(conn, conversation_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC",
        (conversation_id,),
    ).fetchall()]


def _touch(conn, conversation_id: int, when: str) -> None:
    conn.execute("UPDATE conversations SET last_message_at = ? WHERE id = ?", (when, conversation_id))


def _maybe_summary(conn, conversation: dict, client: dict, reason: str) -> str:
    """AI-сводка для менеджера при передаче диалога (сохраняется и показывается в инбоксе)."""
    messages = _messages(conn, conversation["id"])
    text = summary_for_manager(
        {**conversation, "handoff_reason": reason},
        client,
        _orders(conn, client["id"]),
        messages,
        _topic_name(conn, conversation.get("topic")),
    )
    conn.execute("UPDATE conversations SET summary = ? WHERE id = ?", (text, conversation["id"]))
    return text


async def _magi_answer(conn, conversation: dict, client: dict, text: str) -> dict | None:
    settings = _settings(conn)
    if not settings["magi_enabled"] or not conversation["magi_enabled"]:
        return None
    orders = _orders(conn, client["id"])
    history = [
        dict(row)
        for row in conn.execute(
            "SELECT author, body FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 8",
            (conversation["id"],),
        ).fetchall()
    ][::-1]
    if history and history[-1]["body"] == text:
        history.pop()
    result = await magi_reply(
        text=text,
        client=client,
        orders=orders,
        kb=_kb(conn),
        threshold=settings["confidence_threshold"],
        channel=conversation["channel"],
        history=history,
        rules=_rules(conn),
    )
    when = _iso(_now())
    cursor = conn.execute(
        "INSERT INTO messages (conversation_id, author, body, intent, confidence, provider, created_at) "
        "VALUES (?, 'magi', ?, ?, ?, ?, ?)",
        (conversation["id"], result.reply, result.intent, result.confidence, result.provider, when),
    )
    _touch(conn, conversation["id"], when)
    if conversation.get("first_response_at") is None:
        conn.execute("UPDATE conversations SET first_response_at = ? WHERE id = ?", (when, conversation["id"]))
    if result.handoff:
        reason = result.handoff_reason or "Нужна помощь менеджера"
        conn.execute(
            "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting', handoff_reason = ? WHERE id = ?",
            (reason, conversation["id"]),
        )
        _maybe_summary(conn, conversation, client, reason)
        log_audit(conn, {"id": None, "name": "Magi"}, "magi.handoff", "conversation", conversation["id"],
                  f"{conversation['client_name']}: {reason}")
    else:
        conn.execute("UPDATE conversations SET status = 'open' WHERE id = ?", (conversation["id"],))
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


# --------------------------------------------------------------------------- auth

class LoginIn(BaseModel):
    email: str
    password: str


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    author: Literal["lead", "agent"] = "agent"


class HandoffIn(BaseModel):
    reason: str = Field(default="Нужна помощь менеджера", max_length=200)


class NewLeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=120)
    city: str = Field(default="Минск", max_length=80)
    channel: Literal["site", "telegram", "email", "instagram"] = "site"
    message: str = Field(default="Здравствуйте! Хочу узнать о фотокниге.", max_length=1000)


class AgentSettingsIn(BaseModel):
    magi_enabled: bool | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.1, le=0.99)
    auto_channels: list[str] | None = None


@app.post("/api/auth/login")
def login(data: LoginIn, response: Response):
    with get_db() as conn:
        row = conn.execute("SELECT id, name, email, role, team, title FROM users WHERE lower(email) = lower(?)",
                           (data.email.strip(),)).fetchone()
        if row is None or not check_password(data.password):
            raise HTTPException(status_code=401, detail="Неверная почта или пароль")
        user = dict(row)
        log_audit(conn, user, "auth.login", "user", user["id"], None)
    response.set_cookie(value=create_session(user["id"]), **cookie_kwargs())
    return user


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/api/users")
def users(user: dict = Depends(require_roles("director", "head", "analyst"))):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, role, team, title FROM users ORDER BY id"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


# ----------------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    with get_db() as conn:
        client_where, client_params = client_scope(user, "c")
        conv_where, conv_params = conversation_scope(user, "cv")
        cutoff = _iso(_now() - timedelta(days=30))
        day_start = _iso(_now().replace(hour=0, minute=0, second=0))
        day14 = _iso(_now() - timedelta(days=13))
        day14_date = (_now() - timedelta(days=13)).date()

        revenue = conn.execute(
            f"SELECT COALESCE(SUM(o.amount), 0) FROM orders o JOIN clients c ON c.id = o.client_id "
            f"WHERE {client_where} AND o.created_at >= ?", (*client_params, cutoff)
        ).fetchone()[0]
        total_clients, customers = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(c.status = 'customer'), 0) FROM clients c WHERE {client_where}",
            client_params
        ).fetchone()
        new_leads = conn.execute(
            f"SELECT COUNT(*) FROM clients c WHERE {client_where} AND c.created_at >= ?",
            (*client_params, cutoff)
        ).fetchone()[0]
        open_conversations = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where} AND cv.status != 'closed'", conv_params
        ).fetchone()[0]
        total_conversations = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where}", conv_params
        ).fetchone()[0]
        magi_conversations = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where} AND cv.mode = 'magi'", conv_params
        ).fetchone()[0]
        handoffs = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where} AND cv.handoff_reason IS NOT NULL",
            conv_params
        ).fetchone()[0]
        magi_today = conn.execute(
            f"SELECT COUNT(*) FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
            f"WHERE {conv_where} AND m.author = 'magi' AND m.created_at >= ?", (*conv_params, day_start)
        ).fetchone()[0]
        confidence = conn.execute(
            f"SELECT COALESCE(AVG(m.confidence), 0) FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
            f"WHERE {conv_where} AND m.author = 'magi'", conv_params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT m.conversation_id, m.author, m.created_at FROM messages m "
            f"JOIN conversations cv ON cv.id = m.conversation_id WHERE {conv_where} "
            f"ORDER BY m.conversation_id, m.created_at, m.id", conv_params
        ).fetchall()
        first_lead: dict[int, datetime] = {}
        response_times: list[float] = []
        for row in rows:
            cid = row["conversation_id"]
            when = _parse(row["created_at"])
            if row["author"] == "lead" and cid not in first_lead:
                first_lead[cid] = when
            elif row["author"] in ("magi", "agent") and cid in first_lead:
                response_times.append((when - first_lead.pop(cid)).total_seconds() / 60)

        attention_rows = conn.execute(
            f"SELECT cv.*, c.name AS client_name, c.ltv, u.name AS assignee_name, "
            f"(SELECT body FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message, "
            f"(SELECT author FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_author "
            f"FROM conversations cv JOIN clients c ON c.id = cv.client_id "
            f"LEFT JOIN users u ON u.id = cv.assignee_id "
            f"WHERE {conv_where} AND cv.status != 'closed' ORDER BY cv.last_message_at ASC", conv_params
        ).fetchall()
        attention = []
        waiting = 0
        sla = 0
        for row in attention_rows:
            item = dict(row)
            if item["last_author"] == "lead" or item["mode"] == "human":
                waiting += 1
                minutes = max(0, int((_now() - _parse(item["last_message_at"])).total_seconds() // 60))
                if minutes > 60 and (item["last_author"] == "lead" or item["mode"] == "human"):
                    sla += 1
                if len(attention) < 5:
                    attention.append({
                        "id": item["id"], "client_name": item["client_name"], "channel": item["channel"],
                        "reason": item["handoff_reason"] or (item["last_message"] or "")[:90],
                        "minutes": minutes, "mode": item["mode"], "last_author": item["last_author"],
                    })

        series = []
        lead_rows = {r["day"]: r["count"] for r in conn.execute(
            f"SELECT substr(c.created_at, 1, 10) AS day, COUNT(*) AS count FROM clients c "
            f"WHERE {client_where} AND c.created_at >= ? GROUP BY day", (*client_params, day14)
        ).fetchall()}
        rev_rows = {r["day"]: r["total"] for r in conn.execute(
            f"SELECT substr(o.created_at, 1, 10) AS day, SUM(o.amount) AS total FROM orders o "
            f"JOIN clients c ON c.id = o.client_id WHERE {client_where} AND o.created_at >= ? GROUP BY day",
            (*client_params, day14)
        ).fetchall()}
        for i in range(14):
            day = day14_date + timedelta(days=i)
            key = day.isoformat()
            series.append({
                "date": key, "label": day.strftime("%d.%m"),
                "leads": int(lead_rows.get(key, 0)), "revenue": round(float(rev_rows.get(key, 0))),
            })

        channels = [{"channel": r["channel"], "label": CHANNEL_LABELS.get(r["channel"], r["channel"]),
                     "count": r["count"]} for r in conn.execute(
            f"SELECT cv.channel, COUNT(*) AS count FROM conversations cv WHERE {conv_where} GROUP BY cv.channel "
            f"ORDER BY count DESC", conv_params).fetchall()]

        team = []
        if user["role"] in ("director", "analyst"):
            members = conn.execute(
                "SELECT id, name, title, role, team FROM users WHERE role != 'director' ORDER BY role, name"
            ).fetchall()
        elif user["role"] == "head":
            members = conn.execute(
                "SELECT id, name, title, role, team FROM users WHERE team = ? AND role IN ('operator','head') ORDER BY name",
                (user["team"],)
            ).fetchall()
        else:
            members = []
        for member in members:
            open_for_user = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE assignee_id = ? AND status != 'closed'", (member["id"],)
            ).fetchone()[0]
            handoffs_for_user = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE assignee_id = ? AND handoff_reason IS NOT NULL",
                (member["id"],)
            ).fetchone()[0]
            auto_for_user = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE author = 'magi' AND created_at >= ? AND conversation_id IN "
                "(SELECT id FROM conversations WHERE assignee_id = ?)", (day_start, member["id"])
            ).fetchone()[0]
            team.append({
                "id": member["id"], "name": member["name"], "title": member["title"],
                "role": member["role"], "open": open_for_user, "handoffs": handoffs_for_user,
                "auto_replies": auto_for_user,
            })

        settings = _settings(conn)
        info = provider_info()
        return {
            "scope": user["role"],
            "scope_label": "Вся компания" if user["role"] in ("director", "analyst") else (
                user["team"] if user["role"] == "head" else "Мои клиенты"),
            "kpis": {
                "revenue": round(float(revenue)),
                "leads": new_leads,
                "conversion": round(customers / total_clients * 100, 1) if total_clients else 0,
                "open_conversations": open_conversations,
                "waiting": waiting,
                "sla": sla,
                "automation_rate": round(magi_conversations / total_conversations * 100, 1) if total_conversations else 0,
                "avg_confidence": round(float(confidence) * 100, 1),
                "avg_response_min": round(sum(response_times) / len(response_times), 1) if response_times else 0,
                "magi_today": magi_today,
                "handoffs": handoffs,
            },
            "series": series,
            "channels": channels,
            "attention": attention,
            "team": team,
            "magi": {"enabled": settings["magi_enabled"], "threshold": settings["confidence_threshold"],
                     "provider": info["provider"], "model": info["model"]},
        }


# -------------------------------------------------------------------------- leads

@app.get("/api/clients")
def clients(
    search: str = Query(default="", max_length=80),
    status: str = Query(default=""),
    channel: str = Query(default=""),
    user: dict = Depends(current_user),
):
    with get_db() as conn:
        where, params = client_scope(user, "c")
        clauses = [where]
        if search.strip():
            like = f"%{search.strip()}%"
            clauses.append("(c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ? OR c.city LIKE ?)")
            params += [like, like, like, like]
        if status in STATUSES:
            clauses.append("c.status = ?")
            params.append(status)
        if channel in CHANNELS:
            clauses.append("c.channel = ?")
            params.append(channel)
        rows = conn.execute(
            "SELECT c.id, c.name, c.phone, c.email, c.city, c.channel, c.status, c.ltv, c.tags, c.created_at, "
            "u.name AS owner_name, "
            "(SELECT product FROM orders WHERE client_id = c.id ORDER BY created_at DESC LIMIT 1) AS last_product, "
            "(SELECT amount FROM orders WHERE client_id = c.id ORDER BY created_at DESC LIMIT 1) AS last_amount, "
            "(SELECT status FROM orders WHERE client_id = c.id ORDER BY created_at DESC LIMIT 1) AS last_order_status, "
            "(SELECT COUNT(*) FROM conversations cv2 WHERE cv2.client_id = c.id AND cv2.status != 'closed') AS open_conversations "
            "FROM clients c LEFT JOIN users u ON u.id = c.owner_id WHERE " + " AND ".join(clauses) +
            " ORDER BY c.created_at DESC LIMIT 300", params
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": len(rows)}


@app.post("/api/leads")
async def create_lead(data: NewLeadIn, user: dict = Depends(current_user)):
    now = _iso(_now())
    with get_db() as conn:
        if user["role"] == "operator":
            owner_id, team = user["id"], user["team"]
        else:
            manager = conn.execute("SELECT id, team FROM users WHERE role = 'operator' ORDER BY id LIMIT 1").fetchone()
            if manager is None:
                raise HTTPException(status_code=500, detail="Нет доступного менеджера")
            owner_id, team = manager["id"], manager["team"]
        cursor = conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'magi', 'new', 0, 1, ?, ?, '', '', ?)",
            (data.name.strip(), data.phone.strip(), data.email.strip(), data.city.strip(), data.channel,
             owner_id, team, now),
        )
        client_id = cursor.lastrowid
        conv_cursor = conn.execute(
            "INSERT INTO conversations (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled, "
            "handoff_reason, sla_due_at, last_message_at, created_at) "
            "VALUES (?, ?, 'Новый лид', 'greeting', 'open', 'magi', ?, ?, 1, NULL, ?, ?, ?)",
            (client_id, data.channel, owner_id, team, _iso(_now() + timedelta(hours=1)), now, now),
        )
        conversation_id = conv_cursor.lastrowid
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, 'lead', ?, ?)",
            (conversation_id, data.message.strip(), now),
        )
        conversation = _conversation(conn, conversation_id)
        client = _client(conn, client_id)
        if data.message.strip():
            await _magi_answer(conn, conversation, client, data.message.strip())
        log_audit(conn, user, "lead.created", "client", client_id, f"{data.name} · {data.channel}")
        return {"client_id": client_id, "conversation_id": conversation_id}


@app.get("/api/clients/{client_id}")
def client_detail(client_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        where, params = client_scope(user, "c")
        allowed = conn.execute(
            f"SELECT 1 FROM clients c WHERE c.id = ? AND {where}", [client_id, *params]
        ).fetchone()
        if not allowed:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        client = _client(conn, client_id)
        orders = _orders(conn, client_id)
        conv_where, conv_params = conversation_scope(user, "cv")
        conversations = [dict(r) for r in conn.execute(
            f"SELECT cv.*, u.name AS assignee_name FROM conversations cv LEFT JOIN users u ON u.id = cv.assignee_id "
            f"WHERE cv.client_id = ? AND {conv_where} ORDER BY cv.last_message_at DESC",
            (client_id, *conv_params)
        ).fetchall()]
        task_where = "" if user["role"] in MANAGEMENT_ROLES else " AND assignee_id = ?"
        task_params = (client_id,) if not task_where else (client_id, user["id"])
        tasks = [dict(r) for r in conn.execute(
            "SELECT t.*, u.name AS assignee_name FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id "
            "WHERE t.client_id = ?" + task_where + " ORDER BY t.status, t.due_at", task_params
        ).fetchall()]
        return {"client": client, "orders": orders, "conversations": conversations, "tasks": tasks}


# -------------------------------------------------------------------- conversations

@app.get("/api/conversations")
def conversations(
    channel: str = Query(default=""),
    status: str = Query(default=""),
    q: str = Query(default="", max_length=80),
    user: dict = Depends(current_user),
):
    with get_db() as conn:
        where, params = conversation_scope(user, "cv")
        clauses = [where]
        if channel in CHANNELS:
            clauses.append("cv.channel = ?")
            params.append(channel)
        if status in ("open", "waiting", "closed"):
            clauses.append("cv.status = ?")
            params.append(status)
        if q.strip():
            like = f"%{q.strip()}%"
            clauses.append("(c.name LIKE ? OR cv.subject LIKE ?)")
            params += [like, like]
        rows = conn.execute(
            "SELECT cv.*, t.name AS topic_name, c.name AS client_name, c.ltv, c.city, u.name AS assignee_name, "
            "(SELECT body FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message, "
            "(SELECT author FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_author "
            "FROM conversations cv JOIN clients c ON c.id = cv.client_id "
            "LEFT JOIN topics t ON t.key = cv.topic "
            "LEFT JOIN users u ON u.id = cv.assignee_id WHERE " + " AND ".join(clauses) +
            " ORDER BY cv.last_message_at DESC LIMIT 200", params
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@app.get("/api/conversations/{conversation_id}")
def conversation_detail(conversation_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        conversation["topic_name"] = _topic_name(conn, conversation.get("topic"))
        return {
            "conversation": conversation,
            "client": _client(conn, conversation["client_id"]),
            "orders": _orders(conn, conversation["client_id"]),
            "messages": _messages(conn, conversation_id),
        }


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, data: MessageIn, user: dict = Depends(current_user)):
    body = data.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Пустое сообщение")
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        when = _iso(_now())
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, data.author, body, when),
        )
        _touch(conn, conversation_id, when)
        magi_message = None
        if data.author == "agent":
            conn.execute(
                "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'open' WHERE id = ?",
                (conversation_id,),
            )
            if conversation.get("first_response_at") is None:
                conn.execute("UPDATE conversations SET first_response_at = ? WHERE id = ?", (when, conversation_id))
        else:
            refreshed = _conversation(conn, conversation_id)
            client = _client(conn, conversation["client_id"])
            magi_message = await _magi_answer(conn, refreshed, client, body)
            if magi_message is None:
                conn.execute(
                    "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting' WHERE id = ?",
                    (conversation_id,),
                )
                _maybe_summary(conn, refreshed, client, "Magi выключен или канал вне автоответа")
        conversation = _conversation(conn, conversation_id)
        return {"conversation": conversation, "magi_message": magi_message,
                "messages": _messages(conn, conversation_id)}


@app.post("/api/conversations/{conversation_id}/handoff")
def handoff(conversation_id: int, data: HandoffIn, user: dict = Depends(current_user)):
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        reason = data.reason.strip() or "Нужна помощь менеджера"
        conn.execute(
            "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting', "
            "assignee_id = ?, handoff_reason = ? WHERE id = ?",
            (user["id"], reason, conversation_id),
        )
        client = _client(conn, conversation["client_id"])
        summary = _maybe_summary(conn, conversation, client, reason)
        log_audit(conn, user, "conversation.handoff", "conversation", conversation_id,
                  f"{conversation['client_name']}: {reason}")
        return {**_conversation(conn, conversation_id), "summary": summary}


@app.post("/api/conversations/{conversation_id}/resume")
def resume_magi(conversation_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        conn.execute(
            "UPDATE conversations SET mode = 'magi', magi_enabled = 1, status = 'open', handoff_reason = NULL, summary = NULL WHERE id = ?",
            (conversation_id,),
        )
        log_audit(conn, user, "conversation.resume_magi", "conversation", conversation_id,
                  conversation["client_name"])
        return _conversation(conn, conversation_id)


# -------------------------------------------------------------------------- templates

@app.get("/api/templates")
def templates(topic: str = Query(default="", max_length=40), user: dict = Depends(current_user)):
    with get_db() as conn:
        if topic:
            rows = conn.execute("SELECT * FROM templates WHERE topic = ? ORDER BY id", (topic,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM templates ORDER BY topic, id").fetchall()
        return {"items": [dict(r) for r in rows]}


# -------------------------------------------------------------------------- pickups

@app.get("/api/pickups")
def pickups(user: dict = Depends(require_client_service())):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT p.*, o.product, o.amount, o.status AS order_status, c.name AS client_name, c.id AS client_id "
            "FROM pickups p JOIN orders o ON o.id = p.order_id JOIN clients c ON c.id = o.client_id "
            "ORDER BY p.expires_at ASC LIMIT 50"
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            hours_left = (_parse(item["expires_at"]) - _now()).total_seconds() / 3600
            item["hours_left"] = round(hours_left, 1)
            items.append(item)
        return {"items": items}


@app.post("/api/pickups/{pickup_id}/remind")
def remind_pickup(pickup_id: int, user: dict = Depends(require_client_service())):
    with get_db() as conn:
        row = conn.execute(
            "SELECT p.*, o.client_id, o.product FROM pickups p JOIN orders o ON o.id = p.order_id WHERE p.id = ?",
            (pickup_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Пункт выдачи не найден")
        item = dict(row)
        conversation = conn.execute(
            "SELECT * FROM conversations WHERE client_id = ? AND status != 'closed' ORDER BY last_message_at DESC LIMIT 1",
            (item["client_id"],),
        ).fetchone()
        body = (f"Напоминаем: заказ «{item['product']}» ждёт вас в ПВЗ «{item['location']}» до "
                f"{_parse(item['expires_at']).strftime('%d.%m')}. После этого срока отправим обратно на склад.")
        if conversation is None:
            raise HTTPException(status_code=409, detail="Нет открытого диалога с клиентом")
        when = _iso(_now())
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, provider, created_at) VALUES (?, 'magi', ?, 'local', ?)",
            (conversation["id"], body, when),
        )
        conn.execute(
            "UPDATE pickups SET reminded = reminded + 1, reminded_at = ? WHERE id = ?",
            (when, pickup_id),
        )
        log_audit(conn, user, "pickup.remind", "pickup", pickup_id, item["location"])
        return {"ok": True, "message": body}


# ---------------------------------------------------------------------------- agent

def _agent_payload(user: dict) -> dict:
    with get_db() as conn:
        settings = _settings(conn)
        conv_where, conv_params = conversation_scope(user, "cv")
        total = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where}", conv_params
        ).fetchone()[0]
        magi = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where} AND cv.mode = 'magi'", conv_params
        ).fetchone()[0]
        handoffs = conn.execute(
            f"SELECT COUNT(*) FROM conversations cv WHERE {conv_where} AND cv.handoff_reason IS NOT NULL", conv_params
        ).fetchone()[0]
        today = _iso(_now().replace(hour=0, minute=0, second=0))
        magi_today = conn.execute(
            f"SELECT COUNT(*) FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
            f"WHERE {conv_where} AND m.author = 'magi' AND m.created_at >= ?", (*conv_params, today)
        ).fetchone()[0]
        confidence = conn.execute(
            f"SELECT COALESCE(AVG(m.confidence), 0) FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
            f"WHERE {conv_where} AND m.author = 'magi'", conv_params
        ).fetchone()[0]
        intents = [dict(r) for r in conn.execute(
            f"SELECT m.intent, COUNT(*) AS count FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
            f"WHERE {conv_where} AND m.author = 'magi' AND m.intent IS NOT NULL "
            f"GROUP BY m.intent ORDER BY count DESC", conv_params
        ).fetchall()]
        kb = _kb(conn)
        info = provider_info()
        masked_example = masked_client({"name": "Мария Ковалёва", "phone": "+375 29 145-22-08",
                                        "email": "maria.kovaleva@example.by", "notes": "Сын Миша"})
        return {
            "settings": settings,
            "metrics": {
                "automation_rate": round(magi / total * 100, 1) if total else 0,
                "avg_confidence": round(float(confidence) * 100, 1),
                "handoffs": handoffs,
                "magi_today": magi_today,
                "total_conversations": total,
            },
            "intents": intents,
            "kb": kb,
            "provider": info,
            "pii_mask_example": masked_example,
            "can_edit": user["role"] in ("director", "head"),
        }


@app.get("/api/agent")
def agent_settings(user: dict = Depends(current_user)):
    return _agent_payload(user)


@app.patch("/api/agent")
def update_agent(data: AgentSettingsIn, user: dict = Depends(require_roles("director"))):
    with get_db() as conn:
        if data.magi_enabled is not None:
            conn.execute("INSERT INTO settings (key, value) VALUES ('magi_enabled', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         ("1" if data.magi_enabled else "0",))
        if data.confidence_threshold is not None:
            conn.execute("INSERT INTO settings (key, value) VALUES ('confidence_threshold', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (str(round(data.confidence_threshold, 2)),))
            conn.execute("UPDATE rules SET config = ? WHERE key = 'threshold.confidence'",
                         (json.dumps({"value": round(data.confidence_threshold, 2)}),))
        if data.auto_channels is not None:
            channels = [c for c in data.auto_channels if c in CHANNELS]
            if not channels:
                raise HTTPException(status_code=422, detail="Выберите хотя бы один канал")
            conn.execute("INSERT INTO settings (key, value) VALUES ('auto_channels', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (",".join(channels),))
        log_audit(conn, user, "agent.settings", "settings", None, "Настройки Magi обновлены")
    return _agent_payload(user)


# --------------------------------------------------------------------------- pulse

@app.get("/api/pulse")
def pulse(user: dict = Depends(require_roles("director", "analyst"))):
    with get_db() as conn:
        month_start = _now().replace(day=1, hour=0, minute=0, second=0)
        month_key = _now().strftime("%Y-%m")
        elapsed_ratio = (_now() - month_start).total_seconds() / (31 * 86400)  # доля прошедшего месяца
        cutoff30 = _iso(_now() - timedelta(days=30))
        cutoff90 = _iso(_now() - timedelta(days=90))

        month_rev = conn.execute(
            "SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(cost), 0) FROM orders WHERE created_at >= ?",
            (_iso(month_start),)
        ).fetchone()
        delivered, on_time = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(delivered_at <= promised_at), 0) FROM orders "
            "WHERE status = 'delivered' AND delivered_at IS NOT NULL"
        ).fetchone()
        late_orders = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE (delivered_at IS NOT NULL AND delivered_at > promised_at) "
            "OR (delivered_at IS NULL AND promised_at < ? AND status IN ('in_production','moderation','new'))",
            (_iso(_now()),)
        ).fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        defect_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE defect = 1").fetchone()[0]

        answered, in_sla = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(first_response_at <= sla_due_at), 0) FROM conversations "
            "WHERE first_response_at IS NOT NULL"
        ).fetchone()
        total_conv = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        magi_conv = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE mode = 'magi'"
        ).fetchone()[0]
        repeat_clients = conn.execute(
            "SELECT COUNT(*) FROM (SELECT client_id FROM orders GROUP BY client_id HAVING COUNT(*) >= 2)"
        ).fetchone()[0]
        clients_with_order = conn.execute(
            "SELECT COUNT(DISTINCT client_id) FROM orders"
        ).fetchone()[0]
        new_clients = conn.execute("SELECT COUNT(*) FROM clients WHERE created_at >= ?", (cutoff30,)).fetchone()[0]
        active_clients = conn.execute(
            "SELECT COUNT(DISTINCT client_id) FROM orders WHERE created_at >= ?", (cutoff90,)
        ).fetchone()[0]
        avg_check = conn.execute(
            "SELECT COALESCE(AVG(amount), 0) FROM orders WHERE created_at >= ?", (cutoff30,)
        ).fetchone()[0]

        # нагрузка/мощность: 6 недель по плану станков
        monday = (_now() - timedelta(days=_now().weekday())).replace(hour=0, minute=0, second=0)
        weekly_capacity = conn.execute("SELECT SUM(capacity_min_per_day) * 5 FROM machines").fetchone()[0]
        weeks = []
        max_ratio = 0.0
        for i in range(6):
            wstart = monday + timedelta(days=7 * i)
            wend = wstart + timedelta(days=7)
            planned = conn.execute(
                "SELECT COALESCE(SUM(est_minutes), 0) FROM machine_jobs WHERE planned_start >= ? AND planned_start < ?",
                (_iso(wstart), _iso(wend)),
            ).fetchone()[0]
            ratio = planned / weekly_capacity if weekly_capacity else 0
            max_ratio = max(max_ratio, ratio)
            weeks.append({
                "week": f"Н{i + 1}", "start": wstart.strftime("%d.%m"),
                "planned_min": planned, "capacity_min": weekly_capacity,
                "load": round(ratio * 100),
            })

        staff, vacancies_count = conn.execute(
            "SELECT (SELECT COUNT(*) FROM hr_employees WHERE status = 'active'), (SELECT COUNT(*) FROM vacancies WHERE status = 'open')"
        ).fetchone()
        finance = conn.execute(
            "SELECT plan_revenue, fact_revenue, plan_cash, fact_cash FROM finance_periods WHERE month = ?",
            (month_key,),
        ).fetchone()

        values = {
            "revenue_month": round(float(month_rev[0])),
            "gross_margin": round((month_rev[0] - month_rev[1]) / month_rev[0] * 100, 1) if month_rev[0] else 0,
            "on_time": round(on_time / delivered * 100, 1) if delivered else 0,
            "late_share": round(late_orders / total_orders * 100, 1) if total_orders else 0,
            "defect_rate": round(defect_orders / total_orders * 100, 1) if total_orders else 0,
            "sla_rate": round(in_sla / answered * 100, 1) if answered else 0,
            "ai_share": round(magi_conv / total_conv * 100, 1) if total_conv else 0,
            "repeat_rate": round(repeat_clients / clients_with_order * 100, 1) if clients_with_order else 0,
            "new_clients": new_clients,
            "active_clients": active_clients,
            "avg_check": round(float(avg_check)),
            "load_risk": round((max_ratio - 1) * 100, 1) if max_ratio > 1 else 0,
            "staff_coverage": round(staff / (staff + vacancies_count) * 100, 1) if staff + vacancies_count else 0,
            "cash_exec": round(float(finance["fact_cash"] / finance["plan_cash"] * 100), 1) if finance else 0,
        }
        # цели месячных KPI — пропорционально ходу месяца (план-факт на сегодня)
        prorated_target = {"revenue_month": elapsed_ratio, "cash_exec": elapsed_ratio}
        registry = [dict(r) for r in conn.execute("SELECT * FROM kpi_registry ORDER BY id").fetchall()]
        kpis = []
        for kpi in registry:
            value = values.get(kpi["key"])
            if value is None:
                continue
            target = kpi["target"]
            if target is not None and kpi["key"] in prorated_target and elapsed_ratio > 0.03:
                target = round(target * prorated_target[kpi["key"]], 1)
            direction = kpi["direction"]
            if target is None:
                status = "neutral"
            elif direction == "down":
                status = "green" if value <= target else ("red" if value > target * 1.5 else "amber")
            else:
                status = "green" if value >= target else ("red" if value < target * 0.75 else "amber")
            kpis.append({**kpi, "value": value, "status": status})

        critical = [
            {"kpi_key": k["key"], "kpi_name": k["name"], "value": k["value"], "unit": k["unit"],
             "target": k["target"], "owner": k["owner"], "source": k["source"]}
            for k in kpis if k["status"] == "red"
        ]
        open_decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE status IN ('open','in_progress')"
        ).fetchone()[0]
        return {
            "month": month_key,
            "kpis": kpis,
            "critical": critical,
            "weeks": weeks,
            "load_risk_week": next((w["week"] for w in weeks if w["load"] > 100), None),
            "open_decisions": open_decisions,
            "totals": {"orders": total_orders, "clients": total_conv and conn.execute(
                "SELECT COUNT(*) FROM clients").fetchone()[0], "conversations": total_conv},
            "finance_now": dict(finance) if finance else None,
        }


# --------------------------------------------------------------------------- sales

@app.get("/api/sales")
def sales(user: dict = Depends(require_teams("Клиентский сервис"))):
    with get_db() as conn:
        cutoff30 = _iso(_now() - timedelta(days=30))
        funnel = dict(conn.execute(
            "SELECT "
            "COALESCE(SUM(status='new'),0) AS new, "
            "COALESCE(SUM(status='qualified'),0) AS qualified, "
            "COALESCE(SUM(status='customer'),0) AS customers, "
            "COALESCE(SUM(status='sleeping'),0) AS sleeping FROM clients"
        ).fetchone())
        total = sum(funnel.values()) or 1
        conversion = round(funnel["customers"] / total * 100, 1)
        avg_check = conn.execute(
            "SELECT COALESCE(AVG(amount), 0) FROM orders WHERE created_at >= ?", (cutoff30,)
        ).fetchone()[0]
        repeat = conn.execute(
            "SELECT COUNT(*) FROM (SELECT client_id FROM orders GROUP BY client_id HAVING COUNT(*) >= 2)"
        ).fetchone()[0]
        clients_total = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        by_channel = [dict(r) for r in conn.execute(
            "SELECT channel, COUNT(*) AS orders, ROUND(SUM(amount), 0) AS revenue FROM orders "
            "WHERE created_at >= ? GROUP BY channel ORDER BY revenue DESC", (cutoff30,)
        ).fetchall()]
        by_segment = [dict(r) for r in conn.execute(
            "SELECT COALESCE(NULLIF(tags, ''), 'обычный') AS segment, COUNT(*) AS clients, ROUND(SUM(ltv), 0) AS ltv "
            "FROM clients GROUP BY segment ORDER BY ltv DESC LIMIT 8"
        ).fetchall()]
        series = [dict(r) for r in conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS orders, ROUND(SUM(amount), 0) AS revenue "
            "FROM orders WHERE created_at >= ? GROUP BY day ORDER BY day", (_iso(_now() - timedelta(days=29)),)
        ).fetchall()]
        return {
            "funnel": funnel, "conversion": conversion, "avg_check": round(float(avg_check)),
            "repeat_rate": round(repeat / clients_total * 100, 1) if clients_total else 0,
            "by_channel": [{**r, "label": CHANNEL_LABELS.get(r["channel"], r["channel"])} for r in by_channel],
            "by_segment": by_segment,
            "series": series,
        }


# ---------------------------------------------------------------------- production

@app.get("/api/production")
def production(user: dict = Depends(require_teams("Производство"))):
    with get_db() as conn:
        cutoff14 = _iso(_now() - timedelta(days=13))
        plan_fact = [dict(r) for r in conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, "
            "COALESCE(SUM(status IN ('delivered','ready')), 0) AS done, COUNT(*) AS planned "
            "FROM orders WHERE created_at >= ? GROUP BY day ORDER BY day", (cutoff14,)
        ).fetchall()]
        lead_hours = conn.execute(
            "SELECT AVG((julianday(delivered_at) - julianday(created_at)) * 24) FROM orders "
            "WHERE status = 'delivered' AND delivered_at IS NOT NULL AND created_at >= ?",
            (_iso(_now() - timedelta(days=30)),)
        ).fetchone()[0]
        machines = [dict(r) for r in conn.execute("SELECT * FROM machines ORDER BY id").fetchall()]
        for m in machines:
            m["queue_min"] = conn.execute(
                "SELECT COALESCE(SUM(est_minutes), 0) FROM machine_jobs WHERE machine_id = ? AND status = 'queued'",
                (m["id"],),
            ).fetchone()[0]
        queue = [dict(r) for r in conn.execute(
            "SELECT mj.*, m.name AS machine_name, o.product FROM machine_jobs mj "
            "JOIN machines m ON m.id = mj.machine_id LEFT JOIN orders o ON o.id = mj.order_id "
            "WHERE mj.status != 'done' ORDER BY mj.planned_start LIMIT 12"
        ).fetchall()]
        causes = [dict(r) for r in conn.execute(
            "SELECT delay_reason AS cause, COUNT(*) AS count FROM orders "
            "WHERE delay_reason IS NOT NULL GROUP BY delay_reason ORDER BY count DESC"
        ).fetchall()]
        total_cause = sum(c["count"] for c in causes) or 1
        for c in causes:
            c["label"] = DELAY_CAUSE_LABELS.get(c["cause"], c["cause"])
            c["share"] = round(c["count"] / total_cause * 100)
        defect_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE defect = 1").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        monday = (_now() - timedelta(days=_now().weekday())).replace(hour=0, minute=0, second=0)
        weekly_capacity = conn.execute("SELECT SUM(capacity_min_per_day) * 5 FROM machines").fetchone()[0]
        weeks = []
        for i in range(6):
            wstart = monday + timedelta(days=7 * i)
            planned = conn.execute(
                "SELECT COALESCE(SUM(est_minutes), 0) FROM machine_jobs WHERE planned_start >= ? AND planned_start < ?",
                (_iso(wstart), _iso(wstart + timedelta(days=7))),
            ).fetchone()[0]
            weeks.append({
                "week": f"Н{i + 1}", "start": wstart.strftime("%d.%m"),
                "load": round(planned / weekly_capacity * 100) if weekly_capacity else 0,
            })
        return {
            "plan_fact": plan_fact,
            "lead_time_hours": round(float(lead_hours or 0), 1),
            "machines": machines,
            "queue": queue,
            "causes": causes,
            "weeks": weeks,
            "defect_rate": round(defect_orders / total_orders * 100, 1) if total_orders else 0,
        }


@app.get("/api/production/causes/{cause}/orders")
def cause_orders(cause: str, user: dict = Depends(require_teams("Производство"))):
    if cause not in DELAY_CAUSE_LABELS:
        raise HTTPException(status_code=404, detail="Причина не найдена")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT o.id, o.product, o.amount, o.status, o.created_at, o.promised_at, o.delay_reason, "
            "c.name AS client_name, u.name AS owner_name FROM orders o "
            "JOIN clients c ON c.id = o.client_id LEFT JOIN users u ON u.id = c.owner_id "
            "WHERE o.delay_reason = ? ORDER BY o.promised_at ASC LIMIT 30", (cause,)
        ).fetchall()
        return {"cause": DELAY_CAUSE_LABELS[cause], "items": [dict(r) for r in rows]}


# ------------------------------------------------------------------------ finance

@app.get("/api/finance")
def finance(user: dict = Depends(require_teams("Финансы и люди"))):
    with get_db() as conn:
        periods = [dict(r) for r in conn.execute(
            "SELECT * FROM finance_periods ORDER BY month"
        ).fetchall()]
        for p in periods:
            p["margin"] = round((p["fact_revenue"] - p["fact_costs"]) / p["fact_revenue"] * 100, 1) if p["fact_revenue"] else 0
        entries = [dict(r) for r in conn.execute(
            "SELECT fe.*, cp.name AS counterparty_name FROM finance_entries fe "
            "LEFT JOIN counterparties cp ON cp.id = fe.counterparty_id "
            "ORDER BY fe.entry_date DESC LIMIT 24"
        ).fetchall()]
        counterparties = [dict(r) for r in conn.execute(
            "SELECT * FROM counterparties ORDER BY balance DESC"
        ).fetchall()]
        return {"periods": periods, "entries": entries, "counterparties": counterparties}


# ----------------------------------------------------------------------------- hr

@app.get("/api/hr")
def hr(user: dict = Depends(require_teams("Финансы и люди"))):
    with get_db() as conn:
        teams = [dict(r) for r in conn.execute(
            "SELECT team, COUNT(*) AS staff, COALESCE(SUM(status='active'), 0) AS active "
            "FROM hr_employees GROUP BY team ORDER BY staff DESC"
        ).fetchall()]
        vacancies = [dict(r) for r in conn.execute(
            "SELECT * FROM vacancies WHERE status = 'open' ORDER BY opened_at"
        ).fetchall()]
        today = _now().date().isoformat()
        shifts_today = [dict(r) for r in conn.execute(
            "SELECT s.*, e.name, e.team, e.position FROM shifts s JOIN hr_employees e ON e.id = s.employee_id "
            "WHERE s.day = ? ORDER BY e.team LIMIT 40", (today,)
        ).fetchall()]
        week_absence = conn.execute(
            "SELECT COUNT(*) FROM shifts WHERE fact_hours = 0 AND day >= ?",
            (_iso(_now() - timedelta(days=7))[:10],),
        ).fetchone()[0]
        return {
            "teams": teams,
            "vacancies": vacancies,
            "shifts_today": shifts_today,
            "week_absence": week_absence,
            "headcount": conn.execute("SELECT COUNT(*) FROM hr_employees").fetchone()[0],
        }


# ------------------------------------------------------------------------ analyst

@app.get("/api/analyst")
def analyst(user: dict = Depends(require_roles("director", "analyst"))):
    with get_db() as conn:
        def last_event(sql, params=()):
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

        def fresh_minutes(last: str | None) -> int | None:
            if not last:
                return None
            try:
                parsed = _parse(last if "T" in last else last + "T00:00:00Z")
            except ValueError:
                return None
            return round((_now() - parsed).total_seconds() / 60)

        sources = []
        for name, sql, table in [
            ("CRM · обращения", "SELECT MAX(last_message_at) FROM conversations", "conversations"),
            ("CRM · клиенты", "SELECT MAX(created_at) FROM clients", "clients"),
            ("ERP · заказы", "SELECT MAX(created_at) FROM orders", "orders"),
            ("1С · операции", "SELECT MAX(entry_date) FROM finance_entries", "finance_entries"),
            ("HR · смены", "SELECT MAX(day) FROM shifts", "shifts"),
        ]:
            last = last_event(sql)
            records = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            sources.append({"source": name, "last_event": last, "fresh_minutes": fresh_minutes(last), "records": records})

        dup_phones = conn.execute(
            "SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT phone, COUNT(*) AS n FROM clients WHERE phone != '' GROUP BY phone HAVING n > 1)"
        ).fetchone()[0]
        missing_phone = conn.execute("SELECT COUNT(*) FROM clients WHERE phone IS NULL OR phone = ''").fetchone()[0]
        missing_email = conn.execute("SELECT COUNT(*) FROM clients WHERE email IS NULL OR email = ''").fetchone()[0]
        missing_promised = conn.execute("SELECT COUNT(*) FROM orders WHERE promised_at IS NULL").fetchone()[0]
        missing_first_response = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE first_response_at IS NULL AND status != 'open'"
        ).fetchone()[0]

        month_key = _now().strftime("%Y-%m")
        month_start = _now().replace(day=1, hour=0, minute=0, second=0)
        crm_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM orders WHERE created_at >= ?", (_iso(month_start),)
        ).fetchone()[0]
        erp_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM orders WHERE status = 'delivered' AND created_at >= ?", (_iso(month_start),)
        ).fetchone()[0]
        fin = conn.execute(
            "SELECT fact_revenue FROM finance_periods WHERE month = ?", (month_key,)
        ).fetchone()
        fin_revenue = fin["fact_revenue"] if fin else 0
        base = crm_revenue or 1
        reconciliation = {
            "month": month_key,
            "crm_revenue": round(float(crm_revenue)),
            "erp_delivered": round(float(erp_revenue)),
            "finance_fact": round(float(fin_revenue)),
            "gap_crm_finance_pct": round(abs(crm_revenue - fin_revenue) / base * 100, 1),
            "note": "CRM считает все заказы, 1С — оплаченные. Расхождение до 3% объясняется предоплатами и отложенными отгрузками.",
        }
        return {
            "sources": sources,
            "quality": {
                "dup_phones": dup_phones,
                "missing_phone": missing_phone,
                "missing_email": missing_email,
                "missing_promised": missing_promised,
                "missing_first_response": missing_first_response,
            },
            "reconciliation": reconciliation,
        }


# ----------------------------------------------------------------------- decisions

class DecisionIn(BaseModel):
    kpi_key: str = Field(default="", max_length=40)
    problem: str = Field(min_length=5, max_length=300)
    impact: str = Field(default="", max_length=300)
    cause: str = Field(default="", max_length=300)
    action: str = Field(min_length=5, max_length=500)
    owner_id: int | None = None
    due_at: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class DecisionPatch(BaseModel):
    status: Literal["open", "in_progress", "done", "cancelled"] | None = None
    action: str | None = Field(default=None, min_length=5, max_length=500)
    result_note: str | None = Field(default=None, max_length=500)


@app.get("/api/decisions")
def decisions(
    status: str = Query(default=""),
    priority: str = Query(default=""),
    user: dict = Depends(current_user),
):
    with get_db() as conn:
        clauses, params = [], []
        if status in ("open", "in_progress", "done", "cancelled"):
            clauses.append("d.status = ?")
            params.append(status)
        if priority in ("low", "normal", "high"):
            clauses.append("d.priority = ?")
            params.append(priority)
        if user["role"] == "head" and user["team"] != "Компания":
            clauses.append("(d.kpi_key IN ('sla_rate','ai_share','repeat_rate','new_clients','active_clients','avg_check') OR d.owner_id = ?)")
            params.append(user["id"])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            "SELECT d.*, u1.name AS owner_name, u2.name AS created_by_name, k.name AS kpi_name "
            "FROM decisions d LEFT JOIN users u1 ON u1.id = d.owner_id "
            "LEFT JOIN users u2 ON u2.id = d.created_by LEFT JOIN kpi_registry k ON k.key = d.kpi_key "
            f"{where} ORDER BY CASE d.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, "
            "CASE d.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, d.due_at LIMIT 100", params
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@app.post("/api/decisions")
def create_decision(data: DecisionIn, user: dict = Depends(require_roles("director", "head", "analyst"))):
    with get_db() as conn:
        kpi = conn.execute("SELECT name FROM kpi_registry WHERE key = ?", (data.kpi_key,)).fetchone() if data.kpi_key else None
        now = _iso(_now())
        cursor = conn.execute(
            "INSERT INTO decisions (kpi_key, problem, impact, cause, action, owner_id, due_at, priority, status, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
            (data.kpi_key or None, data.problem.strip(), data.impact.strip(), data.cause.strip(),
             data.action.strip(), data.owner_id, data.due_at, data.priority, user["id"], now, now),
        )
        decision_id = cursor.lastrowid
        log_audit(conn, user, "decision.create", "decision", decision_id,
                  f"{kpi['name'] if kpi else 'KPI'}: {data.problem[:80]}")
        return {"id": decision_id}


@app.patch("/api/decisions/{decision_id}")
def patch_decision(decision_id: int, data: DecisionPatch, user: dict = Depends(require_roles("director", "head", "analyst"))):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Решение не найдено")
        updates, params = [], []
        if data.status is not None:
            updates.append("status = ?")
            params.append(data.status)
        if data.action is not None:
            updates.append("action = ?")
            params.append(data.action)
        if data.result_note is not None:
            updates.append("result_note = ?")
            params.append(data.result_note)
        if not updates:
            raise HTTPException(status_code=422, detail="Нет изменений")
        updates.append("updated_at = ?")
        params.append(_iso(_now()))
        params.append(decision_id)
        conn.execute(f"UPDATE decisions SET {', '.join(updates)} WHERE id = ?", params)
        log_audit(conn, user, "decision.update", "decision", decision_id,
                  "; ".join(u for u in [data.status, data.action, data.result_note] if u)[:160])
        return dict(conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone())


# --------------------------------------------------------------------------- rules

class RulePatch(BaseModel):
    config: dict
    enabled: bool | None = None


class RuleTestIn(BaseModel):
    key: str
    config: dict


@app.get("/api/rules")
def list_rules(user: dict = Depends(require_roles("director", "head", "analyst"))):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT r.*, u.name AS updated_by_name FROM rules r LEFT JOIN users u ON u.id = r.updated_by ORDER BY r.id"
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["config"] = json.loads(item["config"])
            except (TypeError, ValueError):
                item["config"] = {}
            items.append(item)
        topics = [dict(r) for r in conn.execute("SELECT * FROM topics ORDER BY id").fetchall()]
        return {"items": items, "topics": topics}


@app.patch("/api/rules/{key}")
def patch_rule(key: str, data: RulePatch, user: dict = Depends(require_roles("director", "head"))):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rules WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Правило не найдено")
        conn.execute(
            "UPDATE rules SET config = ?, enabled = ?, updated_by = ?, updated_at = ? WHERE key = ?",
            (json.dumps(data.config, ensure_ascii=False),
             1 if (data.enabled if data.enabled is not None else row["enabled"]) else 0,
             user["id"], _iso(_now()), key),
        )
        if key == "threshold.confidence":
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('confidence_threshold', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(round(float(data.config.get("value", 0.55)), 2)),),
            )
        log_audit(conn, user, "rules.update", "rule", key, json.dumps(data.config, ensure_ascii=False)[:160])
        return {"ok": True}


@app.post("/api/rules/test")
def test_rule(data: RuleTestIn, user: dict = Depends(require_roles("director", "head"))):
    """Прогон последних сообщений через движок: текущие правила против предлагаемых."""
    from .magi import local_reply

    with get_db() as conn:
        rows = conn.execute(
            "SELECT cv.id, cv.channel, m.body, c.id AS client_id FROM messages m "
            "JOIN conversations cv ON cv.id = m.conversation_id JOIN clients c ON c.id = cv.client_id "
            "WHERE m.author = 'lead' ORDER BY m.id DESC LIMIT 120"
        ).fetchall()
        current_rules = _rules(conn)
        proposed_rules = {**current_rules, data.key: data.config}
        all_orders = {r["id"]: [dict(x) for x in conn.execute(
            "SELECT * FROM orders WHERE client_id = ?", (r["id"],)
        ).fetchall()] for r in conn.execute("SELECT id FROM clients LIMIT 200").fetchall()}
        kb = _kb(conn)
        threshold = _settings(conn)["confidence_threshold"]
        old_auto = new_auto = 0
        samples = []
        for row in rows:
            client = dict(conn.execute("SELECT * FROM clients WHERE id = ?", (row["client_id"],)).fetchone())
            orders = all_orders.get(row["client_id"], [])
            old = local_reply(row["body"], client, orders, kb, threshold, current_rules, row["channel"])
            new = local_reply(row["body"], client, orders, kb, threshold, proposed_rules, row["channel"])
            old_auto += not old.handoff
            new_auto += not new.handoff
            if old.handoff != new.handoff and len(samples) < 5:
                samples.append({
                    "conversation_id": row["id"], "text": row["body"][:120],
                    "old": ("автоответ" if not old.handoff else f"человек: {old.handoff_reason}"),
                    "new": ("автоответ" if not new.handoff else f"человек: {new.handoff_reason}"),
                })
        total = len(rows)
        return {
            "total": total,
            "old": {"auto": old_auto, "human": total - old_auto, "auto_pct": round(old_auto / total * 100, 1) if total else 0},
            "new": {"auto": new_auto, "human": total - new_auto, "auto_pct": round(new_auto / total * 100, 1) if total else 0},
            "samples": samples,
        }


# ---------------------------------------------------------------------------- audit

@app.get("/api/audit")
def audit(user: dict = Depends(require_roles("director"))):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT a.*, u.name AS user_name FROM audit a LEFT JOIN users u ON u.id = a.user_id "
            "ORDER BY a.created_at DESC, a.id DESC LIMIT 100"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@app.post("/api/demo/reset")
def demo_reset(user: dict = Depends(require_roles("director"))):
    if os.getenv("MAGI_DEMO_MODE", "1") != "1":
        raise HTTPException(status_code=403, detail="Сброс доступен только в демо-режиме")
    db.reset_db()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "magi-crm"}


db.init_db()

if WEB_DIST.exists():
    app.frontend("/", directory=str(WEB_DIST), fallback="index.html")
else:
    @app.get("/")
    def root():
        return {"name": "Magi CRM", "docs": "/docs", "hint": "Соберите web: npm run build"}
