import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Decision, User } from "../types";
import { Badge, Card, ErrorNote, Modal, Spinner, formatDateTime, formatDate } from "../components";
import { IconCheck } from "../icons";

const STATUS_LABELS: Record<string, string> = {
  open: "Открыто",
  in_progress: "В работе",
  done: "Выполнено",
  cancelled: "Отменено",
};

const PRIORITY_LABELS: Record<string, string> = { low: "Низкий", normal: "Обычный", high: "Высокий" };

const STATUS_TONES: Record<string, "blue" | "amber" | "green" | "neutral"> = {
  open: "blue",
  in_progress: "amber",
  done: "green",
  cancelled: "neutral",
};

const DEFAULT_KPIS = [
  { key: "sla_rate", name: "Ответ в SLA" },
  { key: "ai_share", name: "Сценарии ИИ" },
  { key: "on_time", name: "Заказы в срок" },
  { key: "late_share", name: "Просроченные заказы" },
  { key: "defect_rate", name: "Брак и перепечатка" },
  { key: "load_risk", name: "Риск перегрузки" },
  { key: "cash_exec", name: "Исполнение БДДС" },
  { key: "gross_margin", name: "Валовая маржа" },
  { key: "staff_coverage", name: "Обеспеченность персоналом" },
  { key: "repeat_rate", name: "Повторные покупки" },
];

export function DecisionModal({
  kpis = DEFAULT_KPIS,
  initial,
  onClose,
  onCreated,
}: {
  kpis?: { key: string; name: string }[];
  initial?: { kpi_key?: string; problem?: string; cause?: string };
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [users, setUsers] = useState<{ id: number; name: string; title: string }[]>([]);
  const [form, setForm] = useState({
    kpi_key: initial?.kpi_key ?? DEFAULT_KPIS[0].key,
    problem: initial?.problem ?? "",
    impact: "",
    cause: initial?.cause ?? "",
    action: "",
    owner_id: "",
    due_at: "",
    priority: "normal",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.users().then((r) => setUsers(r.items)).catch(() => setUsers([]));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const result = await api.createDecision({
        kpi_key: form.kpi_key,
        problem: form.problem,
        impact: form.impact,
        cause: form.cause,
        action: form.action,
        owner_id: form.owner_id ? Number(form.owner_id) : null,
        due_at: form.due_at ? new Date(`${form.due_at}T12:00:00Z`).toISOString() : null,
        priority: form.priority,
      });
      onCreated(result.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить решение");
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Карточка решения"
      subtitle="Проблема → влияние → причина → действие → владелец → срок"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-quiet" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={(e) => submit(e as unknown as FormEvent)} disabled={saving || form.problem.length < 5 || form.action.length < 5}>
            {saving ? "Сохраняем…" : "Создать решение"}
          </button>
        </>
      }
    >
      <form className="form-grid" onSubmit={submit}>
        <label className="field span-2">
          <span>KPI</span>
          <select value={form.kpi_key} onChange={(e) => setForm({ ...form, kpi_key: e.target.value })}>
            {kpis.map((k) => (
              <option key={k.key} value={k.key}>{k.name}</option>
            ))}
          </select>
        </label>
        <label className="field span-2">
          <span>Проблема</span>
          <input value={form.problem} onChange={(e) => setForm({ ...form, problem: e.target.value })} required minLength={5} />
        </label>
        <label className="field">
          <span>Влияние</span>
          <input value={form.impact} onChange={(e) => setForm({ ...form, impact: e.target.value })} />
        </label>
        <label className="field">
          <span>Причина</span>
          <input value={form.cause} onChange={(e) => setForm({ ...form, cause: e.target.value })} />
        </label>
        <label className="field span-2">
          <span>Действие</span>
          <textarea value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })} rows={2} required minLength={5} />
        </label>
        <label className="field">
          <span>Владелец</span>
          <select value={form.owner_id} onChange={(e) => setForm({ ...form, owner_id: e.target.value })}>
            <option value="">Не назначен</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.name} · {u.title}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Срок</span>
          <input type="date" value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} />
        </label>
        <label className="field span-2">
          <span>Приоритет</span>
          <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            <option value="low">Низкий</option>
            <option value="normal">Обычный</option>
            <option value="high">Высокий</option>
          </select>
        </label>
        {error && <p className="form-error span-2">{error}</p>}
      </form>
    </Modal>
  );
}

export function Decisions({ user }: { user: User }) {
  const [items, setItems] = useState<Decision[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [creating, setCreating] = useState(false);
  const canManage = user.role !== "operator";

  const load = () => {
    api.decisions({ status, priority })
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message));
  };

  useEffect(load, [status, priority]);

  async function patch(id: number, data: { status?: string; result_note?: string }) {
    await api.patchDecision(id, data);
    load();
  }

  if (error) return <ErrorNote text={error} />;
  if (!items) return <Spinner label="Загружаю реестр решений…" />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Сигнал → причина → владелец → действие → проверка</div>
          <h1>Реестр решений</h1>
          <p className="muted">Каждая карточка сохраняется и проверяется повторно. Все изменения — в журнале.</p>
        </div>
        {canManage && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>Новое решение</button>
        )}
      </header>

      <div className="toolbar">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Статус">
          <option value="">Все статусы</option>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Приоритет">
          <option value="">Все приоритеты</option>
          {Object.entries(PRIORITY_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      {items.length === 0 ? (
        <Card><p className="muted">Решений по фильтру нет.</p></Card>
      ) : (
        <div className="decision-list">
          {items.map((d) => (
            <Card key={d.id} className={`decision-card ${d.priority === "high" ? "decision-high" : ""}`}>
              <div className="decision-head">
                <div className="decision-title">
                  {d.kpi_name && <Badge tone="blue">{d.kpi_name}</Badge>}
                  <Badge tone={STATUS_TONES[d.status]}>{STATUS_LABELS[d.status]}</Badge>
                  {d.priority === "high" && <Badge tone="red">Высокий приоритет</Badge>}
                </div>
                <span className="muted small">обновлено {formatDateTime(d.updated_at)}</span>
              </div>
              <h3 className="decision-problem">{d.problem}</h3>
              <dl className="facts decision-facts">
                {d.impact && <div><dt>Влияние</dt><dd>{d.impact}</dd></div>}
                {d.cause && <div><dt>Причина</dt><dd>{d.cause}</dd></div>}
                <div><dt>Действие</dt><dd>{d.action}</dd></div>
                <div><dt>Владелец</dt><dd>{d.owner_name ?? "Не назначен"}</dd></div>
                <div><dt>Срок</dt><dd>{formatDate(d.due_at)}</dd></div>
                {d.result_note && <div><dt>Результат</dt><dd>{d.result_note}</dd></div>}
              </dl>
              {canManage && d.status !== "done" && d.status !== "cancelled" && (
                <div className="decision-actions">
                  {d.status === "open" && (
                    <button className="btn btn-small" onClick={() => patch(d.id, { status: "in_progress" })}>
                      В работу
                    </button>
                  )}
                  <button
                    className="btn btn-small"
                    onClick={() => {
                      const note = window.prompt("Что изменилось после решения? (результат проверки)");
                      if (note !== null) patch(d.id, { status: "done", result_note: note });
                    }}
                  >
                    <IconCheck size={14} /> Выполнено с результатом
                  </button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {creating && (
        <DecisionModal onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />
      )}
    </div>
  );
}
