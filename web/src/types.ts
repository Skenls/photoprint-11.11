export type Role = "director" | "head" | "operator" | "analyst";

export const isHeadOf = (role: Role, team: string, teamName: string) =>
  role === "director" || role === "analyst" || (role === "head" && team === teamName);

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  team: string;
  title: string;
}

export interface Kpis {
  revenue: number;
  leads: number;
  conversion: number;
  open_conversations: number;
  waiting: number;
  sla: number;
  automation_rate: number;
  avg_confidence: number;
  avg_response_min: number;
  magi_today: number;
  handoffs: number;
}

export interface SeriesPoint {
  date: string;
  label: string;
  leads: number;
  revenue: number;
}

export interface ChannelCount {
  channel: string;
  label: string;
  count: number;
}

export interface Attention {
  id: number;
  client_name: string;
  channel: string;
  reason: string;
  minutes: number;
  status: string;
  mode: string;
  last_author: string;
}

export interface TeamRow {
  id: number;
  name: string;
  title: string;
  role: string;
  open: number;
  handoffs: number;
  auto_replies: number;
}

export interface Dashboard {
  scope: Role;
  scope_label: string;
  kpis: Kpis;
  series: SeriesPoint[];
  channels: ChannelCount[];
  attention: Attention[];
  team: TeamRow[];
  magi: {
    enabled: boolean;
    provider: string;
    model: string;
    threshold: number;
  };
}

export interface Client {
  id: number;
  name: string;
  phone: string;
  email: string;
  city: string;
  channel: string;
  status: string;
  ltv: number;
  consent: number;
  owner_id: number;
  team: string;
  tags: string;
  notes: string;
  created_at: string;
  owner_name?: string;
  last_product?: string;
  last_amount?: number;
  last_order_status?: string;
  open_conversations?: number;
}

export interface Order {
  id: number;
  client_id: number;
  product: string;
  amount: number;
  cost?: number;
  channel?: string;
  payment?: string;
  status: string;
  created_at: string;
  promised_at: string;
  delivered_at: string | null;
  defect?: number;
  delay_reason?: string | null;
}

export interface Conversation {
  id: number;
  client_id: number;
  channel: string;
  subject: string;
  topic: string | null;
  topic_name?: string | null;
  status: "open" | "waiting" | "closed";
  mode: "magi" | "human";
  assignee_id: number | null;
  team: string;
  magi_enabled: number;
  handoff_reason: string | null;
  summary: string | null;
  sla_due_at: string | null;
  first_response_at: string | null;
  outcome: string | null;
  last_message_at: string;
  created_at: string;
  client_name: string;
  ltv: number;
  city: string;
  assignee_name?: string;
  last_message?: string;
  last_author?: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  author: "lead" | "magi" | "agent" | "system";
  body: string;
  intent: string | null;
  confidence: number | null;
  provider: string | null;
  created_at: string;
}

export interface ConversationDetail {
  conversation: Conversation;
  client: Client;
  orders: Order[];
  messages: Message[];
}

export interface ClientDetail {
  client: Client;
  orders: Order[];
  conversations: Conversation[];
}

export interface KbArticle {
  id: number;
  topic: string;
  question: string;
  answer: string;
  keywords: string;
}

export interface AgentPayload {
  settings: {
    magi_enabled: boolean;
    confidence_threshold: number;
    auto_channels: string[];
  };
  metrics: {
    automation_rate: number;
    avg_confidence: number;
    handoffs: number;
    magi_today: number;
    total_conversations: number;
  };
  intents: { intent: string; count: number }[];
  kb: KbArticle[];
  provider: { provider: string; model: string };
  pii_mask_example: { name: string; phone: string; email: string; notes: string };
  can_edit: boolean;
}

export interface AuditRow {
  id: number;
  user_id: number | null;
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: string;
  created_at: string;
  user_name?: string;
}

// ---------------------------------------------------------------- единая система

export interface KpiPassport {
  key: string;
  name: string;
  unit: string;
  formula: string;
  source: string;
  target: number | null;
  direction: "up" | "down";
  owner: string;
  value: number;
  status: "green" | "amber" | "red" | "neutral";
}

export interface LoadWeek {
  week: string;
  start: string;
  planned_min: number;
  capacity_min: number;
  load: number;
}

export interface PulsePayload {
  month: string;
  kpis: KpiPassport[];
  critical: { kpi_key: string; kpi_name: string; value: number; unit: string; target: number | null; owner: string; source: string }[];
  weeks: LoadWeek[];
  load_risk_week: string | null;
  open_decisions: number;
  totals: { orders: number; clients: number; conversations: number };
  finance_now: { plan_revenue: number; fact_revenue: number; plan_cash: number; fact_cash: number } | null;
}

export interface SalesPayload {
  funnel: { new: number; qualified: number; customers: number; sleeping: number };
  conversion: number;
  avg_check: number;
  repeat_rate: number;
  by_channel: { channel: string; label: string; orders: number; revenue: number }[];
  by_segment: { segment: string; clients: number; ltv: number }[];
  series: { day: string; orders: number; revenue: number }[];
}

export interface Machine {
  id: number;
  name: string;
  kind: string;
  capacity_min_per_day: number;
  status: string;
  downtime_min_month: number;
  queue_min: number;
}

export interface MachineJob {
  id: number;
  machine_id: number;
  machine_name: string;
  order_id: number | null;
  product: string | null;
  est_minutes: number;
  status: "queued" | "running" | "done";
  planned_start: string;
}

export interface ProductionPayload {
  plan_fact: { day: string; done: number; planned: number }[];
  lead_time_hours: number;
  machines: Machine[];
  queue: MachineJob[];
  causes: { cause: string; label: string; count: number; share: number }[];
  defect_rate: number;
}

export interface FinancePeriod {
  month: string;
  plan_revenue: number;
  fact_revenue: number;
  plan_costs: number;
  fact_costs: number;
  plan_cash: number;
  fact_cash: number;
  margin: number;
}

export interface FinanceEntry {
  id: number;
  period_month: string;
  kind: "debit" | "credit";
  counterparty_id: number | null;
  counterparty_name: string | null;
  category: string;
  amount: number;
  entry_date: string;
}

export interface Counterparty {
  id: number;
  name: string;
  kind: string;
  balance: number;
  updated_at: string;
}

export interface FinancePayload {
  periods: FinancePeriod[];
  entries: FinanceEntry[];
  counterparties: Counterparty[];
}

export interface HrPayload {
  teams: { team: string; staff: number; active: number }[];
  vacancies: { id: number; team: string; position: string; opened_at: string; candidates: number; status: string }[];
  shifts_today: { id: number; name: string; team: string; position: string; planned_hours: number; fact_hours: number; note: string }[];
  week_absence: number;
  headcount: number;
}

export interface AnalystPayload {
  sources: { source: string; last_event: string | null; fresh_minutes: number | null; records: number }[];
  quality: { dup_phones: number; missing_phone: number; missing_email: number; missing_promised: number; missing_first_response: number };
  reconciliation: { month: string; crm_revenue: number; erp_delivered: number; finance_fact: number; gap_crm_finance_pct: number; note: string };
}

export interface Decision {
  id: number;
  kpi_key: string | null;
  kpi_name: string | null;
  problem: string;
  impact: string;
  cause: string;
  action: string;
  owner_id: number | null;
  owner_name: string | null;
  created_by_name: string | null;
  due_at: string | null;
  priority: "low" | "normal" | "high";
  status: "open" | "in_progress" | "done" | "cancelled";
  result_note: string;
  created_at: string;
  updated_at: string;
}

export interface RuleItem {
  id: number;
  key: string;
  title: string;
  kind: "route" | "threshold" | "trigger" | "sla" | "reminder";
  config: Record<string, unknown>;
  enabled: number | boolean;
  updated_by_name: string | null;
  updated_at: string;
}

export interface RuleTestResult {
  total: number;
  old: { auto: number; human: number; auto_pct: number };
  new: { auto: number; human: number; auto_pct: number };
  samples: { conversation_id: number; text: string; old: string; new: string }[];
}

export interface TopicRow {
  id: number;
  key: string;
  name: string;
  sla_hours: number;
  description: string;
}

export interface TemplateItem {
  id: number;
  topic: string;
  title: string;
  body: string;
}

export interface PickupItem {
  id: number;
  order_id: number;
  location: string;
  ready_at: string;
  expires_at: string;
  reminded: number;
  hours_left: number;
  product: string;
  amount: number;
  client_name: string;
  client_id: number;
}
