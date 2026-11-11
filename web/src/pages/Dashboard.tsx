import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dashboard, User } from "../types";
import {
  Avatar,
  BarChart,
  Card,
  ChannelBadge,
  ErrorNote,
  KpiCard,
  ROLE_LABELS,
  Spinner,
  formatMinutes,
  formatMoney,
  formatNumber,
  formatPercent,
  firstName,
} from "../components";
import { IconArrow, IconClock, IconSpark } from "../icons";

export function DashboardPage({
  user,
  onOpenInbox,
  onOpenMagi,
}: {
  user: User;
  onOpenInbox: (conversationId: number) => void;
  onOpenMagi: () => void;
}) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch(() => setError("Не удалось загрузить дашборд."));
  }, []);

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Собираем данные…" />;

  const { kpis } = data;
  const isDirector = user.role === "director";
  const today = new Date().toLocaleDateString("ru-RU", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  const cards =
    user.role === "operator"
      ? [
          { label: "Активные диалоги", value: formatNumber(kpis.open_conversations), hint: `${kpis.waiting} ждут ответа` },
          { label: "Ждут ответа", value: formatNumber(kpis.waiting), tone: kpis.waiting > 0 ? ("danger" as const) : ("default" as const), hint: "старше 60 минут — SLA" },
          { label: "Новые лиды", value: formatNumber(kpis.leads), hint: "за 30 дней" },
          { label: "Выручка по клиентам", value: formatMoney(kpis.revenue), hint: "за 30 дней" },
          { label: "Ответы Magi", value: formatPercent(Math.round(kpis.automation_rate)), tone: "magi" as const, hint: `порог ${formatPercent(Math.round(data.magi.threshold * 100))}` },
          { label: "Средний ответ", value: formatMinutes(kpis.avg_response_min), hint: "до первого ответа" },
        ]
      : [
          { label: isDirector ? "Выручка, 30 дней" : "Выручка отдела", value: formatMoney(kpis.revenue), hint: "по заказам клиентов" },
          { label: "Новые лиды", value: formatNumber(kpis.leads), hint: "за 30 дней" },
          { label: "Конверсия в клиента", value: formatPercent(kpis.conversion), hint: "от всей базы" },
          { label: "Автоответ Magi", value: formatPercent(Math.round(kpis.automation_rate)), tone: "magi" as const, hint: `порог ${formatPercent(Math.round(data.magi.threshold * 100))}` },
          { label: "Активные диалоги", value: formatNumber(kpis.open_conversations), hint: `${kpis.waiting} ждут ответа` },
          { label: "Просрочен SLA", value: formatNumber(kpis.sla), tone: kpis.sla > 0 ? ("danger" as const) : ("default" as const), hint: "дольше 60 минут" },
        ];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">{ROLE_LABELS[user.role]} · {data.scope_label}</div>
          <h1>Добрый день, {firstName(user.name)}</h1>
          <p className="muted">{today} · данные обновлены только что</p>
        </div>
        <div className="page-head-actions">
          <span className="status-pill">
            <span className="status-dot" /> Демо-данные
          </span>
          <button className="btn" onClick={() => onOpenInbox(data.attention[0]?.id ?? 0)}>
            Открыть инбокс <IconArrow size={16} />
          </button>
        </div>
      </header>

      <div className="kpi-grid">
        {cards.map((card) => (
          <KpiCard key={card.label} {...card} />
        ))}
      </div>

      <div className="grid grid-2 grid-charts">
        <Card title="Выручка по дням" subtitle="Последние 14 дней">
          <BarChart data={data.series} field="revenue" ariaLabel="Выручка по дням за 14 дней" />
        </Card>
        <Card title="Новые лиды" subtitle="Последние 14 дней">
          <BarChart data={data.series} field="leads" tone="blue" ariaLabel="Новые лиды по дням за 14 дней" />
        </Card>
      </div>

      <div className="grid grid-2">
        <Card
          title="Требуют внимания"
          subtitle="Сначала те, кто ждёт дольше"
          action={<span className="count-chip">{data.attention.length}</span>}
          bodyClassName="card-body flush"
        >
          {data.attention.length === 0 ? (
            <div className="quiet">Всё разобрано. Новых зависших диалогов нет.</div>
          ) : (
            <ul className="attention-list">
              {data.attention.map((item) => (
                <li key={item.id}>
                  <Avatar name={item.client_name} size={38} />
                  <div className="attention-copy">
                    <div className="attention-top">
                      <strong>{item.client_name}</strong>
                      <ChannelBadge channel={item.channel} />
                    </div>
                    <p>{item.reason}</p>
                  </div>
                  <div className="attention-side">
                    <span className={`wait ${item.minutes > 60 ? "wait-late" : ""}`}>
                      <IconClock size={13} /> {formatMinutes(item.minutes)}
                    </span>
                    <button className="link-btn" onClick={() => onOpenInbox(item.id)}>
                      Открыть
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Каналы" subtitle="Откуда приходят диалоги">
          <div className="channel-bars">
            {data.channels.length === 0 && <div className="quiet">Пока нет диалогов.</div>}
            {data.channels.map((channel) => {
              const max = Math.max(...data.channels.map((row) => row.count), 1);
              return (
                <div className="channel-row" key={channel.channel}>
                  <div className="channel-row-top">
                    <ChannelBadge channel={channel.channel} />
                    <strong>{channel.count}</strong>
                  </div>
                  <div className="meter">
                    <span style={{ width: `${(channel.count / max) * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <div className="grid grid-2">
        {user.role !== "operator" ? (
          <Card title="Команда" subtitle="Нагрузка и качество" bodyClassName="card-body flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Сотрудник</th>
                  <th>Активные</th>
                  <th>Передачи</th>
                  <th>Ответы Magi</th>
                </tr>
              </thead>
              <tbody>
                {data.team.map((member) => (
                  <tr key={member.id}>
                    <td>
                      <div className="person">
                        <Avatar name={member.name} size={32} />
                        <div>
                          <strong>{member.name}</strong>
                          <small>{member.title}</small>
                        </div>
                      </div>
                    </td>
                    <td>{member.open}</td>
                    <td>{member.handoffs}</td>
                    <td>{member.auto_replies}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ) : (
          <Card title="Как работает Magi" subtitle="Правила, которые видит менеджер">
            <ul className="rule-list">
              <li><span className="rule-dot rule-ok" /> Отвечает на статус заказа, цены, доставку и оплату</li>
              <li><span className="rule-dot rule-warn" /> Передаёт человеку жалобы, возвраты и персональные скидки</li>
              <li><span className="rule-dot rule-magi" /> Показывает уверенность и причину передачи</li>
              <li><span className="rule-dot rule-blue" /> Не отправляет сообщения без данных из CRM</li>
            </ul>
          </Card>
        )}

        <Card
          title="Magi сегодня"
          subtitle={data.magi.provider === "openai" ? `OpenAI-совместимый · ${data.magi.model}` : "Локальный движок · офлайн"}
          action={
            user.role !== "operator" ? (
              <button className="link-btn" onClick={onOpenMagi}>
                Настроить
              </button>
            ) : undefined
          }
        >
          <div className="magi-stats">
            <div>
              <span>Ответил</span>
              <strong>{data.kpis.magi_today}</strong>
            </div>
            <div>
              <span>Передал человеку</span>
              <strong>{data.kpis.handoffs}</strong>
            </div>
            <div>
              <span>Уверенность</span>
              <strong>{Math.round(data.kpis.avg_confidence)}%</strong>
            </div>
          </div>
          <div className="magi-note">
            <IconSpark size={16} />
            <p>
              {data.magi.enabled
                ? `Порог автоответа — ${formatPercent(Math.round(data.magi.threshold * 100))}. Ниже порога Magi передаёт диалог менеджеру.`
                : "Автоответы выключены. Все новые сообщения ждут менеджера."}
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
