export type Role = "director" | "manager" | "operator";

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
  status: string;
  created_at: string;
  promised_at: string;
  delivered_at: string | null;
}

export interface Conversation {
  id: number;
  client_id: number;
  channel: string;
  subject: string;
  status: "open" | "waiting" | "closed";
  mode: "magi" | "human";
  assignee_id: number | null;
  team: string;
  magi_enabled: number;
  handoff_reason: string | null;
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
