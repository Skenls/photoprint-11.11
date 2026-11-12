"""Динамические промпты Magi: одна задача — один промпт и один срез контекста.

Зачем: маленькие LLM (7B-класса) стабильно работают только с коротким промптом и
узким контекстом. Тема обращения определяется локальным классификатором (без LLM),
дальше модели уходит промпт этой задачи и только нужные ей данные из CRM.
"""

from __future__ import annotations

from typing import Callable

# ------------------------------------------------------------------ контекст

def _slice_order_status(client: dict, orders: list[dict], kb: list[dict]) -> dict:
    return {
        "клиент": client.get("name"),
        "последний_заказ": {k: orders[0].get(k) for k in
                            ("product", "status", "promised_at", "delivered_at", "amount")} if orders else None,
        "всего_заказов": len(orders),
    }


def _slice_kb(topic_keys: list[str]):
    def build(client: dict, orders: list[dict], kb: list[dict]) -> dict:
        entries = [row["answer"] for row in kb if row.get("topic") in topic_keys]
        return {"клиент": client.get("name"), "город": client.get("city"), "база_знаний": entries}
    return build


def _slice_price(client: dict, orders: list[dict], kb: list[dict]) -> dict:
    entries = [row["answer"] for row in kb if row.get("topic") in ("price_book", "price_other")]
    last = orders[0] if orders else None
    return {
        "клиент": client.get("name"),
        "сегмент": client.get("tags"),
        "база_знаний": entries,
        "его_последний_заказ": {k: last.get(k) for k in ("product", "amount")} if last else None,
    }


def _slice_greeting(client: dict, orders: list[dict], kb: list[dict]) -> dict:
    return {
        "клиент": client.get("name"),
        "сегмент": client.get("tags"),
        "заметки": client.get("notes"),  # персональный контекст: дни рождения, события
        "заказов_всего": len(orders),
    }


def _slice_complaint(client: dict, orders: list[dict], kb: list[dict]) -> dict:
    last = orders[0] if orders else None
    return {
        "клиент": client.get("name"),
        "сегмент": client.get("tags"),
        "последний_заказ": {k: last.get(k) for k in ("product", "status", "promised_at")} if last else None,
        "правило": "жалобы всегда передаются человеку: handoff=true",
    }


def _slice_other(client: dict, orders: list[dict], kb: list[dict]) -> dict:
    return {
        "клиент": client.get("name"),
        "сегмент": client.get("tags"),
        "темы_базы_знаний": [row["question"] for row in kb],
        "есть_заказы": bool(orders),
    }


CONTEXT_SLICES: dict[str, Callable[[dict, list[dict], list[dict]], dict]] = {
    "greeting": _slice_greeting,
    "order_status": _slice_order_status,
    "price_book": _slice_price,
    "price_other": _slice_price,
    "delivery": _slice_kb(["delivery"]),
    "payment": _slice_kb(["payment"]),
    "pickup": _slice_kb(["pickup"]),
    "production": _slice_kb(["production"]),
    "discount": _slice_kb(["discount"]),
    "custom": _slice_kb(["custom"]),
    "complaint": _slice_complaint,
    "return": _slice_complaint,
    "quality": _slice_complaint,
    "docs": _slice_kb(["docs"]),
    "promo": _slice_kb(["discount"]),
    "partnership": _slice_kb(["partnership"]),
    "other": _slice_other,
}

# темы, для которых полезна история диалога (для фактических тем — лишний токены)
CHAT_TOPICS = {"greeting", "other", "complaint", "return", "custom", "partnership"}

# ------------------------------------------------------------------- промпты

_OUTPUT_FORMAT = (
    "Ответ верни ТОЛЬКО JSON без markdown: "
    '{"reply": "текст 2-4 предложения", "confidence": 0.0-1.0, '
    '"handoff": true/false, "handoff_reason": "строка или null"}. '
    "Персональные данные маскированы — не пытайся их восстановить. "
    "Не выдумывай цены, сроки, статусы и обещания."
)

TASK_PROMPTS: dict[str, str] = {
    "order_status": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: сообщить статус заказа.\n"
        "Используй ТОЛЬКО поле «последний_заказ» из контекста: статус и обещанный срок.\n"
        "Обращайся по имени. Если заказа нет или он просрочен — handoff=true, объясни, что подключаешь менеджера.\n"
        + _OUTPUT_FORMAT
    ),
    "price_book": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: назвать цену.\n"
        "Отвечай только цифрами из «база_знаний». Уточни, что итоговая цена зависит от числа страниц.\n"
        "Персональную скидку не обещай — handoff=true с причиной «Персональные условия».\n"
        + _OUTPUT_FORMAT
    ),
    "price_other": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: назвать цену на календарь, холст или печать.\n"
        "Отвечай только цифрами из «база_знаний». Не выдумывай позиции, которых нет в прайсе.\n"
        + _OUTPUT_FORMAT
    ),
    "delivery": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про доставку.\n"
        "Используй только «база_знаний». Если клиент просит нестандартный срок или точное время — handoff=true.\n"
        + _OUTPUT_FORMAT
    ),
    "payment": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про оплату.\n"
        "Используй только «база_знаний». Спорные случаи (рассрочка, счёт на юрлицо) — handoff=true.\n"
        + _OUTPUT_FORMAT
    ),
    "pickup": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про самовывоз и ПВЗ.\n"
        "Используй только «база_знаний»: адреса и часы работы. Заказ держать не обещай.\n"
        + _OUTPUT_FORMAT
    ),
    "production": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про срок производства.\n"
        "Используй только «база_знаний». Срочный заказ «к конкретной дате» — handoff=true с причиной «Срочность».\n"
        + _OUTPUT_FORMAT
    ),
    "discount": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про скидки.\n"
        "Только условия из «база_знаний». Персональные и VIP-условия — handoff=true, не торгуйся.\n"
        + _OUTPUT_FORMAT
    ),
    "custom": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: ответить про индивидуальный заказ.\n"
        "Скажи общий срок из «база_знаний» и что менеджер уточнит детали. Детали макета не обсуждай сам — handoff=true с причиной «Индивидуальный макет».\n"
        + _OUTPUT_FORMAT
    ),
    "complaint": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: принять жалобу.\n"
        "Извинись, покажи что понял проблему и сразу handoff=true с причиной «Жалоба или вопрос о качестве».\n"
        "Ни в коем случае не оправдывайся и не обещай компенсацию сам.\n"
        + _OUTPUT_FORMAT
    ),
    "return": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: принять запрос на возврат.\n"
        "Спокойно прими запрос и сделай handoff=true с причиной «Возврат по заявлению клиента». Условия возврата сам не называешь.\n"
        + _OUTPUT_FORMAT
    ),
    "quality": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: сообщение о браке.\n"
        "Извинись, уточни номер заказа и дефект, сразу handoff=true с причиной «Брак: нужна перепечатка».\n"
        + _OUTPUT_FORMAT
    ),
    "docs": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: счёт, договор, реквизиты.\n"
        "Ответь по «база_знаний»: выставим в течение рабочего дня, попроси реквизиты. Бухгалтерские нюансы — handoff=true.\n"
        + _OUTPUT_FORMAT
    ),
    "promo": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: рассказать про действующие акции.\n"
        "Только то, что в «база_знаний». Придумывать акции запрещено.\n"
        + _OUTPUT_FORMAT
    ),
    "partnership": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: входящий запрос о сотрудничестве (B2B).\n"
        "Кратко: да, работаем с B2B, условия обсуждает менеджер по партнёрам. handoff=true с причиной «Запрос о сотрудничестве».\n"
        + _OUTPUT_FORMAT
    ),
    "greeting": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: первое знакомство.\n"
        "Поздоровайся по имени, представься, спроси чем помочь. Если в «заметки» есть событие (день рождения, свадьба) — мягко упомяни, что поможем успеть к нему. Компании печатаем фотокниги, календари, холсты; типовой срок — 1 рабочий день.\n"
        + _OUTPUT_FORMAT
    ),
    "other": (
        "Ты Magi — помощник клиентского сервиса фотопечатной компании. Задача: вопрос не по теме из списка.\n"
        "Веди себя честно: если не уверен, что понял вопрос, переспроси; если после ответа нужны действия — handoff=true с причиной «Magi не уверен в ответе».\n"
        + _OUTPUT_FORMAT
    ),
}

# интент для записи в messages по теме
TOPIC_INTENT = {
    "greeting": "greeting",
    "order_status": "order_status",
    "price_book": "price",
    "price_other": "price",
    "delivery": "delivery",
    "payment": "payment",
    "pickup": "pickup",
    "production": "delivery",
    "discount": "discount",
    "custom": "custom",
    "complaint": "complaint",
    "return": "complaint",
    "quality": "complaint",
    "docs": "docs",
    "promo": "discount",
    "partnership": "partnership",
    "other": "other",
}


def task_prompt(topic: str) -> str:
    return TASK_PROMPTS.get(topic, TASK_PROMPTS["other"])


def build_context(topic: str, client: dict, orders: list[dict], kb: list[dict]) -> dict:
    builder = CONTEXT_SLICES.get(topic, _slice_other)
    return builder(client, orders, kb)
