import { useEffect, useState } from "react";
import { api } from "../api";
import type { PulsePayload, User } from "../types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  KpiStatusDot,
  MiniBars,
  Spinner,
  formatMoney,
  formatNumber,
} from "../components";
import { DecisionModal } from "./Decisions";
import { IconArrow } from "../icons";

function fmt(value: number, unit: string): string {
  if (unit === "BYN") return formatMoney(value);
  if (unit === "%") return `${String(value).replace(".", ",")}%`;
  return formatNumber(value);
}

export function Pulse({ user, onNavigate }: { user: User; onNavigate: (page: string) => void }) {
  const [data, setData] = useState<PulsePayload | null>(null);
  const [error, setError] = useState("");
  const [decisionFor, setDecisionFor] = useState<{ kpi_key: string; problem: string; cause: string } | null>(null);

  useEffect(() => {
    api.pulse().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Собираем пульс компании…" />;

  const reds = data.kpis.filter((k) => k.status === "red");

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Единая система · месяц {data.month}</div>
          <h1>Пульс компании</h1>
          <p className="muted">
            {data.totals.orders} заказов · {data.totals.clients} клиентов · {data.totals.conversations} обращений ·
            открытых решений: {data.open_decisions}
          </p>
        </div>
        <button className="btn" onClick={() => onNavigate("decisions")}>
          Реестр решений <IconArrow size={16} />
        </button>
      </header>

      {reds.length === 0 ? (
        <div className="pulse-ok">
          <Badge tone="green">Критических отклонений нет</Badge>
        </div>
      ) : null}

      <div className="kpi-grid pulse-grid">
        {data.kpis.map((kpi) => (
          <div className={`kpi kpi-${kpi.status === "red" ? "danger" : kpi.status === "green" ? "accent" : "default"}`} key={kpi.key}>
            <div className="kpi-label">
              <KpiStatusDot status={kpi.status} /> {kpi.name}
            </div>
            <div className="kpi-value">{fmt(kpi.value, kpi.unit)}</div>
            <div className="kpi-hint">
              Цель: {kpi.target == null ? "—" : fmt(kpi.target, kpi.unit)} · {kpi.source}
              {kpi.status !== "green" && (
                <button
                  className="link-btn kpi-fix"
                  onClick={() =>
                    setDecisionFor({
                      kpi_key: kpi.key,
                      problem: `${kpi.name}: ${fmt(kpi.value, kpi.unit)} при цели ${kpi.target == null ? "—" : fmt(kpi.target, kpi.unit)}`,
                      cause: "",
                    })
                  }
                >
                  Решение
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-2">
        <Card
          title="Нагрузка / мощность производства"
          subtitle="План станков против мощности на 6 недель"
          action={
            data.load_risk_week ? (
              <Badge tone="red">Риск перегрузки · {data.load_risk_week}</Badge>
            ) : (
              <Badge tone="green">В норме</Badge>
            )
          }
        >
          <MiniBars
            items={data.weeks.map((w) => ({
              label: `${w.week} · ${w.start}`,
              value: w.load,
              tone: w.load > 100 ? "red" : w.load >= 95 ? "amber" : "green",
            }))}
            format={(v) => `${v}%`}
          />
          {data.load_risk_week && (
            <div className="pulse-risk-note">
              План превышает мощность на {Math.max(...data.weeks.map((w) => w.load)) - 100}%.
              Владелец: производство. Шаг: изменить нагрузку. Срок: до запуска акции.
            </div>
          )}
        </Card>

        <Card title="Критические отклонения" subtitle="Красные KPI — переход к причине и решению">
          {data.critical.length === 0 ? (
            <EmptyState title="Всё в цели" text="Красных метрик нет. Отклонения не требуют решений." />
          ) : (
            <ul className="attention-list">
              {data.critical.map((item) => (
                <li key={item.kpi_key}>
                  <span className="kpi-dot kpi-dot-red" />
                  <div className="attention-copy">
                    <div className="attention-top">
                      <strong>{item.kpi_name}</strong>
                      <span>{fmt(item.value, item.unit)}</span>
                    </div>
                    <p>Цель: {item.target == null ? "—" : fmt(item.target, item.unit)} · владелец: {item.owner}</p>
                  </div>
                  <button
                    className="link-btn"
                    onClick={() =>
                      setDecisionFor({
                        kpi_key: item.kpi_key,
                        problem: `${item.kpi_name}: ${fmt(item.value, item.unit)} при цели ${item.target == null ? "—" : fmt(item.target, item.unit)}`,
                        cause: "",
                      })
                    }
                  >
                    Создать решение
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid grid-3 quick-links">
        <button className="card card-link-tile" onClick={() => onNavigate("sales")}>
          <strong>Продажи и клиент</strong>
          <span>Воронка, конверсия, средний чек, каналы</span>
        </button>
        <button className="card card-link-tile" onClick={() => onNavigate("production")}>
          <strong>Производство и качество</strong>
          <span>Очередь станков, lead time, причины просрочки</span>
        </button>
        <button className="card card-link-tile" onClick={() => onNavigate("finance")}>
          <strong>Финансы и люди</strong>
          <span>БДР/БДДС, контрагенты, штат и вакансии</span>
        </button>
      </div>

      {decisionFor && (
        <DecisionModal
          kpis={data.kpis.map((k) => ({ key: k.key, name: k.name }))}
          initial={{ kpi_key: decisionFor.kpi_key, problem: decisionFor.problem, cause: decisionFor.cause }}
          onClose={() => setDecisionFor(null)}
          onCreated={() => setDecisionFor(null)}
        />
      )}
      {user.role === "analyst" ? null : null}
    </div>
  );
}
