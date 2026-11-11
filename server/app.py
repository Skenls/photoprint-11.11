from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .magi import provider_info, reply as magi_reply
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
    require_roles,
)
from .db import get_db

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="Magi CRM", version="1.0.0")
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


def _conversation(conn, conversation_id: int) -> dict:
    row = conn.execute(
        "SELECT cv.*, c.name AS client_name, c.ltv, c.city, c.phone, u.name AS assignee_name "
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


async def _magi_answer(conn, conversation: dict, client: dict, text: str) -> dict | None:
    settings = _settings(conn)
    if not settings["magi_enabled"] or not conversation["magi_enabled"]:
        return None
    if conversation["channel"] not in settings["auto_channels"]:
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
    )
    when = _iso(_now())
    cursor = conn.execute(
        "INSERT INTO messages (conversation_id, author, body, intent, confidence, provider, created_at) "
        "VALUES (?, 'magi', ?, ?, ?, ?, ?)",
        (conversation["id"], result.reply, result.intent, result.confidence, result.provider, when),
    )
    _touch(conn, conversation["id"], when)
    if result.handoff:
        conn.execute(
            "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting', handoff_reason = ? WHERE id = ?",
            (result.handoff_reason or "Нужна помощь менеджера", conversation["id"]),
        )
        log_audit(conn, {"id": None, "name": "Magi"}, "magi.handoff", "conversation", conversation["id"],
                  f"{conversation['client_name']}: {result.handoff_reason or 'нужна помощь'}")
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

        # first response time, computed in Python over the scoped conversations
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
        if user["role"] == "director":
            members = conn.execute(
                "SELECT id, name, title, role, team FROM users WHERE role != 'director' ORDER BY role, name"
            ).fetchall()
        elif user["role"] == "manager":
            members = conn.execute(
                "SELECT id, name, title, role, team FROM users WHERE team = ? AND role != 'director' ORDER BY name",
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
            "scope_label": "Вся компания" if user["role"] == "director" else (
                user["team"] if user["role"] == "manager" else "Мои клиенты"),
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
        if user["role"] == "director":
            manager = conn.execute("SELECT id, team FROM users WHERE role = 'manager' ORDER BY id LIMIT 1").fetchone()
            if manager is None:
                raise HTTPException(status_code=500, detail="Нет доступного менеджера")
            owner_id, team = manager["id"], manager["team"]
        else:
            owner_id, team = user["id"], user["team"]
        cursor = conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'magi', 'new', 0, 1, ?, ?, '', '', ?)",
            (data.name.strip(), data.phone.strip(), data.email.strip(), data.city.strip(), data.channel,
             owner_id, team, now),
        )
        client_id = cursor.lastrowid
        conv_cursor = conn.execute(
            "INSERT INTO conversations (client_id, channel, subject, status, mode, assignee_id, team, magi_enabled, handoff_reason, last_message_at, created_at) "
            "VALUES (?, ?, 'Новый лид', 'open', 'magi', ?, ?, 1, NULL, ?, ?)",
            (client_id, data.channel, owner_id, team, now, now),
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
        task_where = "" if user["role"] in ("director", "manager") else " AND assignee_id = ?"
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
            "SELECT cv.*, c.name AS client_name, c.ltv, c.city, u.name AS assignee_name, "
            "(SELECT body FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message, "
            "(SELECT author FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_author "
            "FROM conversations cv JOIN clients c ON c.id = cv.client_id "
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
        else:
            refreshed = _conversation(conn, conversation_id)
            client = _client(conn, conversation["client_id"])
            magi_message = await _magi_answer(conn, refreshed, client, body)
            if magi_message is None:
                conn.execute(
                    "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting' WHERE id = ?",
                    (conversation_id,),
                )
        conversation = _conversation(conn, conversation_id)
        return {"conversation": conversation, "magi_message": magi_message,
                "messages": _messages(conn, conversation_id)}


@app.post("/api/conversations/{conversation_id}/handoff")
def handoff(conversation_id: int, data: HandoffIn, user: dict = Depends(current_user)):
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        conn.execute(
            "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting', "
            "assignee_id = ?, handoff_reason = ? WHERE id = ?",
            (user["id"], data.reason.strip() or "Нужна помощь менеджера", conversation_id),
        )
        log_audit(conn, user, "conversation.handoff", "conversation", conversation_id,
                  f"{conversation['client_name']}: {data.reason}")
        return _conversation(conn, conversation_id)


@app.post("/api/conversations/{conversation_id}/resume")
def resume_magi(conversation_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        conversation = _conversation(conn, conversation_id)
        if not can_access_conversation(user, conversation):
            raise HTTPException(status_code=403, detail="Диалог другого подразделения")
        conn.execute(
            "UPDATE conversations SET mode = 'magi', magi_enabled = 1, status = 'open', handoff_reason = NULL WHERE id = ?",
            (conversation_id,),
        )
        log_audit(conn, user, "conversation.resume_magi", "conversation", conversation_id,
                  conversation["client_name"])
        return _conversation(conn, conversation_id)


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
            "can_edit": user["role"] == "director",
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
        if data.auto_channels is not None:
            channels = [c for c in data.auto_channels if c in CHANNELS]
            if not channels:
                raise HTTPException(status_code=422, detail="Выберите хотя бы один канал")
            conn.execute("INSERT INTO settings (key, value) VALUES ('auto_channels', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (",".join(channels),))
        log_audit(conn, user, "agent.settings", "settings", None, "Настройки Magi обновлены")
    return _agent_payload(user)


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
