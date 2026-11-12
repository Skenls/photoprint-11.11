"""Telegram-бот Magi (aiogram 3) с полной интеграцией в CRM.

Запуск:  .venv/bin/python -m server.telegram_bot
Токен:   MAGI_TELEGRAM_TOKEN в .env (не хранится в репозитории).

Как работает интеграция:
- входящее сообщение → клиент по tg_handle (id Telegram) → диалог в инбоксе →
  ответ Magi (динамический промпт + правила; без ключа LLM — локальный движок);
- передача человеку → диалог уходит менеджеру, дальше отвечает CRM;
- ответ менеджера из CRM на telegram-диалог → строка в tg_outbox, бот отправляет клиенту.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message as TgMessage

from . import db
from .magi import reply as magi_reply, summary_for_manager
from .db import get_db, iso, utcnow

PENDING_INTERVAL = 2.0


def _token() -> str:
    return os.getenv("MAGI_TELEGRAM_TOKEN", "").strip()


def _first_operator(conn) -> dict | None:
    return conn.execute("SELECT id, team FROM users WHERE role = 'operator' ORDER BY id LIMIT 1").fetchone()


def _resolve_client(conn, tg_id: str, display_name: str, username: str | None) -> dict:
    row = conn.execute("SELECT * FROM clients WHERE tg_handle = ?", (tg_id,)).fetchone()
    if row is not None:
        return dict(row)
    operator = _first_operator(conn)
    owner_id, team = (operator["id"], operator["team"]) if operator else (None, "Клиентский сервис")
    name = display_name or (f"@{username}" if username else "Клиент Telegram")
    now = iso(utcnow())
    cursor = conn.execute(
        "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, tg_handle, created_at) "
        "VALUES (?, '', '', '', 'telegram', 'telegram', 'new', 0, 1, ?, 'Клиентский сервис', '', 'Из Telegram-бота', ?, ?)",
        (name, owner_id, tg_id, now),
    )
    return dict(conn.execute("SELECT * FROM clients WHERE id = ?", (cursor.lastrowid,)).fetchone())


def _open_conversation(conn, client: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM conversations WHERE client_id = ? AND status != 'closed' AND channel = 'telegram' "
        "ORDER BY last_message_at DESC LIMIT 1",
        (client["id"],),
    ).fetchone()
    if row is not None:
        return dict(row)
    now = utcnow()
    operator = _first_operator(conn)
    assignee = operator["id"] if operator else None
    cursor = conn.execute(
        "INSERT INTO conversations (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled, "
        "handoff_reason, sla_due_at, last_message_at, created_at) "
        "VALUES (?, 'telegram', 'Telegram', 'greeting', 'open', 'magi', ?, 'Клиентский сервис', 1, NULL, ?, ?, ?)",
        (client["id"], assignee, iso(now + timedelta(hours=1)), iso(now), iso(now)),
    )
    return dict(conn.execute("SELECT * FROM conversations WHERE id = ?", (cursor.lastrowid,)).fetchone())


def _settings_and_rules(conn) -> tuple[float, dict[str, dict], bool]:
    raw = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    threshold = float(raw.get("confidence_threshold", "0.55"))
    enabled = raw.get("magi_enabled", "1") == "1"
    rules = {}
    for row in conn.execute("SELECT key, config, enabled FROM rules").fetchall():
        try:
            rules[row["key"]] = json.loads(row["config"])
        except (TypeError, ValueError):
            rules[row["key"]] = {}
    return threshold, rules, enabled


async def ingest_telegram_message(tg_id: str, display_name: str, username: str | None, text: str) -> str | None:
    """Полный путь входящего сообщения Telegram. Возвращает текст ответа Magi (или None)."""
    if not text.strip():
        return None
    with get_db() as conn:
        client = _resolve_client(conn, tg_id, display_name, username)
        conversation = _open_conversation(conn, client)
        if not conversation["magi_enabled"]:
            return None
        now = iso(utcnow())
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, 'lead', ?, ?)",
            (conversation["id"], text.strip(), now),
        )
        conn.execute("UPDATE conversations SET last_message_at = ? WHERE id = ?", (now, conversation["id"]))
        threshold, rules, enabled = _settings_and_rules(conn)
        if not enabled:
            return None
        orders = [dict(r) for r in conn.execute(
            "SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC", (client["id"],)
        ).fetchall()]
        kb = [dict(r) for r in conn.execute("SELECT * FROM kb ORDER BY id").fetchall()]
        history = [dict(r) for r in conn.execute(
            "SELECT author, body FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 8",
            (conversation["id"],),
        ).fetchall()][::-1]
        if history and history[-1]["body"] == text.strip():
            history.pop()
        result = await magi_reply(
            text=text.strip(), client=client, orders=orders, kb=kb,
            channel="telegram", threshold=threshold, history=history, rules=rules,
        )
        when = iso(utcnow())
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, intent, confidence, provider, created_at) "
            "VALUES (?, 'magi', ?, ?, ?, ?, ?)",
            (conversation["id"], result.reply, result.intent, result.confidence, result.provider, when),
        )
        conn.execute(
            "UPDATE conversations SET first_response_at = ? WHERE id = ? AND first_response_at IS NULL",
            (when, conversation["id"]),
        )
        if result.handoff:
            reason = result.handoff_reason or "Нужна помощь менеджера"
            conn.execute(
                "UPDATE conversations SET mode = 'human', magi_enabled = 0, status = 'waiting', handoff_reason = ? WHERE id = ?",
                (reason, conversation["id"]),
            )
            orders_full = orders
            summary = summary_for_manager(
                {**conversation, "handoff_reason": reason}, client, orders_full,
                [dict(r) for r in conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation["id"],)
                ).fetchall()],
                "Telegram",
            )
            conn.execute("UPDATE conversations SET summary = ? WHERE id = ?", (summary, conversation["id"]))
            conn.execute(
                "INSERT INTO audit (user_id, actor, action, entity, entity_id, detail, created_at) "
                "VALUES (NULL, 'Magi', 'magi.handoff', 'conversation', ?, ?, ?)",
                (conversation["id"], f"{client['name']}: {reason}", when),
            )
    return result.reply


async def on_message(message: TgMessage, bot: Bot) -> None:
    if message.chat.type != "private":
        return
    tg_id = str(message.from_user.id)
    username = message.from_user.username
    display_name = message.from_user.full_name
    if message.text and message.text.startswith("/start"):
        await message.answer(
            "Здравствуйте! Я Magi — помощник клиентского сервиса Фотопринт.\n"
            "Подскажу по заказу, доставке, ценам и срокам. Сложные вопросы передам менеджеру."
        )
        return
    reply_text = await ingest_telegram_message(tg_id, display_name, username, message.text or message.caption or "")
    if reply_text:
        await message.answer(reply_text)


async def outbox_worker(bot: Bot) -> None:
    """Ответы менеджеров из CRM на telegram-диалоги уходят клиенту."""
    while True:
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT o.id, o.body, c.tg_handle FROM tg_outbox o "
                    "JOIN conversations cv ON cv.id = o.conversation_id "
                    "JOIN clients c ON c.id = cv.client_id "
                    "WHERE o.sent_at IS NULL AND c.tg_handle != '' ORDER BY o.id LIMIT 20"
                ).fetchall()
                for row in rows:
                    try:
                        await bot.send_message(int(row["tg_handle"]), row["body"])
                        conn.execute("UPDATE tg_outbox SET sent_at = ? WHERE id = ?", (iso(utcnow()), row["id"]))
                    except Exception:
                        # Telegram недоступен — отправим в следующем проходе
                        pass
        except Exception:
            pass
        await asyncio.sleep(PENDING_INTERVAL)


async def main() -> None:
    token = _token()
    if not token:
        raise SystemExit(
            "MAGI_TELEGRAM_TOKEN не задан. Добавьте токен в .env (MAGI_TELEGRAM_TOKEN=...) и перезапустите бота."
        )
    db.init_db()
    bot = Bot(token)
    dp = Dispatcher()
    dp.message.register(on_message, F.text | F.photo | F.caption)
    asyncio.create_task(outbox_worker(bot))
    print("Magi Telegram-бот запущен (long polling). Ctrl+C — остановить.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
