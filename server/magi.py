from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
    "in_production": "в производстве",
    "ready": "готов",
    "delivered": "доставлен",
    "delayed": "задерживается",
}

_HANDOFF_RULES = [
    (("брак", "возврат", "перепечат", "испортили", "плохо напечатали", "полосы", "жалоб", "недоволен", "суд", "роспотреб"), "complaint", "Жалоба или вопрос о качестве"),
    (("персональн", "индивидуальн скидк", "торг", "спецуслов"), "handoff", "Персональные условия"),
    (("позови", "позовите", "человек", "менеджер", "оператор", "позвони", "соедини"), "handoff", "Клиент просит человека"),
    (("паспорт", "персональные данные", "юрист", "адвокат"), "handoff", "Юридический вопрос"),
]

_GREETINGS = ("здравствуйте", "добрый день", "добрый вечер", "привет", "доброе утро")
_THANKS = ("спасибо", "благодарю", "спс")


@dataclass
class MagiResult:
    reply: str
    intent: str
    confidence: float
    handoff: bool = False
    handoff_reason: str | None = None
    provider: str = "local"


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


def local_reply(text: str, client: dict, orders: list[dict], kb: list[dict], threshold: float = 0.55) -> MagiResult:
    """Offline deterministic Magi. This is the demo engine, not a language model."""
    normalized = _norm(text)
    name = _first_name(client.get("name", ""))

    for keywords, intent, reason in _HANDOFF_RULES:
        if any(keyword in normalized for keyword in keywords):
            return MagiResult(
                reply=f"{name}, спасибо, что написали. Передаю вопрос менеджеру — он подключится в течение 15 минут и поможет.",
                intent=intent,
                confidence=0.28,
                handoff=True,
                handoff_reason=reason,
            )

    asks_order = any(word in normalized for word in ("мой заказ", "где заказ", "статус", "готов", "успеет", "успеваем", "когда будет", "придет"))
    asks_delivery = any(word in normalized for word in ("доставка", "курьер", "самовывоз", "привез", "пункт выдачи", "забрать"))
    asks_price = any(word in normalized for word in ("цена", "стоимость", "сколько стоит", "прайс", "почем"))
    asks_payment = any(word in normalized for word in ("оплата", "оплатить", "картой", "предоплата", "рассрочк"))
    asks_discount = any(word in normalized for word in ("скидка", "промокод", "дешевле", "акция"))
    asks_custom = any(word in normalized for word in ("индивидуальн", "макет", "нестандарт", "свадеб", "свой дизайн"))

    if asks_order:
        order = _last_order(orders)
        if not order:
            return MagiResult(
                reply=f"{name}, не вижу заказов на этот контакт. Уточните, пожалуйста, номер заказа — передам менеджеру, чтобы он проверил.",
                intent="order_status",
                confidence=0.4,
                handoff=True,
                handoff_reason="Нет заказа в базе",
            )
        status = order.get("status", "new")
        product = order.get("product", "заказ")
        promised = _date(order.get("promised_at"))
        status_label = ORDER_STATUS_LABELS.get(status, status)
        try:
            promised_dt = datetime.fromisoformat(str(order.get("promised_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            promised_dt = None
        if promised_dt and promised_dt < datetime.now(timezone.utc) and status not in {"delivered", "ready"}:
            return MagiResult(
                reply=f"{name}, вижу, что заказ «{product}» должен был быть готов {promised}. Передаю менеджеру: он проверит статус и свяжется с вами.",
                intent="order_status",
                confidence=0.84,
                handoff=True,
                handoff_reason="Обещанный срок прошёл",
            )
        if status == "delayed":
            return MagiResult(
                reply=f"{name}, вижу, что заказ «{product}» задерживается. Передаю менеджеру: он свяжется и предложит решение.",
                intent="order_status",
                confidence=0.86,
                handoff=True,
                handoff_reason="Заказ задерживается",
            )
        if status == "delivered":
            reply = f"{name}, заказ «{product}» уже доставлен. Если что-то не так — напишите, разберёмся."
        elif status == "ready":
            reply = f"{name}, заказ «{product}» готов и передан в доставку. Ожидайте в ближайшее время."
        elif status == "in_production":
            reply = f"{name}, заказ «{product}» сейчас в производстве. Обещанный срок — {promised}, успеваем."
        else:
            reply = f"{name}, заказ «{product}» принят. Обещанный срок — {promised}. Если понадобится срочно — скажите."
        return MagiResult(reply=reply, intent="order_status", confidence=0.93)

    if asks_discount:
        return MagiResult(
            reply=f"{name}, на второй заказ в течение 30 дней действует скидка 10%. Персональные условия согласует менеджер.",
            intent="discount",
            confidence=0.74,
        )

    if asks_custom:
        return MagiResult(
            reply=f"{name}, индивидуальный макет и нестандартный размер делаем от 3 дней. Менеджер уточнит детали и стоимость — передать ему запрос?",
            intent="custom",
            confidence=0.78,
        )

    if asks_price or asks_delivery or asks_payment:
        match, confidence = _kb_match(normalized, kb)
        if match:
            intent = "price" if asks_price else ("delivery" if asks_delivery else "payment")
            return MagiResult(reply=match["answer"], intent=intent, confidence=confidence)

    if any(word in normalized for word in _THANKS):
        return MagiResult(reply=f"Рад помочь, {name}! Если появятся вопросы — я на связи.", intent="thanks", confidence=0.95)

    if any(word in normalized for word in _GREETINGS) and len(normalized) < 90:
        return MagiResult(
            reply=f"Здравствуйте, {name}! Я Magi, помощник клиентского сервиса. Подскажу по заказу, доставке, ценам и срокам. Чем помочь?",
            intent="greeting",
            confidence=0.82,
        )

    match, confidence = _kb_match(normalized, kb)
    if match and confidence >= threshold:
        topic = match.get("topic", "other")
        intent = {"price_book": "price", "price_other": "price", "production": "delivery"}.get(topic, topic)
        return MagiResult(reply=match["answer"], intent=intent, confidence=confidence)

    return MagiResult(
        reply=f"{name}, уточню этот вопрос у менеджера — он подключится в течение 15 минут. Чтобы не терять время, опишите, пожалуйста, заказ или продукт.",
        intent="handoff",
        confidence=0.32,
        handoff=True,
        handoff_reason="Magi не уверен в ответе",
    )


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
5. Верни ТОЛЬКО JSON без markdown:
{"reply": "текст", "intent": "greeting|order_status|price|delivery|payment|discount|custom|complaint|handoff|other", "confidence": 0.0, "handoff": false, "handoff_reason": null}"""


async def openai_reply(text: str, client: dict, orders: list[dict], kb: list[dict], channel: str,
                       history: list[dict] | None = None) -> MagiResult | None:
    """One OpenAI-compatible completion with CRM context. Returns None on any failure."""
    key = os.getenv("MAGI_API_KEY", "").strip()
    if not key:
        return None
    base_url = os.getenv("MAGI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("MAGI_MODEL", "gpt-4.1-mini")
    context = {
        "channel": channel,
        "client": {
            "name": client.get("name"),
            "city": client.get("city"),
            "status": client.get("status"),
            "ltv": client.get("ltv"),
            "tags": client.get("tags"),
            "notes": client.get("notes"),
        },
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
                "content": f"Сообщение лида: {text}\n\nДанные CRM:\n{json.dumps(context, ensure_ascii=False)}",
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
                history: list[dict] | None = None) -> MagiResult:
    result = await openai_reply(text, client, orders, kb, channel, history)
    if result is None:
        result = local_reply(text, client, orders, kb, threshold)
    if not result.handoff and result.confidence < threshold:
        result.handoff = True
        result.handoff_reason = "Низкая уверенность Magi"
        result.reply = f"{_first_name(client.get('name', ''))}, уточню этот вопрос у менеджера — он подключится в течение 15 минут."
    return result
