from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

INTENT_LABELS = {
    "greeting": "Приветствие",
    "order_status": "Статус заказа",
    "price": "Цены",
    "delivery": "Доставка",
    "payment": "Оплата",
    "discount": "Скидки",
    "custom": "Индивидуальный заказ",
    "complaint": "Жалоба",
    "handoff": "Передача человеку",
    "thanks": "Благодарность",
    "other": "Другое",
}

ORDER_STATUS_LABELS = {
    "new": "принят",
    "moderation": "на модерации",
    "in_production": "в производстве",
    "ready": "готов",
    "delivered": "доставлен",
    "delayed": "задерживается",
}

_GREETINGS = ("здравствуйте", "добрый день", "добрый вечер", "привет", "доброе утро")
_THANKS = ("спасибо", "благодарю", "спс")

DEFAULT_RULES: dict[str, dict] = {
    "route.auto_answer": {"channels": ["site", "telegram", "email", "instagram"],
                          "intents": ["greeting", "order_status", "price", "delivery", "payment",
                                      "pickup", "discount", "quality", "docs"]},
    "threshold.confidence": {"value": 0.55},
    "trigger.complaint": {"keywords": ["брак", "возврат", "жалоб", "испортили", "плохо напечатали",
                                       "перепечат", "полосы", "недоволен", "вернуть деньги"]},
    "trigger.vip_discount": {"segments": "VIP", "keywords": ["персональн", "индивидуальн скидк", "спецуслов"]},
}

_PHONE_RE = re.compile(r"\+?\d[\d\s()\-]{8,}\d")
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_DOCS_RE = re.compile(r"(счет|счёт|договор|закрывающ|реквизит)")


@dataclass
class MagiResult:
    reply: str
    intent: str
    confidence: float
    handoff: bool = False
    handoff_reason: str | None = None
    provider: str = "local"
    topic: str | None = None
    rule_hits: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- PII mask

def mask_text(text: str) -> str:
    text = _PHONE_RE.sub("+375 XX ***-**-**", text or "")
    text = _EMAIL_RE.sub("***@***", text)
    return text


def masked_client(client: dict) -> dict:
    name = client.get("name") or ""
    parts = name.split()
    initials = f"{parts[0][0]}." if parts else ""
    masked = dict(client)
    masked["name"] = f"{initials} {parts[-1][0]}." if len(parts) > 1 else initials
    masked["phone"] = mask_text(client.get("phone") or "")
    masked["email"] = mask_text(client.get("email") or "")
    masked["notes"] = mask_text(client.get("notes") or "")
    return masked


# ----------------------------------------------------------------- rule engine

def _norm(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _first_name(name: str) -> str:
    return name.split()[0] if name else "друг"


def _date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m")
    except ValueError:
        return "—"


def _last_order(orders: list[dict]) -> dict | None:
    if not orders:
        return None
    return max(orders, key=lambda o: o.get("created_at") or "")


def _kb_match(text: str, kb: list[dict]) -> tuple[dict | None, float]:
    best = None
    best_hits = 0
    for row in kb:
        keywords = [k.strip().lower() for k in row.get("keywords", "").split(",") if k.strip()]
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits > best_hits:
            best, best_hits = row, hits
    if not best:
        return None, 0.0
    return best, min(0.94, 0.64 + best_hits * 0.07)


def _rules_map(rules: dict[str, dict] | None) -> dict[str, dict]:
    merged = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    for key, cfg in (rules or {}).items():
        if key in merged and isinstance(cfg, dict):
            merged[key].update(cfg)
    return merged


def _trigger_rules(normalized: str, client: dict, rules: dict[str, dict], hits: list[str]) -> tuple[str, str] | None:
    tags = (client.get("tags") or "")
    if any(word in normalized for word in rules["trigger.complaint"]["keywords"]):
        hits.append("trigger.complaint")
        return "complaint", "Жалоба или вопрос о качестве"
    vip_words = rules["trigger.vip_discount"]["keywords"]
    if "VIP" in tags and any(word in normalized for word in vip_words):
        hits.append("trigger.vip_discount")
        return "handoff", "Персональные условия для VIP-клиента"
    if any(word in normalized for word in ("позови", "позовите", "человек", "менеджер", "оператор", "соедини")):
        hits.append("request.human")
        return "handoff", "Клиент просит человека"
    if any(word in normalized for word in ("паспорт", "персональные данные", "юрист", "адвокат")):
        hits.append("request.legal")
        return "handoff", "Юридический вопрос"
    return None


def local_reply(text: str, client: dict, orders: list[dict], kb: list[dict], threshold: float = 0.55,
                rules: dict[str, dict] | None = None, channel: str = "site") -> MagiResult:
    """Offline deterministic Magi driven by editable rules. This is the demo engine, not a language model."""
    r = _rules_map(rules)
    threshold = float(r["threshold.confidence"].get("value", threshold))
    normalized = _norm(text)
    name = _first_name(client.get("name", ""))
    hits: list[str] = []

    if channel not in r["route.auto_answer"]["channels"]:
        hits.append("route.auto_answer:channel-off")
        return MagiResult(
            reply=f"{name}, передаю сообщение менеджеру — он ответит в рабочие часы.",
            intent="handoff", confidence=0.3, handoff=True,
            handoff_reason="Канал вне автоответа (правило route)", topic="other", rule_hits=hits,
        )

    trigger = _trigger_rules(normalized, client, r, hits)
    if trigger:
        intent, reason = trigger
        return MagiResult(
            reply=f"{name}, спасибо, что написали. Передаю вопрос менеджеру — он подключится в течение 15 минут и поможет.",
            intent=intent, confidence=0.28, handoff=True, handoff_reason=reason,
            topic=intent if intent == "complaint" else "other", rule_hits=hits,
        )

    asks_order = any(word in normalized for word in ("мой заказ", "где заказ", "статус", "готов", "успеет", "успеваем", "когда будет", "придет"))
    asks_delivery = any(word in normalized for word in ("доставка", "курьер", "самовывоз", "привез", "пункт выдачи", "забрать"))
    asks_price = any(word in normalized for word in ("цена", "стоимость", "сколько стоит", "прайс", "почем"))
    asks_payment = any(word in normalized for word in ("оплата", "оплатить", "картой", "предоплата", "рассрочк"))
    asks_discount = any(word in normalized for word in ("скидка", "промокод", "дешевле", "акция"))
    asks_custom = any(word in normalized for word in ("индивидуальн", "макет", "нестандарт", "свадеб", "свой дизайн"))

    if asks_order:
        intent = "order_status"
        if intent not in r["route.auto_answer"]["intents"]:
            hits.append("route.auto_answer:intent-off")
            return MagiResult(
                reply=f"{name}, уточню статус у менеджера — он подключится в течение 15 минут.",
                intent=intent, confidence=0.4, handoff=True, handoff_reason="Тема вне автоответа (правило route)",
                topic="order_status", rule_hits=hits,
            )
        order = _last_order(orders)
        if not order:
            return MagiResult(
                reply=f"{name}, не вижу заказов на этот контакт. Уточните, пожалуйста, номер заказа — передам менеджеру, чтобы он проверил.",
                intent=intent, confidence=0.4, handoff=True, handoff_reason="Нет заказа в базе",
                topic="order_status", rule_hits=hits,
            )
        status = order.get("status", "new")
        product = order.get("product", "заказ")
        promised = _date(order.get("promised_at"))
        try:
            promised_dt = datetime.fromisoformat(str(order.get("promised_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            promised_dt = None
        if promised_dt and promised_dt < datetime.now(timezone.utc) and status not in {"delivered", "ready"}:
            return MagiResult(
                reply=f"{name}, вижу, что заказ «{product}» должен был быть готов {promised}. Передаю менеджеру: он проверит статус и свяжется с вами.",
                intent=intent, confidence=0.84, handoff=True, handoff_reason="Обещанный срок прошёл",
                topic="order_status", rule_hits=hits,
            )
        if status in {"delayed", "moderation"} and status == "delayed":
            return MagiResult(
                reply=f"{name}, вижу, что заказ «{product}» задерживается. Передаю менеджеру: он свяжется и предложит решение.",
                intent=intent, confidence=0.86, handoff=True, handoff_reason="Заказ задерживается",
                topic="order_status", rule_hits=hits,
            )
        if status == "delivered":
            reply = f"{name}, заказ «{product}» уже доставлен. Если что-то не так — напишите, разберёмся."
        elif status == "ready":
            reply = f"{name}, заказ «{product}» готов и передан в доставку. Ожидайте в ближайшее время."
        elif status == "in_production":
            reply = f"{name}, заказ «{product}» сейчас в производстве. Обещанный срок — {promised}, успеваем."
        else:
            reply = f"{name}, заказ «{product}» принят. Обещанный срок — {promised}. Если понадобится срочно — скажите."
        return MagiResult(reply=reply, intent=intent, confidence=0.93, topic="order_status", rule_hits=hits)

    if asks_discount:
        if "discount" not in r["route.auto_answer"]["intents"]:
            hits.append("route.auto_answer:intent-off")
            return MagiResult(
                reply=f"{name}, по скидкам подключу менеджера — он ответит в течение 15 минут.",
                intent="discount", confidence=0.4, handoff=True, handoff_reason="Тема вне автоответа (правило route)",
                topic="discount", rule_hits=hits,
            )
        return MagiResult(
            reply=f"{name}, на второй заказ в течение 30 дней действует скидка 10%. Персональные условия согласует менеджер.",
            intent="discount", confidence=0.74, topic="discount", rule_hits=hits,
        )

    if asks_custom:
        return MagiResult(
            reply=f"{name}, индивидуальный макет и нестандартный размер делаем от 3 дней. Менеджер уточнит детали и стоимость — передать ему запрос?",
            intent="custom", confidence=0.78, topic="custom", rule_hits=hits,
        )

    if asks_price or asks_delivery or asks_payment:
        intent = "price" if asks_price else ("delivery" if asks_delivery else "payment")
        if intent not in r["route.auto_answer"]["intents"]:
            hits.append("route.auto_answer:intent-off")
            return MagiResult(
                reply=f"{name}, уточню у менеджера — он подключится в течение 15 минут.",
                intent=intent, confidence=0.4, handoff=True, handoff_reason="Тема вне автоответа (правило route)",
                topic=intent, rule_hits=hits,
            )
        match, confidence = _kb_match(normalized, kb)
        if match:
            return MagiResult(reply=match["answer"], intent=intent, confidence=confidence, topic=intent, rule_hits=hits)

    if any(word in normalized for word in _THANKS):
        return MagiResult(reply=f"Рад помочь, {name}! Если появятся вопросы — я на связи.", intent="thanks",
                          confidence=0.95, topic="greeting", rule_hits=hits)

    if any(word in normalized for word in _GREETINGS) and len(normalized) < 90:
        return MagiResult(
            reply=f"Здравствуйте, {name}! Я Magi, помощник клиентского сервиса. Подскажу по заказу, доставке, ценам и срокам. Чем помочь?",
            intent="greeting", confidence=0.82, topic="greeting", rule_hits=hits,
        )

    match, confidence = _kb_match(normalized, kb)
    if match:
        topic = match.get("topic", "other")
        intent = {"price_book": "price", "price_other": "price", "production": "delivery"}.get(topic, topic)
        if confidence >= threshold and intent in r["route.auto_answer"]["intents"]:
            return MagiResult(reply=match["answer"], intent=intent, confidence=confidence, topic=topic, rule_hits=hits)

    return MagiResult(
        reply=f"{name}, уточню этот вопрос у менеджера — он подключится в течение 15 минут. Чтобы не терять время, опишите, пожалуйста, заказ или продукт.",
        intent="handoff", confidence=0.32, handoff=True, handoff_reason="Magi не уверен в ответе",
        topic="other", rule_hits=hits,
    )


def rules_map_from_db(rows) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        row = dict(row)
        try:
            out[row["key"]] = json.loads(row["config"])
        except (TypeError, ValueError):
            out[row["key"]] = {}
        out[row["key"]]["_enabled"] = bool(row.get("enabled", 1))
    return out


def provider_info() -> dict:
    key = os.getenv("MAGI_API_KEY", "").strip()
    return {
        "provider": "openai" if key else "local",
        "model": os.getenv("MAGI_MODEL", "gpt-4.1-mini") if key else "Правила + база знаний",
        "base_url": os.getenv("MAGI_BASE_URL", "https://api.openai.com/v1") if key else None,
    }


SYSTEM_PROMPT = """Ты Magi — AI-ассистент клиентского сервиса компании Фотопринт.
Компания печатает фотокниги, календари, холсты и фотографии. Средний срок — 1 рабочий день.

Правила:
1. Отвечай по-русски, кратко (2–4 предложения), обращайся по имени.
2. Используй только данные клиента, заказов и базы знаний из сообщения. Не выдумывай цены, сроки и статусы.
3. Если вопрос про брак, возврат, жалобу, персональную скидку, юридический вопрос или данных не хватает — handoff=true.
4. Не обещай действий, которых нет в данных. Передача менеджеру — нормальный ответ.
5. Персональные данные в контексте маскированы (телефоны, почта, инициалы). Не пытайся их восстановить.
6. Верни ТОЛЬКО JSON без markdown:
{"reply": "текст", "intent": "greeting|order_status|price|delivery|payment|discount|custom|complaint|handoff|other", "confidence": 0.0, "handoff": false, "handoff_reason": null}"""


async def openai_reply(text: str, client: dict, orders: list[dict], kb: list[dict], channel: str,
                       history: list[dict] | None = None) -> MagiResult | None:
    """One OpenAI-compatible completion with masked CRM context. Returns None on any failure."""
    key = os.getenv("MAGI_API_KEY", "").strip()
    if not key:
        return None
    base_url = os.getenv("MAGI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("MAGI_MODEL", "gpt-4.1-mini")
    context = {
        "channel": channel,
        "client": masked_client(client),
        "orders": [
            {k: order.get(k) for k in ("product", "amount", "status", "created_at", "promised_at", "delivered_at")}
            for order in orders[:5]
        ],
        "knowledge_base": [{"topic": row["topic"], "answer": row["answer"]} for row in kb],
    }
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[
                {"role": "user" if item.get("author") == "lead" else "assistant", "content": item.get("body", "")}
                for item in (history or [])[-6:]
                if item.get("body")
            ],
            {
                "role": "user",
                "content": f"Сообщение лида: {mask_text(text)}\n\nДанные CRM:\n{json.dumps(context, ensure_ascii=False)}",
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client_http:
            response = await client_http.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(content[start:end + 1])
        reply_text = str(data.get("reply", "")).strip()
        if not reply_text:
            return None
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.6))))
        handoff = bool(data.get("handoff", False))
        reason = data.get("handoff_reason") if handoff else None
        return MagiResult(
            reply=reply_text,
            intent=str(data.get("intent", "other")),
            confidence=confidence,
            handoff=handoff,
            handoff_reason=str(reason) if reason else ("Передано менеджеру" if handoff else None),
            provider=f"openai:{model}",
        )
    except Exception:
        # Any provider/network/JSON failure falls back to the offline engine.
        return None


async def reply(text: str, client: dict, orders: list[dict], kb: list[dict], channel: str, threshold: float,
                history: list[dict] | None = None, rules: dict[str, dict] | None = None) -> MagiResult:
    result = await openai_reply(text, client, orders, kb, channel, history)
    if result is None:
        result = local_reply(text, client, orders, kb, threshold, rules, channel)
    if not result.handoff and result.confidence < threshold:
        result.handoff = True
        result.handoff_reason = "Низкая уверенность Magi"
        result.reply = f"{_first_name(client.get('name', ''))}, уточню этот вопрос у менеджера — он подключится в течение 15 минут."
    return result


def summary_for_manager(conversation: dict, client: dict, orders: list[dict], messages: list[dict],
                        topic_name: str) -> str:
    """AI-сводка для менеджера при передаче диалога."""
    name = client.get("name", "клиент")
    tags = (client.get("tags") or "").replace(",", ", ") or "—"
    ltv = f"{round(float(client.get('ltv') or 0)):,}".replace(",", " ")
    last = orders[0] if orders else None
    last_line = "заказов нет" if not last else (
        f"«{last.get('product')}» — {ORDER_STATUS_LABELS.get(last.get('status'), last.get('status'))}, "
        f"обещано {_date(last.get('promised_at'))}"
    )
    tried = [m["body"] for m in messages if m.get("author") == "magi"][-2:]
    lead = [m["body"] for m in messages if m.get("author") == "lead"][-2:]
    questions = {
        "complaint": "какой именно дефект, номер страницы/заказа",
        "quality": "какой дефект и номер заказа",
        "return": "причина возврата и способ оплаты",
        "discount": "какой объём скидки обсуждаем",
        "custom": "формат, тираж и дедлайн",
        "delivery": "адрес и удобное время",
        "handoff": "что именно не разрешили автоматом",
    }.get(conversation.get("topic") or "", "детали запроса")
    lines = [
        f"Клиент: {name} · сегмент: {tags} · LTV {ltv} BYN",
        f"Тема: {topic_name} · причина передачи: {conversation.get('handoff_reason') or 'нужна помощь'}",
        f"Последний заказ: {last_line}",
        "Сказал(а): " + " | ".join(mask_text(t)[:120] for t in reversed(lead)) if lead else "Сказал(а): —",
    ]
    if tried:
        lines.append("Magi уже ответил: " + " | ".join(t[:100] for t in reversed(tried)))
    lines.append(f"Уточнить: {questions}. SLA до {_date(conversation.get('sla_due_at'))}.")
    return "\n".join(lines)
