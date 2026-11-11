import { useEffect, useState } from "react";
import { api } from "../api";
import type { HrPayload } from "../types";
import { Badge, Card, ErrorNote, Spinner, formatDate } from "../components";

export function Hr() {
  const [data, setData] = useState<HrPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.hr().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote text={error} />;
  if (!data) return <Spinner label="Загружаю кадры…" />;

  const staffTotal = data.teams.reduce((s, t) => s + t.staff, 0);
  const activeTotal = data.teams.reduce((s, t) => s + t.active, 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">HR / Персонал</div>
          <h1>Люди и смены</h1>
          <p className="muted">Штат и факт, вакансии, отсутствие, табелирование. Без реальных ФИО — синтетические данные.</p>
        </div>
        <div className="page-head-stats">
          <div className="stat-tile"><span>Штат</span><strong>{data.headcount}</strong></div>
          <div className="stat-tile"><span>На смене сегодня</span><strong>{activeTotal}</strong></div>
          <div className="stat-tile"><span>Пропуски за неделю</span><strong>{data.week_absence}</strong></div>
        </div>
      </header>

      <div className="grid grid-2">
        <Card title="Штат по отделам" subtitle={`План ${staffTotal} · активных ${activeTotal}`} bodyClassName="card-body flush">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Отдел</th><th>Штат</th><th>Активных</th><th>Обеспеченность</th></tr></thead>
              <tbody>
                {data.teams.map((t) => (
                  <tr key={t.team}>
                    <td><strong>{t.team}</strong></td>
                    <td className="num">{t.staff}</td>
                    <td className="num">{t.active}</td>
                    <td className="num">
                      <Badge tone={t.active >= t.staff * 0.9 ? "green" : "amber"}>
                        {Math.round((t.active / t.staff) * 100)}%
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Вакансии" subtitle="Открытые позиции и кандидаты">
          {data.vacancies.length === 0 ? (
            <p className="muted">Открытых вакансий нет.</p>
          ) : (
            <div className="queue-list">
              {data.vacancies.map((v) => (
                <div className="queue-row" key={v.id}>
                  <div>
                    <strong>{v.position}</strong>
                    <small>{v.team}</small>
                  </div>
                  <span className="muted">с {formatDate(v.opened_at)}</span>
                  <Badge tone="blue">{v.candidates} кандидатов</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Смены сегодня" subtitle="Плановые и фактические часы" bodyClassName="card-body flush">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Сотрудник</th><th>Отдел</th><th>Должность</th><th>План</th><th>Факт</th><th>Примечание</th></tr></thead>
            <tbody>
              {data.shifts_today.map((s) => (
                <tr key={s.id}>
                  <td><strong>{s.name}</strong></td>
                  <td className="muted">{s.team}</td>
                  <td className="muted">{s.position}</td>
                  <td className="num">{s.planned_hours} ч</td>
                  <td className="num">{s.fact_hours} ч</td>
                  <td>{s.note ? <Badge tone="amber">{s.note}</Badge> : <Badge tone="green">На смене</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
