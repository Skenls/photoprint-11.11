import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Conversation, ConversationDetail, TemplateItem, User } from "../types";
import {
  Avatar,
  ChannelBadge,
  ClientStatus,
  ConversationStatus,
  EmptyState,
  ErrorNote,
  INTENT_LABELS,
  ModeBadge,
  Modal,
  Spinner,
  formatDateTime,
  formatMinutes,
  formatMoney,
  timeAgo,
} from "../components";
import {
  IconArrow,
  IconCheck,
  IconPlus,
  IconSearch,
  IconSend,
  IconSpark,
  IconUser,
} from "../icons";

const CHANNELS = [
  { value: "", label: "Все каналы" },
  { value: "site", label: "Сайт" },
  { value: "telegram", label: "Telegram" },
  { value: "email", label: "Email" },
  { value: "instagram", label: "Instagram" },
];

const STATUSES = [
  { value: "", label: "Все диалоги" },
  { value: "open", label: "Открытые" },
  { value: "waiting", label: "Ждут ответа" },
  { value: "closed", label: "Закрытые" },
];

export function InboxPage({
  user,
  initialId,
  onOpenClient,
}: {
  user: User;
  initialId?: string;
  onOpenClient: (clientId: number) => void;
}) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(
    initialId ? Number(initialId) : null,
  );
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [composer, setComposer] = useState("");
  const [asLead, setAsLead] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [newLeadOpen, setNewLeadOpen] = useState(false);
  const [actionNote, setActionNote] = useState("");
  const [allTemplates, setAllTemplates] = useState<TemplateItem[]>([]);
  const messagesRef = useRef<HTMLDivElement>(null);
  const detailIdRef = useRef<number | null>(null);
  const lastDetailIdRef = useRef<number | null>(null);

  useEffect(() => {
    api.templates().then((r) => setAllTemplates(r.items)).catch(() => setAllTemplates([]));
  }, []);

  const chatTemplates = (() => {
    const topic = detail?.conversation.topic;
    const matched = topic ? allTemplates.filter((t) => t.topic === topic) : [];
    return matched.length > 0 ? matched : allTemplates.slice(0, 4);
  })();

  const fillTemplate = (t: TemplateItem) => {
    const firstName = (detail?.client.name ?? "").split(" ")[0];
    const last = detail?.orders[0];
    const filled = t.body
      .replaceAll("{name}", firstName)
      .replaceAll("{product}", last?.product ?? "заказ")
      .replaceAll("{order_status}", last ? ({ new: "принят", moderation: "на модерации", in_production: "в производстве", ready: "готов", delivered: "доставлен" } as Record<string, string>)[last.status] ?? last.status : "в работе")
      .replaceAll("{promised}", last?.promised_at ? new Date(last.promised_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "скоро");
    setComposer(filled);
  };

  const filtersRef = useRef({ search: query, channel, status });
  filtersRef.current = { search: query, channel, status };

  const loadList = (silent = false) => {
    if (!silent) setLoading(true);
    api
      .conversations(filtersRef.current)
      .then((data) => {
        setItems(data.items);
        setError("");
      })
      .catch(() => {
        if (!silent) setError("Не удалось загрузить диалоги.");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const timer = window.setTimeout(loadList, 220);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, channel, status]);

  useEffect(() => {
    if (initialId) setSelectedId(Number(initialId));
  }, [initialId]);

  useEffect(() => {
    if (!selectedId && items.length > 0) setSelectedId(items[0].id);
  }, [items, selectedId]);

  const loadDetail = (id: number, silent = false) => {
    detailIdRef.current = id;
    if (!silent) setDetailLoading(true);
    api
      .conversation(id)
      .then((data) => {
        // Диалог мог смениться, пока летел ответ — не затираем свежий выбор.
        if (detailIdRef.current === id) setDetail(data);
      })
      .catch(() => {
        if (detailIdRef.current !== id) return;
        setDetail(null);
        setError("Диалог недоступен: он вне вашей зоны доступа.");
      })
      .finally(() => {
        if (detailIdRef.current === id) setDetailLoading(false);
      });
  };

  useEffect(() => {
    detailIdRef.current = null;
    setActionNote("");
    if (selectedId) loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId]);

  const runOrderAction = async (action: "rush" | "redone" | "extend" | "promo") => {
    const order = detail?.orders[0];
    const conversationId = detail?.conversation.id;
    if (!order || conversationId == null) return;
    try {
      const result = await api.orderAction(order.id, action);
      setActionNote(result.message);
      loadDetail(conversationId, true);
      loadList(true);
    } catch {
      setActionNote("Действие недоступно: заказ вне вашей зоны доступа.");
    }
  };

  // Real-time: SSE-событие «update» → тихо обновляем список и открытый диалог.
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("update", () => {
      loadList(true);
      if (detailIdRef.current) loadDetail(detailIdRef.current, true);
    });
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Горячие клавиши: Alt+цифра — шаблон, J/K — навигация по диалогам.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && /^[1-9]$/.test(event.key)) {
        const template = chatTemplates[Number(event.key) - 1];
        if (template) {
          event.preventDefault();
          fillTemplate(template);
        }
        return;
      }
      const target = event.target as HTMLElement | null;
      const typing = !!target && (/^(input|textarea|select)$/i.test(target.tagName) || target.isContentEditable);
      if (typing || newLeadOpen || (event.key !== "j" && event.key !== "k")) return;
      if (items.length === 0) return;
      const current = items.findIndex((item) => item.id === selectedId);
      const fallback = current === -1 ? 0 : current;
      const next = event.key === "j" ? Math.min(fallback + 1, items.length - 1) : Math.max(fallback - 1, 0);
      if (next !== fallback) {
        event.preventDefault();
        setSelectedId(items[next].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    // Скроллим только контейнер сообщений: scrollIntoView прокручивал бы
    // заодно список диалогов, карточку клиента и саму страницу.
    const el = messagesRef.current;
    if (!el) return;
    const openedAnother = lastDetailIdRef.current !== detail?.conversation.id;
    lastDetailIdRef.current = detail?.conversation.id ?? null;
    // При живом обновлении не дёргаем скролл, если менеджер читает историю выше.
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (openedAnother || nearBottom) el.scrollTop = el.scrollHeight;
  }, [detail?.conversation.id, detail?.messages.length, detail?.conversation.mode]);

  const send = async () => {
    const body = composer.trim();
    if (!body || !selectedId || sending) return;
    setSending(true);
    try {
      await api.send(selectedId, body, asLead ? "lead" : "agent");
      setComposer("");
      loadDetail(selectedId);
      loadList();
    } catch {
      setError("Сообщение не отправилось. Попробуйте ещё раз.");
    } finally {
      setSending(false);
    }
  };

  const handoff = async () => {
    if (!selectedId) return;
    try {
      await api.handoff(selectedId, "Нужна помощь менеджера");
      loadDetail(selectedId);
      loadList();
    } catch {
      setError("Не удалось передать диалог.");
    }
  };

  const resume = async () => {
    if (!selectedId) return;
    try {
      await api.resume(selectedId);
      loadDetail(selectedId);
      loadList();
    } catch {
      setError("Не удалось вернуть диалог Magi.");
    }
  };

  const conversation = detail?.conversation;

  return (
    <div className="page page-inbox">
      <header className="page-head">
        <div>
          <div className="eyebrow">Единый инбокс</div>
          <h1>
            {user.role === "operator" ? "Мои диалоги" : "Диалоги с клиентами"}
          </h1>
          <p className="muted">Сайт, Telegram, email и Instagram в одном окне.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setNewLeadOpen(true)}>
          <IconPlus size={16} /> Новый лид
        </button>
      </header>

      {error && <ErrorNote text={error} />}

      <div className="inbox">
        <section className="inbox-list">
          <div className="inbox-list-head">
            <label className="search compact">
              <IconSearch size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Поиск по клиенту"
                aria-label="Поиск диалогов"
              />
            </label>
            <div className="filter-row">
              <select value={channel} onChange={(event) => setChannel(event.target.value)} aria-label="Канал">
                {CHANNELS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Статус диалога">
                {STATUSES.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="inbox-scroll">
            {loading && items.length === 0 ? (
              <Spinner label="Загружаем диалоги…" />
            ) : items.length === 0 ? (
              <EmptyState title="Диалогов нет" text="Измените фильтры или создайте нового лида." />
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  className={`dialog-item ${selectedId === item.id ? "active" : ""}`}
                  onClick={() => setSelectedId(item.id)}
                >
                  <Avatar name={item.client_name} size={38} />
                  <div className="dialog-copy">
                    <div className="dialog-top">
                      <strong>{item.client_name}</strong>
                      <span className="dialog-time">{timeAgo(item.last_message_at)}</span>
                    </div>
                    <div className="dialog-subject">{item.subject || "Без темы"}</div>
                    <div className="dialog-bottom">
                      <span className="dialog-preview">{item.last_message || "Нет сообщений"}</span>
                      <span className={`status-dot status-${item.status}`} title={item.status} />
                    </div>
                    <div className="dialog-tags">
                      <ChannelBadge channel={item.channel} />
                      {item.mode === "human" && <span className="mini-chip">у человека</span>}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="chat">
          {!conversation ? (
            <div className="chat-empty">
              <EmptyState
                icon={<IconSpark size={28} />}
                title="Выберите диалог"
                text="Слева — все обращения. Magi уже отвечает на типовые вопросы."
              />
            </div>
          ) : detailLoading && !detail ? (
            <Spinner label="Открываем диалог…" />
          ) : (
            <>
              <header className="chat-head">
                <div className="chat-person">
                  <Avatar name={conversation.client_name} size={40} />
                  <div>
                    <strong>{conversation.client_name}</strong>
                    <span>
                      {conversation.city || "—"} · {conversation.subject || "Без темы"}
                    </span>
                  </div>
                </div>
                <div className="chat-head-actions">
                  <ChannelBadge channel={conversation.channel} />
                  <ModeBadge mode={conversation.mode} />
                  <ConversationStatus status={conversation.status} />
                  {conversation.sla_due_at && conversation.status !== "closed" && (
                    <span
                      className={`sla-chip ${new Date(conversation.sla_due_at).getTime() < Date.now() ? "sla-late" : ""}`}
                      title="Ответ по SLA темы"
                    >
                      SLA {formatMinutes(Math.round((new Date(conversation.sla_due_at).getTime() - Date.now()) / 60000))}
                    </span>
                  )}
                  {conversation.mode === "magi" && (
                    <button className="btn btn-small" onClick={handoff}>
                      <IconUser size={14} /> Передать человеку
                    </button>
                  )}
                </div>
              </header>

              {conversation.mode === "human" && (
                <div className="handoff-banner">
                  <IconUser size={17} />
                  <div>
                    <strong>Диалог у человека</strong>
                    <span>{conversation.handoff_reason || "Нужна помощь менеджера"}</span>
                  </div>
                  <button className="link-btn" onClick={resume}>Вернуть Magi</button>
                </div>
              )}

              {conversation.summary && conversation.mode === "human" && (
                <div className="summary-banner">
                  <IconSpark size={15} />
                  <div>
                    <strong>AI-сводка для менеджера</strong>
                    <pre>{conversation.summary}</pre>
                  </div>
                </div>
              )}

              <div className="messages" ref={messagesRef}>
                {detail.messages.map((message) => (
                  <div key={message.id} className={`message message-${message.author}`}>
                    <div className="message-meta">
                      {message.author === "lead" ? "Клиент" : message.author === "magi" ? "Magi" : "Менеджер"}
                      <span>{new Date(message.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                    <div className="bubble">
                      {message.author === "magi" && <IconSpark size={14} className="bubble-spark" />}
                      {message.body}
                    </div>
                    {message.author === "magi" && message.confidence != null && (
                      <div className="message-foot">
                        <span className={`confidence ${message.confidence < 0.6 ? "confidence-low" : ""}`}>
                          <IconCheck size={12} /> уверенность {Math.round(message.confidence * 100)}%
                        </span>
                        {message.intent && <span>{INTENT_LABELS[message.intent] ?? message.intent}</span>}
                        {message.provider && <span>{message.provider === "local" ? "локальный движок" : message.provider}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="composer">
                {!asLead && chatTemplates.length > 0 && (
                  <div className="template-chips">
                    {chatTemplates.map((t, index) => (
                      <button
                        key={t.id}
                        className="template-chip"
                        title={t.body}
                        onClick={() => fillTemplate(t)}
                      >
                        {index < 9 ? `Alt+${index + 1} · ` : ""}{t.title}
                      </button>
                    ))}
                  </div>
                )}
                <div className="composer-row">
                  <textarea
                    value={composer}
                    onChange={(event) => setComposer(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault();
                        send();
                      } else if (event.key === "Tab" && !event.shiftKey && !composer.trim() && !asLead) {
                        // Tab на пустом поле — принять последний ответ Magi как черновик.
                        const magi = detail?.messages.filter((m) => m.author === "magi") ?? [];
                        const last = magi[magi.length - 1];
                        if (last) {
                          event.preventDefault();
                          setComposer(last.body);
                        }
                      }
                    }}
                    placeholder={
                      asLead
                        ? "Например: «Успеет ли фотокнига к 14 ноября?»"
                        : "Ответить клиенту…"
                    }
                    rows={3}
                    aria-label="Сообщение"
                  />
                  <button
                    className="btn btn-primary btn-send"
                    onClick={send}
                    disabled={!composer.trim() || sending}
                  >
                    {sending ? "…" : <IconSend size={17} />}
                    <span>{asLead ? "Как клиент" : "Отправить"}</span>
                  </button>
                </div>
                <div className="composer-foot">
                  <label className="lead-toggle">
                    <input
                      type="checkbox"
                      checked={asLead}
                      onChange={(event) => setAsLead(event.target.checked)}
                    />
                    <span>Демо: писать от лица клиента</span>
                  </label>
                  <p className="composer-hint">
                    {asLead
                      ? "Magi ответит автоматически, если уверен. Иначе передаст диалог человеку."
                      : "Ответ менеджера переводит диалог в ручной режим."}
                    {" "}Ctrl+Enter — отправить · Tab — ответ Magi · Alt+цифра — шаблон · J/K — диалоги.
                  </p>
                </div>
              </div>
            </>
          )}
        </section>

        <aside className="context">
          {detail ? (
            <>
              <div className="context-head">
                <div className="context-title">
                  <Avatar name={detail.client.name} size={42} />
                  <div>
                    <strong>{detail.client.name}</strong>
                    <ClientStatus status={detail.client.status} />
                  </div>
                </div>
                <button className="link-btn" onClick={() => onOpenClient(detail.client.id)}>
                  Карточка <IconArrow size={14} />
                </button>
              </div>

              <div className="context-block">
                <div className="context-label">Клиент</div>
                <dl className="facts compact">
                  <div><dt>Телефон</dt><dd>{detail.client.phone || "—"}</dd></div>
                  <div><dt>Email</dt><dd>{detail.client.email || "—"}</dd></div>
                  <div><dt>LTV</dt><dd>{formatMoney(detail.client.ltv)}</dd></div>
                  <div><dt>Ответственный</dt><dd>{detail.client.owner_name || "—"}</dd></div>
                </dl>
                {detail.client.tags && (
                  <div className="tags">
                    {detail.client.tags.split(",").filter(Boolean).map((tag) => (
                      <span className="tag" key={tag}>{tag.trim()}</span>
                    ))}
                  </div>
                )}
              </div>

              <div className="context-block">
                <div className="context-label">Последний заказ</div>
                {detail.orders[0] ? (
                  <div className="context-order">
                    <strong>{detail.orders[0].product}</strong>
                    <span>{formatMoney(detail.orders[0].amount)} · {formatDateTime(detail.orders[0].promised_at)}</span>
                  </div>
                ) : (
                  <p className="quiet">Заказов нет.</p>
                )}
                {detail.orders.length > 1 && (
                  <div className="context-history">
                    <p className="context-label">Ранее</p>
                    {detail.orders.slice(1, 3).map((order) => (
                      <div key={order.id}>
                        <span>{order.product}</span>
                        <span>{formatMoney(order.amount)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {detail.orders[0] && user.role !== "analyst" && (
                <div className="context-block">
                  <div className="context-label">Быстрые действия</div>
                  <div className="order-actions">
                    <button className="btn btn-small" onClick={() => runOrderAction("rush")} title="Поставить заказ первым в очереди цеха">Срочная печать</button>
                    <button className="btn btn-small" onClick={() => runOrderAction("redone")} title="Создать повтор печати без оплаты">Повтор печати</button>
                    <button className="btn btn-small" onClick={() => runOrderAction("extend")} title="+3 дня хранения в пункте выдачи">Продлить ПВЗ</button>
                    <button className="btn btn-small" onClick={() => runOrderAction("promo")} title="Промокод −10% в карточку клиента">Промокод −10%</button>
                  </div>
                  {actionNote && <p className="order-action-note">{actionNote}</p>}
                </div>
              )}

              <div className="context-block">
                <div className="context-label">Следующий шаг</div>
                <div className={`next-step ${conversation?.mode === "human" ? "next-human" : ""}`}>
                  {conversation?.mode === "human" ? (
                    <>
                      <IconUser size={16} />
                      <p>Ответить клиенту. Причина передачи: {conversation.handoff_reason || "нужна помощь"}.</p>
                    </>
                  ) : (
                    <>
                      <IconSpark size={16} />
                      <p>Magi ведёт диалог. Вмешайтесь, если клиент просит человека.</p>
                    </>
                  )}
                </div>
              </div>

              <div className="context-block">
                <div className="context-label">Ожидание</div>
                <div className="context-wait">
                  <span>Последнее сообщение</span>
                  <strong>{formatMinutes(Math.max(0, Math.round((Date.now() - new Date(detail.conversation.last_message_at).getTime()) / 60000)))}</strong>
                </div>
              </div>
            </>
          ) : (
            <div className="context-empty">Контекст клиента появится здесь.</div>
          )}
        </aside>
      </div>

      {newLeadOpen && (
        <NewLeadModal
          onClose={() => setNewLeadOpen(false)}
          onCreated={(conversationId) => {
            setNewLeadOpen(false);
            setSelectedId(conversationId);
            loadList();
          }}
        />
      )}
    </div>
  );
}

function NewLeadModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (conversationId: number) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [channel, setChannel] = useState("site");
  const [tgHandle, setTgHandle] = useState("");
  const [message, setMessage] = useState("Здравствуйте! Хочу узнать о фотокниге.");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      const result = await api.createLead({ name, phone, channel, message, tg_handle: tgHandle });
      onCreated(result.conversation_id);
    } catch {
      setError("Не удалось создать лида.");
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Новый лид"
      subtitle="Создадим клиента и диалог. Magi ответит первым."
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-quiet" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={!name.trim() || saving}>
            {saving ? "Создаём…" : "Создать и ответить"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <label className="field">
          <span>Имя</span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, Анна" autoFocus />
        </label>
        <label className="field">
          <span>Телефон</span>
          <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+375 29 …" />
        </label>
        <label className="field">
          <span>Канал</span>
          <select value={channel} onChange={(event) => setChannel(event.target.value)}>
            <option value="site">Сайт</option>
            <option value="telegram">Telegram</option>
            <option value="email">Email</option>
            <option value="instagram">Instagram</option>
          </select>
        </label>
        {channel === "telegram" && (
          <label className="field">
            <span>Telegram ID или @name</span>
            <input
              value={tgHandle}
              onChange={(event) => setTgHandle(event.target.value)}
              placeholder="1287875313 или @ivan"
            />
          </label>
        )}
        <label className="field field-wide">
          <span>Первое сообщение</span>
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={3} />
        </label>
        {error && <p className="form-error">{error}</p>}
      </div>
    </Modal>
  );
}
