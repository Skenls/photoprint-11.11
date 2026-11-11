import { useEffect, useState } from "react";
import { api } from "../api";
import type { FinancePayload } from "../types";
import { Badge, Card, ErrorNote, Spinner, formatMoney } from "../components";

function pct(fact: number, plan: number): string {
  if (!plan) return "—";
  return `${String(Math.round((fact / plan) * 100)).replace(".", ",")}%`;
}

export function Finance() {
  const [data, setData] = useState<FinancePayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.finance().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Загружаю 1С-витрину…" />;

  const current = data.periods[data.periods.length - 1];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">1С / Финансы</div>
          <h1>Финансы и деньги</h1>
          <p className="muted">БДР/БДДС план-факт, себестоимость и маржа, дебет/кредит, контрагенты. Все суммы — BYN.</p>
        </div>
        <div className="page-head-stats">
          <div className="stat-tile"><span>Маржа, {current?.month}</span><strong>{String(current?.margin ?? 0).replace(".", ",")}%</strong></div>
          <div className="stat-tile"><span>БДДС исполнение</span><strong>{current ? pct(current.fact_cash, current.plan_cash) : "—"}</strong></div>
        </div>
      </header>

      <Card title="БДР / БДДС по месяцам" subtitle="План против факта" bodyClassName="card-body flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Месяц</th>
                <th>Выручка план</th>
                <th>Выручка факт</th>
                <th>Исполнение</th>
                <th>Затраты план</th>
                <th>Затраты факт</th>
                <th>Маржа</th>
                <th>ДДС план</th>
                <th>ДДС факт</th>
              </tr>
            </thead>
            <tbody>
              {data.periods.map((p) => (
                <tr key={p.month}>
                  <td><strong>{p.month}</strong></td>
                  <td className="num">{formatMoney(p.plan_revenue)}</td>
                  <td className="num">{formatMoney(p.fact_revenue)}</td>
                  <td className="num">
                    <Badge tone={p.fact_revenue >= p.plan_revenue ? "green" : "amber"}>{pct(p.fact_revenue, p.plan_revenue)}</Badge>
                  </td>
                  <td className="num">{formatMoney(p.plan_costs)}</td>
                  <td className="num">{formatMoney(p.fact_costs)}</td>
                  <td className="num">{String(p.margin).replace(".", ",")}%</td>
                  <td className="num">{formatMoney(p.plan_cash)}</td>
                  <td className="num">{formatMoney(p.fact_cash)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-2">
        <Card title="Операции (дебет/кредит)" subtitle="Последние записи витрины 1С" bodyClassName="card-body flush">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Дата</th><th>Тип</th><th>Контрагент</th><th>Категория</th><th>Сумма</th></tr></thead>
              <tbody>
                {data.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap">{e.entry_date}</td>
                    <td>{e.kind === "debit" ? <Badge tone="green">Дебет</Badge> : <Badge tone="amber">Кредит</Badge>}</td>
                    <td>{e.counterparty_name ?? "—"}</td>
                    <td className="muted">{e.category}</td>
                    <td className="num">{formatMoney(e.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Контрагенты" subtitle="Сальдо на текущий момент">
          <div className="cp-list">
            {data.counterparties.map((cp) => (
              <div className="cp-row" key={cp.id}>
                <div>
                  <strong>{cp.name}</strong>
                  <small>{cp.kind}</small>
                </div>
                <span className={cp.balance >= 0 ? "cp-positive" : "cp-negative"}>
                  {formatMoney(cp.balance)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
