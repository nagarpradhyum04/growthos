export type LeadStatus =
  | "NEW" | "RESEARCHED" | "QUALIFIED" | "DISQUALIFIED" | "DRAFTED" | "CONTACTED" | "REPLIED" | "COMPLETED" | "SUPPRESSED" | "CONVERTED";
export type EmailStatus =
  | "DRAFT" | "APPROVED" | "SCHEDULED" | "SENT" | "DELIVERED" | "REPLIED" | "FAILED" | "SUPPRESSED" | "COMPLETED";

export interface Me {
  user: { id: string; email: string; name: string; organization_id: string };
  organization: { id: string; name: string; automated_sending_enabled: boolean };
}

export interface Campaign {
  id: string;
  name: string;
  objective: string;
  target_audience: string;
  status: "ACTIVE" | "PAUSED" | "COMPLETED";
  max_followups: number | null;
  followup_delay_days: number | null;
  created_at: string;
  leads: number;
  qualified_leads: number;
  emails_sent: number;
  replies: number;
  effective_max_followups: number;
}

export interface LeadListItem {
  id: string;
  campaign_id: string;
  campaign_name: string;
  company_name: string;
  contact_name: string | null;
  contact_email: string | null;
  qualification_score: number | null;
  qualified: boolean | null;
  status: LeadStatus;
  disabled: boolean;
  last_activity_at: string;
}

export interface Contact {
  id: string;
  name: string | null;
  role: string | null;
  email: string | null;
  suppressed: boolean;
  suppression_reason: string | null;
  unsubscribed: boolean;
  forgotten_at: string | null;
}

export interface ResearchData {
  company_summary: string;
  industry: string;
  company_size: string;
  likely_pain_points: string[];
  relevant_signals: string[];
  personalization_points: string[];
  sources: { claim: string; url: string }[];
  confidence: number;
  evidence_urls?: string[];
  evidence_errors?: string[];
}

export interface Email {
  id: string;
  campaign_id: string;
  lead_id: string;
  contact_id: string;
  sequence_number: number;
  subject: string;
  body: string;
  status: EmailStatus;
  edited_by_human: boolean;
  approved_at: string | null;
  scheduled_for: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmailReview extends Email {
  company_name: string;
  contact_name: string | null;
  contact_email: string | null;
  personalization_used: string[];
  draft_confidence: number | null;
  research: ResearchData | null;
  send_check: SendCheck;
}

export interface SafetyCheck {
  key: string;
  label: string;
  passed: boolean;
  reasons: string[];
}

export interface SendCheck {
  allowed: boolean;
  reasons: string[];
  checks: SafetyCheck[];
}

export interface AgentRun {
  id: string;
  agent_name: string;
  lead_id: string | null;
  campaign_id: string | null;
  provider: string;
  model: string;
  prompt_version: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  attempts: number;
  error: string | null;
  started_at: string;
  completed_at: string | null;
  latency_ms: number | null;
  output: Record<string, unknown> | null;
}

export interface ReplyWithContext extends Reply {
  company_name: string;
  followups_cancelled: number;
  followups_pending: number;
  contact_suppressed: boolean;
  contact_forgotten: boolean;
}

export interface Reply {
  id: string;
  email_id: string | null;
  lead_id: string;
  contact_id: string;
  campaign_id: string;
  subject: string;
  body: string;
  received_at: string;
  classification: string | null;
  summary: string | null;
  recommended_action: string | null;
  requires_human_attention: boolean;
  opt_out_detected: boolean;
  analyzed_at: string | null;
  agent_run_id: string | null;
}

export interface Followup {
  id: string;
  sequence_number: number;
  due_at: string;
  status: string;
  cancel_reason: string | null;
  email_id: string | null;
}

export interface LeadDetail {
  id: string;
  campaign: Campaign;
  company_name: string;
  website: string;
  notes: string;
  status: LeadStatus;
  disabled: boolean;
  qualified: boolean | null;
  qualification_score: number | null;
  qualification_reason: string | null;
  recommended_angle: string | null;
  qualification_breakdown: Record<string, unknown> | null;
  last_activity_at: string;
  created_at: string;
  contacts: Contact[];
  research: { id: string; data: ResearchData; confidence: number; created_at: string } | null;
  emails: Email[];
  replies: Reply[];
  followups: Followup[];
  timeline: TimelineEvent[];
}

export interface Metrics {
  leads_total: number;
  leads_researched: number;
  leads_qualified: number;
  leads_disqualified: number;
  drafts_awaiting_review: number;
  emails_sent: number;
  initial_emails_sent: number;
  followups_sent: number;
  followups_pending: number;
  contacts_emailed: number;
  replies: number;
  contacts_replied: number;
  reply_rate_pct: number | null;
  interested_contacts: number;
  conversion_rate_pct: number | null;
  contacts_suppressed: number;
  reply_breakdown: Record<string, number>;
  meeting_requests: number;
  positive_replies: number;
  conversions: number;
  personalized_pct: number | null;
}

export interface Analytics {
  overall: Metrics & { campaigns_total: number; active_campaigns: number; pending_approvals: number; open_opportunities: number };
  email_intelligence: { routine: number; opportunity: number; human_attention: number; opt_out: number; unclassified: number };
  lifecycle: {
    customers: number;
    purchases: number;
    support_questions: number;
    customer_messages: number;
    warranty_requests: number;
    service_requests: number;
    lifecycle_messages_sent: number;
    repeat_customers: number;
  };
  campaigns: (Metrics & { campaign_id: string; name: string; status: string; target_audience: string })[];
}

export interface Insights {
  summary: string;
  what_worked: string[];
  what_did_not_work: string[];
  recommendations: string[];
}

export interface Job {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  last_error: string | null;
  result: Record<string, unknown> | null;
}

export interface TimelineEvent {
  at: string;
  type: string;
  description: string;
  actor: "agent" | "human" | "system" | "contact";
}

// ---------------- Orchestrator / trace ----------------
export interface TraceEvent {
  id: string;
  workflow_id: string;
  agent: string;
  action: string;
  status: "STARTED" | "COMPLETED" | "SKIPPED" | "WAITING" | "ESCALATED" | "BLOCKED" | "FAILED" | "RETRYING";
  result: string;
  detail: Record<string, unknown>;
  state_after: string | null;
  lead_id: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  workflow_type?: string;
  goal?: string;
  company_name?: string | null;
}

export interface WorkflowSummary {
  id: string;
  type: "GOAL" | "LEAD" | "INBOUND" | "LIFECYCLE";
  goal: string;
  state: string;
  parent_id: string | null;
  lead_id: string | null;
  campaign_id: string | null;
  customer_id: string | null;
  plan: string[];
  summary: Record<string, number>;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  company_name: string | null;
}

export interface WorkflowDetail extends WorkflowSummary {
  events: TraceEvent[];
  children: WorkflowSummary[];
}

export interface ApprovalItem {
  id: string;
  type: "OUTBOUND_EMAIL" | "REPLY_ESCALATION" | "MESSAGE_ESCALATION" | "WARRANTY_CLAIM" | "SERVICE_REQUEST";
  status: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  tier: "GREEN" | "YELLOW" | "RED" | null;
  category: string;
  title: string;
  reason: string;
  recommended_action: string;
  suggested_response: string;
  lead_id: string | null;
  company_name: string | null;
  customer_id: string | null;
  customer_name: string | null;
  workflow_id: string | null;
  can_automate: boolean;
  subject: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface MemoryItem {
  id: string;
  scope: string;
  subject_id: string | null;
  category: string;
  key: string;
  content: string;
  data: Record<string, unknown>;
  source: string;
  importance: number;
  updated_at: string;
}

export interface Policy {
  max_messages_per_contact_30d: number;
  min_hours_between_messages: number;
  blocked_domains: string[];
  banned_phrases: string[];
  escalation_rules: Record<string, string>;
  large_order_threshold: number;
  auto_handle_routine: boolean;
  warranty_auto_approve: boolean;
  lifecycle_enabled: boolean;
  lifecycle_rules: Record<string, number>;
  lifecycle_max_per_7d: number;
  locked_categories: string[];
}

// ---------------- Customers ----------------
export interface WarrantyInfo {
  status: "ACTIVE" | "EXPIRING_SOON" | "EXPIRED" | "NO_WARRANTY";
  days_left: number | null;
}

export interface PurchaseRow {
  id: string;
  product_id: string;
  product_name: string;
  sku: string;
  category: string;
  purchased_at: string;
  warranty_expires_at: string | null;
  warranty: WarrantyInfo;
  serial_number: string;
  quantity: number;
  order_value: number | null;
  status: string;
}

export interface OwnerMessage {
  id: string;
  channel: string;
  sender: "customer" | "business" | "ai";
  body: string;
  tier: "GREEN" | "YELLOW" | "RED" | null;
  intents: string[];
  analysis: Record<string, unknown>;
  sources: { title: string; section: string }[];
  handled_automatically: boolean;
  created_at: string;
  customer_id: string;
  customer_name?: string;
}

export interface CustomerRow {
  id: string;
  name: string;
  email: string;
  phone: string;
  company: string;
  status: string;
  lead_id: string | null;
  notes: string;
  preferences: Record<string, boolean>;
  portal_access: boolean;
  created_at: string;
}

export interface CustomerDetail extends CustomerRow {
  purchases: PurchaseRow[];
  warranty_claims: { id: string; issue: string; status: string; created_at: string }[];
  service_requests: { id: string; issue: string; status: string; scheduled_for: string | null }[];
  messages: OwnerMessage[];
  memory: { category: string; key: string; content: string; source: string; updated_at: string }[];
}

export interface ProductRow {
  id: string;
  name: string;
  sku: string;
  category: string;
  description: string;
  warranty_months: number;
  price: number | null;
  active: boolean;
}

export interface KnowledgeDoc {
  id: string;
  title: string;
  doc_type: string;
  content: string;
  product_id: string | null;
  chunks: number | null;
  updated_at: string;
}

export interface ClaimRow {
  id: string;
  issue: string;
  status: string;
  eligibility: {
    likely_eligible?: boolean;
    checks?: { check: string; passed: boolean; detail?: string }[];
    warranty?: WarrantyInfo;
    policy_excerpts?: { title: string; section: string; text: string }[];
  };
  resolution_note: string | null;
  created_at: string;
  customer_id: string;
  customer_name: string;
  product_name: string;
  serial_number: string;
  purchased_at: string;
  warranty_expires_at: string | null;
}

export interface ServiceRow {
  id: string;
  issue: string;
  status: string;
  preferred_date: string | null;
  preferred_time: string;
  contact_phone: string;
  contact_email: string;
  scheduled_for: string | null;
  owner_note: string | null;
  created_at: string;
  customer_id: string;
  customer_name: string;
  product_name: string;
}

// ---------------- Portal (customer-facing; no internal fields) ----------------
export interface PortalProduct {
  purchase_id: string;
  product_name: string;
  category: string;
  description: string;
  purchased_at: string;
  serial_number: string;
  quantity: number;
  status: string;
  warranty_expires_at: string | null;
  warranty: WarrantyInfo;
  warranty_months: number;
}

export interface PortalMessage {
  id: string;
  sender: "customer" | "business" | "ai";
  body: string;
  sources: { title: string; section: string }[];
  created_at: string;
}

export interface PortalClaim {
  id: string;
  product_name: string;
  purchase_id: string;
  issue: string;
  status: string;
  resolution_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PortalService {
  id: string;
  product_name: string;
  purchase_id: string;
  issue: string;
  status: string;
  preferred_date: string | null;
  preferred_time: string;
  scheduled_for: string | null;
  note: string | null;
  created_at: string;
}

export interface PortalNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  read: boolean;
  created_at: string;
}
