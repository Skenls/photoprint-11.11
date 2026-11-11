import { useEffect, useState } from "react";
import { api } from "../api";
import type { AnalystPayload } from "../types";
import { Badge, Card, ErrorNote, Spinner, formatDateTime, formatMoney } from "../components";

function freshness(minutes: number | null): { tone: "green" | "amber" | "red"; label: string } {
  if (minutes == null) return { tone: "red", label: "нет данных" };
  if (minutes < 24 * 60) return { tone: "green", label: `${Math.round(minutes / 60)} ч назад` };
  if (minutes < 72 * 60) return { tone: "amber", label: `${Math.round(minutes / (60 * 24))} дн назад` };
  return { tone: "red", label: `${Math.round(minutes / (60 * 24))} дн назад` };
}

export function AnalystPage() {
  const [data, setData] = useState<AnalystPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.analyst().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Проверяю качество данных…" />;

  const q = data.quality;
  const rec = data.reconciliation;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Качество данных</div>
          <h1>Аналитика источников</h1>
          <p className="muted">Свежесть источников, пропуски и дубли, сверка финансовых итогов CRM ↔ ERP ↔ 1С.</p>
        </div>
      </header>

      <div className="grid grid-2">
        <Card title="Свежесть источников" subtitle="Когда было последнее событие">
          <div className="source-list">
            {data.sources.map((s) => {
              const f = freshness(s.fresh_minutes);
              return (
                <div className="source-row" key={s.source}>
                  <div>
                    <strong>{s.source}</strong>
                    <small>{s.records} записей · последнее: {s.last_event ? formatDateTime(s.last_event) : "—"}</small>
                  </div>
                  <Badge tone={f.tone}>{f.label}</Badge>
                </div>
              );
            })}
          </div>
        </Card>

        <Card title="Пропуски и дубли" subtitle="Контракт данных: типы, статусы, время">
          <ul className="rules-list">
            <li><span className="rule-dot amber" /><div><strong>Дубли клиентов по телефону: {q.dup_phones}</strong><p>Объединить карточки в CRM.</p></div></li>
            <li><span className="rule-dot amber" /><div><strong>Без телефона: {q.missing_phone}</strong><p>Заполнить при следующем контакте.</p></div></li>
            <li><span className="rule-dot amber" /><div><strong>Без email: {q.missing_email}</strong><p>Мешает дублированию и рассылкам.</p></div></li>
            <li><span className="rule-dot amber" /><div><strong>Заказы без обещанного срока: {q.missing_promised}</strong><p>Обязательное поле для расчёта «в срок».</p></div></li>
            <li><span className="rule-dot amber" /><div><strong>Обращения без первого ответа: {q.missing_first_response}</strong><p>Открытые диалоги ждут менеджера.</p></div></li>
          </ul>
        </Card>
      </div>

      <Card
        title="Сверка финансовых итогов"
        subtitle={`Месяц ${rec.month} · CRM ↔ ERP ↔ 1С`}
        action={<Badge tone={rec.gap_crm_finance_pct <= 3 ? "green" : "red"}>Расхождение {String(rec.gap_crm_finance_pct).replace(".", ",")}%</Badge>}
      >
        <div className="recon-grid">
          <div className="recon-tile">
            <span>CRM · все заказы</span>
            <strong>{formatMoney(rec.crm_revenue)}</strong>
          </div>
          <div className="recon-tile">
            <span>ERP · доставленные</span>
            <strong>{formatMoney(rec.erp_delivered)}</strong>
          </div>
          <div className="recon-tile">
            <span>1С · оплаченный факт</span>
            <strong>{formatMoney(rec.finance_fact)}</strong>
          </div>
        </div>
        <p className="muted small">{rec.note}</p>
      </Card>
    </div>
  );
}
