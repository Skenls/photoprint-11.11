import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Role, User } from "../types";
import { ErrorNote, initials } from "../components";
import { IconArrow, IconSpark } from "../icons";

const DEMO_USERS: Array<{ role: Role; email: string; name: string; description: string }> = [
  {
    role: "director",
    email: "director@magi.by",
    name: "Ирина Соколова",
    description: "Вся компания: выручка, отделы, качество Magi",
  },
  {
    role: "manager",
    email: "manager@magi.by",
    name: "Анна Петрова",
    description: "Только клиентский сервис: очередь и команда",
  },
  {
    role: "operator",
    email: "operator@magi.by",
    name: "Игорь Лебедев",
    description: "Только свои диалоги и клиенты",
  },
];

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState(DEMO_USERS[0].email);
  const [password, setPassword] = useState("demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function signIn(withEmail = email) {
    setLoading(true);
    setError("");
    try {
      const user = await api.login(withEmail, password || "demo");
      onLogin(user);
    } catch {
      setError("Не удалось войти. Проверьте email и пароль.");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void signIn();
  }

  return (
    <div className="login">
      <aside className="login-left">
        <div className="brand brand-light">
          <span className="brand-mark brand-mark-light">
            <IconSpark size={20} />
          </span>
          <div>
            <div className="brand-name">Magi</div>
            <div className="brand-sub">CRM клиентского сервиса</div>
          </div>
        </div>

        <div className="login-copy">
          <span className="eyebrow">Space Hackathon 2026</span>
          <h1>Сервис, который отвечает раньше, чем клиент спросит.</h1>
          <p>
            Сайт, Telegram, Instagram и почта — в одном инбоксе. Magi знает заказ и историю клиента,
            отвечает на типовые вопросы и передаёт человеку сложное.
          </p>
          <ul className="login-points">
            <li>
              <span>01</span> Единая очередь вместо пяти вкладок
            </li>
            <li>
              <span>02</span> Данные клиента и заказа — рядом с диалогом
            </li>
            <li>
              <span>03</span> Директор видит всё, менеджер — только своё
            </li>
          </ul>
        </div>

        <div className="login-foot">
          <span className="status-dot" /> Демо-данные · без реальных персональных данных
        </div>
      </aside>

      <main className="login-right">
        <div className="login-card">
          <h2>Вход в Magi</h2>
          <p className="muted">Демо-доступ. Пароль для всех ролей — <code>demo</code>.</p>

          <form onSubmit={onSubmit} className="form">
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="field">
              <span>Пароль</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            {error && <ErrorNote text={error} />}
            <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
              {loading ? "Входим…" : "Войти"}
              {!loading && <IconArrow size={17} />}
            </button>
          </form>

          <div className="login-divider">
            <span>или быстрый вход</span>
          </div>

          <div className="role-list">
            {DEMO_USERS.map((demo) => (
              <button
                key={demo.role}
                className="role-card"
                onClick={() => {
                  setEmail(demo.email);
                  setPassword("demo");
                  void signIn(demo.email);
                }}
                disabled={loading}
              >
                <span className={`role-mark role-${demo.role}`}>
                  {initials(demo.name)}
                </span>
                <span className="role-copy">
                  <strong>{demo.name}</strong>
                  <small>{demo.description}</small>
                </span>
                <IconArrow size={16} />
              </button>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
