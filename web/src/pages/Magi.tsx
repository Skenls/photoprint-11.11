import { useEffect, useState } from "react";
import { api } from "../api";
import type { AgentPayload, LearningPayload, User } from "../types";
import {
  Card,
  ErrorNote,
  KpiCard,
  Spinner,
  formatNumber,
  formatPercent,
} from "../components";
import { IconBot, IconCheck, IconRefresh, IconSpark } from "../icons";

const INTENTS: Record<string, string> = {
  greeting: "Приветствие",
  order_status: "Статус заказа",
  price: "Цена",
  delivery: "Доставка",
  payment: "Оплата",
  discount: "Скидки",
  production: "Сроки",
  pickup: "Самовывоз",
  custom: "Нестандарт",
  complaint: "Жалоба",
  thanks: "Благодарность",
  other: "Другое",
};

const CHANNELS = [
  { id: "site", label: "Сайт" },
  { id: "telegram", label: "Telegram" },
  { id: "email", label: "Email" },
  { id: "instagram", label: "Instagram" },
];

export function Magi({ user }: { user: User }) {
  const [data, setData] = useState<AgentPayload | null>(null);
  const [learning, setLearning] = useState<LearningPayload | null>(null);
  const [learningError, setLearningError] = useState("");
  const [learningBusy, setLearningBusy] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [threshold, setThreshold] = useState(0.55);
  const [channels, setChannels] = useState<string[]>([]);

  function apply(payload: AgentPayload) {
    setData(payload);
    setEnabled(payload.settings.magi_enabled);
    setThreshold(payload.settings.confidence_threshold);
    setChannels(payload.settings.auto_channels);
  }

  useEffect(() => {
    api.agent().then(apply).catch((e) => setError(e.message));
    if (user.role === "director" || (user.role === "head" && user.team === "Клиентский сервис")) {
      api.learning().then(setLearning).catch((e) => setLearningError(e.message));
    }
  }, []);

  async function grow(kind: "kb" | "rule", payload: { topic?: string; reason?: string }) {
    setLearningBusy(kind + (payload.topic ?? payload.reason ?? ""));
    setLearningError("");
    try {
      await api.applyLearning({ kind, ...payload });
      setLearning(await api.learning());
      if (kind === "kb") {
        apply(await api.agent());
      }
    } catch (e) {
      setLearningError(e instanceof Error ? e.message : "Не удалось применить");
    } finally {
      setLearningBusy("");
    }
  }

  async function save() {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await api.updateAgent({
        magi_enabled: enabled,
        confidence_threshold: threshold,
        auto_channels: channels,
      });
      apply(await api.agent());
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  async function resetDemo() {
    if (!confirm("Сбросить демо-данные и вернуть исходное состояние?")) return;
    try {
      await api.resetDemo();
      window.location.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сбросить");
    }
  }

  if (!data) {
    return error ? <ErrorNote text={error} /> : <Spinner label="Загружаю настройки Magi" />;
  }

  const { metrics, settings, provider, can_edit } = data;
  const local = provider.provider === "local";

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Агент клиентского сервиса</div>
          <h1>Magi</h1>
          <p className="page-sub">
            Отвечает на типовые вопросы по данным CRM и передаёт человеку всё,
            что требует решения.
          </p>
        </div>
        <div className={`agent-state ${enabled ? "on" : "off"}`}>
          <span className="dot" />
          {enabled ? "Magi включён" : "Magi выключен"}
        </div>
      </div>

      {error && <ErrorNote text={error} />}

      <div className="kpi-grid">
        <KpiCard
          label="Автоответ"
          value={formatPercent(metrics.automation_rate)}
          hint="диалогов ведёт Magi"
          tone="accent"
        />
        <KpiCard
          label="Уверенность"
          value={formatPercent(metrics.avg_confidence)}
          hint="средняя по ответам"
        />
        <KpiCard
          label="Передачи человеку"
          value={formatNumber(metrics.handoffs)}
          hint="за всё время"
          tone={metrics.handoffs > 0 ? "warn" : "default"}
        />
        <KpiCard
          label="Ответов сегодня"
          value={formatNumber(metrics.magi_today)}
          hint={`из ${metrics.total_conversations} диалогов`}
        />
      </div>

      <div className="grid grid-2">
        <Card
          title="Настройки"
          subtitle={can_edit ? "Меняются без перезапуска" : "Меняет только директор"}
        >
          <div className="form-stack">
            <label className="field">
              <span>Порог уверенности</span>
              <div className="range-row">
                <input
                  type="range"
                  min={0.3}
                  max={0.95}
                  step={0.05}
                  value={threshold}
                  disabled={!can_edit}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                />
                <strong>{Math.round(threshold * 100)}%</strong>
              </div>
              <small>
                Ниже порога Magi не отвечает сам, а передаёт диалог менеджеру.
              </small>
            </label>

            <label className="check-row">
              <input
                type="checkbox"
                checked={enabled}
                disabled={!can_edit}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              <span>
                <strong>Автоответ включён</strong>
                <small>Новые сообщения лидов обрабатываются сразу</small>
              </span>
            </label>

            <div className="field">
              <span>Каналы</span>
              <div className="check-grid">
                {CHANNELS.map((c) => (
                  <label key={c.id} className="check-row compact">
                    <input
                      type="checkbox"
                      checked={channels.includes(c.id)}
                      disabled={!can_edit}
                      onChange={(e) =>
                        setChannels((prev) =>
                          e.target.checked
                            ? [...prev, c.id]
                            : prev.filter((x) => x !== c.id),
                        )
                      }
                    />
                    <span>{c.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {can_edit ? (
              <div className="form-actions">
                <button className="btn btn-primary" onClick={save} disabled={saving}>
                  {saving ? "Сохраняю…" : "Сохранить"}
                </button>
                {saved && (
                  <span className="saved-note">
                    <IconCheck size={15} /> Сохранено
                  </span>
                )}
              </div>
            ) : (
              <p className="muted-note">
                Вы видите настройки, но менять их может только директор.
              </p>
            )}
          </div>
        </Card>

        <Card title="Провайдер" subtitle="Как Magi получает ответ">
          <div className="provider-card">
            <div className="provider-icon">
              <IconSpark size={22} />
            </div>
            <div>
              <strong>{local ? "Локальный движок" : "OpenAI-совместимый API"}</strong>
              <p>
                {local
                  ? "Правила + база знаний. Работает офлайн, без внешних запросов и ключей."
                  : `Модель ${provider.model}. Запросы уходят на настроенный endpoint.`}
              </p>
            </div>
          </div>
          <div className="provider-facts">
            <div>
              <span>Режим</span>
              <strong>{local ? "локальный" : "OpenAI-совместимый"}</strong>
            </div>
            <div>
              <span>Модель</span>
              <strong>{provider.model}</strong>
            </div>
            <div>
              <span>Порог</span>
              <strong>{Math.round(settings.confidence_threshold * 100)}%</strong>
            </div>
          </div>
          <p className="muted-note">
            {local
              ? "Чтобы включить модель, задайте MAGI_BASE_URL, MAGI_API_KEY и MAGI_MODEL. При ошибке API Magi вернётся к локальным правилам."
              : "Ключ хранится только в переменных окружения. В репозиторий он не попадает."}
          </p>
          <p className="muted-note">
            Персональные данные перед отправкой в модель маскируются: телефоны, почта и инициалы вместо ФИО.
            Пример: <code>{data.pii_mask_example.name} · {data.pii_mask_example.phone} · {data.pii_mask_example.email}</code>
          </p>
          <p className="muted-note">
            Правила Magi меняются вживую в <a href="#rules">Конструкторе правил</a> — без разработчиков и релизов.
          </p>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Когда Magi передаёт человеку">
          <ul className="rules-list">
            <li>
              <span className="rule-dot red" />
              <div>
                <strong>Жалоба, брак или возврат</strong>
                <p>Сначала извинение, затем диалог забирает менеджер.</p>
              </div>
            </li>
            <li>
              <span className="rule-dot amber" />
              <div>
                <strong>Персональная скидка или торг</strong>
                <p>Стандартные условия отвечает сам, исключения — человек.</p>
              </div>
            </li>
            <li>
              <span className="rule-dot amber" />
              <div>
                <strong>Уверенность ниже порога</strong>
                <p>Лучше передать, чем выдумать цену или срок.</p>
              </div>
            </li>
            <li>
              <span className="rule-dot blue" />
              <div>
                <strong>Просьба позвать человека</strong>
                <p>Сразу, без попытки уговорить остаться с ботом.</p>
              </div>
            </li>
          </ul>
        </Card>

        <Card title="Темы обращений" subtitle="По ответам Magi за всё время">
          {data.intents.length === 0 ? (
            <p className="muted-note">Пока нет данных.</p>
          ) : (
            <div className="intent-list">
              {data.intents.map((row) => {
                const max = Math.max(...data.intents.map((r) => r.count));
                return (
                  <div className="intent-row" key={row.intent}>
                    <span>{INTENTS[row.intent] ?? row.intent}</span>
                    <div className="intent-track">
                      <div style={{ width: `${(row.count / max) * 100}%` }} />
                    </div>
                    <strong>{row.count}</strong>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {learning && (
        <Card
          title="Развитие Magi"
          subtitle="Измерить → предложить → подтвердить → Magi растёт (30 дней)"
          action={
            <span className="muted small">
              {learning.acceptance.filter((a) => a.acceptance_pct != null).length} тем под наблюдением
            </span>
          }
        >
          {learningError && <ErrorNote text={learningError} />}
          <div className="learning-grid">
            <div>
              <h3 className="section-label">Принятость автоответов по темам</h3>
              <div className="kb-row-wrap">
                {learning.acceptance.filter((a) => a.auto > 0).slice(0, 8).map((a) => (
                  <div className="learning-row" key={a.topic}>
                    <span className="learning-topic">{a.name}</span>
                    <div className="meter">
                      <span
                        className={a.acceptance_pct != null && a.acceptance_pct < 70 ? "t-red" : ""}
                        style={{ width: `${a.acceptance_pct ?? 0}%` }}
                      />
                    </div>
                    <strong>{a.acceptance_pct == null ? "—" : `${a.acceptance_pct}%`}</strong>
                    <small>{a.auto} авто · {a.manager_answers} ответов менеджера</small>
                  </div>
                ))}
                {learning.acceptance.every((a) => a.auto === 0) && (
                  <p className="muted-note">Пока нет закрытых автоответов за период.</p>
                )}
              </div>
              <p className="muted-note">
                «Принятость» = доля диалогов, где клиент не вернулся с новым вопросом в течение 48 часов после
                автоответа. Ниже 70% — тема кандидат на передачу человеку или правку правила.
              </p>
            </div>

            <div>
              <h3 className="section-label">Предложения на основе работы</h3>
              {learning.rule_suggestions.length === 0 && learning.kb_suggestions.length === 0 && (
                <p className="muted-note">Пока предложений нет: частые причины передачи появятся здесь.</p>
              )}
              {learning.rule_suggestions.map((s) => (
                <div className="learning-suggest" key={s.reason}>
                  <div>
                    <strong>Частая передача: «{s.reason}»</strong>
                    <small>{s.count} раз(а) за 30 дней → правило «{s.keywords.join(", ")}» → сразу человеку</small>
                  </div>
                  {(user.role === "director" || (user.role === "head" && user.team === "Клиентский сервис")) && (
                    <button
                      className="btn btn-small"
                      disabled={learningBusy === "rule" + s.reason}
                      onClick={() => grow("rule", { reason: s.reason })}
                    >
                      {learningBusy === "rule" + s.reason ? "…" : "Создать правило"}
                    </button>
                  )}
                </div>
              ))}
              {learning.kb_suggestions.map((s) => (
                <div className="learning-suggest" key={s.topic}>
                  <div>
                    <strong>База знаний: «{s.name}»</strong>
                    <small>менеджеры отвечали {s.count} раз. Пример: «{s.sample_answer.slice(0, 90)}…»</small>
                  </div>
                  {(user.role === "director" || (user.role === "head" && user.team === "Клиентский сервис")) && (
                    <button
                      className="btn btn-small"
                      disabled={learningBusy === "kb" + s.topic}
                      onClick={() => grow("kb", { topic: s.topic })}
                    >
                      {learningBusy === "kb" + s.topic ? "…" : "В базу знаний"}
                    </button>
                  )}
                </div>
              ))}
              <p className="muted-note">
                Так Magi развивается по ходу работы: популярный ответ менеджера становится статьёй базы знаний,
                частая причина передачи — правилом. Каждое применение — в журнале.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card
        title="База знаний"
        subtitle="Magi отвечает только тем, что здесь написано"
        bodyClassName="card-body flush"
      >
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Тема</th>
                <th>Вопрос</th>
                <th>Ответ</th>
              </tr>
            </thead>
            <tbody>
              {data.kb.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="kb-topic">{row.topic}</span>
                  </td>
                  <td>{row.question}</td>
                  <td className="kb-answer">{row.answer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {user.role === "director" && (
        <Card title="Демо-режим" subtitle="Только для стенда">
          <div className="danger-row">
            <div>
              <strong>Сбросить данные</strong>
              <p>
                Вернёт 60 клиентов, 18 диалогов и исходные настройки. Действие
                необратимо.
              </p>
            </div>
            <button className="btn btn-danger" onClick={resetDemo}>
              <IconRefresh size={16} /> Сбросить демо
            </button>
          </div>
        </Card>
      )}

      <div className="page-foot">
        <IconBot size={15} /> Magi не отправляет сообщения клиентам без записи в
        CRM. Все действия агента и менеджеров попадают в журнал.
      </div>
    </div>
  );
}
