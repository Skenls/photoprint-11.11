import type {
  AgentPayload,
  AuditRow,
  Client,
  Conversation,
  ConversationDetail,
  Dashboard,
  Message,
  User,
} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = "Не удалось выполнить запрос";
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) message = data.detail;
    } catch {
      // keep the default message
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  me: () => request<User>("/auth/me"),
  login: (email: string, password: string) =>
    request<User>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  dashboard: () => request<Dashboard>("/dashboard"),
  clients: (filters: { search?: string; status?: string; channel?: string }) =>
    request<{ items: Client[]; total: number }>(`/clients${query(filters)}`),
  client: (id: number) =>
    request<{ client: Client; orders: import("./types").Order[]; conversations: Conversation[] }>(
      `/clients/${id}`,
    ),
  conversations: (filters: { search?: string; status?: string; channel?: string }) =>
    request<{ items: Conversation[]; total: number }>(`/conversations${query(filters)}`),
  conversation: (id: number) => request<ConversationDetail>(`/conversations/${id}`),
  send: (id: number, body: string, author: "lead" | "agent") =>
    request<{ conversation: Conversation; message: Message; magi_message: Message | null }>(
      `/conversations/${id}/messages`,
      { method: "POST", body: JSON.stringify({ body, author }) },
    ),
  handoff: (id: number, reason: string) =>
    request<Conversation>(`/conversations/${id}/handoff`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  resume: (id: number) =>
    request<Conversation>(`/conversations/${id}/resume`, { method: "POST" }),
  createLead: (data: {
    name: string;
    phone?: string;
    email?: string;
    city?: string;
    channel: string;
    message?: string;
  }) =>
    request<{ client_id: number; conversation_id: number }>("/leads", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  agent: () => request<AgentPayload>("/agent"),
  updateAgent: (data: {
    magi_enabled?: boolean;
    confidence_threshold?: number;
    auto_channels?: string[];
  }) => request<AgentPayload>("/agent", { method: "PATCH", body: JSON.stringify(data) }),
  audit: () => request<{ items: AuditRow[] }>("/audit"),
  resetDemo: () => request<{ ok: boolean }>("/demo/reset", { method: "POST" }),
};
