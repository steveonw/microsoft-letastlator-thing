export type AnalysisMode = "guided" | "rush";

export type InformationType =
  | "official_policy"
  | "official_context"
  | "factual_reporting"
  | "public_opinion"
  | "stakeholder_claim"
  | "ai_interpretation"
  | "human_interpretation"
  | "unverified";

export type VerificationStatus =
  | "supported"
  | "partially_supported"
  | "needs_clarification"
  | "unsupported"
  | "needs_human_review";

export type StepStatus =
  | "draft"
  | "verified"
  | "needs_refresh";

export type HumanReviewStatus =
  | "not_reviewed"
  | "in_review"
  | "reviewed"
  | "approved";

export type PiiRedactionStatus =
  | "not_checked"
  | "not_detected"
  | "redacted"
  | "not_applicable";

export type StepKind =
  | "policy_understanding"
  | "major_provisions"
  | "stakeholders"
  | "public_response"
  | "themes_viewpoints"
  | "verification"
  | "draft_brief";

export type Confidence = "low" | "medium" | "high";

export interface Policy {
  id: string;
  title: string;
  jurisdiction: string;
  version?: string | null;
  source_ids: string[];
}

export interface Source {
  id: string;
  title: string;
  information_type: InformationType;
  url?: string | null;
  agency?: string | null;
  published_at?: string | null;
  submitted_at?: string | null;
  version?: string | null;
  raw_text?: string | null;
  pii_redaction_status: PiiRedactionStatus;
  duplicate_cluster_id?: string | null;
}

export interface Evidence {
  id: string;
  source_id: string;
  snippet: string;
  locator?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  retrieved_at: string;
}

export interface Claim {
  id: string;
  text: string;
  original_text?: string | null;
  information_type: InformationType;
  evidence_ids: string[];
  verification_status: VerificationStatus;
  verification_note?: string | null;
  confidence: Confidence;
}

export interface HumanReview {
  status: HumanReviewStatus;
  notes: string[];
  flagged_claim_ids: string[];
  edited_claim_ids: string[];
}

export interface AnalysisStep {
  id: string;
  kind: StepKind;
  title: string;
  status: StepStatus;
  depends_on: string[];
  claims: Claim[];
  ai_output?: string | null;
  human_review: HumanReview;
  version: number;
}

export interface AnalysisRun {
  schema_version: "0.2.0";
  id: string;
  mode: AnalysisMode;
  policy: Policy;
  sources: Source[];
  evidence: Evidence[];
  steps: AnalysisStep[];
  current_step_id?: string | null;
  final_review_status: HumanReviewStatus;
}
