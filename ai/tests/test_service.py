"""작성: rootkit · 2026-10-23. SQLite + service acceptance tests using a scripted model."""

from contextlib import closing, nullcontext
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.errors import DomainError, ModelError
from app.models import Answer
from app.service import Service
from app.storage import Storage
from tests.helpers import ScriptedProvider, catalog, catalog_review, documents, facts, feedback, knowledge, semantics


class PipelineTests(unittest.TestCase):
    def setUp(self):
        repair_setting = patch.dict("os.environ", {"EVALUATION_REPAIR_ATTEMPTS": "0"})
        repair_setting.start()
        self.addCleanup(repair_setting.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = Storage(Path(self.directory.name) / "test.sqlite3")
        self.provider = ScriptedProvider()
        self.service = Service(self.storage, self.provider)

    def prepare(self, label="a", approve=False, review=True, activate=True):
        dataset = self.service.import_dataset(label.upper(), documents(label))
        self.provider.add("extract_knowledge", knowledge(label))
        self.service.extract_knowledge(label.upper(), dataset["version"])
        if approve:
            self.service.approve_term(label.upper(), dataset["version"], f"{label}-term", ["승인 별칭"])
        self.provider.add("generate_catalog", catalog(label))
        result = self.service.generate_catalog(label.upper(), dataset["version"])
        if review:
            self.provider.add("review_catalog", catalog_review(label))
            self.service.review_catalog(result["catalog_id"])
        if activate:
            self.service.activate_catalog(result["catalog_id"])
        return result

    def snapshot(self, attempt_id):
        with closing(self.storage.connect()) as connection:
            return json.loads(connection.execute("SELECT snapshot FROM attempts WHERE id=?", (attempt_id,)).fetchone()[0])

    def active_id(self):
        with closing(self.storage.connect()) as connection:
            row = connection.execute("SELECT catalog_id FROM active_catalog WHERE singleton=1").fetchone()
        return row[0] if row else None

    def add_evaluation(self, applies=True, label="a", semantic_passed=True, fact_passed=True, suggestion=None):
        self.provider.add("evaluate", feedback(applies, label, suggestion))
        self.provider.add("review_feedback_semantics", semantics(applies, semantic_passed, semantic_passed))
        self.provider.add("review_feedback_facts", facts(fact_passed, ["deadline"] if applies else []))

    def submit(self, attempt, request="request-1", body="출고 준비표를 확인해 주세요. 배송 일정은 확인 중입니다.", user="alice"):
        return self.service.evaluate(user, attempt["attempt_id"], request, Answer(subject="검토 요청", body=body))

    def test_reviewed_a_can_be_issued_for_both_stages_without_private_rubric(self):
        created = self.prepare()
        self.assertEqual(self.provider.count("generate_catalog"), 1)
        self.assertEqual(self.provider.count("review_catalog"), 1)
        for stage in (1, 2):
            attempt = self.service.start_attempt("alice", stage)
            exercise = attempt["exercise"]
            self.assertEqual(exercise["dataset_id"], "A")
            self.assertEqual(exercise["stage"], stage)
            self.assertNotIn("criteria", exercise)
            self.assertNotIn("review", exercise)
            self.assertNotIn("knowledge", attempt)
            self.assertEqual(self.snapshot(attempt["attempt_id"])["criteria_version"], created["catalog_id"])

    def test_b_replacement_does_not_inherit_a_documents_terms_or_criteria(self):
        self.prepare("a", approve=True)
        a = self.service.start_attempt("alice", 2)
        self.prepare("b")
        b = self.service.start_attempt("alice", 2)
        saved = self.snapshot(b["attempt_id"])
        self.assertEqual(saved["dataset_id"], "B")
        self.assertEqual(saved["knowledge"]["terms"], [])
        self.assertTrue(all(source["id"].startswith("b-") for source in saved["documents"]))
        self.assertTrue(all(source_id.startswith("b-") for source_id in b["exercise"]["source_ids"]))
        self.assertNotEqual(saved["criteria_version"], self.snapshot(a["attempt_id"])["criteria_version"])
        self.assertIn("2026-12-18", b["exercise"]["scenario"])
        self.assertNotIn("2026-11-12", json.dumps(saved, ensure_ascii=False))

    def test_regenerated_catalog_has_a_distinct_exercise_version_for_same_dataset_revision(self):
        self.prepare()
        first = self.service.start_attempt("alice", 2)
        self.provider.add("generate_catalog", catalog())
        replacement = self.service.generate_catalog("A", 1)
        self.provider.add("review_catalog", catalog_review())
        self.service.review_catalog(replacement["catalog_id"])
        self.service.activate_catalog(replacement["catalog_id"])
        second = self.service.start_attempt("alice", 2)
        self.assertEqual(first["exercise"]["dataset_version"], second["exercise"]["dataset_version"])
        self.assertEqual(first["exercise"]["id"], second["exercise"]["id"])
        self.assertNotEqual(first["exercise"]["version"], second["exercise"]["version"])
        self.assertEqual(self.service.get_attempt(first["attempt_id"], "alice"), first)

    def test_display_time_snapshot_survives_switch_before_first_submission_and_resubmission(self):
        created_a = self.prepare("a", approve=True)
        shown_a = self.service.start_attempt("alice", 2)
        before = self.snapshot(shown_a["attempt_id"])
        self.prepare("b")
        self.assertEqual(self.service.get_attempt(shown_a["attempt_id"], "alice"), shown_a)
        self.add_evaluation(True, "a")
        first = self.submit(shown_a)
        self.assertEqual(first["status"], "needs_revision")
        self.assertIn("2026-11-12", first["feedback"][0]["suggestion"])
        self.add_evaluation(False, "a")
        second = self.submit(shown_a, request="request-2", body="출고 준비표 12개를 2026-11-12 15:00 KST까지 확인해 주시면 감사하겠습니다. 배송 일정은 확인 중입니다.")
        self.assertEqual(second["status"], "match")
        after = self.snapshot(shown_a["attempt_id"])
        self.assertEqual(after, before)
        self.assertEqual(after["criteria_version"], created_a["catalog_id"])
        self.assertEqual(after["dataset_id"], "A")
        for task, payload in self.provider.calls:
            if task == "evaluate":
                self.assertIn("2026-11-12", json.dumps(payload, ensure_ascii=False))
                self.assertNotIn("2026-12-18", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(self.provider.count("generate_catalog"), 2)

    def test_same_request_and_answer_reuses_result_but_changed_answer_conflicts(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation()
        first = self.submit(attempt)
        calls = len(self.provider.calls)
        self.assertEqual(self.submit(attempt), first)
        self.assertEqual(len(self.provider.calls), calls)
        with self.assertRaises(DomainError) as conflict:
            self.submit(attempt, body="같은 요청 ID에 다른 답안을 보내면 충돌해야 합니다.")
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(len(self.provider.calls), calls)
        with closing(self.storage.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 1)

    def test_concurrent_duplicate_requests_and_process_restart_reuse_stored_result(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation()
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: self.submit(attempt), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.provider.count("evaluate"), 1)
        self.service = Service(Storage(self.storage.path), ScriptedProvider())
        self.assertEqual(self.submit(attempt), first)

    def test_ownership_protects_attempt_submission_and_history(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        for operation in [lambda: self.service.get_attempt(attempt["attempt_id"], "mallory"),
                          lambda: self.submit(attempt, user="mallory")]:
            with self.subTest(operation=operation), self.assertRaises(DomainError) as denied:
                operation()
            self.assertIn(denied.exception.status_code, (403, 404))
        self.add_evaluation()
        self.submit(attempt)
        self.assertNotIn(attempt["attempt_id"], json.dumps(self.service.history("mallory")))
        self.assertIn(attempt["attempt_id"], json.dumps(self.service.history("alice")))

    def test_unreviewed_catalog_cannot_activate(self):
        created_a = self.prepare()
        created_b = self.prepare("b", review=False, activate=False)
        with self.assertRaises(DomainError):
            self.service.activate_catalog(created_b["catalog_id"])
        self.assertEqual(self.active_id(), created_a["catalog_id"])

    def test_failed_review_excludes_questions_and_preserves_previous_active_catalog(self):
        created_a = self.prepare()
        created_b = self.prepare("b", review=False, activate=False)
        self.provider.add("review_catalog", catalog_review("b", passed=False))
        reviewed = self.service.review_catalog(created_b["catalog_id"])
        self.assertEqual(reviewed["status"], "rejected")
        self.assertEqual(reviewed["passed_count"], 0)
        with self.assertRaises(DomainError):
            self.service.activate_catalog(created_b["catalog_id"])
        self.assertEqual(self.active_id(), created_a["catalog_id"])
        self.assertIn("문제 조건", json.dumps(self.service.review_export(), ensure_ascii=False))

    def test_partial_review_only_issues_passing_stage(self):
        created = self.prepare(review=False, activate=False)
        review = catalog_review()
        review["reviews"][0].update(passed=False, reasons=["STEP 1 원문의 표현 조건이 불명확합니다."])
        self.provider.add("review_catalog", review)
        self.service.review_catalog(created["catalog_id"])
        self.service.activate_catalog(created["catalog_id"])
        self.assertEqual(self.service.start_attempt("alice", 2)["exercise"]["stage"], 2)
        with self.assertRaises(DomainError):
            self.service.start_attempt("alice", 1)

    def test_incomplete_review_cannot_claim_success_or_replace_active_catalog(self):
        created_a = self.prepare()
        created_b = self.prepare("b", review=False, activate=False)
        review = catalog_review("b")
        review["reviews"].pop()
        self.provider.add("review_catalog", review)
        with self.assertRaises(DomainError) as rejected:
            self.service.review_catalog(created_b["catalog_id"])
        self.assertEqual(rejected.exception.status_code, 503)
        with self.assertRaises(DomainError):
            self.service.activate_catalog(created_b["catalog_id"])
        self.assertEqual(self.active_id(), created_a["catalog_id"])

    def test_empty_or_failed_generation_does_not_replace_active_catalog(self):
        created_a = self.prepare()
        dataset = self.service.import_dataset("B", documents("b"))
        self.provider.add("extract_knowledge", knowledge("b"))
        self.service.extract_knowledge("B", dataset["version"])
        for response in [{"exercises": []}, ModelError("synthetic model timeout")]:
            self.provider.add("generate_catalog", response)
            with self.subTest(response=response), self.assertRaises(DomainError):
                self.service.generate_catalog("B", dataset["version"])
            self.assertEqual(self.active_id(), created_a["catalog_id"])
        self.assertIn("failed", json.dumps(self.service.review_export()))

    def test_no_active_catalog_is_explicit_and_does_not_fallback_to_demo(self):
        with self.assertRaises(DomainError) as missing:
            self.service.start_attempt("alice", 2)
        self.assertIn(missing.exception.status_code, (409, 503))
        self.assertEqual(self.provider.calls, [])

    def test_no_api_key_is_a_real_failure_without_generated_catalog(self):
        self.service.import_dataset("A", documents())
        with patch.dict("os.environ", {"MODEL_API_KEY": "", "MODEL_NAME": "fixture-model"}):
            with self.assertRaises(DomainError) as missing:
                Service(self.storage).extract_knowledge("A", 1)
        self.assertEqual(missing.exception.status_code, 503)
        self.assertIsNone(self.active_id())
        with closing(self.storage.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM catalogs").fetchone()[0], 0)

    def test_append_creates_new_version_and_keeps_previous_snapshot_immutable(self):
        self.prepare(approve=True)
        attempt = self.service.start_attempt("alice", 2)
        initial = self.snapshot(attempt["attempt_id"])
        added = documents()[0].model_copy(update={"id": "a-new", "case_id": "a-new", "body": "새로운 독립 문서입니다."})
        imported = self.service.import_dataset("A", [added], mode="append")
        self.assertEqual(imported["version"], 2)
        with closing(self.storage.connect()) as connection:
            rows = connection.execute("SELECT version,documents,knowledge FROM datasets WHERE dataset_id='A' ORDER BY version").fetchall()
        self.assertEqual(len(json.loads(rows[0]["documents"])), 5)
        self.assertEqual(len(json.loads(rows[1]["documents"])), 6)
        self.assertEqual(self.snapshot(attempt["attempt_id"]), initial)
        self.assertFalse(any(term.get("approved") for term in json.loads(rows[1]["knowledge"]).get("terms", [])))

    def test_replace_same_dataset_does_not_merge_old_documents_or_approvals(self):
        self.prepare(approve=True)
        replacement = documents("b")
        imported = self.service.import_dataset("A", replacement, mode="replace")
        self.assertEqual(imported["version"], 2)
        with closing(self.storage.connect()) as connection:
            row = connection.execute("SELECT documents,knowledge FROM datasets WHERE dataset_id='A' AND version=2").fetchone()
        self.assertTrue(all(item["id"].startswith("b-") for item in json.loads(row["documents"])))
        self.assertFalse(any(term.get("approved") for term in json.loads(row["knowledge"]).get("terms", [])))

    def test_approved_aliases_are_pinned_with_terms_but_candidates_are_not(self):
        self.prepare(approve=True)
        attempt = self.service.start_attempt("alice", 2)
        terms = self.snapshot(attempt["attempt_id"])["knowledge"]["terms"]
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]["approved_aliases"], ["승인 별칭"])
        self.assertNotIn("출고 준비표 약칭", terms[0]["approved_aliases"])

    def test_already_satisfied_condition_emits_no_defect(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation(applies=False)
        result = self.submit(attempt, body="출고 준비표 12개를 2026-11-12 15:00 KST까지 확인 부탁드립니다. 배송 일정은 확인 중입니다.")
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["feedback"], [])
        self.assertIsNone(result["total"])

    def test_semantic_paraphrase_is_accepted_without_exact_reference_text(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation()
        result = self.submit(attempt)
        self.assertEqual(result["status"], "needs_revision")
        actual = result["feedback"][0]["explanation"]
        reference = self.snapshot(attempt["attempt_id"])["exercise"]["criteria"][0]["reference_text"]
        self.assertNotEqual(actual, reference)
        self.assertEqual(self.provider.count("review_feedback_semantics"), 1)
        self.assertEqual(self.provider.count("review_feedback_facts"), 1)

    def test_review_payloads_separate_feedback_audit_from_learner_grading(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 1)
        self.add_evaluation()
        answer = "LEARNER_ONLY_MARKER: 기한을 아직 작성하지 않은 답안입니다."
        result = self.submit(attempt, body=answer)
        self.assertEqual(result["status"], "needs_revision")
        semantic_payload = [payload for task, payload in self.provider.calls if task == "review_feedback_semantics"][-1]
        fact_payload = [payload for task, payload in self.provider.calls if task == "review_feedback_facts"][-1]
        self.assertEqual(semantic_payload["learner_answer"]["body"], answer)
        self.assertEqual(semantic_payload["expected_criterion_ids"], ["deadline"])
        self.assertEqual(semantic_payload["criterion_checks"][0]["criterion"]["criterion_id"], "deadline")
        self.assertTrue(semantic_payload["criterion_checks"][0]["proposed_decision"]["applies"])
        self.assertIn("reference_text", semantic_payload["criterion_checks"][0]["reference"])
        self.assertNotIn("exercise", semantic_payload)
        self.assertNotIn("original", semantic_payload["disclosed_exercise"])
        self.assertEqual(fact_payload["emitted_feedback_ids"], ["deadline"])
        self.assertIn("2026-11-12", fact_payload["feedback_to_verify"][0]["suggestion"])
        self.assertNotIn("explanation", fact_payload["feedback_to_verify"][0])
        self.assertNotIn("LEARNER_ONLY_MARKER", json.dumps(fact_payload))
        self.assertNotIn("criterion_checks", fact_payload)
        self.assertNotIn('"defect"', json.dumps(fact_payload))
        self.assertNotIn("original", fact_payload["disclosed_exercise"])

    def test_vague_or_wrong_condition_feedback_fails_semantic_review(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation(semantic_passed=False)
        result = self.submit(attempt)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["feedback"], [])

    def test_global_review_rejection_is_not_overridden_by_positive_individual_decisions(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.provider.add("evaluate", feedback())
        inconsistent = semantics(applies=True, equivalent=True, passed=False)
        inconsistent["reasons"] = ["AI 피드백이 잘못된 기한을 정확하게 지적했습니다."]
        self.provider.add("review_feedback_semantics", inconsistent)
        self.provider.add("review_feedback_facts", facts())
        result = self.submit(attempt)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["feedback"], [])
        audit = [event for event in self.service.review_export()["events"] if event["operation"] == "evaluate"][-1]
        self.assertEqual(audit["status"], "rejected")
        self.assertFalse(audit["detail"]["semantic_review"]["passed"])
        self.assertEqual(audit["detail"]["semantic_review"]["reasons"], inconsistent["reasons"])

    def test_semantic_review_must_quote_actual_answer_but_missing_conditions_allow_empty_evidence(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        answer = "출고 준비표를 확인해 주세요. 배송 일정은 확인 중입니다."
        cases = [("출고 준비표를 확인해 주세요.", "needs_revision"),
                 ("2026-11-12 15:00 KST까지 회신해 주세요.", "insufficient_evidence"),
                 ("", "needs_revision")]
        for index, (quote, expected) in enumerate(cases):
            with self.subTest(quote=quote):
                self.provider.add("evaluate", feedback())
                review = semantics()
                review["decisions"][0].update(answer_evidence=quote,
                                             reason="답안에 자료 확인 요청은 있지만 요청 기한은 없습니다.")
                self.provider.add("review_feedback_semantics", review)
                self.provider.add("review_feedback_facts", facts())
                result = self.submit(attempt, request=f"answer-evidence-{index}", body=answer)
                self.assertEqual(result["status"], expected)
                if expected == "insufficient_evidence":
                    self.assertEqual(result["feedback"], [])
                    audit = [event for event in self.service.review_export()["events"] if event["operation"] == "evaluate"][-1]
                    self.assertIn("absent from the submitted answer", " ".join(audit["detail"]["reasons"]))

    def test_correct_explanation_does_not_hide_wrong_date_quantity_or_status_example(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        for index, wrong_example in enumerate([
            "2026-11-02 15:00 KST까지 검토해 주세요.",
            "출고 준비표 99개를 2026-11-12 15:00 KST까지 검토해 주세요.",
            "배송 일정은 확정 완료되었습니다. 2026-11-12 15:00 KST까지 검토해 주세요.",
        ]):
            with self.subTest(wrong_example=wrong_example):
                self.add_evaluation(fact_passed=False, suggestion=wrong_example)
                result = self.submit(attempt, request=f"wrong-example-{index}")
                self.assertEqual(result["status"], "insufficient_evidence")
                self.assertEqual(result["feedback"], [])
        self.assertEqual(self.provider.count("review_feedback_semantics"), 3)
        self.assertEqual(self.provider.count("review_feedback_facts"), 3)

    def test_model_failure_is_audited_without_fake_result_and_retry_can_succeed(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.provider.add("evaluate", ModelError("synthetic model outage"))
        with self.assertRaises(DomainError) as failed:
            self.submit(attempt)
        self.assertEqual(failed.exception.status_code, 503)
        with closing(self.storage.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        with self.assertRaises(DomainError) as conflict:
            self.submit(attempt, body="실패한 요청 ID라도 다른 답안에는 재사용하지 않습니다.")
        self.assertEqual(conflict.exception.status_code, 409)
        self.add_evaluation()
        self.assertEqual(self.submit(attempt)["status"], "needs_revision")
        self.assertIn("failed", json.dumps(self.service.review_export()))

    def test_audit_export_retains_failed_feedback_answer_proposal_and_pinned_evidence(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        answer = "검토 대상 12개에 대한 요청입니다. 배송 일정은 확인 중입니다."
        bad_suggestion = "2027-01-01 15:00 KST까지 검토해 주세요."
        self.add_evaluation(fact_passed=False, suggestion=bad_suggestion)
        self.assertEqual(self.submit(attempt, body=answer)["status"], "insufficient_evidence")
        audit = self.service.review_export()
        serialized = json.dumps(audit, ensure_ascii=False)
        self.assertIn(answer, serialized)
        self.assertIn(bad_suggestion, serialized)
        self.assertIn(attempt["attempt_id"], serialized)
        self.assertIn("2026-11-12", serialized)
        self.assertIn("수정 예시", serialized)

    def test_review_repair_repeats_independent_reviews_and_preserves_rounds_and_idempotency(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        pinned = self.snapshot(attempt["attempt_id"])
        trace = [{"task": "evaluate", "model": "fixture", "attempt": 1, "outcome": "success", "duration_ms": 1}]
        self.provider.evaluation_budget = lambda: nullcontext(trace)
        self.add_evaluation(semantic_passed=False)
        self.add_evaluation()
        with patch.dict("os.environ", {"EVALUATION_REPAIR_ATTEMPTS": "1"}):
            result = self.submit(attempt)
        self.assertEqual(result["status"], "needs_revision")
        self.assertEqual(self.provider.count("evaluate"), 2)
        self.assertEqual(self.provider.count("review_feedback_semantics"), 2)
        self.assertEqual(self.provider.count("review_feedback_facts"), 2)
        payloads = [payload for task, payload in self.provider.calls if task == "evaluate"]
        self.assertEqual(payloads[1]["expected_criterion_ids"], ["deadline"])
        self.assertTrue(payloads[1]["repair"]["review_failure_reasons"])
        for task, payload in self.provider.calls:
            if task == "review_feedback_facts":
                self.assertEqual(payload["emitted_feedback_ids"], ["deadline"])
        audit = [event for event in self.service.review_export()["events"] if event["operation"] == "evaluate"][-1]["detail"]
        self.assertEqual([item["status"] for item in audit["rounds"]], ["rejected", "completed"])
        self.assertFalse(audit["rounds"][0]["semantic_review"]["passed"])
        self.assertEqual(audit["model_calls"], trace)
        self.assertEqual(self.snapshot(attempt["attempt_id"]), pinned)
        calls = len(self.provider.calls)
        self.assertEqual(self.submit(attempt), result)
        self.assertEqual(len(self.provider.calls), calls)
        self.add_evaluation()
        self.assertEqual(self.submit(attempt, request="explicit-reevaluation")["status"], "needs_revision")
        self.assertEqual(self.provider.count("evaluate"), 3)

    def test_repair_is_bounded_and_never_turns_repeated_fact_rejection_into_pass(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        self.add_evaluation(fact_passed=False)
        self.add_evaluation(fact_passed=False)
        with patch.dict("os.environ", {"EVALUATION_REPAIR_ATTEMPTS": "99"}):
            result = self.submit(attempt)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["feedback"], [])
        self.assertIn("답안이 틀렸다는 뜻은 아닙니다", result["summary"])
        self.assertEqual(self.provider.count("evaluate"), 2)
        self.assertEqual(self.provider.count("review_feedback_facts"), 2)
        audit = [event for event in self.service.review_export()["events"] if event["operation"] == "evaluate"][-1]
        self.assertEqual(audit["status"], "rejected")
        self.assertEqual(len(audit["detail"]["rounds"]), 2)
        self.assertTrue(all(item["errors"] for item in audit["detail"]["rounds"]))

    def test_schema_and_criterion_membership_failures_can_be_repaired_without_losing_audit(self):
        self.prepare()
        attempt = self.service.start_attempt("alice", 2)
        wrong_membership = feedback()
        wrong_membership["decisions"][0]["criterion_id"] = "general-advice-1"
        for index, invalid in enumerate([{"not_a_proposal": True}, wrong_membership]):
            with self.subTest(invalid=invalid):
                self.provider.add("evaluate", invalid)
                self.add_evaluation()
                with patch.dict("os.environ", {"EVALUATION_REPAIR_ATTEMPTS": "1"}):
                    result = self.submit(attempt, request=f"schema-repair-{index}")
                self.assertEqual(result["status"], "needs_revision")
                audit = [event for event in self.service.review_export()["events"] if event["operation"] == "evaluate"][-1]["detail"]
                self.assertEqual(audit["rounds"][0]["proposal"], invalid)
                self.assertEqual(audit["rounds"][0]["code"], "invalid_model_response")
                self.assertEqual(audit["rounds"][1]["status"], "completed")
                self.assertEqual(audit["criteria_version"], self.snapshot(attempt["attempt_id"])["criteria_version"])


if __name__ == "__main__":
    unittest.main()
