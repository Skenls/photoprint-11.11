"""Встроенная бухгалтерия «Magi Finance» вместо 1С-коннектора.

Принципы (ACCOUNTING_PLAN.md): двойная запись, неизменяемый журнал (только сторно),
жёсткая привязка проводок к заказам/клиентам/контрагентам, отчёты чистым SQL в реальном времени.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CHART: list[tuple[str, str, str]] = [
    # код, название, тип (asset/liability/revenue/expense)
    ("50", "Касса компании", "asset"),
    ("51", "Расчётные счета в банках", "asset"),
    ("57", "Переводы в пути (эквайринг, ЕРИП)", "asset"),
    ("10", "Материалы на складе", "asset"),
    ("20", "Основное производство", "asset"),
    ("43", "Готовая продукция", "asset"),
    ("60", "Расчёты с поставщиками", "liability"),
    ("62", "Расчёты с покупателями", "liability"),
    ("68", "Расчёты по налогам и сборам", "liability"),
    ("70", "Расчёты по оплате труда", "liability"),
    ("02", "Амортизация оборудования", "liability"),
    ("90.1", "Выручка от реализации", "revenue"),
    ("90.2", "Себестоимость продаж", "expense"),
    ("90.7", "Расходы на доставку и эквайринг", "expense"),
    ("26", "Общехозяйственные расходы", "expense"),
]

COMPANY = 'ООО «Фотопринт»'
COMPANY_UNP = "190000000"
MATERIAL_RATE = 0.55      # доля себестоимости, уходящая в материалы (Дт 20 Кт 10)
ACQUIRING_RATE = 0.025    # комиссия эквайринга


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> datetime:
    return datetime.now(timezone.utc)


def seed_accounts(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM acc_accounts").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO acc_accounts (code, name, type) VALUES (?, ?, ?)", CHART
    )


def next_number(conn, date: str) -> str:
    year = date[:4]
    seq = conn.execute(
        "SELECT COUNT(*) FROM acc_transactions WHERE number LIKE ?",
        (f"TR-{year}-%",),
    ).fetchone()[0] + 1
    while True:
        number = f"TR-{year}-{seq:06d}"
        if conn.execute("SELECT 1 FROM acc_transactions WHERE number = ?", (number,)).fetchone() is None:
            return number
        seq += 1


def post(conn, *, date: str, doc_type: str, doc_id: str | None, description: str,
         entries: list[dict], created_by: int | None = None,
         storno_of_id: int | None = None, created_at: str | None = None) -> int:
    """Атомарная операция: набор сбалансированных проводок. Баланс проверяется до записи."""
    total_debit = round(sum(e["amount"] for e in entries), 2)
    total_credit = round(sum(e["amount"] for e in entries), 2)
    if not entries or total_debit <= 0 or abs(total_debit - total_credit) > 0.005:
        raise ValueError(f"Проводки не сбалансированы: Дт {total_debit} != Кт {total_credit}")
    when = created_at or iso(now())
    cursor = conn.execute(
        "INSERT INTO acc_transactions (number, doc_type, doc_id, date, description, is_posted, storno_of_id, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (next_number(conn, date), doc_type, doc_id, date, description, storno_of_id, created_by, when),
    )
    tx_id = cursor.lastrowid
    for e in entries:
        if round(e["amount"], 2) <= 0:
            raise ValueError("Сумма проводки должна быть > 0")
        conn.execute(
            "INSERT INTO acc_entries (transaction_id, account_debit, account_credit, amount, currency, "
            "counterparty_id, client_id, order_id, cost_center, note) "
            "VALUES (?, ?, ?, ?, 'BYN', ?, ?, ?, ?, ?)",
            (tx_id, e["debit"], e["credit"], round(e["amount"], 2),
             e.get("counterparty_id"), e.get("client_id"), e.get("order_id"), e.get("cost_center", ""), e.get("note", "")),
        )
    return tx_id


def storno(conn, tx_id: int, created_by: int | None = None, reason: str = "") -> int:
    """Корректировка ошибки: зеркальная сторно-операция, исходные строки не изменяются."""
    tx = conn.execute("SELECT * FROM acc_transactions WHERE id = ?", (tx_id,)).fetchone()
    if tx is None:
        raise ValueError("Операция не найдена")
    if conn.execute(
        "SELECT 1 FROM acc_transactions WHERE storno_of_id = ?", (tx_id,)
    ).fetchone() is not None:
        raise ValueError("Сторно по этой операции уже есть")
    entries = []
    for row in conn.execute("SELECT * FROM acc_entries WHERE transaction_id = ?", (tx_id,)):
        entries.append({
            "debit": row["account_credit"], "credit": row["account_debit"],
            "amount": row["amount"], "counterparty_id": row["counterparty_id"],
            "client_id": row["client_id"], "order_id": row["order_id"],
            "cost_center": row["cost_center"], "note": "сторно",
        })
    description = f"Сторно {tx['number']}: {reason or tx['description']}"
    return post(
        conn, date=iso(now())[:10], doc_type="storno", doc_id=tx["doc_id"],
        description=description, entries=entries, created_by=created_by, storno_of_id=tx_id,
    )


# ------------------------------------------------------------------ проводки по событиям CRM

def _order_entries(order: dict, client_id: int | None) -> list[dict]:
    """Типовые проводки по завершённому заказу (оплата эквайрингом → выручка → себестоимость)."""
    amount = round(float(order.get("amount") or 0), 2)
    cost = round(float(order.get("cost") or 0), 2)
    materials = round(cost * MATERIAL_RATE, 2)
    fee = round(amount * ACQUIRING_RATE, 2)
    settle = round(amount - fee, 2)
    e = [
        {"debit": "57", "credit": "62", "amount": amount, "client_id": client_id,
         "order_id": order["id"], "note": "оплата эквайрингом"},
        {"debit": "51", "credit": "57", "amount": settle, "client_id": client_id,
         "order_id": order["id"], "note": "зачисление на р/с"},
        {"debit": "90.7", "credit": "57", "amount": fee, "order_id": order["id"],
         "note": f"комиссия эквайринга {ACQUIRING_RATE:.1%}"},
        {"debit": "62", "credit": "90.1", "amount": amount, "client_id": client_id,
         "order_id": order["id"], "note": "выручка от реализации"},
        {"debit": "90.2", "credit": "43", "amount": cost, "order_id": order["id"],
         "note": "себестоимость продаж"},
        {"debit": "43", "credit": "20", "amount": cost, "order_id": order["id"],
         "note": "выпуск готовой продукции"},
        {"debit": "20", "credit": "10", "amount": materials, "order_id": order["id"],
         "note": "списание материалов (бумага, расходники)"},
    ]
    return [row for row in e if row["amount"] > 0]


def dispatch_order(conn, order: dict, *, created_by: int | None = None) -> int | None:
    """Событие «заказ доставлен»: оплата + выручка + себестоимость одной операцией."""
    doc_id = f"order:{order['id']}"
    if conn.execute("SELECT 1 FROM acc_transactions WHERE doc_type = 'order_delivered' AND doc_id = ?", (doc_id,)).fetchone():
        return None
    client_id = order.get("client_id")
    date = (order.get("delivered_at") or order.get("promised_at") or iso(now()))[:10]
    return post(
        conn, date=date, doc_type="order_delivered", doc_id=doc_id,
        description=f"Заказ №{order['id']} «{order['product']}» — оплата и признание выручки",
        entries=_order_entries(order, client_id), created_by=created_by,
    )


def post_monthly_expenses(conn, *, months: list[str], created_by: int | None = None) -> list[int]:
    """Регулярные операции месяца: аренда, зарплата цеха, амортизация, софт."""
    demo = [
        ("rent", "26", "60", 8000, "Аренда производственного помещения", "Аренда"),
        ("payroll", "20", "70", 45000, "Сдельная оплата труда цеха печати", "зарплата"),
        ("depreciation", "20", "02", 6500, "Амортизация печатного оборудования", "амортизация"),
        ("software", "26", "60", 3200, "Софт и сервисы (CRM, бумага по постоплате)", "софт"),
        ("supplies", "26", "60", 2400, "Канцелярия, клининг, транспорт", "офис"),
    ]
    ids = []
    for month in months:
        for key, debit, credit, amount, description, center in demo:
            doc_id = f"month:{month}:{key}"
            if conn.execute("SELECT 1 FROM acc_transactions WHERE doc_type = 'period' AND doc_id = ?", (doc_id,)).fetchone():
                continue
            cp = conn.execute(
                "SELECT id FROM counterparties WHERE kind != 'client' ORDER BY id LIMIT 1"
            ).fetchone()
            ids.append(post(
                conn, date=f"{month}-28", doc_type="period", doc_id=doc_id,
                description=description,
                entries=[{"debit": debit, "credit": credit, "amount": amount,
                          "counterparty_id": cp["id"] if cp else None, "cost_center": center}],
                created_by=created_by,
            ))
    return ids


def ensure_demo_ledger(conn) -> dict:
    """Гарантирует: план счетов есть, завершённые заказы разнесены, расходы месяцев начислены."""
    seed_accounts(conn)
    posted = 0
    for order in conn.execute(
        "SELECT * FROM orders WHERE delivered_at IS NOT NULL ORDER BY id"
    ).fetchall():
        if dispatch_order(conn, dict(order)) is not None:
            posted += 1
    months = sorted({row[0] for row in conn.execute(
        "SELECT DISTINCT substr(created_at, 1, 7) FROM orders"
    ).fetchall()})
    months = months[-2:] if len(months) > 2 else months
    monthly = post_monthly_expenses(conn, months=months or [iso(now())[:7]])
    return {"orders_posted": posted, "period_posted": len(monthly)}


# ------------------------------------------------------------------ отчёты (чистый SQL, реальное время)

DEBIT_SIDE = {"asset", "expense"}


def osv(conn, date_from: str, date_to: str) -> dict:
    """Оборотно-сальдовая ведомость: сальдо на начало, обороты, сальдо на конец."""
    accounts = {row["code"]: dict(row) for row in conn.execute("SELECT * FROM acc_accounts").fetchall()}
    debits_before = {row["code"]: row["d"] for row in conn.execute(
        "SELECT e.account_debit AS code, SUM(e.amount) AS d FROM acc_entries e "
        "JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 AND t.date < ? GROUP BY 1",
        (date_from,),
    ).fetchall()}
    credits_before = {row["code"]: row["d"] for row in conn.execute(
        "SELECT e.account_credit AS code, SUM(e.amount) AS d FROM acc_entries e "
        "JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 AND t.date < ? GROUP BY 1",
        (date_from,),
    ).fetchall()}
    debits = {row["code"]: row["d"] for row in conn.execute(
        "SELECT account_debit AS code, SUM(amount) AS d FROM acc_entries e "
        "JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 AND t.date >= ? AND t.date <= ? GROUP BY 1",
        (date_from, date_to),
    ).fetchall()}
    credits = {row["code"]: row["d"] for row in conn.execute(
        "SELECT account_credit AS code, SUM(amount) AS d FROM acc_entries e "
        "JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 AND t.date >= ? AND t.date <= ? GROUP BY 1",
        (date_from, date_to),
    ).fetchall()}

    rows, total_open, total_debit, total_credit, total_close = [], 0.0, 0.0, 0.0, 0.0
    for code, acc in accounts.items():
        d0 = debits_before.get(code, 0.0) - credits_before.get(code, 0.0)  # + = актив
        opening = d0 if acc["type"] in DEBIT_SIDE else -d0
        dt_, kt = debits.get(code, 0.0), credits.get(code, 0.0)
        closing_raw = opening + (dt_ - kt) if acc["type"] in DEBIT_SIDE else opening - (dt_ - kt)
        rows.append({
            "code": code, "name": acc["name"], "type": acc["type"],
            "opening": round(opening, 2), "debit": round(dt_, 2),
            "credit": round(kt, 2), "closing": round(closing_raw, 2),
        })
        total_open += opening
        total_debit += dt_
        total_credit += kt
        total_close += closing_raw
    rows.sort(key=lambda r: r["code"])
    close_active = round(sum(r["closing"] for r in rows if r["type"] in DEBIT_SIDE), 2)
    close_passive = round(sum(r["closing"] for r in rows if r["type"] not in DEBIT_SIDE), 2)
    return {
        "rows": rows,
        "totals": {
            "opening": round(total_open, 2), "debit": round(total_debit, 2),
            "credit": round(total_credit, 2), "closing": round(total_close, 2),
            "assets": close_active, "passives": close_passive,
        },
        # Актив = Пассив (расходные счета закрывают выручку в пределах отчётного окна).
        "balanced": abs(close_active - close_passive) < 0.01 and round(total_debit, 2) == round(total_credit, 2),
    }


def pnl_and_cashflow(conn) -> dict:
    """P&L (метод начисления) и Cash Flow (кассовый метод) помесячно."""
    months = [row[0] for row in conn.execute(
        "SELECT DISTINCT substr(t.date, 1, 7) AS m FROM acc_transactions t "
        "WHERE t.is_posted = 1 ORDER BY m"
    ).fetchall()]
    agg = {}
    for row in conn.execute(
        "SELECT substr(t.date, 1, 7) AS m, e.account_debit, e.account_credit, SUM(e.amount) AS s "
        "FROM acc_entries e JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 GROUP BY 1, 2, 3"
    ).fetchall():
        agg.setdefault(row["m"], {"revenue": 0.0, "cogs": 0.0, "fees": 0.0, "overhead": 0.0,
                                  "cash_in": 0.0, "cash_out": 0.0})
        m = agg[row["m"]]
        if row["account_credit"] == "90.1":
            m["revenue"] += row["s"]
        elif row["account_debit"] == "90.2":
            m["cogs"] += row["s"]
        elif row["account_debit"] in ("90.7", "26"):
            m["fees" if row["account_debit"] == "90.7" else "overhead"] += row["s"]
        if row["account_debit"] in ("50", "51"):
            m["cash_in"] += row["s"]
        if row["account_credit"] in ("50", "51"):
            m["cash_out"] += row["s"]
    pnl = []
    for month in months:
        m = agg.get(month, {})
        revenue, cogs = round(m.get("revenue", 0), 2), round(m.get("cogs", 0), 2)
        fees, overhead = round(m.get("fees", 0), 2), round(m.get("overhead", 0), 2)
        profit = round(revenue - cogs - fees - overhead, 2)
        pnl.append({
            "month": month, "revenue": revenue, "cogs": cogs, "fees": fees,
            "overhead": overhead, "profit": profit,
            "margin": round(profit / revenue * 100, 1) if revenue else 0,
            "cash_in": round(m.get("cash_in", 0), 2), "cash_out": round(m.get("cash_out", 0), 2),
            "net_cash": round(m.get("cash_in", 0) - m.get("cash_out", 0), 2),
        })
    return {"months": pnl}


def aging(conn) -> dict:
    """Дебиторка (62) и кредиторка (60) по срокам: до 7 / 8-14 / 15-30 / 30+ дней."""
    def _bucket(days: int) -> str:
        if days <= 7:
            return "d7"
        if days <= 14:
            return "d14"
        if days <= 30:
            return "d30"
        return "d30plus"

    def collect(sql: str, invert: bool = False):
        out = []
        for row in conn.execute(sql).fetchall():
            balance = round((row["cr"] - row["dr"]) if invert else (row["dr"] - row["cr"]), 2)
            if abs(balance) < 0.01:
                continue
            age = (now().replace(tzinfo=None) - datetime.fromisoformat(row["oldest"])).days if row["oldest"] else 0
            item = dict(row)
            item["balance"] = balance
            item["bucket"] = _bucket(max(0, age))
            out.append(item)
        return out

    ar = collect(
        "SELECT c.id, c.name, SUM(CASE WHEN e.account_debit = '62' THEN e.amount ELSE 0 END) AS dr, "
        "SUM(CASE WHEN e.account_credit = '62' THEN e.amount ELSE 0 END) AS cr, MIN(t.date) AS oldest "
        "FROM acc_entries e JOIN acc_transactions t ON t.id = e.transaction_id "
        "JOIN clients c ON c.id = e.client_id WHERE t.is_posted = 1 AND e.client_id IS NOT NULL "
        "AND (e.account_debit = '62' OR e.account_credit = '62') GROUP BY c.id"
    )
    ap = collect(
        "SELECT cp.id, cp.name, SUM(CASE WHEN e.account_credit = '60' THEN e.amount ELSE 0 END) AS cr, "
        "SUM(CASE WHEN e.account_debit = '60' THEN e.amount ELSE 0 END) AS dr, MIN(t.date) AS oldest "
        "FROM acc_entries e JOIN acc_transactions t ON t.id = e.transaction_id "
        "JOIN counterparties cp ON cp.id = e.counterparty_id WHERE t.is_posted = 1 "
        "AND e.counterparty_id IS NOT NULL AND (e.account_debit = '60' OR e.account_credit = '60') GROUP BY cp.id",
        invert=True,
    )
    return {"receivables": ar, "payables": ap}


def auditor(conn) -> list[dict]:
    """Magi Auditor: аномалии учёта — отрицательная маржа, зависший эквайринг, задвоенные оплаты."""
    anomalies = []
    for row in conn.execute(
        "SELECT order_id, "
        "SUM(CASE WHEN account_credit = '90.1' THEN amount ELSE 0 END) AS revenue, "
        "SUM(CASE WHEN account_debit = '90.2' THEN amount ELSE 0 END) AS cogs "
        "FROM acc_entries WHERE order_id IS NOT NULL GROUP BY order_id "
        "HAVING cogs > revenue AND revenue > 0"
    ).fetchall():
        anomalies.append({
            "kind": "negative_margin", "severity": "high",
            "text": f"Заказ №{row['order_id']}: себестоимость {row['cogs']:.2f} > выручки {row['revenue']:.2f} — проверить цену или расход материалов",
        })
    cutoff = (now() - timedelta(days=3)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN e.account_debit = '57' THEN e.amount ELSE 0 END), 0) - "
        "COALESCE(SUM(CASE WHEN e.account_credit = '57' THEN e.amount ELSE 0 END), 0) AS stuck "
        "FROM acc_entries e JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE t.is_posted = 1 AND t.date <= ? AND (e.account_debit = '57' OR e.account_credit = '57')",
        (cutoff,),
    ).fetchone()
    if row["stuck"] and row["stuck"] > 0.01:
        anomalies.append({
            "kind": "stuck_acquiring", "severity": "medium",
            "text": f"На счёте 57 зависло {row['stuck']:.2f} BYN старше 3 дней — эквайринг не зачислил деньги",
        })
    for row in conn.execute(
        "SELECT e.client_id, e.amount, COUNT(*) AS n, MIN(t.date) AS d1 FROM acc_entries e "
        "JOIN acc_transactions t ON t.id = e.transaction_id "
        "WHERE e.account_debit = '57' AND e.client_id IS NOT NULL AND t.is_posted = 1 "
        "GROUP BY e.client_id, e.amount, substr(t.date, 1, 10) HAVING n > 1"
    ).fetchall():
        anomalies.append({
            "kind": "duplicate_payment", "severity": "medium",
            "text": f"Клиент #{row['client_id']}: {row['n']} одинаковых платежа по {row['amount']:.2f} BYN ({row['d1']}) — возможен дубль",
        })
    return anomalies


# ------------------------------------------------------------------ банк: импорт выписки Клиент-Банка

def parse_bank_statement(text: str, *, company_mark: str = "Фотопринт") -> dict:
    """Парсер формата 1CClientBankExchange (Клиент-Банк банков РБ/РФ)."""
    lines_out, header = [], {}
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("СекцияРасчСчет"):
            current = {"_kind": "account"}
            continue
        if line.startswith("СекцияДокумент"):
            current = {"_kind": "doc"}
            continue
        if line.startswith("КонецДокумента"):
            if current and current.get("_kind") == "doc":
                lines_out.append(_bank_line(current, company_mark))
            current = None
            continue
        if "=" not in line or current is None:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if current.get("_kind") == "account":
            header[key] = value
        else:
            current[key] = value
    return {"header": header, "lines": lines_out}


def _bank_line(doc: dict, company_mark: str) -> dict:
    amount = _float(doc.get("Сумма", "0"))
    payer, receiver = doc.get("Плательщик", ""), doc.get("Получатель", "")
    inflow = company_mark.lower() in receiver.lower()
    purpose = doc.get("НазначениеПлатежа", "")
    return {
        "doc_number": doc.get("Номер", ""),
        "doc_date": _date_ru(doc.get("Дата", "")),
        "amount": amount,
        "payer": payer or receiver,
        "purpose": purpose,
        "inflow": inflow,
        "order_id": _order_ref(purpose),
    }


def _float(value: str) -> float:
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def _date_ru(value: str) -> str:
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", value.strip())
    if not match:
        return iso(now())[:10]
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def _order_ref(purpose: str) -> int | None:
    match = re.search(r"(?:#|№\s?|заказ[а-я]*\s*№?\s*)(\d{1,6})", purpose.lower())
    return int(match.group(1)) if match else None


def import_statement(conn, text: str, *, created_by: int | None = None) -> dict:
    """Импорт выписки: разбор + авто-сопоставление оплат с заказами. Постирование — отдельным действием."""
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if conn.execute("SELECT 1 FROM acc_transactions WHERE doc_type = 'bank_statement' AND doc_id = ?", (digest,)).fetchone():
        return {"duplicate": True, "lines": [], "matched": 0, "unmatched": 0}
    parsed = parse_bank_statement(text)
    matched = unmatched = 0
    for line in parsed["lines"]:
        if line["amount"] <= 0 or not line["inflow"]:
            continue  # списания со счёта в демо не разносим
        order = None
        if line["order_id"]:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (line["order_id"],)).fetchone()
        client_id = order["client_id"] if order else None
        status = "matched" if order else "unmatched"
        if status == "matched":
            matched += 1
        else:
            unmatched += 1
        conn.execute(
            "INSERT INTO acc_bank_lines (statement_hash, doc_number, doc_date, amount, payer, purpose, "
            "matched_order_id, matched_client_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (digest, line["doc_number"], line["doc_date"], line["amount"], line["payer"][:200],
             line["purpose"][:400], order["id"] if order else None, client_id, status, iso(now())),
        )
    conn.execute(
        "INSERT INTO acc_transactions (number, doc_type, doc_id, date, description, is_posted, created_at) "
        "VALUES (?, 'bank_statement', ?, ?, ?, 0, ?)",
        (next_number(conn, iso(now())[:10]), digest, iso(now())[:10],
         f"Выписка: импортировано строк {matched + unmatched}", iso(now())),
    )
    return {"duplicate": False, "lines": parsed["lines"], "matched": matched, "unmatched": unmatched}


def post_bank_lines(conn, line_ids: list[int], *, created_by: int | None = None) -> dict:
    """Разнесение сопоставленных оплат: Дт 51 (банк) — Кт 62 (клиент)."""
    posted = 0
    for line_id in line_ids:
        line = conn.execute(
            "SELECT * FROM acc_bank_lines WHERE id = ? AND status = 'matched'", (line_id,)
        ).fetchone()
        if line is None:
            continue
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (line["matched_order_id"],)).fetchone()
        tx_id = post(
            conn, date=line["doc_date"], doc_type="bank_payment", doc_id=f"bankline:{line_id}",
            description=f"Оплата по выписке №{line['doc_number']}: {line['purpose'][:80]}",
            entries=[{"debit": "51", "credit": "62", "amount": line["amount"],
                      "client_id": line["matched_client_id"], "order_id": line["matched_order_id"],
                      "note": line["payer"][:80]}],
            created_by=created_by,
        )
        conn.execute(
            "UPDATE acc_bank_lines SET status = 'posted', posted_tx_id = ? WHERE id = ?", (tx_id, line_id)
        )
        posted += 1
    return {"posted": posted}


# ------------------------------------------------------------------ документы и сверка

DOC_PREFIX = {"invoice": "SCH", "act": "AKT", "ttn": "TTN"}


def create_document(conn, kind: str, order_id: int) -> dict:
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise ValueError("Заказ не найден")
    client = conn.execute("SELECT * FROM clients WHERE id = ?", (order["client_id"],)).fetchone()
    amount = round(float(order["amount"] or 0), 2)
    vat = round(amount * 0.2 / 1.2, 2)  # НДС 20% в сумме
    net = round(amount - vat, 2)
    number = f"{DOC_PREFIX.get(kind, 'DOC')}-{iso(now())[:4]}-{order_id:05d}"
    date = iso(now())[:10]
    labels = {
        "invoice": "СЧЁТ НА ОПЛАТУ",
        "act": "АКТ выполненных работ",
        "ttn": "ТОВАРНАЯ НАКЛАДНАЯ (ТН-2)",
    }
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>{number}</title><style>
body {{ font-family: Roboto, Arial, sans-serif; margin: 40px; color: #111; }}
h1 {{ font-size: 18px; }} table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
td, th {{ border: 1px solid #999; padding: 6px 10px; text-align: left; font-size: 13px; }}
.right {{ text-align: right; }} .head {{ margin-top: 8px; font-size: 13px; }}
.total {{ font-weight: bold; }}
@media print {{ .no-print {{ display: none; }} }}
</style></head><body>
<p class="no-print"><button onclick="window.print()">Печать / PDF</button></p>
<h1>{labels.get(kind, kind)} № {number} от {_date_ru(date)}</h1>
<div class="head"><strong>Поставщик:</strong> {COMPANY}, УНП {COMPANY_UNP}</div>
<div class="head"><strong>Покупатель:</strong> {client["name"]}, {client["city"] or "—"}, тел. {client["phone"] or "—"}</div>
<table>
<tr><th>№</th><th>Наименование</th><th class="right">Сумма без НДС, BYN</th></tr>
<tr><td>1</td><td>{order["product"]} (заказ №{order["id"]})</td><td class="right">{net:.2f}</td></tr>
<tr class="total"><td colspan="2">Итого без НДС</td><td class="right">{net:.2f}</td></tr>
<tr><td colspan="2">НДС 20%</td><td class="right">{vat:.2f}</td></tr>
<tr class="total"><td colspan="2">Всего к оплате</td><td class="right">{amount:.2f}</td></tr>
</table>
<p style="margin-top:24px">Подписи: ______________________ / ______________________</p>
</body></html>"""
    cursor = conn.execute(
        "INSERT INTO acc_documents (kind, number, date, order_id, total_amount, vat_amount, status, body_html, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'issued', ?, ?)",
        (kind, number, date, order_id, amount, vat, html, iso(now())),
    )
    return {"id": cursor.lastrowid, "number": number, "kind": kind, "amount": amount, "vat": vat}


def reconciliation(conn, *, counterparty_id: int | None = None, client_id: int | None = None) -> dict:
    """Акт сверки: движения по 60/62 с контрагентом/клиентом и сальдо на конец."""
    param, who_field = (counterparty_id, "e.counterparty_id") if counterparty_id else (client_id, "e.client_id")
    if param is None:
        raise ValueError("Нужен counterparty_id или client_id")
    who = conn.execute(
        "SELECT name FROM counterparties WHERE id = ?" if counterparty_id else "SELECT name FROM clients WHERE id = ?",
        (param,),
    ).fetchone()
    rows = conn.execute(
        f"SELECT t.date, t.number, t.description, "
        f"SUM(CASE WHEN e.account_debit IN ('60','62') THEN e.amount ELSE 0 END) AS debit, "
        f"SUM(CASE WHEN e.account_credit IN ('60','62') THEN e.amount ELSE 0 END) AS credit "
        f"FROM acc_entries e JOIN acc_transactions t ON t.id = e.transaction_id "
        f"WHERE t.is_posted = 1 AND {who_field} = ? AND (e.account_debit IN ('60','62') OR e.account_credit IN ('60','62')) "
        f"GROUP BY t.id ORDER BY t.date, t.id",
        (param,),
    ).fetchall()
    items, balance = [], 0.0
    for row in rows:
        balance += row["debit"] - row["credit"]
        items.append({"date": row["date"][:10], "number": row["number"],
                      "description": row["description"], "debit": round(row["debit"], 2),
                      "credit": round(row["credit"], 2), "balance": round(balance, 2)})
    return {"name": who["name"] if who else "—", "items": items,
            "closing": round(balance, 2)}
