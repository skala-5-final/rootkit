"""작성: rootkit · 2026-10-23. Grounding and independent review safeguards."""

from copy import deepcopy
import unittest

from pydantic import ValidationError

from app.guards import emitted_feedback, exercise_errors, feedback_review_errors, validate_decisions
from app.knowledge import validate_knowledge
from app.models import EvaluationProposal, ExerciseDraft, FactsReview, KnowledgeProposal, SemanticReview
from tests.helpers import documents, exercise, facts, feedback, knowledge, semantics


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.documents = [source.model_dump() for source in documents()]
        self.knowledge = validate_knowledge(KnowledgeProposal.model_validate(knowledge()), documents())

    def errors(self, draft):
        return exercise_errors(ExerciseDraft.model_validate(draft), self.documents, self.knowledge)

    def test_task_deadline_cannot_become_an_unfounded_company_rule(self):
        draft = exercise()
        draft["criteria"][0]["category"] = "company"
        self.assertTrue(self.errors(draft))

    def test_unapproved_term_cannot_be_used_as_company_criterion(self):
        draft = exercise()
        draft["criteria"][0].update(category="company", kind="term", term_id="a-term", evidence_ids=["a-mail-1"])
        self.assertTrue(any("human-approved" in error for error in self.errors(draft)))
        self.knowledge["terms"][0].update(approved=True, approved_aliases=["검토표"])
        self.assertEqual(self.errors(draft), [])

    def test_general_advice_cannot_claim_company_evidence(self):
        draft = exercise()
        draft["criteria"][0].update(category="general", kind="general", evidence_ids=["a-mail-1"])
        self.assertTrue(any("general advice" in error for error in self.errors(draft)))

    def test_pattern_cannot_cross_recipient_language_or_situation(self):
        draft = exercise()
        draft["criteria"][0].update(category="company", kind="pattern", pattern_id="a-pattern", evidence_ids=["a-mail-1"])
        self.assertEqual(self.errors(draft), [])
        for field, value in [("recipient_group", "customer"), ("language", "en"), ("situation", "welcome")]:
            with self.subTest(field=field):
                wrong = deepcopy(draft)
                wrong[field] = value
                self.assertTrue(any("not applicable" in error for error in self.errors(wrong)))

    def test_source_fact_must_exist_in_its_own_dataset_evidence(self):
        draft = exercise()
        draft["facts"][-1]["value"] = "완료"
        self.assertTrue(any("absent from source" in error for error in self.errors(draft)))
        draft = exercise()
        draft["source_ids"] = ["b-mail-1"]
        self.assertTrue(any("outside its dataset" in error for error in self.errors(draft)))

    def test_unknown_source_fact_is_rejected_without_crashing(self):
        draft = exercise()
        draft["source_ids"] = ["missing-source"]
        draft["facts"][-1]["source_ids"] = ["missing-source"]
        self.assertTrue(self.errors(draft))

    def test_step_two_cannot_smuggle_an_original_email(self):
        draft = exercise(stage=2)
        draft["original"] = "STEP 2 should show a scenario, not a hidden rewriting original."
        with self.assertRaises(ValidationError):
            ExerciseDraft.model_validate(draft)

    def test_practice_fact_cannot_masquerade_as_historical_source_fact(self):
        draft = exercise()
        draft["facts"][0]["source_ids"] = ["a-mail-1"]
        self.assertTrue(any("Practice fact" in error for error in self.errors(draft)))

    def test_unknown_criterion_or_evidence_cannot_be_injected_into_feedback(self):
        proposal = feedback()
        proposal["decisions"][0]["criterion_id"] = "invented"
        self.assertTrue(validate_decisions(exercise(), EvaluationProposal.model_validate(proposal)))
        proposal = feedback()
        proposal["decisions"][0]["evidence_ids"] = ["b-mail-1"]
        self.assertTrue(validate_decisions(exercise(), EvaluationProposal.model_validate(proposal)))

    def test_general_feedback_is_explicitly_labeled_and_fact_reviewed(self):
        proposal = feedback(applies=False)
        proposal["general_feedback"] = [{"explanation": "문단을 짧게 나누면 읽기 쉽습니다.", "suggestion": "인사와 본문을 별도 문단으로 나누세요."}]
        parsed = EvaluationProposal.model_validate(proposal)
        emitted = emitted_feedback(exercise(), parsed)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].category, "general")
        self.assertTrue(emitted[0].explanation.startswith("일반 조언:"))
        self.assertEqual(emitted[0].evidence_ids, [])
        errors = feedback_review_errors(parsed, SemanticReview.model_validate(semantics(False)), FactsReview.model_validate(facts(feedback_ids=[])), emitted)
        self.assertTrue(any("every emitted" in error for error in errors))

    def test_semantic_reviewer_must_confirm_conditional_applicability(self):
        parsed = EvaluationProposal.model_validate(feedback(True))
        errors = feedback_review_errors(parsed, SemanticReview.model_validate(semantics(False)), FactsReview.model_validate(facts()), emitted_feedback(exercise(), parsed))
        self.assertTrue(any("applicability" in error for error in errors))

    def test_existing_general_advice_label_is_not_duplicated(self):
        proposal = feedback(applies=False)
        explanation = "일반 조언: 문단을 짧게 나누면 읽기 쉽습니다."
        proposal["general_feedback"] = [{"explanation": explanation, "suggestion": "확인해 주셔서 감사합니다."}]
        emitted = emitted_feedback(exercise(), EvaluationProposal.model_validate(proposal))
        self.assertEqual(emitted[0].explanation, explanation)

    def test_review_cannot_skip_a_criterion_or_feedback_example(self):
        parsed = EvaluationProposal.model_validate(feedback())
        review = semantics()
        review["decisions"] = []
        errors = feedback_review_errors(parsed, SemanticReview.model_validate(review), FactsReview.model_validate(facts(feedback_ids=[])), emitted_feedback(exercise(), parsed))
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
