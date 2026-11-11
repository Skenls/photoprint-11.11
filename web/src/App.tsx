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

type Page = "dashboard" | "inbox" | "clients" | "magi" | "audit";

const NAV: { page: Page; label: string; icon: typeof IconChart; roles?: string[] }[] = [
  { page: "dashboard", label: "Обзор", icon: IconChart },
  { page: "inbox", label: "Инбокс", icon: IconInbox },
  { page: "clients", label: "Клиенты", icon: IconUsers },
  { page: "magi", label: "Magi", icon: IconSpark },
  { page: "audit", label: "Журнал", icon: IconShield, roles: ["director"] },
];

const TITLES: Record<Page, string> = {
  dashboard: "Обзор",
  inbox: "Инбокс",
  clients: "Клиенты",
  magi: "Magi",
  audit: "Журнал действий",
};

function parseHash(): { page: Page; param: string } {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [page, param = ""] = raw.split("/");
  const known = ["dashboard", "inbox", "clients", "magi", "audit"];
  return { page: (known.includes(page) ? page : "dashboard") as Page, param };
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
          go("dashboard");
        }}
      />
    );
  }

  const page = route.page === "audit" && user.role !== "director" ? "dashboard" : route.page;
  const nav = NAV.filter((item) => !item.roles || item.roles.includes(user.role));

  const logout = async () => {
    await api.logout();
    setUser(null);
    go("dashboard");
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
            <div className="brand-sub">CRM клиентского сервиса</div>
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
            <span className="status-dot ok" />
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
              {user.role === "director"
                ? "Вся компания"
                : user.role === "manager"
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
              onOpenClient={(id) => go(`clients/${id}`)}
            />
          )}
          {page === "clients" && (
            <Clients
              user={user}
              initialId={route.param}
              onOpenInbox={(id) => go(`inbox/${id}`)}
            />
          )}
          {page === "magi" && <Magi user={user} />}
          {page === "audit" && <Audit />}
        </main>
      </div>
    </div>
  );
}
