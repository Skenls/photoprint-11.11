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
    "moderation": "Модерация",
    "in_production": "В производстве",
    "ready": "Готов",
    "delivered": "Доставлен",
    "delayed": "Задерживается",
}
ROLE_LABELS = {
    "director": "Директор",
    "head": "Руководитель отдела",
    "operator": "Менеджер",
    "analyst": "Аналитик",
}
TEAMS = ["Клиентский сервис", "Производство", "Финансы и люди", "Компания"]


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
    role TEXT NOT NULL CHECK (role IN ('director', 'head', 'operator', 'analyst')),
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
    tg_handle TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    amount REAL NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    channel TEXT NOT NULL DEFAULT 'site',
    payment TEXT NOT NULL DEFAULT 'online',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    promised_at TEXT,
    delivered_at TEXT,
    defect INTEGER NOT NULL DEFAULT 0,
    delay_reason TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'waiting', 'closed')),
    mode TEXT NOT NULL CHECK (mode IN ('magi', 'human')),
    assignee_id INTEGER REFERENCES users(id),
    team TEXT NOT NULL,
    magi_enabled INTEGER NOT NULL DEFAULT 1,
    handoff_reason TEXT,
    summary TEXT,
    sla_due_at TEXT,
    first_response_at TEXT,
    resolved_at TEXT,
    outcome TEXT,
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

CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    capacity_min_per_day INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    downtime_min_month INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS machine_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    est_minutes INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done')),
    planned_start TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS hr_employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    team TEXT NOT NULL,
    position TEXT NOT NULL,
    hired_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    planned_hours_week INTEGER NOT NULL DEFAULT 40
);

CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    position TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    candidates INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES hr_employees(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    planned_hours REAL NOT NULL,
    fact_hours REAL NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS finance_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL UNIQUE,
    plan_revenue REAL NOT NULL,
    fact_revenue REAL NOT NULL,
    plan_costs REAL NOT NULL,
    fact_costs REAL NOT NULL,
    plan_cash REAL NOT NULL,
    fact_cash REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS counterparties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finance_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_month TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('debit', 'credit')),
    counterparty_id INTEGER REFERENCES counterparties(id),
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    entry_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kpi_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    formula TEXT NOT NULL,
    source TEXT NOT NULL,
    target REAL,
    direction TEXT NOT NULL DEFAULT 'up',
    owner TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_key TEXT,
    problem TEXT NOT NULL,
    impact TEXT NOT NULL DEFAULT '',
    cause TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    owner_id INTEGER REFERENCES users(id),
    due_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
    result_note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('route', 'threshold', 'trigger', 'sla', 'reminder')),
    config TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sla_hours INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pickups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    location TEXT NOT NULL,
    ready_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0,
    reminded_at TEXT
);

CREATE TABLE IF NOT EXISTS tg_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tg_outbox_pending ON tg_outbox(sent_at);

CREATE INDEX IF NOT EXISTS idx_clients_owner ON clients(owner_id);
CREATE INDEX IF NOT EXISTS idx_clients_team ON clients(team);
CREATE INDEX IF NOT EXISTS idx_orders_client ON orders(client_id);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_conv_assignee ON conversations(assignee_id);
CREATE INDEX IF NOT EXISTS idx_conv_team ON conversations(team);
CREATE INDEX IF NOT EXISTS idx_conv_topic ON conversations(topic);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_machine ON machine_jobs(machine_id);
"""

TOPICS = [
    ("greeting", "Приветствие", 1, "Первый контакт, знакомство"),
    ("order_status", "Статус заказа", 2, "Где мой заказ, сроки"),
    ("price_book", "Цены: фотокниги", 2, "Прайс и расчёт"),
    ("price_other", "Цены: прочая продукция", 2, "Календари, холсты, печать"),
    ("delivery", "Доставка", 4, "Курьер, почта, сроки"),
    ("payment", "Оплата", 4, "Способы и статусы оплаты"),
    ("pickup", "Самовывоз / ПВЗ", 2, "Где и когда забрать"),
    ("production", "Сроки производства", 4, "Готовность, срочность"),
    ("discount", "Скидки и промо", 8, "Акции, промокоды"),
    ("custom", "Индивидуальный заказ", 24, "Макет, нестандарт"),
    ("complaint", "Жалоба", 1, "Недоволен обслуживанием"),
    ("return", "Возврат", 4, "Возврат денег/заказа"),
    ("quality", "Брак и качество", 2, "Перепечатка, дефекты"),
    ("docs", "Документы и счёт", 24, "Договор, закрывающие"),
    ("promo", "Акции и рассылки", 8, "Маркетинговые вопросы"),
    ("partnership", "Сотрудничество", 24, "B2B, опт, партнёры"),
    ("other", "Другое", 4, "Всё остальное"),
]

TOPIC_BY_KEY = {key: (name, sla) for key, name, sla, _ in TOPICS}


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
        (2, "Анна Петрова", "head.crm@magi.by", "head", "Клиентский сервис", "Руководитель клиентского сервиса"),
        (3, "Игорь Лебедев", "manager@magi.by", "operator", "Клиентский сервис", "Менеджер по клиентам"),
        (4, "Дмитрий Круглов", "head.production@magi.by", "head", "Производство", "Руководитель производства"),
        (5, "Ольга Миронова", "head.finance@magi.by", "head", "Финансы и люди", "Руководитель финансов и HR"),
        (6, "Марина Зайцева", "analyst@magi.by", "analyst", "Компания", "Аналитик по данным"),
    ]
    conn.executemany(
        "INSERT INTO users (id, name, email, role, team, title) VALUES (?, ?, ?, ?, ?, ?)",
        users,
    )

    conn.executemany(
        "INSERT INTO topics (key, name, sla_hours, description) VALUES (?, ?, ?, ?)",
        TOPICS,
    )

    conn.executemany(
        "INSERT INTO kb (topic, question, answer, keywords) VALUES (?, ?, ?, ?)",
        [
            ("delivery", "Сколько идёт доставка?", "По Минску доставляем за 1 день, по Беларуси — за 1–2 дня. Курьер по Минску стоит 12 BYN, самовывоз бесплатный.", "доставка,курьер,гомель,минск,пункт выдачи,когда привез,привезете"),
            ("production", "Какой срок производства?", "Фотокниги печатаем за 1 рабочий день. Если заказ подтверждён до 16:00, он будет готов завтра.", "срок,готовность,когда будет,успеет,производство,сколько дней,завтра"),
            ("price_book", "Сколько стоит фотокнига?", "Фотокнига Classic 20×20 — от 290 BYN, Premium 21×30 — от 620 BYN, Mini 15×15 — от 160 BYN. Точная цена зависит от количества страниц.", "цена,стоимость,сколько стоит,фотокнига,прайс,premium,classic,mini"),
            ("price_other", "Сколько стоит календарь, холст или печать?", "Календарь настенный — от 75 BYN, холст 40×60 — от 180 BYN, печать фото 10×15 — от 45 BYN.", "календарь,холст,печать,фотографии,цена,стоимость"),
            ("payment", "Как можно оплатить?", "Оплатить можно картой онлайн или при получении. Для индивидуальных заказов берём предоплату 50%.", "оплата,карта,предоплата,рассрочка,наличные"),
            ("quality", "Что делать, если брак?", "Брак переделываем бесплатно. Напишите номер заказа — менеджер согласует замену.", "брак,возврат,переделать,испортили,недоволен,плохо напечатали"),
            ("discount", "Есть ли скидка?", "На второй заказ в течение 30 дней действует скидка 10%. Персональные условия согласует менеджер.", "скидка,промокод,дешевле,акция,второй заказ"),
            ("pickup", "Где забрать заказ?", "Самовывоз: Минск, ул. Тимирязева 65Б, пн–сб с 9:00 до 20:00. Также работают пункты в Гомеле и Бресте.", "самовывоз,адрес,забрать,пункт выдачи,офис,пвз"),
            ("custom", "Можно сделать нестандартный заказ?", "Индивидуальный макет и нестандартный размер делаем от 3 дней. Менеджер уточнит детали и стоимость.", "индивидуальный,макет,размер,свадьба,нестандарт,свой дизайн"),
            ("docs", "Можно получить счёт и договор?", "Да, выставим счёт и пришлём договор в течение рабочего дня. Напишите реквизиты компании.", "счёт,счет,договор,закрывающие,реквизиты,бухгалтерия"),
            ("partnership", "Работаете с компаниями?", "Да, для B2B — оптовые цены и отсрочка по договору. Передам менеджеру по партнёрам.", "b2b,опт,партнер,компания,сотрудничество,корпоратив"),
        ],
    )

    conn.executemany(
        "INSERT INTO templates (topic, title, body) VALUES (?, ?, ?)",
        [
            ("order_status", "Статус из ERP", "Здравствуйте, {name}! Ваш заказ «{product}» — {order_status}. Обещанный срок — {promised}. Успеваем."),
            ("delivery", "Срок доставки", "Здравствуйте, {name}! По Минску доставляем за 1 день, по Беларуси — за 1–2 дня. Курьер — 12 BYN, самовывоз бесплатный."),
            ("quality", "Брак → перепечатка", "{name}, очень жаль, что так вышло. Переделаем бесплатно. Уточните, пожалуйста, номер заказа и что именно повреждено — согласую перепечатку."),
            ("discount", "Скидка на повтор", "{name}, на второй заказ в течение 30 дней действует скидка 10%. Промокод отправил в чат."),
            ("payment", "Оплата", "{name}, оплатить можно картой онлайн или при получении. Для индивидуальных заказов — предоплата 50%. Ссылку пришлю в чат."),
            ("pickup", "ПВЗ", "{name}, самовывоз: Минск, ул. Тимирязева 65Б, пн–сб 9:00–20:00. Заказ уже ждёт вас."),
            ("complaint", "Жалоба → менеджер", "{name}, спасибо, что написали. Передаю вопрос менеджеру — он подключится в течение 15 минут и поможет."),
            ("docs", "Счёт и договор", "{name}, выставим счёт и пришлём договор в течение рабочего дня. Уточните реквизиты компании, пожалуйста."),
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
    tags_pool = ["", "", "", "повторный", "VIP", "подарок", "семья", "свадьба", "дети", "опт"]
    sources = ["google", "instagram", "telegram", "email", "рекомендация", "наружная реклама"]

    for i in range(190):
        if i % 2 == 0:
            name = f"{female_first[(i // 2) % len(female_first)]} {female_last[(i * 3 + 1) % len(female_last)]}"
        else:
            name = f"{male_first[(i // 2) % len(male_first)]} {male_last[(i * 3 + 4) % len(male_last)]}"
        channel = CHANNELS[i % len(CHANNELS)]
        status = statuses[i % len(statuses)]
        owner = 3 if i % 5 else 2
        days_ago = rng.randint(0, 60)
        if status == "new":
            days_ago = rng.randint(0, 5)
        conn.execute(
            """INSERT INTO clients
               (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'Клиентский сервис', ?, '', ?)""",
            (name, f"+375 {rng.choice(['29', '33', '25', '44'])} {100 + i:03d}-{10 + i % 80:02d}-{20 + i % 70:02d}",
             f"client{i + 10}@example.by", cities[i % len(cities)], channel, sources[i % len(sources)], status,
             1 if i % 17 else 0, owner, tags_pool[i % len(tags_pool)], iso(now - timedelta(days=days_ago))),
        )

    products = [
        ("Фотокнига Premium 21×30", 620.0, 0.52),
        ("Фотокнига Classic 20×20", 290.0, 0.48),
        ("Фотокнига Mini 15×15", 160.0, 0.45),
        ("Календарь настенный", 75.0, 0.5),
        ("Печать фотографий 10×15", 45.0, 0.55),
        ("Холст 40×60", 180.0, 0.5),
    ]
    product_weights = [22, 30, 10, 14, 14, 10]

    def add_order(client_id: int, created: datetime, *, status: str | None = None, forced_late: str | None = None) -> None:
        product, base, margin = rng.choices(products, weights=product_weights, k=1)[0]
        amount = round(base * rng.uniform(0.9, 1.3), 2)
        cost = round(amount * margin * rng.uniform(0.92, 1.08), 2)
        channel = CHANNELS[rng.randrange(len(CHANNELS))]
        payment = rng.choice(["online", "online", "online", "cash", "invoice"])
        created = created - timedelta(minutes=rng.randint(0, 600))
        production_days = rng.randint(1, 3)
        promised = created + timedelta(days=production_days)
        if forced_late:
            # 2,4% заказов просрочено; причины: доставка 58%, модерация 25%, производство 17%
            delivered = promised + timedelta(days=rng.randint(1, 3))
            conn.execute(
                "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, delivered_at, defect, delay_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, 'delivered', ?, ?, ?, 0, ?)",
                (client_id, product, amount, cost, channel, payment, iso(created), iso(promised), iso(delivered), forced_late),
            )
            return
        if status is None:
            status = rng.choice(
                ["delivered"] * 66 + ["ready"] * 8 + ["in_production"] * 12 + ["moderation"] * 6 + ["new"] * 5 + ["delayed"] * 3
            )
        age_days = (now - created).days
        if age_days > 3 and status in ("new", "moderation", "in_production", "ready"):
            # старые заказы не висят открытыми — они уже доставлены
            status = "delivered"
        defect = 1 if rng.random() < 0.018 else 0
        if status == "delivered":
            late = rng.random() < 0.024
            delivered = promised + timedelta(hours=rng.randint(4, 30)) if late else promised - timedelta(hours=rng.randint(0, 20))
            conn.execute(
                "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, delivered_at, defect, delay_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (client_id, product, amount, cost, channel, payment, status, iso(created), iso(promised), iso(delivered), defect),
            )
        elif status == "delayed":
            conn.execute(
                "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, delivered_at, defect, delay_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, 'in_production', ?, ?, ?, ?, ?)",
                (client_id, product, amount, cost, channel, payment, iso(created), iso(promised), None, defect,
                 rng.choices(["delivery", "moderation", "production"], weights=[58, 25, 17], k=1)[0]),
            )
        else:
            conn.execute(
                "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, delivered_at, defect, delay_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
                (client_id, product, amount, cost, channel, payment, status, iso(created), iso(promised), defect),
            )

    # герой-заказы Марии
    hero_orders = [
        ("Фотокнига Premium 21×30", 620, 322, "in_production", now - timedelta(days=1), now + timedelta(days=2), None),
        ("Фотокнига Classic 20×20", 370, 185, "delivered", now - timedelta(days=45), now - timedelta(days=43), now - timedelta(days=43)),
        ("Печать фотографий 10×15", 250, 128, "delivered", now - timedelta(days=70), now - timedelta(days=69), now - timedelta(days=69)),
    ]
    for product, amount, cost, status, created, promised, delivered in hero_orders:
        conn.execute(
            "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, delivered_at, defect, delay_reason) "
            "VALUES (1, ?, ?, ?, 'telegram', 'online', ?, ?, ?, ?, 0, NULL)",
            (product, amount, cost, status, iso(created), iso(promised), iso(delivered) if delivered else None),
        )

    # 13 намеренно просроченных заказов (причины 58/25/17) + основной поток
    late_clients = rng.sample(range(11, 201), 13)
    for i, client_id in enumerate(late_clients):
        cause = "delivery" if i < 7 else ("moderation" if i < 10 else "production")
        add_order(client_id, now - timedelta(days=rng.randint(3, 12)), forced_late=cause)
    for client_id in range(2, 201):
        order_count = 1 if rng.random() < 0.25 else 3 + (1 if rng.random() < 0.5 else 0) + (1 if rng.random() < 0.2 else 0)
        for _ in range(order_count):
            status = None
            # 25% заказов — свежие (акция к 14 ноября): оборот и нагрузка растут
            days_ago = rng.choice([rng.randint(0, 11)] * 3 + [rng.randint(12, 90)])
            if client_id > 100:
                status = None
            add_order(client_id, now - timedelta(days=days_ago), status=status)

    conn.execute(
        """UPDATE clients SET ltv = COALESCE(
             (SELECT ROUND(SUM(amount), 2) FROM orders WHERE orders.client_id = clients.id), 0)"""
    )
    conn.execute(
        "UPDATE clients SET tags = TRIM(tags || ',VIP', ',') WHERE ltv >= 900 AND tags NOT LIKE '%VIP%'"
    )
    # Telegram-демо: два клиента уже «в боте»
    conn.execute("UPDATE clients SET tg_handle = '7000000001' WHERE id = 1")
    conn.execute("UPDATE clients SET tg_handle = '7000000002' WHERE id = 3")

    # ---------------------------------------------------------------- станки
    conn.executemany(
        "INSERT INTO machines (id, name, kind, capacity_min_per_day, status, downtime_min_month) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "Print HP-1", "Цифровая печать", 480, "ok", 140),
            (2, "Print HP-2", "Цифровая печать", 480, "ok", 90),
            (3, "Laminator L1", "Ламинация", 360, "warn", 260),
            (4, "Bind B1", "Переплёт", 300, "ok", 60),
            (5, "Cut C1", "Резка", 240, "ok", 40),
        ],
    )
    weekly_capacity = (480 + 480 + 360 + 300 + 240) * 5
    week_ratios = [0.50, 0.95, 1.00, 1.04, 1.08, 1.11]  # Н6 = +11% — риск перегрузки
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for w, ratio in enumerate(week_ratios):
        target = int(weekly_capacity * ratio)
        week_start = monday + timedelta(days=7 * w)
        remaining = target
        job_no = 0
        while remaining > 0:
            job_no += 1
            est = min(remaining, rng.choice([60, 90, 120, 150, 180, 240]))
            remaining -= est
            machine_id = rng.randint(1, 5)
            planned = week_start + timedelta(days=rng.randint(0, 5), minutes=rng.randint(480, 1100))
            if w == 0 and job_no % 3 == 0:
                status, finished = "running", None
            elif w == 0 and job_no % 3 == 1:
                status, finished = "done", iso(planned + timedelta(minutes=est))
            else:
                status, finished = "queued", None
            conn.execute(
                "INSERT INTO machine_jobs (machine_id, order_id, est_minutes, status, planned_start, finished_at) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (machine_id, est, status, iso(planned), finished),
            )

    # часть заданий текущей недели привязываем к живым заказам в работе
    live_orders = [r["id"] for r in conn.execute(
        "SELECT id FROM orders WHERE status IN ('in_production','moderation','new') ORDER BY id LIMIT 20"
    ).fetchall()]
    if live_orders:
        current_jobs = conn.execute(
            "SELECT id FROM machine_jobs WHERE planned_start >= ? AND status != 'done' ORDER BY id LIMIT ?",
            (iso(monday), len(live_orders)),
        ).fetchall()
        for i, job in enumerate(current_jobs):
            conn.execute("UPDATE machine_jobs SET order_id = ? WHERE id = ?", (live_orders[i % len(live_orders)], job["id"]))

    # ------------------------------------------------------------- разговоры
    channel_names = {"site": "Сайт", "telegram": "Telegram", "email": "Почта", "instagram": "Instagram"}
    topic_questions = {
        "greeting": "Здравствуйте! Подскажите, где можно уточнить статус заказа?",
        "order_status": "Здравствуйте! Мой заказ ещё не пришёл. Что с ним?",
        "price_book": "Сколько стоит фотокнига Premium 21×30?",
        "price_other": "Подскажите цену на холст 40×60?",
        "delivery": "Сколько идёт доставка в Гомель?",
        "payment": "Можно оплатить картой при получении?",
        "pickup": "Где забрать заказ самовывозом?",
        "production": "Какой сейчас срок производства фотокниг?",
        "discount": "Есть ли скидка на второй заказ?",
        "custom": "Нужна фотокнига нестандартного размера. Возможно?",
        "complaint": "Это уже второй раз, когда вы задерживаете заказ. Очень недовольна!",
        "return": "Хочу вернуть заказ и получить деньги обратно.",
        "quality": "В книге две страницы с полосами. Это брак?",
        "docs": "Выставите, пожалуйста, счёт на компанию.",
        "promo": "Какая сейчас действует акция?",
        "partnership": "Мы типография из Бреста, обсудить сотрудничество.",
        "other": "Здравствуйте, вопрос по заказу.",
    }
    topic_answers = {
        "greeting": "Здравствуйте, {name}! Я Magi, помощник клиентского сервиса. Подскажу по заказу, доставке, ценам и срокам. Чем помочь?",
        "order_status": "{name}, заказ «{product}» — {status}. Обещанный срок — {promised}.",
        "price_book": "Фотокнига Classic 20×20 — от 290 BYN, Premium 21×30 — от 620 BYN, Mini 15×15 — от 160 BYN. Точная цена зависит от количества страниц.",
        "price_other": "Холст 40×60 — от 180 BYN, календарь — от 75 BYN, печать фото 10×15 — от 45 BYN.",
        "delivery": "По Минску доставляем за 1 день, по Беларуси — за 1–2 дня. Курьер — 12 BYN, самовывоз бесплатный.",
        "payment": "Оплатить можно картой онлайн или при получении. Для индивидуальных заказов — предоплату 50%.",
        "pickup": "Самовывоз: Минск, ул. Тимирязева 65Б, пн–сб с 9:00 до 20:00.",
        "production": "Фотокниги печатаем за 1 рабочий день. Заказ подтверждён до 16:00 — готов завтра.",
        "discount": "На второй заказ в течение 30 дней действует скидка 10%.",
        "custom": "Индивидуальный макет делаем от 3 дней. Менеджер уточнит детали и стоимость.",
        "complaint": "{name}, очень жаль, что так вышло. Передаю вопрос менеджеру — он подключится в течение 15 минут.",
        "return": "{name}, возврат оформлю через менеджера. Он свяжется в течение 15 минут и предложит решение.",
        "quality": "Брак переделываем бесплатно. Уточните номер заказа — менеджер согласует замену.",
        "docs": "Выставим счёт и пришлём договор в течение рабочего дня. Уточните реквизиты, пожалуйста.",
        "promo": "Сейчас действует скидка 10% на второй заказ и сезонные цены на календари.",
        "partnership": "Для B2B у нас оптовые цены и отсрочка по договору. Передам менеджеру по партнёрам.",
        "other": "{name}, уточню этот вопрос у менеджера — он подключится в течение 15 минут.",
    }
    human_topics = {"complaint", "return", "partnership", "custom"}
    confidence_by_topic = {"order_status": 0.93, "price_book": 0.88, "price_other": 0.9, "delivery": 0.9,
                           "payment": 0.86, "pickup": 0.9, "production": 0.88, "discount": 0.74, "greeting": 0.82}

    def add_conversation(client_id: int, topic: str, minutes_ago: int, *, status: str, mode: str,
                         assignee_id: int, first_in_sla: bool, handoff_reason: str | None = None,
                         extra_messages: list[dict] | None = None, subject: str | None = None) -> int:
        client = dict(conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone())
        channel = client["channel"]
        created = now - timedelta(minutes=minutes_ago)
        _, sla_hours = TOPIC_BY_KEY[topic]
        sla_due = created + timedelta(hours=sla_hours)
        first_response = created + timedelta(minutes=rng.randint(2, 55)) if first_in_sla else sla_due + timedelta(minutes=rng.randint(10, 240))
        resolved = created + timedelta(hours=rng.randint(1, 30)) if status == "closed" else None
        cur = conn.execute(
            """INSERT INTO conversations
               (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled,
                handoff_reason, sla_due_at, first_response_at, resolved_at, outcome, last_message_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'Клиентский сервис', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_id, channel, subject or topic_questions[topic][:60], topic, status, mode, assignee_id,
             1 if mode == "magi" else 0, handoff_reason, iso(sla_due), iso(first_response), iso(resolved) if resolved else None,
             ("solved" if not handoff_reason else "handoff") if status == "closed" else None,
             iso(created + timedelta(minutes=6)), iso(created)),
        )
        conv_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, 'lead', ?, ?)",
            (conv_id, topic_questions[topic], iso(created)),
        )
        if mode == "magi":
            answer = topic_answers[topic].format(
                name=client["name"].split()[0],
                product="Фотокнига Classic 20×20",
                status="в производстве",
                promised=first_response.strftime("%d.%m"),
            )
            conn.execute(
                "INSERT INTO messages (conversation_id, author, body, intent, confidence, provider, created_at) VALUES (?, 'magi', ?, ?, ?, 'local', ?)",
                (conv_id, answer, topic, confidence_by_topic.get(topic, 0.85), iso(first_response)),
            )
        else:
            agent_body = topic_answers[topic].format(
                name=client["name"].split()[0], product="заказ", status="готов", promised=first_response.strftime("%d.%m"),
            )
            conn.execute(
                "INSERT INTO messages (conversation_id, author, body, intent, provider, created_at) VALUES (?, 'agent', ?, ?, 'human', ?)",
                (conv_id, agent_body, topic, iso(first_response)),
            )
        for m in (extra_messages or []):
            conn.execute(
                "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (conv_id, m["author"], m["body"], iso(now - timedelta(minutes=m.get("minutes_ago", minutes_ago - 5)))),
            )
        if mode == "human" and handoff_reason:
            from .magi import summary_for_manager

            client_row = dict(client)
            orders = [dict(r) for r in conn.execute(
                "SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC", (client_id,)
            ).fetchall()]
            msgs = [dict(r) for r in conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,)
            ).fetchall()]
            text = summary_for_manager(
                {"topic": topic, "handoff_reason": handoff_reason, "sla_due_at": iso(sla_due)},
                client_row, orders, msgs, TOPIC_BY_KEY[topic][0],
            )
            conn.execute("UPDATE conversations SET summary = ? WHERE id = ?", (text, conv_id))
        return conv_id

    # герой-диалоги (как раньше)
    add_conversation(1, "order_status", 14, status="open", mode="magi", assignee_id=3, first_in_sla=True, subject="Заказ к дню рождения")
    add_conversation(2, "delivery", 70, status="waiting", mode="human", assignee_id=3, first_in_sla=True,
                     handoff_reason="Нужен нестандартный сценарий доставки", subject="Доставка в Гомель")
    add_conversation(3, "quality", 135, status="waiting", mode="human", assignee_id=3, first_in_sla=True,
                     handoff_reason="Жалоба на качество печати", subject="Брак в фотокниге")
    add_conversation(4, "price_other", 8, status="open", mode="magi", assignee_id=3, first_in_sla=True, subject="Цена на холст")
    add_conversation(5, "price_book", 1500, status="closed", mode="magi", assignee_id=3, first_in_sla=True, subject="Календари")
    add_conversation(6, "order_status", 30, status="open", mode="magi", assignee_id=3, first_in_sla=True, subject="Статус заказа")
    add_conversation(7, "discount", 195, status="waiting", mode="human", assignee_id=2, first_in_sla=True,
                     handoff_reason="Персональные условия согласует руководитель", subject="Персональная скидка")
    add_conversation(8, "greeting", 12, status="open", mode="magi", assignee_id=3, first_in_sla=True, subject="Новый заказ")
    add_conversation(9, "custom", 62, status="open", mode="magi", assignee_id=2, first_in_sla=True, subject="Свадебная книга")
    add_conversation(10, "return", 2900, status="closed", mode="human", assignee_id=2, first_in_sla=False, subject="Возврат")

    # генерация 300+ обращений
    topic_keys = [t[0] for t in TOPICS]
    topic_weights = [6, 12, 10, 8, 11, 9, 7, 9, 6, 4, 3, 2, 4, 3, 3, 2, 6]
    topic_pool = rng.choices(topic_keys, weights=topic_weights, k=306)
    for i, topic in enumerate(topic_pool):
        client_id = 1 + (i * 7 + 3) % 200
        minutes_ago = rng.randint(10, 60 * 24 * 30)
        roll = rng.random()
        if topic in human_topics:
            status = "closed" if roll < 0.7 else "waiting"
            mode = "human"
            handoff_reason = rng.choice(["Жалоба на качество", "Клиент просит человека", "Персональные условия",
                                         "Индивидуальный макет", "Возврат по договору"])
        else:
            mode = "magi" if roll < 0.78 else "human"
            if mode == "magi":
                status = "closed" if roll < 0.6 else "open"
                handoff_reason = None
            else:
                status = "waiting" if roll < 0.85 else "closed"
                handoff_reason = "Magi не уверен в ответе"
        first_in_sla = rng.random() < 0.92
        assignee = 3 if rng.random() < 0.75 else 2
        add_conversation(client_id, topic, minutes_ago, status=status, mode=mode,
                         assignee_id=assignee, first_in_sla=first_in_sla, handoff_reason=handoff_reason)

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

    # --------------------------------------------------------------- ПВЗ
    ready_orders = conn.execute(
        "SELECT id, created_at FROM orders WHERE status = 'ready' ORDER BY id LIMIT 5"
    ).fetchall()
    for row in ready_orders:
        ready = parse_dt(row["created_at"]) + timedelta(days=1)
        conn.execute(
            "INSERT INTO pickups (order_id, location, ready_at, expires_at, reminded) VALUES (?, ?, ?, ?, ?)",
            (row["id"], rng.choice(["Минск, Тимирязева 65Б", "Гомель, просп. Ленина 12", "Брест, ул. Московская 210"]),
             iso(ready), iso(ready + timedelta(days=5)), 1 if rng.random() < 0.4 else 0),
        )

    # ------------------------------------------------------------------ HR
    hr_plan = [
        ("Производство", [("Оператор печатной машины", 5), ("Переплётчик", 4), ("Резчик", 2), ("Ламинировщик", 2), ("Кладовщик", 1)]),
        ("Клиентский сервис", [("Менеджер по клиентам", 4), ("Руководитель отдела", 1), ("Модератор", 1)]),
        ("Модерация", [("Модератор", 3)]),
        ("Финансы и люди", [("Бухгалтер", 2), ("Кассир", 1), ("HR-специалист", 1)]),
        ("Маркетинг", [("Маркетолог", 1)]),
        ("ИТ", [("Инженер по системам", 1)]),
    ]
    emp_names = ["Пётр Баранцев", "Светлана Гурко", "Алексей Дрозд", "Нина Вергей", "Олег Кухарев", "Юлия Савчук",
                 "Вадим Пинчук", "Алина Лойко", "Руслан Мисюченко", "Дарья Хилько", "Егор Шамец", "Вера Кохно",
                 "Станислав Ровдо", "Полина Титок", "Артур Гайдук", "Ксения Бабич", "Максим Сурганов",
                 "Ирина Качан", "Денис Ветохин", "Лариса Смолич", "Антон Довнар", "Оксана Лукашевич",
                 "Павел Гончарук", "Рита Абламейко", "Сергей Пичук", "Жанна Климович", "Никита Достан",
                 "Маргарита Урбан"]
    emp_idx = 0
    employee_ids = []
    for team, positions in hr_plan:
        for position, count in positions:
            for _ in range(count):
                name = emp_names[emp_idx % len(emp_names)]
                emp_idx += 1
                status = "active"
                if emp_idx % 11 == 0:
                    status = "vacation"
                elif emp_idx % 13 == 0:
                    status = "sick"
                cur = conn.execute(
                    "INSERT INTO hr_employees (name, team, position, hired_at, status, planned_hours_week) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, team, position, iso(now - timedelta(days=rng.randint(90, 1200))), status, 40),
                )
                employee_ids.append((int(cur.lastrowid), team))
    # штат = 28, план — 31 (3 вакансии → обеспеченность 90%)
    for team, position in [("Производство", "Оператор печатной машины"), ("Клиентский сервис", "Менеджер по клиентам"),
                           ("Финансы и люди", "Бухгалтер"), ("Модерация", "Модератор")]:
        conn.execute(
            "INSERT INTO vacancies (team, position, opened_at, candidates, status) VALUES (?, ?, ?, ?, 'open')",
            (team, position, iso(now - timedelta(days=rng.randint(5, 40))), rng.randint(0, 6)),
        )
    for emp_id, team in employee_ids:
        for d in range(7):
            day = (now - timedelta(days=d)).date()
            planned = 8.0
            roll = rng.random()
            if roll < 0.04:
                fact, note = 0.0, rng.choice(["Отпуск", "Больничный"])
            elif roll < 0.1:
                fact, note = rng.choice([6.0, 7.0]), "Сокращённый день"
            else:
                fact, note = 8.0, ""
            conn.execute(
                "INSERT INTO shifts (employee_id, day, planned_hours, fact_hours, note) VALUES (?, ?, ?, ?, ?)",
                (emp_id, day.isoformat(), planned, fact, note),
            )

    # --------------------------------------------------------------- 1С
    months = ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
    plans = [68000, 71500, 74000, 79000, 86000, 94000]
    today_day = utcnow().day
    current_month = utcnow().strftime("%Y-%m")
    for idx, month in enumerate(months):
        plan_rev = plans[idx]
        if month == current_month:
            # факт текущего месяца сверяется с CRM (расхождение ~2% — предоплаты)
            crm_rev = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM orders WHERE created_at >= ?",
                (iso(utcnow().replace(day=1, hour=0, minute=0, second=0)),),
            ).fetchone()[0]
            fact_rev = round(crm_rev * 0.98, 0)
            fact_costs = round(fact_rev * 0.55, 0)
            fact_cash = round(fact_rev * 0.92, 0)
        else:
            fact_rev = round(plan_rev * rng.uniform(0.97, 1.04), 0)
            fact_costs = round(plan_rev * 0.6 * rng.uniform(0.96, 1.05), 0)
            fact_cash = round(fact_rev * rng.uniform(0.9, 1.0), 0)
        conn.execute(
            "INSERT INTO finance_periods (month, plan_revenue, fact_revenue, plan_costs, fact_costs, plan_cash, fact_cash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (month, plan_rev, fact_rev, round(plan_rev * 0.6, 0), fact_costs, round(plan_rev * 0.95, 0), fact_cash),
        )
    counterparties = [
        ("ООО «Бумажный двор»", "поставщик", -4200),
        ("Типография «Альфа-Принт»", "поставщик", -1800),
        ("ООО «Краски и тонеры»", "поставщик", -960),
        ("Курьерская служба «Почта BY»", "подрядчик", -310),
        ("ИП Ремизович (доставка)", "подрядчик", -180),
        ("ООО «Ритейл Партнёр»", "клиент (B2B)", 5400),
        ("ЗАО «Фото-Маркет»", "клиент (B2B)", 2200),
        ("ООО «Позитроника»", "клиент (B2B)", 1350),
    ]
    for name, kind, balance in counterparties:
        conn.execute(
            "INSERT INTO counterparties (name, kind, balance, updated_at) VALUES (?, ?, ?, ?)",
            (name, kind, balance, iso(now - timedelta(hours=rng.randint(1, 72)))),
        )
    expense_categories = ["Бумага и расходники", "Зарплата", "Аренда", "Доставка", "Краски и тонеры", "Реклама"]
    income_categories = ["Оплата розница", "Оплата B2B", "Предоплата"]
    for month in months:
        max_day = today_day if month == current_month else 28
        for kind, categories in (("debit", income_categories), ("credit", expense_categories)):
            for category in categories:
                amount = round(rng.uniform(800, 9000), 2)
                day = min(max_day, rng.randint(1, 28))
                conn.execute(
                    "INSERT INTO finance_entries (period_month, kind, counterparty_id, category, amount, entry_date) VALUES (?, ?, ?, ?, ?, ?)",
                    (month, kind, rng.randint(1, len(counterparties)), category, amount, f"{month}-{day:02d}"),
                )

    # ------------------------------------------------------------- KPI-паспорта
    conn.executemany(
        "INSERT INTO kpi_registry (key, name, unit, formula, source, target, direction, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("revenue_month", "Оборот за месяц", "BYN", "SUM(orders.amount) за календарный месяц", "ERP · orders", 94000, "up", "Финансы и люди"),
            ("gross_margin", "Валовая маржа", "%", "(SUM(amount) - SUM(cost)) / SUM(amount) · 100", "ERP · orders", 45, "up", "Финансы и люди"),
            ("on_time", "Заказы в срок", "%", "заказы с delivered_at ≤ promised_at / все доставленные · 100", "ERP · orders", 97.6, "up", "Производство"),
            ("late_share", "Просроченные заказы", "%", "заказы позже обещанного срока / все заказы в сроке · 100", "ERP · orders", 2.4, "down", "Производство"),
            ("defect_rate", "Брак и перепечатка", "%", "заказы с defect=1 / все заказы · 100", "ERP · orders", 1.8, "down", "Производство"),
            ("sla_rate", "Ответ в SLA", "%", "обращения с первым ответом ≤ SLA темы / все отвеченные · 100", "CRM · conversations", 92, "up", "Клиентский сервис"),
            ("ai_share", "Сценарии ИИ", "%", "обращения, закрытые Magi без человека / все обращения · 100", "CRM · conversations", 68, "up", "Клиентский сервис"),
            ("repeat_rate", "Повторные покупки", "%", "клиенты с ≥2 заказами / клиенты с ≥1 заказом · 100", "ERP · orders", 35, "up", "Клиентский сервис"),
            ("new_clients", "Новые клиенты", "шт", "COUNT(clients) за 30 дней", "CRM · clients", 60, "up", "Клиентский сервис"),
            ("active_clients", "Активные клиенты", "шт", "клиенты с заказом за 90 дней", "ERP · orders", 120, "up", "Клиентский сервис"),
            ("avg_check", "Средний чек", "BYN", "SUM(amount) / COUNT(orders) за 30 дней", "ERP · orders", 240, "up", "Клиентский сервис"),
            ("load_risk", "Риск перегрузки", "%", "max(план производства недели / мощность) − 100 на горизонте 6 недель", "ERP · план станков", 0, "down", "Производство"),
            ("staff_coverage", "Обеспеченность персоналом", "%", "штат / штат+вакансии · 100", "HR · сотрудники, вакансии", 92, "up", "Финансы и люди"),
            ("cash_exec", "Исполнение БДДС", "%", "факт ДДС / план ДДС · 100, месяц", "1С · finance", 95, "up", "Финансы и люди"),
        ],
    )

    conn.executemany(
        "INSERT INTO decisions (kpi_key, problem, impact, cause, action, owner_id, due_at, priority, status, result_note, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("load_risk", "Перегрузка производства на Н5–Н6", "План превышает мощность на 11%", "Акция к 14 ноября добавила заказы",
             "Сместить 15% неприоритетных заказов на Н4 и открыть субботнюю смену", 4, iso(now + timedelta(days=5)), "high", "in_progress",
             "Смена согласована, перенос 40 заказов", 1, iso(now - timedelta(days=2)), iso(now - timedelta(hours=6))),
            ("sla_rate", "Ответ в SLA ниже цели по темам «Доставка» и «Оплата»", "8% обращений отвечают позже SLA", "Ночью и утром нет дежурного менеджера",
             "Включить автоответы Magi по этим темам и шаблоны в один клик", 2, iso(now + timedelta(days=3)), "normal", "open", "", 1, iso(now - timedelta(days=1)), iso(now - timedelta(days=1))),
            ("defect_rate", "Брак на ламинации вырос после смены рулона", "Доля перепечаток 2,6% против цели 1,8%", "Партия рулона L1 с браком",
             "Заменить поставщика рулона и ужесточить входной контроль", 4, iso(now + timedelta(days=7)), "normal", "open", "", 5, iso(now - timedelta(days=3)), iso(now - timedelta(days=3))),
        ],
    )

    rules_config = [
        ("route.auto_answer", "Автоответ Magi по каналам и темам", "route",
         {"channels": CHANNELS, "intents": ["greeting", "order_status", "price", "delivery", "payment", "pickup", "discount", "quality", "docs"]}),
        ("threshold.confidence", "Порог уверенности Magi", "threshold", {"value": 0.55}),
        ("trigger.complaint", "Жалоба или возврат → сразу человек", "trigger",
         {"keywords": ["брак", "возврат", "жалоб", "испортили", "плохо напечатали", "перепечат", "полосы", "недоволен", "вернуть деньги"]}),
        ("trigger.vip_discount", "VIP + персональная скидка → руководитель", "trigger", {"segments": "VIP", "keywords": ["персональн", "индивидуальн скидк", "спецуслов"]}),
        ("sla.escalation", "Эскалация, когда SLA истёк", "sla", {"factor": 2.0}),
        ("reminder.pickup", "Напоминание о заказе в ПВЗ", "reminder", {"hours_before": 24, "max_reminders": 2}),
    ]
    for key, title, kind, config in rules_config:
        conn.execute(
            "INSERT INTO rules (key, title, kind, config, enabled, updated_by, updated_at) VALUES (?, ?, ?, ?, 1, 1, ?)",
            (key, title, kind, __import__("json").dumps(config, ensure_ascii=False), iso(now - timedelta(days=rng.randint(1, 20)))),
        )

    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("magi_enabled", "1"), ("confidence_threshold", "0.55"), ("auto_channels", "site,telegram,email,instagram")],
    )

    conn.executemany(
        "INSERT INTO audit (user_id, actor, action, entity, entity_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "Ирина Соколова", "auth.login", "user", "1", "Вход в систему", iso(now - timedelta(hours=2))),
            (3, "Игорь Лебедев", "magi.handoff", "conversation", "3", "Жалоба на качество печати", iso(now - timedelta(minutes=130))),
            (2, "Анна Петрова", "rules.update", "rule", "threshold.confidence", "Порог уверенности: 0.55", iso(now - timedelta(days=1))),
            (1, "Ирина Соколова", "decision.create", "decision", "1", "Перегрузка производства на Н5–Н6", iso(now - timedelta(days=2))),
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
