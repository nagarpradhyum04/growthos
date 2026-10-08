export type LeadStatus =
  | "NEW" | "RESEARCHED" | "QUALIFIED" | "DISQUALIFIED" | "DRAFTED" | "CONTACTED" | "REPLIED" | "COMPLETED" | "SUPPRESSED";
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
  send_check: { allowed: boolean; reasons: string[] };
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
  timeline: { at: string; type: string; description: string }[];
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
}

export interface Analytics {
  overall: Metrics & { campaigns_total: number; active_campaigns: number };
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
