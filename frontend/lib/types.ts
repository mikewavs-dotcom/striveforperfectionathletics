export type OrgType =
  | "booster_club"
  | "nil_collective"
  | "youth_sports_org"
  | "travel_program"
  | "showcase_operator"
  | "high_school"
  | "school_district"
  | "college"
  | "business"
  | "other";

export type ContactRole =
  | "athletic_director"
  | "compliance_officer"
  | "head_coach"
  | "assistant_coach"
  | "board_officer"
  | "executive_director"
  | "marketing_contact"
  | "owner"
  | "unknown";

export type Offer = "camps" | "panels" | "media";

export type SourceRunStatus = "success" | "partial" | "failed";

export type SortField =
  | "name"
  | "state"
  | "city"
  | "created_at"
  | "last_verified"
  | "camps_score"
  | "panels_score"
  | "media_score";

export type SortDir = "asc" | "desc";

export interface OfferScores {
  camps: number | null;
  panels: number | null;
  media: number | null;
}

export interface Contact {
  id: string;
  organization_id: string;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  title_raw: string | null;
  role: ContactRole | null;
  email: string | null;
  phone: string | null;
  source_url: string | null;
  confidence: number | null;
  is_minor_related: boolean;
  first_seen_at: string | null;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationListItem {
  id: string;
  name: string;
  canonical_name: string | null;
  org_type: OrgType;
  website: string | null;
  phone: string | null;
  street: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  county: string | null;
  ein: string | null;
  source_urls: string[] | null;
  last_verified_at: string | null;
  is_active: boolean;
  scores: OfferScores;
  top_contact: Contact | null;
}

export interface PaginatedOrganizations {
  items: OrganizationListItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface Score {
  id: string;
  organization_id: string;
  offer: Offer;
  score: number;
  rationale: string;
  signals: Record<string, unknown>;
  model_version: string;
  scored_at: string;
}

export interface PolicyEvent {
  id: string;
  jurisdiction: string;
  source_url: string;
  event_type: string;
  detected_at: string;
  effective_date: string | null;
  summary: string | null;
  linked_organization_id: string | null;
}

export interface Sponsor {
  id: string;
  brand_name: string;
  detected_on_url: string;
  detected_on_organization_id: string | null;
  logo_image_url: string | null;
  extraction_confidence: number | null;
  matched_organization_id: string | null;
  detected_at: string;
}

export interface OrganizationDetail extends Omit<OrganizationListItem, "scores" | "top_contact"> {
  contacts: Contact[];
  scores: Score[];
  policy_events: PolicyEvent[];
  sponsors: Sponsor[];
  annual_revenue: string | null;
  program_expenses: string | null;
  fiscal_year: number | null;
  roster_size_estimate: number | null;
  events_per_year: number | null;
}

export interface DashboardStats {
  organization_count: number;
  contact_count: number;
  new_records_last_30_days: number;
  policy_event_count: number;
}

export interface SourceRun {
  id: string;
  collector_name: string;
  started_at: string;
  finished_at: string | null;
  status: SourceRunStatus;
  records_found: number | null;
  records_new: number | null;
  records_updated: number | null;
  error_message: string | null;
  pages_fetched: number | null;
}

export interface CollectorWithRuns {
  name: string;
  runs: SourceRun[];
}

export interface PaginatedPolicyEvents {
  items: PolicyEvent[];
  page: number;
  page_size: number;
  total: number;
}

export interface OutreachStatus {
  configured: boolean;
}

export interface OutreachCampaign {
  id?: number | string;
  name?: string;
  status?: string;
}

export interface OutreachAccount {
  id?: number | string;
  email?: string;
  isActive?: boolean;
}

export interface PushLeadsResult {
  pushed: number;
  skipped_minor: number;
  skipped_no_email: number;
  campaign_id: number;
}
