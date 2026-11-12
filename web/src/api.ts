import type {
  AgentPayload,
  AnalystPayload,
  AuditRow,
  Client,
  Conversation,
  ConversationDetail,
  Dashboard,
  Decision,
  FinancePayload,
  HrPayload,
  LearningPayload,
  ImportApplyResult,
  ImportReport,
  Message,
  PickupItem,
  ProductionPayload,
  PulsePayload,
  RuleItem,
  RuleTestResult,
  SalesPayload,
  TemplateItem,
  TopicRow,
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
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
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
    tg_handle?: string;
  }) =>
    request<{ client_id: number; conversation_id: number }>("/leads", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  patchClient: (id: number, data: Partial<Pick<import("./types").Client, "name" | "phone" | "email" | "city" | "tg_handle">>) =>
    request<import("./types").Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  orderAction: (id: number, action: "rush" | "redone" | "extend" | "promo") =>
    request<{ ok: boolean; message: string }>(`/orders/${id}/action`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  rescueRun: () => request<{ checked: number; sent: number; skipped: number }>("/rescue/run", { method: "POST" }),
  agent: () => request<AgentPayload>("/agent"),
  updateAgent: (data: {
    magi_enabled?: boolean;
    confidence_threshold?: number;
    auto_channels?: string[];
  }) => request<AgentPayload>("/agent", { method: "PATCH", body: JSON.stringify(data) }),
  audit: () => request<{ items: AuditRow[] }>("/audit"),
  users: () => request<{ items: { id: number; name: string; role: string; team: string; title: string }[] }>("/users"),
  resetDemo: () => request<{ ok: boolean }>("/demo/reset", { method: "POST" }),
  pulse: () => request<PulsePayload>("/pulse"),
  accounting: () => request<import("./types").AccountingPayload>("/accounting"),
  accountingOsv: (from: string, to: string) =>
    request<import("./types").OsvPayload>(`/accounting/osv?from_date=${from}&to_date=${to}`),
  accountingStorno: (txId: number, reason: string) =>
    request<{ ok: boolean }>("/accounting/storno", { method: "POST", body: JSON.stringify({ tx_id: txId, reason }) }),
  accountingImportStatement: (text: string) =>
    request<{ duplicate: boolean; message?: string; matched: number; unmatched: number }>(
      "/accounting/import-statement",
      { method: "POST", body: JSON.stringify({ text }) },
    ),
  accountingPostBank: (lineIds: number[]) =>
    request<{ posted: number }>("/accounting/bank/post", {
      method: "POST",
      body: JSON.stringify({ line_ids: lineIds }),
    }),
  accountingCreateDocument: (kind: string, orderId: number) =>
    request<{ id: number; number: string }>("/accounting/documents", {
      method: "POST",
      body: JSON.stringify({ kind, order_id: orderId }),
    }),
  accountingReconciliation: (params: { counterparty_id?: number; client_id?: number }) =>
    request<{ name: string; items: { date: string; number: string; description: string; debit: number; credit: number; balance: number }[]; closing: number }>(
      `/accounting/reconciliation${params.counterparty_id ? `?counterparty_id=${params.counterparty_id}` : `?client_id=${params.client_id ?? 0}`}`,
    ),  sales: () => request<SalesPayload>("/sales"),
  production: () => request<ProductionPayload>("/production"),
  causeOrders: (cause: string) =>
    request<{ cause: string; items: (import("./types").Order & { client_name: string; owner_name: string })[] }>(
      `/production/causes/${cause}/orders`,
    ),
  finance: () => request<FinancePayload>("/finance"),
  hr: () => request<HrPayload>("/hr"),
  analyst: () => request<AnalystPayload>("/analyst"),
  decisions: (filters: { status?: string; priority?: string } = {}) =>
    request<{ items: Decision[] }>(`/decisions${query(filters)}`),
  createDecision: (data: {
    kpi_key?: string;
    problem: string;
    impact?: string;
    cause?: string;
    action: string;
    owner_id?: number | null;
    due_at?: string | null;
    priority?: string;
  }) => request<{ id: number }>("/decisions", { method: "POST", body: JSON.stringify(data) }),
  patchDecision: (id: number, data: { status?: string; action?: string; result_note?: string }) =>
    request<Decision>(`/decisions/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  rules: () => request<{ items: RuleItem[]; topics: TopicRow[] }>("/rules"),
  patchRule: (key: string, data: { config: Record<string, unknown>; enabled?: boolean }) =>
    request<{ ok: boolean }>(`/rules/${key}`, { method: "PATCH", body: JSON.stringify(data) }),
  testRule: (key: string, config: Record<string, unknown>) =>
    request<RuleTestResult>("/rules/test", { method: "POST", body: JSON.stringify({ key, config }) }),
  templates: (topic?: string) =>
    request<{ items: TemplateItem[] }>(`/templates${query({ topic })}`),
  pickups: () => request<{ items: PickupItem[] }>("/pickups"),
  remindPickup: (id: number) =>
    request<{ ok: boolean; message: string }>(`/pickups/${id}/remind`, { method: "POST" }),
  learning: () => request<LearningPayload>("/agent/learning"),
  applyLearning: (data: { kind: "kb" | "rule"; topic?: string; reason?: string }) =>
    request<{ ok: boolean; rule?: string; topic?: string }>("/agent/learning/apply", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  importPreview: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportReport>("/import/preview", { method: "POST", body: form });
  },
  importApply: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportApplyResult>("/import/apply", { method: "POST", body: form });
  },
};
