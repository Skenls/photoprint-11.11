import { useRef, useState } from "react";
import { api } from "../api";
import type { ImportApplyResult, ImportReport } from "../types";
import { Badge, Card, ErrorNote, Spinner } from "../components";
import { IconCheck, IconRefresh } from "../icons";

const STEPS = [
  "В старой CRM (Битрикс24) — CRM → Настройки → Экспорт контактов в CSV/JSON.",
  "Загрузите файл здесь: система распознаёт колонки (Имя, Телефон, E-mail, Город, Источник, Комментарий).",
  "Проверьте отчёт: что создаётся, что объединяется с существующими клиентами по телефону/email.",
  "Нажмите «Импортировать» — данные попадут в инбокс и карточки клиентов, запись появится в журнале.",
];

export function Import() {
  const [report, setReport] = useState<ImportReport | null>(null);
  const [result, setResult] = useState<ImportApplyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");

  function pickFile() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Выберите CSV или JSON файл");
      return;
    }
    setFileName(file.name);
    return file;
  }

  async function run(kind: "preview" | "apply") {
    const file = pickFile();
    if (!file) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      if (kind === "preview") {
        setReport(await api.importPreview(file));
      } else {
        setResult(await api.importApply(file));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось обработать файл");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Переезд со старой системы</div>
          <h1>Миграция клиентов</h1>
          <p className="muted">
            Один файл — вся клиентская база из Битрикс24 или другой CRM. Дубликаты объединяются по телефону и email,
            импорт журналируется.
          </p>
        </div>
      </header>

      <div className="grid grid-2">
        <Card title="Как переехать" subtitle="4 шага, без разработчиков">
          <ol className="steps-list">
            {STEPS.map((step, i) => (
              <li key={i}><span>{i + 1}</span>{step}</li>
            ))}
          </ol>
          <p className="muted-note">
            Пример файла — <code>docs/import-example.csv</code>. Поддерживаются разделители «;», «,» и таб, кодировка
            UTF-8/CP1251, до 5000 строк.
          </p>
        </Card>

        <Card title="Загрузка файла" subtitle="Сначала проверка, потом импорт">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            onChange={() => { setReport(null); setResult(null); setError(""); }}
            aria-label="Файл экспорта из старой CRM"
          />
          {fileName && <p className="muted small">Файл: {fileName}</p>}
          <div className="rule-actions">
            <button className="btn" onClick={() => run("preview")} disabled={loading}>
              <IconRefresh size={15} /> Проверить
            </button>
            <button className="btn btn-primary" onClick={() => run("apply")} disabled={loading}>
              <IconCheck size={15} /> Импортировать
            </button>
          </div>
          {loading && <Spinner label="Читаю файл…" />}
          {error && <ErrorNote text={error} />}
        </Card>
      </div>

      {report && (
        <Card title="Отчёт проверки" subtitle={report.filename} bodyClassName="card-body flush">
          <div className="import-stats">
            <div><span>Строк</span><strong>{report.total_rows}</strong></div>
            <div><span>Создадутся</span><strong>{report.will_create}</strong></div>
            <div><span>Объединятся</span><strong>{report.will_merge}</strong></div>
          </div>
          <div className="import-mapping">
            {Object.entries(report.mapped_columns).map(([field, header]) => (
              <span className="tag" key={field}>{header} → {field}</span>
            ))}
            {report.unmapped_columns.map((header) => (
              <span className="tag tag-muted" key={header}>{header} → пропущено</span>
            ))}
          </div>
          {report.issues.length > 0 && (
            <div className="import-issues">
              {report.issues.map((issue, i) => <p key={i}>{issue}</p>)}
            </div>
          )}
        </Card>
      )}

      {result && (
        <Card
          title="Импорт выполнен"
          subtitle={result.report.filename}
          action={<Badge tone="green">Готово</Badge>}
        >
          <div className="import-stats">
            <div><span>Создано</span><strong>{result.created}</strong></div>
            <div><span>Объединено</span><strong>{result.merged}</strong></div>
            <div><span>Пропущено</span><strong>{result.skipped}</strong></div>
          </div>
          <p className="muted-note">
            Новые клиенты — в «Клиентах» и инбоксе. Запись об импорте — в журнале. Повторная загрузка того же файла
            не создаёт дублей: совпадения объединяются.
          </p>
        </Card>
      )}
    </div>
  );
}
