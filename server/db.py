from __future__ import annotations

import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("MAGI_DB", str(ROOT / "data" / "magi.db")))

CHANNELS = ["site", "telegram", "email", "instagram"]
CHANNEL_LABELS = {
    "site": "Сайт",
    "telegram": "Telegram",
    "email": "Почта",
    "instagram": "Instagram",
}
STATUS_LABELS = {
    "new": "Новый",
    "qualified": "В работе",
    "customer": "Клиент",
    "sleeping": "Спящий",
}
ORDER_STATUS_LABELS = {
    "new": "Принят",
    "in_production": "В производстве",
    "ready": "Готов",
    "delivered": "Доставлен",
    "delayed": "Задерживается",
}
ROLE_LABELS = {
    "director": "Директор",
    "manager": "Руководитель отдела",
    "operator": "Менеджер",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('director', 'manager', 'operator')),
    team TEXT NOT NULL,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    city TEXT,
    channel TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    ltv REAL NOT NULL DEFAULT 0,
    consent INTEGER NOT NULL DEFAULT 1,
    owner_id INTEGER REFERENCES users(id),
    team TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    promised_at TEXT,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'waiting', 'closed')),
    mode TEXT NOT NULL CHECK (mode IN ('magi', 'human')),
    assignee_id INTEGER REFERENCES users(id),
    team TEXT NOT NULL,
    magi_enabled INTEGER NOT NULL DEFAULT 1,
    handoff_reason TEXT,
    last_message_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    author TEXT NOT NULL CHECK (author IN ('lead', 'magi', 'agent', 'system')),
    body TEXT NOT NULL,
    intent TEXT,
    confidence REAL,
    provider TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    assignee_id INTEGER REFERENCES users(id),
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    keywords TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clients_owner ON clients(owner_id);
CREATE INDEX IF NOT EXISTS idx_clients_team ON clients(team);
CREATE INDEX IF NOT EXISTS idx_orders_client ON orders(client_id);
CREATE INDEX IF NOT EXISTS idx_conv_assignee ON conversations(assignee_id);
CREATE INDEX IF NOT EXISTS idx_conv_team ON conversations(team);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at);
"""


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed(conn)


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def seed(conn: sqlite3.Connection) -> None:
    rng = random.Random(42)
    now = utcnow()

    users = [
        (1, "Ирина Соколова", "director@magi.by", "director", "Компания", "Генеральный директор"),
        (2, "Анна Петрова", "manager@magi.by", "manager", "Клиентский сервис", "Руководитель клиентского сервиса"),
        (3, "Игорь Лебедев", "operator@magi.by", "operator", "Клиентский сервис", "Менеджер по клиентам"),
    ]
    conn.executemany(
        "INSERT INTO users (id, name, email, role, team, title) VALUES (?, ?, ?, ?, ?, ?)",
        users,
    )

    conn.executemany(
        "INSERT INTO kb (topic, question, answer, keywords) VALUES (?, ?, ?, ?)",
        [
            ("delivery", "Сколько идёт доставка?", "По Минску доставляем за 1 день, по Беларуси — за 1–2 дня. Курьер по Минску стоит 12 BYN, самовывоз бесплатный.", "доставка,курьер,гомель,минск,пункт выдачи,когда привез,привезете"),
            ("production", "Какой срок производства?", "Фотокниги печатаем за 1 рабочий день. Если заказ подтверждён до 16:00, он будет готов завтра.", "срок,готовность,когда будет,успеет,производство,сколько дней,завтра"),
            ("price_book", "Сколько стоит фотокнига?", "Фотокнига Classic 20×20 — от 290 BYN, Premium 21×30 — от 620 BYN, Mini 15×15 — от 160 BYN. Точная цена зависит от количества страниц.", "цена,стоимость,сколько стоит,фотокнига,прайс,premium,classic,mini"),
            ("price_other", "Сколько стоит календарь, холст или печать?", "Календарь настенный — от 75 BYN, холст 40×60 — от 180 BYN, печать фото 10×15 — от 45 BYN.", "календарь,холст,печать,фотографии,цена,стоимость"),
            ("payment", "Как можно оплатить?", "Оплатить можно картой онлайн или при получении. Для индивидуальных заказов берём предоплату 50%.", "оплата,карта,предоплата,рассрочка,наличные"),
            ("returns", "Что делать, если брак?", "Брак переделываем бесплатно. Напишите номер заказа — менеджер согласует замену.", "брак,возврат,переделать,испортили,недоволен,плохо напечатали"),
            ("discount", "Есть ли скидка?", "На второй заказ в течение 30 дней действует скидка 10%. Персональные условия согласует менеджер.", "скидка,промокод,дешевле,акция,второй заказ"),
            ("pickup", "Где забрать заказ?", "Самовывоз: Минск, ул. Тимирязева 65Б, пн–сб с 9:00 до 20:00.", "самовывоз,адрес,забрать,пункт выдачи,офис"),
            ("custom", "Можно сделать нестандартный заказ?", "Индивидуальный макет и нестандартный размер делаем от 3 дней. Менеджер уточнит детали и стоимость.", "индивидуальный,макет,размер,свадьба,нестандарт,свой дизайн"),
        ],
    )

    seed_clients = [
        ("Мария Ковалёва", "+375 29 145-22-08", "maria.kovaleva@example.by", "Минск", "telegram", "instagram", "customer", 3, "VIP,повторный", "Сын Миша, 6 лет. День рождения 14 ноября. Заказ — фотокнига Premium.", 80),
        ("Андрей Новиков", "+375 29 311-07-44", "a.novikov@example.by", "Гомель", "site", "google", "qualified", 3, "повторный", "Просил уточнить доставку курьером.", 22),
        ("Ольга Сидорова", "+375 33 602-18-90", "o.sidorova@example.by", "Минск", "email", "email", "customer", 3, "VIP", "Жалоба на брак в фотокниге. Нужен разбор.", 35),
        ("Дмитрий Козлов", "+375 44 780-31-15", "d.kozlov@example.by", "Брест", "telegram", "telegram", "new", 3, "", "Интересуется холстом.", 1),
        ("Елена Морозова", "+375 29 508-44-72", "e.morozova@example.by", "Минск", "instagram", "instagram", "customer", 3, "повторный", "", 48),
        ("Сергей Волков", "+375 25 917-60-33", "s.volkov@example.by", "Витебск", "site", "google", "customer", 3, "", "", 12),
        ("Наталья Павлова", "+375 29 688-12-05", "n.pavlova@example.by", "Минск", "email", "email", "qualified", 2, "VIP", "Просит персональную скидку.", 5),
        ("Павел Семёнов", "+375 33 440-29-81", "p.semenov@example.by", "Гродно", "telegram", "telegram", "new", 3, "", "Хочет заказать фотокнигу.", 0),
        ("Виктория Орлова", "+375 29 233-77-10", "v.orlova@example.by", "Минск", "site", "instagram", "qualified", 2, "свадьба", "Свадьба 20 декабря, нужна индивидуальная книга.", 3),
        ("Алексей Фёдоров", "+375 44 155-90-26", "a.fedorov@example.by", "Могилёв", "email", "email", "customer", 2, "повторный", "Возврат закрыт, клиент остался.", 55),
    ]
    for row in seed_clients:
        name, phone, email, city, channel, source, status, owner, tags, notes, days_ago = row
        conn.execute(
            """INSERT INTO clients
               (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, 'Клиентский сервис', ?, ?, ?)""",
            (name, phone, email, city, channel, source, status, owner, tags, notes, iso(now - timedelta(days=days_ago))),
        )

    female_first = ["Анна", "Екатерина", "Ирина", "Ольга", "Татьяна", "Юлия", "Светлана", "Марина", "Полина", "Ксения"]
    male_first = ["Александр", "Максим", "Иван", "Артём", "Роман", "Кирилл", "Денис", "Владислав", "Михаил", "Павел"]
    female_last = ["Иванова", "Петрова", "Смирнова", "Кузнецова", "Попова", "Васильева", "Соколова", "Михайлова",
                   "Новикова", "Фёдорова", "Морозова", "Волкова", "Алексеева", "Лебедева", "Семёнова", "Егорова",
                   "Павлова", "Козлова", "Степанова", "Николаева", "Орлова", "Андреева", "Макарова", "Никитина", "Захарова"]
    male_last = ["Иванов", "Петров", "Смирнов", "Кузнецов", "Попов", "Васильев", "Соколов", "Михайлов",
                 "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев", "Лебедев", "Семёнов", "Егоров",
                 "Павлов", "Козлов", "Степанов", "Николаев", "Орлов", "Андреев", "Макаров", "Никитин", "Захаров"]
    cities = ["Минск", "Минск", "Минск", "Гомель", "Брест", "Гродно", "Витебск", "Могилёв", "Бобруйск", "Барановичи"]
    statuses = ["customer", "customer", "customer", "customer", "qualified", "qualified", "new", "new", "sleeping"]
    tags_pool = ["", "", "", "повторный", "VIP", "подарок", "семья"]
    for i in range(50):
        if i % 2 == 0:
            name = f"{female_first[(i // 2) % len(female_first)]} {female_last[(i * 3 + 1) % len(female_last)]}"
        else:
            name = f"{male_first[(i // 2) % len(male_first)]} {male_last[(i * 3 + 4) % len(male_last)]}"
        channel = CHANNELS[i % len(CHANNELS)]
        status = statuses[i % len(statuses)]
        owner = 3 if i % 5 else 2
        days_ago = rng.randint(0, 30)
        if status == "new":
            days_ago = rng.randint(0, 5)
        conn.execute(
            """INSERT INTO clients
               (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'Клиентский сервис', ?, '', ?)""",
            (name, f"+375 29 {200 + i:03d}-{10 + i % 80:02d}-{20 + i % 70:02d}", f"client{i}@example.by",
             cities[i % len(cities)], channel, channel if channel != "site" else "google", status,
             1 if i % 17 else 0, owner, tags_pool[i % len(tags_pool)], iso(now - timedelta(days=days_ago))),
        )

    products = [
        ("Фотокнига Premium 21×30", 620.0),
        ("Фотокнига Classic 20×20", 290.0),
        ("Фотокнига Mini 15×15", 160.0),
        ("Календарь настенный", 75.0),
        ("Печать фотографий 10×15", 45.0),
        ("Холст 40×60", 180.0),
    ]
    product_weights = [18, 28, 12, 15, 17, 10]
    order_statuses = ["delivered"] * 72 + ["ready"] * 8 + ["in_production"] * 10 + ["new"] * 5 + ["delayed"] * 5

    def add_order(client_id: int, product: str, amount: float, status: str, created: datetime, promised: datetime, delivered: datetime | None):
        conn.execute(
            "INSERT INTO orders (client_id, product, amount, status, created_at, promised_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (client_id, product, round(amount, 2), status, iso(created), iso(promised), iso(delivered) if delivered else None),
        )

    add_order(1, "Фотокнига Premium 21×30", 620, "in_production", now - timedelta(days=1), now + timedelta(days=2), None)
    add_order(1, "Фотокнига Classic 20×20", 370, "delivered", now - timedelta(days=45), now - timedelta(days=43), now - timedelta(days=43))
    add_order(1, "Печать фотографий 10×15", 250, "delivered", now - timedelta(days=70), now - timedelta(days=69), now - timedelta(days=69))

    for client_id in range(2, 61):
        order_count = 1 + (1 if rng.random() < 0.45 else 0) + (1 if rng.random() < 0.18 else 0)
        for _ in range(order_count):
            product, base = rng.choices(products, weights=product_weights, k=1)[0]
            amount = base * rng.uniform(0.9, 1.3)
            status = rng.choice(order_statuses)
            if status in {"new", "in_production", "ready"}:
                created = now - timedelta(days=rng.randint(0, 2), minutes=rng.randint(0, 600))
                promised = now + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 8))
            elif status == "delayed":
                created = now - timedelta(days=rng.randint(3, 12), minutes=rng.randint(0, 600))
                promised = now - timedelta(days=rng.randint(1, 4))
            else:
                created = now - timedelta(days=rng.randint(3, 40), minutes=rng.randint(0, 600))
                promised = created + timedelta(days=rng.randint(1, 3))
            delivered = promised + timedelta(hours=rng.randint(0, 24)) if status == "delivered" else None
            add_order(client_id, product, amount, status, created, promised, delivered)

    conn.execute(
        """UPDATE clients SET ltv = COALESCE(
             (SELECT ROUND(SUM(amount), 2) FROM orders WHERE orders.client_id = clients.id), 0)"""
    )
    conn.execute(
        "UPDATE clients SET tags = TRIM(REPLACE(',' || tags || ',', ',VIP,', ','), ',') "
        "WHERE ltv < 900 AND tags LIKE '%VIP%'"
    )
    conn.execute(
        "UPDATE clients SET tags = TRIM(tags || ',VIP', ',') WHERE ltv >= 900 AND tags NOT LIKE '%VIP%'"
    )

    def add_conversation(client_id: int, channel: str, subject: str, mode: str, status: str,
                         assignee_id: int, handoff_reason: str | None, messages: list[dict]) -> int:
        ordered = sorted(messages, key=lambda m: m["minutes_ago"], reverse=True)
        created = now - timedelta(minutes=ordered[0]["minutes_ago"])
        last = now - timedelta(minutes=ordered[-1]["minutes_ago"])
        cur = conn.execute(
            """INSERT INTO conversations
               (client_id, channel, subject, status, mode, assignee_id, team, magi_enabled, handoff_reason, last_message_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'Клиентский сервис', ?, ?, ?, ?)""",
            (client_id, channel, subject, status, mode, assignee_id,
             1 if mode == "magi" else 0, handoff_reason, iso(last), iso(created)),
        )
        conv_id = int(cur.lastrowid)
        for m in ordered:
            conn.execute(
                "INSERT INTO messages (conversation_id, author, body, intent, confidence, provider, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conv_id, m["author"], m["body"], m.get("intent"), m.get("confidence"), m.get("provider"), iso(now - timedelta(minutes=m["minutes_ago"]))),
            )
        return conv_id

    add_conversation(1, "telegram", "Заказ к дню рождения", "magi", "open", 3, None, [
        {"author": "lead", "body": "Здравствуйте! Успеет ли фотокнига прийти к 14 ноября? Заказывала Premium 21×30.", "minutes_ago": 14},
        {"author": "magi", "body": "Здравствуйте, Мария! Да, заказ «Фотокнига Premium 21×30» сейчас в производстве. Обещанный срок — 13 ноября, успеваем к дню рождения Миши.", "intent": "order_status", "confidence": 0.94, "provider": "local", "minutes_ago": 13},
    ])
    add_conversation(2, "site", "Доставка в Гомель", "human", "waiting", 3, "Нужен нестандартный сценарий доставки", [
        {"author": "lead", "body": "Сколько идёт доставка в Гомель?", "minutes_ago": 70},
        {"author": "magi", "body": "По Беларуси доставляем за 1–2 дня. В Гомель — обычно на следующий день после готовности.", "intent": "delivery", "confidence": 0.88, "provider": "local", "minutes_ago": 69},
        {"author": "lead", "body": "А можно курьером завтра до 12:00? Это подарок.", "minutes_ago": 50},
        {"author": "magi", "body": "Передам менеджеру: он подтвердит срочную доставку на завтра. Обычно отвечаем в течение 15 минут.", "intent": "delivery", "confidence": 0.42, "provider": "local", "minutes_ago": 46},
    ])
    add_conversation(3, "email", "Брак в фотокниге", "human", "waiting", 3, "Жалоба на качество печати", [
        {"author": "lead", "body": "Здравствуйте. В фотокниге две страницы напечатаны с полосами. Это подарок на юбилей, что делать?", "minutes_ago": 135},
        {"author": "magi", "body": "Очень жаль, что так вышло. Передаю ваш вопрос менеджеру — он свяжется в течение 15 минут и согласует бесплатную перепечатку.", "intent": "complaint", "confidence": 0.28, "provider": "local", "minutes_ago": 130},
    ])
    add_conversation(4, "telegram", "Цена на холст", "magi", "open", 3, None, [
        {"author": "lead", "body": "Сколько стоит холст 40×60?", "minutes_ago": 8},
        {"author": "magi", "body": "Холст 40×60 — от 180 BYN. В цену входит печать и натяжка на каркас. Могу передать менеджеру, чтобы он уточнил макет.", "intent": "price", "confidence": 0.91, "provider": "local", "minutes_ago": 6},
    ])
    add_conversation(5, "instagram", "Календари", "magi", "closed", 3, None, [
        {"author": "lead", "body": "Здравствуйте! Календари ещё делаете?", "minutes_ago": 1500},
        {"author": "magi", "body": "Да, настенный календарь — от 75 BYN. Печатаем за 1 рабочий день.", "intent": "price", "confidence": 0.87, "provider": "local", "minutes_ago": 1498},
        {"author": "lead", "body": "Спасибо, закажу на сайте.", "minutes_ago": 1490},
    ])
    add_conversation(6, "site", "Статус заказа", "magi", "open", 3, None, [
        {"author": "lead", "body": "Где мой заказ? Обещали сегодня.", "minutes_ago": 30},
        {"author": "magi", "body": "Сергей, ваш заказ «Фотокнига Classic 20×20» готов и передан в доставку. Ожидайте сегодня до 18:00.", "intent": "order_status", "confidence": 0.9, "provider": "local", "minutes_ago": 24},
    ])
    add_conversation(7, "email", "Персональная скидка", "human", "waiting", 2, "Персональные условия согласует руководитель", [
        {"author": "lead", "body": "Мы заказываем книги каждый год. Можно сделать персональную скидку 15%?", "minutes_ago": 195},
        {"author": "magi", "body": "Стандартно на второй заказ действует 10%. Персональные условия передам руководителю — он ответит сегодня.", "intent": "discount", "confidence": 0.36, "provider": "local", "minutes_ago": 190},
    ])
    add_conversation(8, "telegram", "Новый заказ", "magi", "open", 3, None, [
        {"author": "lead", "body": "Добрый день! Хочу заказать фотокнигу.", "minutes_ago": 12},
        {"author": "magi", "body": "Здравствуйте, Павел! Помогу. Подскажите, сколько страниц и какой формат нужен — Classic 20×20 или Premium 21×30?", "intent": "greeting", "confidence": 0.82, "provider": "local", "minutes_ago": 9},
    ])
    add_conversation(9, "site", "Свадебная книга", "magi", "open", 2, None, [
        {"author": "lead", "body": "Здравствуйте! Нужна индивидуальная свадебная книга к 20 декабря. Успеете?", "minutes_ago": 62},
        {"author": "magi", "body": "Виктория, индивидуальный макет делаем от 3 дней. К 20 декабря успеваем с запасом. Менеджер поможет с макетом — передать ему детали?", "intent": "custom", "confidence": 0.76, "provider": "local", "minutes_ago": 55},
    ])
    add_conversation(10, "email", "Возврат", "human", "closed", 2, "Возврат согласован", [
        {"author": "lead", "body": "Хочу вернуть заказ, не подошёл размер.", "minutes_ago": 2900},
        {"author": "agent", "body": "Алексей, добрый день. Индивидуальный заказ вернуть нельзя, но мы можем переделать обложку со скидкой 50%. Согласны?", "minutes_ago": 2870},
        {"author": "lead", "body": "Да, давайте переделаем.", "minutes_ago": 2860},
    ])

    generated_questions = [
        ("Здравствуйте! Сколько стоит фотокнига Premium?", "price_book"),
        ("Подскажите, сколько идёт доставка в Гомель?", "delivery"),
        ("Мой заказ уже готов?", "order_status"),
        ("Хочу заказать календарь. Какой срок?", "production"),
        ("Можно оплатить картой при получении?", "payment"),
        ("Есть ли скидка на второй заказ?", "discount"),
        ("Как забрать заказ самовывозом?", "pickup"),
        ("Нужен нестандартный размер фотокниги. Возможно?", "custom"),
    ]
    from .magi import local_reply

    for idx, (question, _topic) in enumerate(generated_questions):
        client_id = 11 + idx
        client = dict(conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone())
        orders = [dict(r) for r in conn.execute("SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC", (client_id,))]
        kb = [dict(r) for r in conn.execute("SELECT * FROM kb")]
        result = local_reply(question, client, orders, kb, 0.55)
        channel = client["channel"]
        closed = idx in (0, 6)
        mode = "human" if result.handoff else "magi"
        status = "closed" if closed else ("waiting" if result.handoff else "open")
        add_conversation(client_id, channel, "Входящий вопрос", mode, status, 3,
                         result.handoff_reason if result.handoff else None, [
            {"author": "lead", "body": question, "minutes_ago": 120 + idx * 37},
            {"author": "magi", "body": result.reply, "intent": result.intent,
             "confidence": result.confidence, "provider": "local", "minutes_ago": 118 + idx * 37},
        ])

    tasks = [
        (1, 1, "Подтвердить магнит в подарок", 3, now + timedelta(hours=3), "open"),
        (3, 3, "Разобрать брак и согласовать перепечатку", 3, now + timedelta(hours=2), "open"),
        (7, 7, "Согласовать персональную скидку", 2, now + timedelta(hours=4), "open"),
        (9, 9, "Уточнить макет свадебной книги", 2, now + timedelta(days=1), "open"),
        (2, 2, "Подтвердить срочную доставку в Гомель", 3, now + timedelta(hours=1), "open"),
        (10, 10, "Проконтролировать переделку обложки", 2, now - timedelta(days=1), "done"),
    ]
    for client_id, conv_id, title, assignee, due, status in tasks:
        conn.execute(
            "INSERT INTO tasks (client_id, conversation_id, title, assignee_id, due_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (client_id, conv_id, title, assignee, iso(due), status, iso(now - timedelta(hours=5))),
        )

    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("magi_enabled", "1"), ("confidence_threshold", "0.55"), ("auto_channels", "site,telegram,email,instagram")],
    )

    conn.executemany(
        "INSERT INTO audit (user_id, actor, action, entity, entity_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "Ирина Соколова", "auth.login", "user", 1, "Вход в систему", iso(now - timedelta(hours=2))),
            (3, "Игорь Лебедев", "magi.handoff", "conversation", "3", "Жалоба на качество печати", iso(now - timedelta(minutes=130))),
            (2, "Анна Петрова", "agent.settings", "settings", None, "Порог уверенности Magi: 0.55", iso(now - timedelta(days=1))),
        ],
    )


def get_settings(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    return {
        "magi_enabled": raw.get("magi_enabled", "1") == "1",
        "confidence_threshold": float(raw.get("confidence_threshold", "0.55")),
        "auto_channels": [c for c in raw.get("auto_channels", "").split(",") if c],
    }
