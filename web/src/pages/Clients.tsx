import { useEffect, useState } from "react";
import { api } from "../api";
import type { Client, ClientDetail, User } from "../types";
import {
  Avatar,
  Card,
  ChannelBadge,
  ClientStatus,
  ConversationStatus,
  EmptyState,
  ErrorNote,
  Spinner,
  formatDateTime,
  formatMoney,
  formatNumber,
} from "../components";
import { IconArrow, IconSearch, IconSpark, IconUsers } from "../icons";

const STATUS_FILTERS = [
  { value: "", label: "Все статусы" },
  { value: "new", label: "Новые" },
  { value: "qualified", label: "В работе" },
  { value: "customer", label: "Клиенты" },
  { value: "sleeping", label: "Спящие" },
];

const CHANNEL_FILTERS = [
  { value: "", label: "Все каналы" },
  { value: "site", label: "Сайт" },
  { value: "telegram", label: "Telegram" },
  { value: "email", label: "Email" },
  { value: "instagram", label: "Instagram" },
];

export function ClientsPage({
  user,
  initialId,
  onOpenInbox,
}: {
  user: User;
  initialId?: string;
  onOpenInbox: (conversationId: number) => void;
}) {
  const [items, setItems] = useState<Client[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(
    initialId ? Number(initialId) : null,
  );
  const [detail, setDetail] = useState<ClientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      api
        .clients({ search: query, status, channel })
        .then((data) => {
          setItems(data.items);
          setError("");
        })
        .catch(() => setError("Не удалось загрузить клиентов."))
        .finally(() => setLoading(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, status, channel]);

  const loadDetail = (id: number) => {
    setDetailLoading(true);
    api
      .client(id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  };

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    loadDetail(selectedId);
  }, [selectedId]);

  const title =
    user.role === "director" || user.role === "analyst"
      ? "Клиенты компании"
      : user.role === "head"
        ? "Клиенты отдела"
        : "Мои клиенты";

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Клиентская база</div>
          <h1>{title}</h1>
          <p className="muted">История заказов, каналы и диалоги — в одной карточке.</p>
        </div>
        <span className="count-chip big">{formatNumber(items.length)}</span>
      </header>

      <div className="toolbar">
        <label className="search">
          <IconSearch size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Имя, телефон, город…"
            aria-label="Поиск клиентов"
          />
        </label>
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Статус клиента">
          {STATUS_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select value={channel} onChange={(event) => setChannel(event.target.value)} aria-label="Канал клиента">
          {CHANNEL_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {(query || status || channel) && (
          <button
            className="btn btn-quiet"
            onClick={() => {
              setQuery("");
              setStatus("");
              setChannel("");
            }}
          >
            Сбросить
          </button>
        )}
      </div>

      {error && <ErrorNote text={error} />}

      <div className="split">
        <Card className="table-card" bodyClassName="card-body flush">
          {loading ? (
            <Spinner label="Загружаем клиентов…" />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<IconUsers size={26} />}
              title="Никого не нашли"
              text="Попробуйте изменить запрос или сбросить фильтры."
            />
          ) : (
            <div className="table-scroll">
              <table className="table table-clickable">
                <thead>
                  <tr>
                    <th>Клиент</th>
                    <th>Канал</th>
                    <th>Статус</th>
                    <th>LTV</th>
                    <th>Последний заказ</th>
                    <th>Ответственный</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((client) => (
                    <tr
                      key={client.id}
                      className={selectedId === client.id ? "row-active" : ""}
                      onClick={() => setSelectedId(client.id)}
                      tabIndex={0}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") setSelectedId(client.id);
                      }}
                    >
                      <td>
                        <div className="person">
                          <Avatar name={client.name} size={34} />
                          <div>
                            <strong>{client.name}</strong>
                            <small>{client.city || "—"}</small>
                          </div>
                        </div>
                      </td>
                      <td><ChannelBadge channel={client.channel} /></td>
                      <td><ClientStatus status={client.status} /></td>
                      <td className="money">{formatMoney(client.ltv)}</td>
                      <td>
                        <span className="cell-strong">{client.last_product || "—"}</span>
                        {client.last_amount ? (
                          <small className="cell-sub">{formatMoney(client.last_amount)}</small>
                        ) : null}
                      </td>
                      <td>{client.owner_name || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <aside className="detail-panel">
          {!selectedId ? (
            <Card className="detail-empty">
              <IconSpark size={24} />
              <h3>Выберите клиента</h3>
              <p>Покажем заказы, историю диалогов и следующий шаг.</p>
            </Card>
          ) : detailLoading ? (
            <Spinner label="Открываем карточку…" />
          ) : !detail ? (
            <EmptyState title="Карточка недоступна" text="Возможно, клиент вне вашей зоны доступа." />
          ) : (
            <ClientCard detail={detail} onOpenInbox={onOpenInbox} onChanged={() => loadDetail(selectedId!)} />
          )}
        </aside>
      </div>
    </div>
  );
}

function ClientCard({
  detail,
  onOpenInbox,
  onChanged,
}: {
  detail: ClientDetail;
  onOpenInbox: (conversationId: number) => void;
  onChanged: () => void;
}) {
  const { client, orders, conversations } = detail;
  const total = orders.reduce((sum, order) => sum + order.amount, 0);
  const openConversation = conversations.find((item) => item.status !== "closed") ?? conversations[0];
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: client.name,
    phone: client.phone,
    email: client.email,
    city: client.city,
    tg_handle: client.tg_handle ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const startEdit = () => {
    setForm({
      name: client.name,
      phone: client.phone,
      email: client.email,
      city: client.city,
      tg_handle: client.tg_handle ?? "",
    });
    setError("");
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.patchClient(client.id, {
        name: form.name,
        phone: form.phone,
        email: form.email,
        city: form.city,
        tg_handle: form.tg_handle,
      });
      setEditing(false);
      onChanged();
    } catch {
      setError("Не удалось сохранить изменения.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="detail-card" bodyClassName="card-body flush">
      <div className="detail-head">
        <Avatar name={client.name} size={48} />
        <div className="detail-title">
          <div className="detail-name-row">
            <h2>{client.name}</h2>
            <ClientStatus status={client.status} />
          </div>
          <p>{client.city || "Город не указан"} · {client.channel === "site" ? "сайт" : client.channel}</p>
        </div>
      </div>

      <div className="detail-actions">
        {openConversation && (
          <button className="btn btn-primary" onClick={() => onOpenInbox(openConversation.id)}>
            Открыть диалог <IconArrow size={15} />
          </button>
        )}
        <span className="detail-ltv">
          LTV <strong>{formatMoney(client.ltv)}</strong>
        </span>
      </div>

      <div className="detail-section">
        <div className="section-head">
          <h3>Контакты</h3>
          <button className="link-btn" onClick={editing ? () => setEditing(false) : startEdit}>
            {editing ? "Отмена" : "Изменить"}
          </button>
        </div>
        {editing ? (
          <div className="client-edit">
            <label className="field"><span>Имя</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="field"><span>Телефон</span>
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </label>
            <label className="field"><span>Email</span>
              <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <label className="field"><span>Город</span>
              <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
            </label>
            <label className="field"><span>Telegram ID / @name</span>
              <input value={form.tg_handle} onChange={(e) => setForm({ ...form, tg_handle: e.target.value })} placeholder="1287875313 или @ivan" />
            </label>
            <button className="btn btn-primary" onClick={save} disabled={saving || !form.name.trim()}>
              {saving ? "Сохраняем…" : "Сохранить"}
            </button>
            {error && <p className="note">{error}</p>}
          </div>
        ) : (
          <dl className="facts">
            <div><dt>Телефон</dt><dd>{client.phone || "—"}</dd></div>
            <div><dt>Email</dt><dd>{client.email || "—"}</dd></div>
            {(client.tg_handle || client.channel === "telegram") && (
              <div><dt>Telegram</dt><dd>{client.tg_handle || "не указан"}</dd></div>
            )}
            <div><dt>Ответственный</dt><dd>{client.owner_name || "—"}</dd></div>
            <div><dt>В базе с</dt><dd>{formatDateTime(client.created_at)}</dd></div>
          </dl>
        )}
        {client.tags && (
          <div className="tags">
            {client.tags.split(",").filter(Boolean).map((tag) => (
              <span className="tag" key={tag}>{tag.trim()}</span>
            ))}
          </div>
        )}
        {client.notes && <p className="note">{client.notes}</p>}
      </div>

      <div className="detail-section">
        <div className="section-head">
          <h3>Заказы</h3>
          <span className="muted">{formatMoney(total)}</span>
        </div>
        <div className="order-list">
          {orders.length === 0 && <p className="quiet">Заказов пока нет.</p>}
          {orders.slice(0, 4).map((order) => (
            <div className="order-row" key={order.id}>
              <div>
                <strong>{order.product}</strong>
                <small>{formatDateTime(order.created_at)}</small>
              </div>
              <div className="order-side">
                <span>{formatMoney(order.amount)}</span>
                <OrderStatus status={order.status} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="detail-section">
        <h3>Диалоги</h3>
        <div className="conversation-list">
          {conversations.length === 0 && <p className="quiet">Диалогов пока нет.</p>}
          {conversations.slice(0, 4).map((conversation) => (
            <button
              className="conversation-row"
              key={conversation.id}
              onClick={() => onOpenInbox(conversation.id)}
            >
              <div>
                <strong>{conversation.subject || "Без темы"}</strong>
                <small>{conversation.last_message || "Нет сообщений"}</small>
              </div>
              <div className="conversation-side">
                <ChannelBadge channel={conversation.channel} />
                <ConversationStatus status={conversation.status} />
              </div>
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function OrderStatus({ status }: { status: string }) {
  const labels: Record<string, string> = {
    new: "Новый",
    in_production: "В производстве",
    ready: "Готов",
    delivered: "Доставлен",
    delayed: "Задержка",
  };
  const tones: Record<string, string> = {
    new: "blue",
    in_production: "warn",
    ready: "ok",
    delivered: "neutral",
    delayed: "danger",
  };
  return <span className={`badge badge-${tones[status] ?? "neutral"}`}>{labels[status] ?? status}</span>;
}
