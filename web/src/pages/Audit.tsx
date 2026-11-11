import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuditRow } from "../types";
import { Card, ErrorNote, Spinner, formatDateTime } from "../components";
import { IconShield } from "../icons";

const ACTIONS: Record<string, string> = {
  "auth.login": "Вход в систему",
  "agent.settings": "Настройки Magi",
  "magi.handoff": "Magi передал человеку",
  "conversation.handoff": "Передача человеку",
  "conversation.resume_magi": "Возврат к Magi",
  "lead.created": "Новый лид",
  "demo.reset": "Сброс демо",
  "decision.create": "Создано решение",
  "decision.update": "Решение обновлено",
  "rules.update": "Правило Magi изменено",
  "pickup.remind": "Напоминание о ПВЗ",
};

const ENTITIES: Record<string, string> = {
  user: "пользователь",
  conversation: "диалог",
  settings: "настройки",
  client: "клиент",
};

export function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.audit().then((r) => setRows(r.items)).catch((e) => setError(e.message));
  }, []);

  if (!rows.length && !error) return <Spinner label="Загружаю журнал" />;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Безопасность</div>
          <h1>Журнал действий</h1>
          <p className="page-sub">
            Кто, что и когда сделал. Записи не редактируются и не удаляются из
            интерфейса.
          </p>
        </div>
        <div className="soft-chip">
          <IconShield size={15} /> Только директор
        </div>
      </div>

      {error && <ErrorNote text={error} />}

      <Card bodyClassName="card-body flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Сотрудник</th>
                <th>Действие</th>
                <th>Объект</th>
                <th>Детали</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="nowrap">{formatDateTime(row.created_at)}</td>
                  <td>
                    <strong>{row.user_name ?? row.actor}</strong>
                  </td>
                  <td>
                    <span className="audit-action">
                      {ACTIONS[row.action] ?? row.action}
                    </span>
                  </td>
                  <td className="muted">
                    {ENTITIES[row.entity] ?? row.entity}
                    {row.entity_id ? ` #${row.entity_id}` : ""}
                  </td>
                  <td className="muted">{row.detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="page-foot">
        Журнал хранится в SQLite. Для пилота: экспорт в SIEM и срок хранения
        задаются политикой компании.
      </p>
    </div>
  );
}
