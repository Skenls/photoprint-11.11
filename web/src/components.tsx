import { useEffect, type ReactNode } from "react";
import { IconAlert, IconClose, IconSpark } from "./icons";
import type { SeriesPoint } from "./types";

export const ROLE_LABELS: Record<string, string> = {
  director: "Директор",
  manager: "Руководитель отдела",
  operator: "Менеджер",
};

export const CHANNEL_LABELS: Record<string, string> = {
  site: "Сайт",
  telegram: "Telegram",
  email: "Email",
  instagram: "Instagram",
};

export const CLIENT_STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  qualified: "В работе",
  customer: "Клиент",
  sleeping: "Спящий",
};

export const ORDER_STATUS_LABELS: Record<string, string> = {
  new: "Принят",
  in_production: "В производстве",
  ready: "Готов",
  delivered: "Доставлен",
  delayed: "Задержка",
};

export const CONVERSATION_STATUS_LABELS: Record<string, string> = {
  open: "Открыт",
  waiting: "Ждёт ответа",
  closed: "Закрыт",
};

export const INTENT_LABELS: Record<string, string> = {
  greeting: "Приветствие",
  order_status: "Статус заказа",
  price: "Цена",
  delivery: "Доставка",
  payment: "Оплата",
  discount: "Скидка",
  production: "Сроки",
  pickup: "Самовывоз",
  custom: "Индивидуальный заказ",
  complaint: "Жалоба",
  return: "Возврат",
  quality: "Качество",
  docs: "Документы",
  promo: "Промо",
  partnership: "Партнёры",
  handoff: "Передано человеку",
  human: "Нужен человек",
  thanks: "Благодарность",
  other: "Другое",
};

export function formatMoney(value: number): string {
  return `${new Intl.NumberFormat("ru-RU").format(Math.round(value))} BYN`;
}

export function formatPercent(value: number): string {
  return `${String(value).replace(".", ",")}%`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

export function timeAgo(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ч`;
  const days = Math.round(hours / 24);
  return `${days} дн`;
}

export function formatMinutes(minutes: number): string {
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
  return `${Math.floor(hours / 24)} дн`;
}

export function initials(name: string): string {
  return (name ?? "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

export function firstName(name: string): string {
  return name?.split(" ")[0] ?? name ?? "";
}

function toneIndex(name: string): number {
  let hash = 0;
  for (const char of name ?? "") hash = (hash * 31 + char.charCodeAt(0)) % 6;
  return hash + 1;
}

export function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  return (
    <span
      className={`avatar avatar-${toneIndex(name)}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.34) }}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

type Tone = "neutral" | "green" | "blue" | "amber" | "red" | "purple" | "magi";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function ChannelBadge({ channel }: { channel: string }) {
  return (
    <span className={`channel channel-${channel}`}>
      <span className="channel-dot" aria-hidden="true" />
      {CHANNEL_LABELS[channel] ?? channel}
    </span>
  );
}

export function ClientStatus({ status }: { status: string }) {
  const tone: Tone =
    status === "customer" ? "green" : status === "new" ? "blue" : status === "qualified" ? "amber" : "neutral";
  return <Badge tone={tone}>{CLIENT_STATUS_LABELS[status] ?? status}</Badge>;
}

export function OrderStatus({ status }: { status: string }) {
  const tone: Tone =
    status === "delayed" ? "red" : status === "ready" ? "green" : status === "in_production" ? "amber" : status === "new" ? "blue" : "neutral";
  return <Badge tone={tone}>{ORDER_STATUS_LABELS[status] ?? status}</Badge>;
}

export function ConversationStatus({ status }: { status: string }) {
  const tone: Tone = status === "open" ? "green" : status === "waiting" ? "amber" : "neutral";
  return <Badge tone={tone}>{CONVERSATION_STATUS_LABELS[status] ?? status}</Badge>;
}

export function ModeBadge({ mode }: { mode: string }) {
  return mode === "magi" ? (
    <span className="badge badge-magi">
      <IconSpark size={12} /> Magi
    </span>
  ) : (
    <Badge tone="blue">Человек</Badge>
  );
}

export function KpiCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "accent" | "danger" | "magi" | "warn";
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
  bodyClassName,
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={bodyClassName ?? "card-body"}>{children}</div>
    </section>
  );
}

export function BarChart({
  data,
  field,
  tone = "green",
  ariaLabel,
}: {
  data: SeriesPoint[];
  field: "leads" | "revenue";
  tone?: "green" | "blue";
  ariaLabel: string;
}) {
  const width = 620;
  const height = 190;
  const padX = 10;
  const padTop = 16;
  const padBottom = 26;
  const chartHeight = height - padTop - padBottom;
  const max = Math.max(1, ...data.map((point) => point[field]));
  const slot = (width - padX * 2) / Math.max(1, data.length);
  const barWidth = Math.max(6, slot - 7);
  const color = tone === "green" ? "var(--accent)" : "var(--blue)";

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {[0, 0.5, 1].map((tick) => {
          const y = padTop + chartHeight * tick;
          return <line key={tick} x1={padX} x2={width - padX} y1={y} y2={y} className="chart-grid" />;
        })}
        {data.map((point, index) => {
          const value = point[field];
          const h = Math.max(value > 0 ? 3 : 0, (value / max) * chartHeight);
          const x = padX + index * slot + (slot - barWidth) / 2;
          const y = padTop + chartHeight - h;
          return (
            <g key={point.date}>
              <rect x={x} y={y} width={barWidth} height={h} rx={4} fill={color} className="chart-bar">
                <title>{`${point.label}: ${value}`}</title>
              </rect>
              {index % 2 === 0 && (
                <text x={x + barWidth / 2} y={height - 6} textAnchor="middle" className="chart-label">
                  {point.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function EmptyState({
  title,
  text,
  action,
  icon,
}: {
  title: string;
  text: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon ?? <IconSpark size={22} />}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function Spinner({ label = "Загружаем…" }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function MiniBars({
  items,
  tone = "green",
  format,
}: {
  items: { label: string; value: number; tone?: "green" | "red" | "amber" | "blue" }[];
  tone?: "green" | "red" | "amber" | "blue";
  format?: (value: number) => string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="mini-bars">
      {items.map((item) => (
        <div className="mini-bar-row" key={item.label}>
          <span className="mini-bar-label">{item.label}</span>
          <div className="mini-bar-track">
            <span
              className={`mini-bar-fill t-${item.tone ?? tone}`}
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <span className="mini-bar-value">{format ? format(item.value) : item.value}</span>
        </div>
      ))}
    </div>
  );
}

export function KpiStatusDot({ status }: { status: string }) {
  return <span className={`kpi-dot kpi-dot-${status}`} aria-hidden="true" />;
}

export function ErrorNote({ text }: { text: string }) {
  return (
    <div className="error-note" role="alert">
      <IconAlert size={16} />
      <span>{text}</span>
    </div>
  );
}

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="modal-sub">{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <IconClose size={18} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        <footer className="modal-foot">{footer}</footer>
      </div>
    </div>
  );
}
