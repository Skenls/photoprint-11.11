import { useEffect, useState } from "react";
import { api } from "../api";
import type { RuleItem, RuleTestResult, TopicRow } from "../types";
import { Badge, Card, ErrorNote, Spinner } from "../components";
import { IconCheck, IconRefresh, IconSpark } from "../icons";

const CHANNELS = [
  { id: "site", label: "Сайт" },
  { id: "telegram", label: "Telegram" },
  { id: "email", label: "Email" },
  { id: "instagram", label: "Instagram" },
];

const INTENT_LABELS: Record<string, string> = {
  greeting: "Приветствия",
  order_status: "Статус заказа",
  price: "Цены",
  delivery: "Доставка",
  payment: "Оплата",
  pickup: "Самовывоз",
  discount: "Скидки",
  quality: "Брак и качество",
  docs: "Документы и счёт",
};

const KIND_LABELS: Record<string, string> = {
  route: "Маршрутизация",
  threshold: "Порог уверенности",
  trigger: "Передача человеку",
  sla: "SLA",
  reminder: "Напоминания",
};

function RuleConfigEditor({
  rule,
  topics,
  onChange,
}: {
  rule: RuleItem;
  topics: TopicRow[];
  onChange: (config: Record<string, unknown>) => void;
}) {
  const cfg = rule.config;
  const intents = (cfg.intents as string[] | undefined) ?? [];
  const channels = (cfg.channels as string[] | undefined) ?? [];

  if (rule.key === "route.auto_answer") {
    return (
      <div className="rule-editor">
        <div className="field">
          <span>Каналы автоответа</span>
          <div className="check-grid">
            {CHANNELS.map((c) => (
              <label key={c.id} className="check-row compact">
                <input
                  type="checkbox"
                  checked={channels.includes(c.id)}
                  onChange={(e) =>
                    onChange({ ...cfg, channels: e.target.checked ? [...channels, c.id] : channels.filter((x) => x !== c.id) })
                  }
                />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="field">
          <span>Темы автоответа</span>
          <div className="check-grid">
            {Object.entries(INTENT_LABELS).map(([key, label]) => (
              <label key={key} className="check-row compact">
                <input
                  type="checkbox"
                  checked={intents.includes(key)}
                  onChange={(e) =>
                    onChange({ ...cfg, intents: e.target.checked ? [...intents, key] : intents.filter((x) => x !== key) })
                  }
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (rule.key === "threshold.confidence") {
    const value = Number(cfg.value ?? 0.55);
    return (
      <div className="field">
        <span>Порог уверенности</span>
        <div className="range-row">
          <input
            type="range"
            min={0.1}
            max={0.99}
            step={0.01}
            value={value}
            onChange={(e) => onChange({ ...cfg, value: Number(e.target.value) })}
          />
          <strong>{Math.round(value * 100)}%</strong>
        </div>
        <small>Ниже порога Magi передаёт диалог человеку.</small>
      </div>
    );
  }

  if (rule.kind === "trigger") {
    const keywords = (cfg.keywords as string[] | undefined) ?? [];
    return (
      <div className="field">
        <span>Ключевые слова (через запятую)</span>
        <input
          value={keywords.join(", ")}
          onChange={(e) => onChange({ ...cfg, keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
        />
        <small>Сообщение с этим словом сразу уходит человеку.</small>
      </div>
    );
  }

  if (rule.kind === "sla") {
    const factor = Number(cfg.factor ?? 2);
    return (
      <div className="field">
        <span>Эскалация: во сколько раз позже SLA поднимать задачу руководителю</span>
        <div className="range-row">
          <input type="range" min={1} max={5} step={0.5} value={factor}
            onChange={(e) => onChange({ ...cfg, factor: Number(e.target.value) })} />
          <strong>×{String(factor).replace(".", ",")}</strong>
        </div>
        <small>SLA по темам: {topics.map((t) => `${t.name} ${t.sla_hours}ч`).slice(0, 4).join(" · ")}…</small>
      </div>
    );
  }

  const hours = Number(cfg.hours_before ?? 24);
  return (
    <div className="field">
      <span>Напоминание о заказе в ПВЗ, часов до конца хранения</span>
      <div className="range-row">
        <input type="range" min={4} max={72} step={4} value={hours}
          onChange={(e) => onChange({ ...cfg, hours_before: Number(e.target.value) })} />
        <strong>{hours} ч</strong>
      </div>
      <small>Magi сам пишет клиенту в диалог и записывает напоминание в журнал.</small>
    </div>
  );
}

export function Rules({ canEdit }: { canEdit: boolean }) {
  const [items, setItems] = useState<RuleItem[] | null>(null);
  const [topics, setTopics] = useState<TopicRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [tests, setTests] = useState<Record<string, RuleTestResult>>({});
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");

  const load = () => {
    api.rules()
      .then((r) => {
        setItems(r.items);
        setTopics(r.topics);
        setDrafts(Object.fromEntries(r.items.map((i) => [i.key, i.config])));
      })
      .catch((e) => setError(e.message));
  };

  useEffect(load, []);

  if (error) return <ErrorNote text={error} />;
  if (!items) return <Spinner label="Загружаю правила Magi…" />;

  async function save(rule: RuleItem) {
    setBusyKey(rule.key);
    setError("");
    try {
      await api.patchRule(rule.key, { config: drafts[rule.key], enabled: Boolean(rule.enabled) });
      await api.testRule(rule.key, drafts[rule.key]).then((t) => setTests((prev) => ({ ...prev, [rule.key]: t })));
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить правило");
    } finally {
      setBusyKey("");
    }
  }

  async function toggle(rule: RuleItem) {
    setBusyKey(rule.key);
    try {
      await api.patchRule(rule.key, { config: drafts[rule.key], enabled: !rule.enabled });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось изменить правило");
    } finally {
      setBusyKey("");
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Правится вживую · без разработчиков и релизов</div>
          <h1>Magi Конструктор правил</h1>
          <p className="muted">
            Ответ на главную боль коробочных CRM: «правка на пять минут ждёт две недели». Здесь руководитель меняет
            правило, проверяет его на последних обращениях и применяет — Magi начинает вести себя иначе сразу.
          </p>
        </div>
        <Badge tone="magi"><IconSpark size={12} /> {items.length} правил</Badge>
      </header>

      {error && <ErrorNote text={error} />}

      <div className="rule-list">
        {items.map((rule) => {
          const test = tests[rule.key];
          const dirty = JSON.stringify(drafts[rule.key]) !== JSON.stringify(rule.config);
          return (
            <Card key={rule.key} className={`rule-card ${rule.enabled ? "" : "rule-off"}`}>
              <div className="decision-head">
                <div className="decision-title">
                  <Badge tone="blue">{KIND_LABELS[rule.kind]}</Badge>
                  <strong className="rule-key">{rule.title}</strong>
                  {rule.enabled ? <Badge tone="green">Включено</Badge> : <Badge tone="neutral">Выключено</Badge>}
                </div>
                {canEdit && (
                  <button className="btn btn-small" onClick={() => toggle(rule)} disabled={busyKey === rule.key}>
                    {rule.enabled ? "Выключить" : "Включить"}
                  </button>
                )}
              </div>

              <div className={canEdit ? "" : "rule-readonly"}>
                <RuleConfigEditor
                  rule={rule}
                  topics={topics}
                  onChange={(config) => setDrafts((prev) => ({ ...prev, [rule.key]: config }))}
                />
              </div>

              <div className="rule-actions">
                {canEdit && (
                  <>
                    <button
                      className="btn btn-small"
                      disabled={busyKey === rule.key}
                      onClick={() => {
                        setBusyKey(rule.key);
                        api.testRule(rule.key, drafts[rule.key])
                          .then((t) => setTests((prev) => ({ ...prev, [rule.key]: t })))
                          .catch((e) => setError(e instanceof Error ? e.message : "Ошибка теста"))
                          .finally(() => setBusyKey(""));
                      }}
                    >
                      <IconRefresh size={14} /> Проверить на потоке
                    </button>
                    <button
                      className="btn btn-primary btn-small"
                      disabled={busyKey === rule.key || !dirty}
                      onClick={() => save(rule)}
                    >
                      <IconCheck size={14} /> {busyKey === rule.key ? "…" : dirty ? "Применить" : "Сохранено"}
                    </button>
                  </>
                )}
                {!canEdit && <span className="muted small">Меняют директор и руководитель клиентского сервиса.</span>}
              </div>

              {test && (
                <div className="rule-test">
                  <div className="rule-test-row">
                    <span>Поток: {test.total} последних обращений</span>
                    <span>Было: автоответ {test.old.auto_pct}%</span>
                    <span className={test.new.auto_pct !== test.old.auto_pct ? "rule-test-changed" : ""}>
                      Станет: автоответ {test.new.auto_pct}%
                    </span>
                  </div>
                  {test.samples.length > 0 && (
                    <ul className="rule-test-samples">
                      {test.samples.map((s) => (
                        <li key={s.conversation_id}>
                          <span className="rule-test-text">«{s.text}»</span>
                          <span>{s.old} → <strong>{s.new}</strong></span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <p className="muted small">
                Обновлено: {rule.updated_by_name ?? "система"}
                {rule.updated_at ? ` · ${new Date(rule.updated_at).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
              </p>
            </Card>
          );
        })}
      </div>

      <p className="page-foot">
        Каждая правка правила сохраняется в журнал аудита: кто, когда и что изменил. Правила читаются Magi
        при каждом сообщении — перезапуск не нужен.
      </p>
    </div>
  );
}
