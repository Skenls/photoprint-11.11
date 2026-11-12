import { useEffect, useState } from "react";
import { api } from "../api";
import type { AccountingPayload, OsvPayload, User } from "../types";
import { Badge, Card, EmptyState, ErrorNote, Spinner, formatMoney } from "../components";

type Tab = "overview" | "osv" | "journal" | "bank" | "docs" | "audit";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Обзор" },
  { key: "osv", label: "ОСВ" },
  { key: "journal", label: "Журнал проводок" },
  { key: "bank", label: "Банк" },
  { key: "docs", label: "Документы" },
  { key: "audit", label: "Аудитор" },
];

const SAMPLE_STATEMENT = `1CClientBankExchange
ВерсияФормата=1.01
СекцияРасчСчет=BY17BLBB30150001000123456789
НачальныйОстаток=25000.00
СекцияДокумент=Платежное поручение
  Номер=1184
  Дата=10.11.2026
  Сумма=620.00
  Плательщик=Сулима Даниил
  Получатель=ООО "Фотопринт", УНП 190000000
  НазначениеПлатежа=Оплата заказа #586 фотокнига Premium
КонецДокумента
СекцияДокумент=Платежное поручение
  Номер=1185
  Дата=10.11.2026
  Сумма=290.00
  Плательщик=Ковалева Мария
  Получатель=ООО "Фотопринт", УНП 190000000
  НазначениеПлатежа=Оплата фотокниги Classic
КонецДокумента
КонецФайла`;

function statusBadge(status: string) {
  if (status === "posted") return <Badge tone="green">разнесено</Badge>;
  if (status === "matched") return <Badge tone="blue">найден заказ</Badge>;
  return <Badge tone="amber">требует уточнения</Badge>;
}

export function Accounting({ user }: { user: User }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<AccountingPayload | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.accounting().then(setData).catch((e) => setError(e.message));
  }, []);

  const reload = () => api.accounting().then(setData).catch((e) => setError(e.message));

  if (error && !data) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Собираю главную книгу…" />;

  const last = data.pnl[data.pnl.length - 1];
  const money = (code: string) =>
    data.accounts.filter((a) => code.includes(a.code)).reduce((sum, a) => sum + (a.closing > 0 ? a.closing : 0), 0);

  const storno = async (txId: number) => {
    const reason = window.prompt("Причина сторно:", "Исправление ошибки");
    if (!reason) return;
    setBusy(true);
    try {
      await api.accountingStorno(txId, reason);
      setNote(`Сторно операции №${txId} создано.`);
      await reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Не удалось выполнить сторно.");
    } finally {
      setBusy(false);
    }
  };

  const canWrite = user.role === "director" || user.role === "head";

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Magi Finance · двойная запись вместо 1С</div>
          <h1>Бухгалтерия</h1>
          <p className="muted">
            {data.transactions.length}+ операций в неизменяемом журнале. Проводки создаются событиями CRM:
            оплата → печать → выдача. ОСВ и P&L — чистый SQL, без пересчёта регистров.
          </p>
        </div>
        <div className="page-head-actions">
          {data.balanced ? <Badge tone="green">Актив = Пассив ✓</Badge> : <Badge tone="red">Баланс не сходится!</Badge>}
        </div>
      </header>

      {note && <ErrorNote text={note} />}

      <div className="tab-row">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab-btn ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {t.key === "audit" && data.anomalies.length > 0 && <span className="count-chip">{data.anomalies.length}</span>}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview data={data} last={last} money={money} />}
      {tab === "osv" && <OsvTab />}
      {tab === "journal" && <Journal data={data} storno={storno} busy={busy} canWrite={canWrite} />}
      {tab === "bank" && <BankTab data={data} reload={reload} setNote={setNote} canWrite={canWrite} />}
      {tab === "docs" && <DocsTab data={data} reload={reload} setNote={setNote} canWrite={canWrite} />}
      {tab === "audit" && <AuditTab data={data} />}
    </div>
  );
}

function Overview({ data, last, money }: { data: AccountingPayload; last: AccountingPayload["pnl"][number]; money: (codes: string) => number }) {
  return (
    <div className="acc-stack">
      <div className="kpi-grid">
        <div className="kpi kpi-accent">
          <div className="kpi-label">Выручка · {last?.month}</div>
          <div className="kpi-value">{formatMoney(last?.revenue ?? 0)}</div>
          <div className="kpi-hint">метод начисления, счёт 90.1</div>
        </div>
        <div className="kpi kpi-default">
          <div className="kpi-label">Себестоимость</div>
          <div className="kpi-value">{formatMoney(last?.cogs ?? 0)}</div>
          <div className="kpi-hint">90.2 · маржа {(last?.margin ?? 0).toFixed(1).replace(".", ",")}%</div>
        </div>
        <div className="kpi kpi-default">
          <div className="kpi-label">Прибыль</div>
          <div className="kpi-value">{formatMoney(last?.profit ?? 0)}</div>
          <div className="kpi-hint">после комиссии и накладных</div>
        </div>
        <div className="kpi kpi-accent">
          <div className="kpi-label">Деньги (50/51/57)</div>
          <div className="kpi-value">{formatMoney(money("5051 57".replace(" ", "")))}</div>
          <div className="kpi-hint">касса, р/с, эквайринг в пути</div>
        </div>
      </div>

      <div className="acc-grid">
        <Card title="P&L / БДР" subtitle="Прибыли и убытки, метод начисления">
          <table className="data-table">
            <thead><tr><th>Месяц</th><th>Выручка</th><th>Себест.</th><th>Комиссия</th><th>Накладн.</th><th>Прибыль</th><th>Маржа</th></tr></thead>
            <tbody>
              {data.pnl.map((m) => (
                <tr key={m.month}>
                  <td>{m.month}</td>
                  <td>{formatMoney(m.revenue)}</td>
                  <td>{formatMoney(m.cogs)}</td>
                  <td>{formatMoney(m.fees)}</td>
                  <td>{formatMoney(m.overhead)}</td>
                  <td className={m.profit >= 0 ? "pos" : "neg"}>{formatMoney(m.profit)}</td>
                  <td>{m.margin.toFixed(1).replace(".", ",")}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Cash Flow / БДДС" subtitle="Движение денег по р/с и кассе, кассовый метод">
          <table className="data-table">
            <thead><tr><th>Месяц</th><th>Приход</th><th>Списание</th><th>Нетто</th></tr></thead>
            <tbody>
              {data.pnl.map((m) => (
                <tr key={m.month}>
                  <td>{m.month}</td>
                  <td>{formatMoney(m.cash_in)}</td>
                  <td>{formatMoney(m.cash_out)}</td>
                  <td className={m.net_cash >= 0 ? "pos" : "neg"}>{formatMoney(m.net_cash)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="acc-grid">
        <Card title="Дебиторка (счёт 62)" subtitle="Покупатели — по срокам долга">
          <AgingList items={data.aging.receivables} empty="Все оплаты собраны — долгов нет." />
        </Card>
        <Card title="Кредиторка (счёт 60)" subtitle="Поставщики — сколько мы должны">
          <AgingList items={data.aging.payables} empty="Задолженности нет." />
        </Card>
      </div>
    </div>
  );
}

function AgingList({ items, empty }: { items: { id: number; name: string; balance: number; bucket: string }[]; empty: string }) {
  if (items.length === 0) return <p className="quiet">{empty}</p>;
  const buckets: Record<string, string> = { d7: "до 7 дней", d14: "8–14 дней", d30: "15–30 дней", d30plus: "30+ дней" };
  return (
    <table className="data-table">
      <thead><tr><th>Контрагент</th><th>Сумма</th><th>Срок</th></tr></thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{formatMoney(Math.abs(item.balance))}</td>
            <td><Badge tone={item.bucket === "d30plus" ? "red" : item.bucket === "d30" ? "amber" : "neutral"}>{buckets[item.bucket]}</Badge></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OsvTab() {
  const yearStart = `${new Date().getFullYear()}-01-01`;
  const today = new Date().toISOString().slice(0, 10);
  const [from, setFrom] = useState(yearStart);
  const [to, setTo] = useState(today);
  const [data, setData] = useState<OsvPayload | null>(null);

  useEffect(() => {
    api.accountingOsv(from, to).then(setData).catch(() => setData(null));
  }, [from, to]);

  return (
    <Card title="Оборотно-сальдовая ведомость" subtitle="Сальдо на начало, обороты, сальдо на конец — за любой период">
      <div className="osv-dates">
        <label className="field"><span>С</span><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="field"><span>По</span><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        {data && (data.balanced ? <Badge tone="green">Дт = Кт ✓</Badge> : <Badge tone="red">Дт ≠ Кт</Badge>)}
      </div>
      {!data ? (
        <Spinner label="Считаю обороты…" />
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Счёт</th><th>Название</th><th className="right">Сальдо нач.</th><th className="right">Дт оборот</th><th className="right">Кт оборот</th><th className="right">Сальдо кон.</th></tr>
          </thead>
          <tbody>
            {data.rows.filter((r) => r.debit > 0 || r.credit > 0 || r.opening !== 0 || r.closing !== 0).map((r) => (
              <tr key={r.code}>
                <td className="mono">{r.code}</td>
                <td>{r.name}</td>
                <td className="right">{r.opening ? formatMoney(r.opening) : "—"}</td>
                <td className="right">{r.debit ? formatMoney(r.debit) : "—"}</td>
                <td className="right">{r.credit ? formatMoney(r.credit) : "—"}</td>
                <td className="right">{r.closing ? formatMoney(r.closing) : "—"}</td>
              </tr>
            ))}
            <tr className="total-row">
              <td colSpan={2}><strong>Итого</strong></td>
              <td className="right"><strong>{formatMoney(data.totals.opening)}</strong></td>
              <td className="right"><strong>{formatMoney(data.totals.debit)}</strong></td>
              <td className="right"><strong>{formatMoney(data.totals.credit)}</strong></td>
              <td className="right"><strong>Актив {formatMoney(data.totals.assets)} = Пассив {formatMoney(data.totals.passives)}</strong></td>
            </tr>
          </tbody>
        </table>
      )}
    </Card>
  );
}

function Journal({ data, storno, busy, canWrite }: { data: AccountingPayload; storno: (id: number) => void; busy: boolean; canWrite: boolean }) {
  if (data.transactions.length === 0) return <EmptyState title="Операций нет" text="Проводки появятся при первой оплате заказа." />;
  return (
    <Card title="Журнал операций" subtitle="Неизменяемый append-only журнал; ошибки исправляются сторно">
      <table className="data-table">
        <thead><tr><th>Номер</th><th>Дата</th><th>Тип</th><th>Описание</th><th>Сторно</th></tr></thead>
        <tbody>
          {data.transactions.map((t) => (
            <tr key={t.id} className={t.doc_type === "storno" ? "storno-row" : ""}>
              <td className="mono">{t.number}</td>
              <td>{t.date}</td>
              <td><Badge tone={t.doc_type === "storno" ? "red" : t.doc_type === "order_delivered" ? "green" : "neutral"}>{t.doc_type}</Badge></td>
              <td>{t.description}{t.author ? ` · ${t.author}` : ""}</td>
              <td>
                {canWrite && t.doc_type !== "storno" && (
                  <button className="btn btn-small" onClick={() => storno(t.id)} disabled={busy}>Сторно</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function BankTab({ data, reload, setNote, canWrite }: { data: AccountingPayload; reload: () => Promise<void>; setNote: (s: string) => void; canWrite: boolean }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = data.bank_lines;

  const importStatement = async (statement: string) => {
    setBusy(true);
    try {
      const result = await api.accountingImportStatement(statement);
      setNote(
        result.duplicate
          ? (result.message ?? "Выписка уже импортирована.")
          : `Импортировано: найдено оплат с заказом — ${result.matched}, без сопоставления — ${result.unmatched}.`,
      );
      await reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Импорт не удался.");
    } finally {
      setBusy(false);
    }
  };

  const postMatched = async () => {
    const ids = pending.filter((l) => l.status === "matched").map((l) => l.id);
    if (ids.length === 0) return;
    setBusy(true);
    try {
      const result = await api.accountingPostBank(ids);
      setNote(`Разнесено проводок: ${result.posted}. Дт 51 — Кт 62.`);
      await reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Разнесение не удалось.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="acc-stack">
      <Card title="Импорт выписки Клиент-Банка" subtitle="Формат 1CClientBankExchange: Приорбанк, Альфа-Банк, Беларусбанк… Дедуп по хэшу файла">
        {canWrite ? (
          <div className="acc-stack">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              placeholder="Вставьте текст выписки из Клиент-Банка…"
              aria-label="Текст выписки"
            />
            <div className="page-head-actions" style={{ justifyContent: "flex-start" }}>
              <button className="btn btn-quiet" onClick={() => setText(SAMPLE_STATEMENT)}>Вставить пример</button>
              <button className="btn btn-primary" onClick={() => importStatement(text)} disabled={busy || text.trim().length < 40}>
                Импортировать
              </button>
            </div>
          </div>
        ) : (
          <p className="quiet">Импорт доступен руководству финансов.</p>
        )}
      </Card>

      <Card title="Оплаты из выписок" subtitle="Матчинг по номеру заказа в назначении платежа → Дт 51 Кт 62">
        {pending.length === 0 ? (
          <p className="quiet">Неразнесённых строк нет.</p>
        ) : (
          <>
            <table className="data-table">
              <thead><tr><th>Документ</th><th>Дата</th><th className="right">Сумма</th><th>Назначение</th><th>Статус</th></tr></thead>
              <tbody>
                {pending.map((l) => (
                  <tr key={l.id}>
                    <td className="mono">№{l.doc_number}</td>
                    <td>{l.doc_date}</td>
                    <td className="right">{formatMoney(l.amount)}</td>
                    <td className="purpose-cell">{l.purpose}{l.matched_order_id ? ` → заказ №${l.matched_order_id}` : ""}</td>
                    <td>{statusBadge(l.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {canWrite && pending.some((l) => l.status === "matched") && (
              <button className="btn btn-primary" onClick={postMatched} disabled={busy} style={{ marginTop: 10 }}>
                Разнести сопоставленные
              </button>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

function DocsTab({ data, reload, setNote, canWrite }: { data: AccountingPayload; reload: () => Promise<void>; setNote: (s: string) => void; canWrite: boolean }) {
  const [orderId, setOrderId] = useState("");
  const [kind, setKind] = useState("invoice");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const doc = await api.accountingCreateDocument(kind, Number(orderId));
      setNote(`Документ ${doc.number} сформирован.`);
      await reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Не удалось создать документ.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="acc-stack">
      <Card title="Первичные документы" subtitle="Счёт на оплату, акт, накладная — печать в PDF из браузера">
        {canWrite ? (
          <div className="docs-form">
            <label className="field"><span>№ заказа</span>
              <input value={orderId} onChange={(e) => setOrderId(e.target.value)} placeholder="587" inputMode="numeric" />
            </label>
            <label className="field"><span>Тип</span>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="invoice">Счёт на оплату</option>
                <option value="act">Акт выполненных работ</option>
                <option value="ttn">Товарная накладная (ТН-2)</option>
              </select>
            </label>
            <button className="btn btn-primary" onClick={create} disabled={busy || !orderId.trim()}>
              Сформировать
            </button>
          </div>
        ) : (
          <p className="quiet">Документы формирует руководство финансов.</p>
        )}
      </Card>

      <Card title="Сформированные документы">
        {data.documents.length === 0 ? (
          <p className="quiet">Документов пока нет.</p>
        ) : (
          <table className="data-table">
            <thead><tr><th>Номер</th><th>Тип</th><th>Дата</th><th>Заказ</th><th className="right">Сумма</th><th className="right">НДС</th><th></th></tr></thead>
            <tbody>
              {data.documents.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.number}</td>
                  <td>{d.kind}</td>
                  <td>{d.date}</td>
                  <td>{d.product ?? "—"}</td>
                  <td className="right">{formatMoney(d.total_amount)}</td>
                  <td className="right">{formatMoney(d.vat_amount)}</td>
                  <td>
                    <a className="link-btn" href={`/api/accounting/documents/${d.id}/print`} target="_blank" rel="noreferrer">
                      Печать
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function AuditTab({ data }: { data: AccountingPayload }) {
  if (data.anomalies.length === 0) {
    return (
      <Card title="Magi Auditor" subtitle="Проверка учёта на аномалии">
        <EmptyState title="Аномалий нет" text="Отрицательная маржа, зависший эквайринг и дубли оплат — не найдены." />
      </Card>
    );
  }
  return (
    <Card title="Magi Auditor" subtitle="Автопоиск ошибок учета">
      <ul className="audit-list">
        {data.anomalies.map((a, i) => (
          <li key={i}>
            <Badge tone={a.severity === "high" ? "red" : "amber"}>{a.severity === "high" ? "критично" : "внимание"}</Badge>
            <span>{a.text}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
