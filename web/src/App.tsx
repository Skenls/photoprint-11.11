import { useEffect, useState } from "react";
import { api } from "./api";
import type { User } from "./types";
import { Avatar, ROLE_LABELS } from "./components";
import {
  IconChart,
  IconInbox,
  IconLogout,
  IconShield,
  IconSpark,
  IconUsers,
} from "./icons";
import { Login } from "./pages/Login";
import { DashboardPage as Dashboard } from "./pages/Dashboard";
import { InboxPage as Inbox } from "./pages/Inbox";
import { ClientsPage as Clients } from "./pages/Clients";
import { Magi } from "./pages/Magi";
import { Audit } from "./pages/Audit";
import { Pulse } from "./pages/Pulse";
import { Production } from "./pages/Production";
import { Finance } from "./pages/Finance";
import { Hr } from "./pages/Hr";
import { AnalystPage } from "./pages/AnalystPage";
import { Decisions } from "./pages/Decisions";
import { Rules } from "./pages/Rules";
import { Import } from "./pages/Import";

type Page =
  | "dashboard" | "pulse" | "inbox" | "clients" | "magi" | "audit"
  | "production" | "finance" | "hr" | "analyst" | "decisions" | "rules" | "import";

interface NavItem {
  page: Page;
  label: string;
  icon: typeof IconChart;
  show: (user: User) => boolean;
}

const isDirector = (u: User) => u.role === "director";
const isAnalyst = (u: User) => u.role === "analyst";
const isManagement = (u: User) => u.role !== "operator";
const headOf = (team: string) => (u: User) => u.role === "head" && u.team === team;
const operatorOr = (fn: (u: User) => boolean) => (u: User) => u.role === "operator" || fn(u);

const NAV: NavItem[] = [
  { page: "pulse", label: "Пульс", icon: IconChart, show: (u) => isDirector(u) || isAnalyst(u) },
  { page: "dashboard", label: "Обзор", icon: IconChart, show: operatorOr((u) => u.role === "head" && u.team === "Клиентский сервис") },
  { page: "inbox", label: "Инбокс", icon: IconInbox, show: (u) => isDirector(u) || u.team === "Клиентский сервис" },
  { page: "clients", label: "Клиенты", icon: IconUsers, show: (u) => isDirector(u) || u.team === "Клиентский сервис" },
  { page: "magi", label: "Magi", icon: IconSpark, show: (u) => isDirector(u) || u.team === "Клиентский сервис" },
  { page: "rules", label: "Конструктор", icon: IconSpark, show: (u) => isDirector(u) || (u.role === "head" && u.team === "Клиентский сервис") },
  { page: "import", label: "Миграция", icon: IconUsers, show: isDirector },
  { page: "production", label: "Производство", icon: IconChart, show: (u) => isDirector(u) || isAnalyst(u) || headOf("Производство")(u) },
  { page: "finance", label: "Финансы", icon: IconChart, show: (u) => isDirector(u) || isAnalyst(u) || headOf("Финансы и люди")(u) },
  { page: "hr", label: "Люди", icon: IconUsers, show: (u) => isDirector(u) || isAnalyst(u) || headOf("Финансы и люди")(u) },
  { page: "decisions", label: "Решения", icon: IconShield, show: isManagement },
  { page: "analyst", label: "Аналитика", icon: IconChart, show: (u) => isDirector(u) || isAnalyst(u) },
  { page: "audit", label: "Журнал", icon: IconShield, show: isDirector },
];

const TITLES: Record<Page, string> = {
  dashboard: "Обзор отдела",
  pulse: "Пульс компании",
  inbox: "Инбокс",
  clients: "Клиенты",
  magi: "Magi",
  audit: "Журнал действий",
  production: "Производство и качество",
  finance: "Финансы (1С)",
  hr: "Люди (HR)",
  analyst: "Аналитика источников",
  decisions: "Реестр решений",
  rules: "Magi Конструктор правил",
  import: "Миграция клиентов",
};

function parseHash(): { page: Page; param: string } {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [page, param = ""] = raw.split("/");
  const known: Page[] = ["dashboard", "pulse", "inbox", "clients", "magi", "audit", "production", "finance", "hr", "analyst", "decisions", "rules", "import"];
  return { page: (known.includes(page as Page) ? page : "dashboard") as Page, param };
}

function go(path: string) {
  window.location.hash = path;
}

function Splash() {
  return (
    <div className="splash">
      <div className="brand-mark">
        <IconSpark size={22} />
      </div>
      <div>
        <strong>Magi</strong>
        <span>Загружаю рабочее пространство…</span>
      </div>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (user === undefined) return <Splash />;
  if (!user) {
    return (
      <Login
        onLogin={(next) => {
          setUser(next);
          go(next.role === "director" ? "pulse" : "dashboard");
        }}
      />
    );
  }

  const nav = NAV.filter((item) => item.show(user));
  const fallback: Page = user.role === "director" ? "pulse" : nav[0]?.page ?? "dashboard";
  const page: Page = nav.some((n) => n.page === route.page) ? route.page : fallback;

  const logout = async () => {
    await api.logout();
    setUser(null);
    go("pulse");
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <IconSpark size={20} />
          </div>
          <div>
            <div className="brand-name">Magi</div>
            <div className="brand-sub">Единая система управления</div>
          </div>
        </div>

        <nav className="nav" aria-label="Разделы">
          <div className="nav-label">Рабочее пространство</div>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.page}
                href={`#${item.page}`}
                className={`nav-item ${page === item.page ? "active" : ""}`}
                aria-current={page === item.page ? "page" : undefined}
              >
                <Icon size={18} />
                <span>{item.label}</span>
                {item.page === "inbox" && <span className="nav-dot" />}
              </a>
            );
          })}
        </nav>

        <div className="sidebar-foot">
          <div className="demo-card">
            <span className="status-dot" />
            <div>
              <strong>Демо-стенд</strong>
              <span>Space Hackathon 2026</span>
            </div>
          </div>
          <p>Синтетические данные. Без реальных ПДн.</p>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <span className="crumb">Magi</span>
            <span className="crumb-sep">/</span>
            <strong>{TITLES[page]}</strong>
          </div>

          <div className="topbar-right">
            <span className="scope-chip">
              {user.role === "director" || user.role === "analyst"
                ? "Вся компания"
                : user.role === "head"
                  ? user.team
                  : "Только мои"}
            </span>
            <div className="user-chip">
              <Avatar name={user.name} size={32} />
              <div className="user-chip-meta">
                <strong>{user.name}</strong>
                <span>{ROLE_LABELS[user.role]}</span>
              </div>
            </div>
            <button className="icon-btn" onClick={logout} title="Выйти" aria-label="Выйти">
              <IconLogout size={18} />
            </button>
          </div>
        </header>

        <main className="content">
          {page === "pulse" && (
            <Pulse
              user={user}
              onNavigate={(target) => go(target === "production" || target === "finance" ? target : target)}
            />
          )}
          {page === "dashboard" && (
            <Dashboard
              user={user}
              onOpenInbox={(id?: number) => go(id ? `inbox/${id}` : "inbox")}
              onOpenMagi={() => go("magi")}
            />
          )}
          {page === "inbox" && (
            <Inbox
              user={user}
              initialId={route.param}
              onOpenClient={(id: number) => go(`clients/${id}`)}
            />
          )}
          {page === "clients" && (
            <Clients
              user={user}
              initialId={route.param}
              onOpenInbox={(id: number) => go(`inbox/${id}`)}
            />
          )}
          {page === "magi" && <Magi user={user} />}
          {page === "rules" && (
            <Rules canEdit={user.role === "director" || (user.role === "head" && user.team === "Клиентский сервис")} />
          )}
          {page === "import" && <Import />}
          {page === "production" && <Production />}
          {page === "finance" && <Finance />}
          {page === "hr" && <Hr />}
          {page === "analyst" && <AnalystPage />}
          {page === "decisions" && <Decisions user={user} />}
          {page === "audit" && <Audit />}
        </main>
      </div>
    </div>
  );
}
