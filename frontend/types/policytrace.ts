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
  | "human_edited"
  | "approved"
  | "needs_refresh";

export type HumanReviewStatus =
  | "not_reviewed"
  | "in_review"
  | "reviewed"
  | "approved";

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
  version?: string | null;
  raw_text?: string | null;
}

export interface Evidence {
  id: string;
  source_id: string;
  snippet: string;
  locator?: string | null;
  retrieved_at: string;
}

export interface Claim {
  id: string;
  text: string;
  information_type: InformationType;
  evidence_ids: string[];
  verification_status: VerificationStatus;
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
  kind: string;
  title: string;
  status: StepStatus;
  depends_on: string[];
  claims: Claim[];
  ai_output?: string | null;
  human_review: HumanReview;
  version: number;
}

export interface AnalysisRun {
  schema_version: "0.1.0";
  id: string;
  mode: AnalysisMode;
  policy: Policy;
  sources: Source[];
  evidence: Evidence[];
  steps: AnalysisStep[];
  current_step_id?: string | null;
  final_review_status: HumanReviewStatus;
}
