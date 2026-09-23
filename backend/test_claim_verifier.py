import json
import unittest
from datetime import datetime, timezone

from claim_verifier import (
    CLAIM_VERIFIER_SYSTEM_PROMPT,
    build_claim_verification_prompt,
    citation_integrity_problem,
    parse_claim_verification,
    verify_analysis,
)
from models import (
    AnalysisMode,
    AnalysisRun,
    AnalysisStep,
    Claim,
    Evidence,
    HumanReviewStatus,
    InformationType,
    PiiRedactionStatus,
    Policy,
    Source,
    StepKind,
    VerificationStatus,
)


RAW_TEXT = "The proposal requires quarterly notification by covered persons."


def analysis_with_claim(*, evidence_ids=None) -> AnalysisRun:
    evidence_ids = ["evidence-1"] if evidence_ids is None else evidence_ids
    source = Source(
        id="source-1",
        title="Official proposal",
        information_type=InformationType.OFFICIAL_POLICY,
        raw_text=RAW_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )
    evidence = Evidence(
        id="evidence-1",
        source_id=source.id,
        snippet=RAW_TEXT,
        locator="Section A | chars 0-65",
        start_offset=0,
        end_offset=len(RAW_TEXT),
        retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
    )
    claim = Claim(
        id="claim-1",
        text="Covered persons would have a quarterly notification requirement.",
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=evidence_ids,
        verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
        verification_note="Awaiting semantic verification.",
        confidence="high",
    )
    step = AnalysisStep(
        id="step-policy-understanding",
        kind=StepKind.POLICY_UNDERSTANDING,
        title="Policy understanding",
        claims=[claim],
    )
    return AnalysisRun(
        id="run-1",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="policy-1",
            title="Demo",
            jurisdiction="United States / federal",
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[evidence],
        steps=[step],
        current_step_id=step.id,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )


class ClaimVerifierTests(unittest.TestCase):
    def test_prompt_contains_claim_and_exact_evidence_but_not_prior_reasoning(self) -> None:
        analysis = analysis_with_claim()
        claim = analysis.steps[0].claims[0]

        prompt = build_claim_verification_prompt(analysis, claim)

        self.assertIn("Claim ID: claim-1", prompt)
        self.assertIn(claim.text, prompt)
        self.assertIn("Source type: official_policy", prompt)
        self.assertIn(RAW_TEXT, prompt)
        self.assertNotIn("Awaiting semantic verification", prompt)
        self.assertIn(
            "Judge support, not policy desirability",
            CLAIM_VERIFIER_SYSTEM_PROMPT,
        )

    def test_supported_result_updates_status_without_rewriting_claim(self) -> None:
        analysis = analysis_with_claim()
        original_text = analysis.steps[0].claims[0].text

        def model_call(system_prompt: str, user_prompt: str) -> str:
            self.assertIn("Evidence Verifier", system_prompt)
            self.assertIn("Claim ID: claim-1", user_prompt)
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "The evidence directly states the quarterly requirement.",
                    "narrower_wording": None,
                }
            )

        verified = verify_analysis(analysis, model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(claim.text, original_text)
        self.assertEqual(claim.verification_status, VerificationStatus.SUPPORTED)
        self.assertIn("Semantic verification:", claim.verification_note)
        self.assertEqual(analysis.steps[0].claims[0].text, original_text)
        self.assertEqual(
            analysis.steps[0].claims[0].verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )

        verification_step = verified.steps[-1]
        self.assertEqual(verification_step.kind, StepKind.VERIFICATION)
        self.assertEqual(verified.current_step_id, verification_step.id)
        self.assertIn("supported: 1", verification_step.ai_output)

    def test_partial_support_preserves_original_and_records_suggestion(self) -> None:
        analysis = analysis_with_claim()

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "partially_supported",
                    "explanation": "The frequency is supported, but the scope is broader than the excerpt.",
                    "narrower_wording": "The source describes a quarterly notification requirement.",
                }
            )

        verified = verify_analysis(analysis, model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.text,
            "Covered persons would have a quarterly notification requirement.",
        )
        self.assertEqual(
            claim.verification_status,
            VerificationStatus.PARTIALLY_SUPPORTED,
        )
        self.assertIn("Suggested narrower wording:", claim.verification_note)
        self.assertIn(
            "The source describes a quarterly notification requirement.",
            claim.verification_note,
        )

    def test_verifier_parser_recovers_json_after_prose_prefix(self) -> None:
        result = parse_claim_verification(
            'Sure! Here is the JSON:\n'
            '{"status":"supported","explanation":"Direct support.",'
            '"narrower_wording":null}'
        )

        self.assertEqual(result.status, VerificationStatus.SUPPORTED)
        self.assertEqual(result.explanation, "Direct support.")

    def test_unparseable_reply_does_not_abort_remaining_claims(self) -> None:
        analysis = analysis_with_claim()
        second = analysis.steps[0].claims[0].model_copy(deep=True)
        second.id = "claim-2"
        second.text = "A second claim with the same grounded evidence."
        analysis.steps[0].claims.append(second)

        calls = 0

        def model_call(system_prompt: str, user_prompt: str) -> str:
            nonlocal calls
            del system_prompt, user_prompt
            calls += 1
            if calls == 1:
                return "Sure, but I forgot to include JSON."
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "The second claim is supported.",
                    "narrower_wording": None,
                }
            )

        verified = verify_analysis(analysis, model_call)
        first, second = verified.steps[0].claims

        self.assertEqual(calls, 2)
        self.assertEqual(
            first.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("unparseable or schema-invalid", first.verification_note)
        self.assertEqual(second.verification_status, VerificationStatus.SUPPORTED)
        self.assertIn("supported: 1", verified.steps[-1].ai_output)
        self.assertIn("needs_human_review: 1", verified.steps[-1].ai_output)

    def test_provider_failure_does_not_abort_remaining_claims(self) -> None:
        analysis = analysis_with_claim()
        second = analysis.steps[0].claims[0].model_copy(deep=True)
        second.id = "claim-2"
        second.text = "A second claim with the same grounded evidence."
        analysis.steps[0].claims.append(second)

        calls = 0

        def model_call(system_prompt: str, user_prompt: str) -> str:
            nonlocal calls
            del system_prompt, user_prompt
            calls += 1
            if calls == 1:
                raise RuntimeError("OpenRouter request timed out after retrying")
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "The second claim is supported.",
                    "narrower_wording": None,
                }
            )

        verified = verify_analysis(analysis, model_call)
        first, second = verified.steps[0].claims

        self.assertEqual(calls, 2)
        self.assertEqual(
            first.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("model provider failed", first.verification_note)
        self.assertEqual(second.verification_status, VerificationStatus.SUPPORTED)

    def test_schema_invalid_reply_does_not_abort_batch(self) -> None:
        analysis = analysis_with_claim()

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return '{"status":"supported","narrower_wording":null}'

        verified = verify_analysis(analysis, model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("schema-invalid", claim.verification_note)

    def test_no_evidence_short_circuits_model_and_stays_human_review(self) -> None:
        analysis = analysis_with_claim(evidence_ids=[])

        def model_call(system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("model should not be called without evidence")

        verified = verify_analysis(analysis, model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("claim has no cited evidence", claim.verification_note)

    def test_mutated_bad_offset_snippet_is_blocked_before_model(self) -> None:
        analysis = analysis_with_claim()
        analysis.evidence[0].snippet = "This no longer matches the source."

        problem = citation_integrity_problem(
            analysis,
            analysis.steps[0].claims[0],
        )
        self.assertIn("does not match source text", problem)

        def model_call(system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("model should not see integrity failures")

        with self.assertRaisesRegex(
            ValueError,
            "deterministic AnalysisRun integrity validation",
        ):
            verify_analysis(analysis, model_call)

    def test_rerun_replaces_verification_step_and_increments_version(self) -> None:
        analysis = analysis_with_claim()

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "Direct support.",
                    "narrower_wording": None,
                }
            )

        first = verify_analysis(analysis, model_call)
        second = verify_analysis(first, model_call)

        verification_steps = [
            step
            for step in second.steps
            if step.kind == StepKind.VERIFICATION
        ]
        self.assertEqual(len(verification_steps), 1)
        self.assertEqual(verification_steps[0].version, 2)


if __name__ == "__main__":
    unittest.main()
