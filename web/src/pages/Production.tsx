import { useEffect, useState } from "react";
import { api } from "../api";
import type { Order, ProductionPayload } from "../types";
import { Badge, Card, ErrorNote, MiniBars, Spinner, formatDateTime, formatMoney } from "../components";

const CAUSE_HINT: Record<string, string> = {
  delivery: "Курьерская служба и сроки отправки",
  moderation: "Проверка макетов перед печатью",
  production: "Очередь станков и переналадка",
};

export function Production() {
  const [data, setData] = useState<ProductionPayload | null>(null);
  const [error, setError] = useState("");
  const [openCause, setOpenCause] = useState<string | null>(null);
  const [causeItems, setCauseItems] = useState<(Order & { client_name: string; owner_name: string })[] | null>(null);
  const [causeLoading, setCauseLoading] = useState(false);

  useEffect(() => {
    api.production().then(setData).catch((e) => setError(e.message));
  }, []);

  async function toggleCause(cause: string) {
    if (openCause === cause) {
      setOpenCause(null);
      setCauseItems(null);
      return;
    }
    setOpenCause(cause);
    setCauseLoading(true);
    try {
      const r = await api.causeOrders(cause);
      setCauseItems(r.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть заказы");
    } finally {
      setCauseLoading(false);
    }
  }

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Собираем производственный контур…" />;

  const totalCause = data.causes.reduce((s, c) => s + c.count, 0) || 1;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">ERP · заказы и производство</div>
          <h1>Производство и качество</h1>
          <p className="muted">План/факт выпуска, очередь станков, lead time и разбор причин просрочки.</p>
        </div>
        <div className="page-head-stats">
          <div className="stat-tile"><span>Lead time</span><strong>{data.lead_time_hours} ч</strong></div>
          <div className="stat-tile"><span>Брак</span><strong>{String(data.defect_rate).replace(".", ",")}%</strong></div>
        </div>
      </header>

      <div className="grid grid-2">
        <Card title="От цифры к причине" subtitle="Просроченные заказы: доли причин">
          {data.causes.map((cause) => (
            <div className="cause-row" key={cause.cause}>
              <div className="cause-main">
                <div className="cause-top">
                  <strong>{cause.label}</strong>
                  <span>{cause.count} заказов · {cause.share}%</span>
                </div>
                <div className="meter"><span style={{ width: `${(cause.count / totalCause) * 100}%` }} /></div>
                <p className="muted">{CAUSE_HINT[cause.cause]}</p>
              </div>
              <button className="btn btn-small" onClick={() => toggleCause(cause.cause)}>
                {openCause === cause.cause ? "Скрыть" : "Заказы-основания"}
              </button>
            </div>
          ))}
          {openCause && (
            <div className="cause-detail">
              {causeLoading ? <Spinner label="Открываем заказы…" /> : (
                causeItems && causeItems.length > 0 ? (
                  <table className="table">
                    <thead><tr><th>Заказ</th><th>Клиент</th><th>Сумма</th><th>Обещано</th><th>Ответственный</th></tr></thead>
                    <tbody>
                      {causeItems.map((o) => (
                        <tr key={o.id}>
                          <td>#{o.id} · {o.product}</td>
                          <td>{o.client_name}</td>
                          <td className="num">{formatMoney(o.amount)}</td>
                          <td>{formatDateTime(o.promised_at)}</td>
                          <td>{o.owner_name ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="muted">Заказов нет.</p>
              )}
              <p className="muted small">Причина → заказы-основания → владелец → действие. Решение создаётся в реестре.</p>
            </div>
          )}
        </Card>

        <Card title="Станки" subtitle="Загрузка очереди и простои за месяц">
          <table className="table">
            <thead><tr><th>Станок</th><th>Тип</th><th>Очередь</th><th>Простой</th><th>Статус</th></tr></thead>
            <tbody>
              {data.machines.map((m) => (
                <tr key={m.id}>
                  <td><strong>{m.name}</strong></td>
                  <td className="muted">{m.kind}</td>
                  <td className="num">{Math.round(m.queue_min / 60)} ч</td>
                  <td className="num">{Math.round(m.downtime_min_month / 60)} ч</td>
                  <td>{m.status === "ok" ? <Badge tone="green">Норма</Badge> : <Badge tone="amber">Внимание</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="section-gap" />
          <h3 className="section-label">Очередь заданий</h3>
          <div className="queue-list">
            {data.queue.map((job) => (
              <div className="queue-row" key={job.id}>
                <span className="queue-machine">{job.machine_name}</span>
                <span className="queue-product">{job.product ?? "переналадка"} · {job.est_minutes} мин</span>
                <span>{formatDateTime(job.planned_start)}</span>
                {job.status === "running" ? <Badge tone="amber">Работает</Badge> : <Badge tone="neutral">Очередь</Badge>}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="План / факт выпуска" subtitle="14 дней: принято и выпущено">
        <MiniBars
          items={data.plan_fact.map((d) => ({
            label: d.day.slice(8, 10) + "." + d.day.slice(5, 7),
            value: d.planned,
            tone: d.done >= d.planned * 0.9 ? "green" : "amber",
          }))}
          format={(v) => `${v}`}
        />
      </Card>
    </div>
  );
}
