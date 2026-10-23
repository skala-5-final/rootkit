"""작성: rootkit · 2026-10-23. Staged catalogs and display-time pinned evaluation."""

import json
import os
import secrets
import uuid
from contextlib import closing, nullcontext

from pydantic import ValidationError

from .errors import DomainError, ModelError
from .guards import (emitted_feedback, exercise_errors, feedback_review_errors,
                     validate_decisions)
from .knowledge import approved_knowledge, retrieve, validate_documents, validate_knowledge
from .models import (Answer, CatalogProposal, CatalogReview, Document, EvaluationProposal,
                     EvaluationResult, FactsReview, KnowledgeProposal, SemanticReview)
from .prompts import PRINCIPLES_VERSION, SCHEMAS
from .provider import HTTPProvider
from .storage import Storage, dump


DISPLAY_FIELDS = ("id", "version", "dataset_id", "dataset_version", "stage", "language",
                  "recipient_group", "title", "scenario", "requirements", "facts", "original",
                  "subject", "recipient", "source_ids")


def display(attempt_id: str, snapshot: dict) -> dict:
    return {"attempt_id": attempt_id,
            "exercise": {field: snapshot["exercise"][field] for field in DISPLAY_FIELDS}}


class Service:
    def __init__(self, storage: Storage, provider=None):
        self.storage = storage
        self.provider = provider or HTTPProvider()

    def _model(self, task: str, payload: dict, audit: dict | None = None):
        try:
            response = self.provider.complete(task, payload)
            if audit is not None:
                key = {"evaluate": "proposal", "review_feedback_semantics": "semantic_review",
                       "review_feedback_facts": "facts_review"}.get(task, task)
                audit[key] = response
            return SCHEMAS[task].model_validate(response)
        except DomainError:
            raise
        except ValidationError as exc:
            if audit is not None:
                audit.setdefault("schema_errors", {})[task] = [
                    {"location": list(error["loc"]), "type": error["type"], "message": error["msg"]}
                    for error in exc.errors(include_input=False, include_context=False)
                ]
            raise ModelError(f"Invalid AI response schema for {task}", "invalid_model_response") from exc
        except Exception as exc:
            raise ModelError(f"AI job failed: {task}") from exc

    def _dataset(self, dataset_id: str, version: int) -> dict:
        with closing(self.storage.connect()) as conn:
            row = conn.execute("SELECT * FROM datasets WHERE dataset_id=? AND version=?", (dataset_id, version)).fetchone()
        if not row:
            raise DomainError("Dataset revision not found", "not_found", 404)
        return {"dataset_id": dataset_id, "version": version,
                "documents": json.loads(row["documents"]), "knowledge": json.loads(row["knowledge"]),
                "term_version": row["term_version"]}

    def import_dataset(self, dataset_id: str, documents: list[Document], mode: str = "replace") -> dict:
        if not dataset_id.strip() or len(dataset_id) > 200 or mode not in {"replace", "append"}:
            raise DomainError("Dataset ID and import mode are invalid")
        documents = [Document.model_validate(document) for document in documents]
        validate_documents(documents)
        with self.storage.transaction() as conn:
            previous = conn.execute("SELECT * FROM datasets WHERE dataset_id=? ORDER BY version DESC LIMIT 1", (dataset_id,)).fetchone()
            version = previous["version"] + 1 if previous else 1
            if mode == "append":
                if not previous:
                    raise DomainError("Append requires an existing dataset", "not_found", 404)
                documents = [Document.model_validate(doc) for doc in json.loads(previous["documents"])] + documents
                validate_documents(documents)
            conn.execute("INSERT INTO datasets(dataset_id,version,documents) VALUES(?,?,?)",
                         (dataset_id, version, dump([document.model_dump() for document in documents])))
            conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                         ("import", f"{dataset_id}:{version}", "completed", dump({"mode": mode, "count": len(documents)})))
        return {"dataset_id": dataset_id, "version": version, "document_count": len(documents), "mode": mode}

    def extract_knowledge(self, dataset_id: str, version: int) -> dict:
        revision = self._dataset(dataset_id, version)
        try:
            proposal: KnowledgeProposal = self._model("extract_knowledge", revision)
            knowledge = validate_knowledge(proposal, [Document.model_validate(doc) for doc in revision["documents"]])
            with self.storage.transaction() as conn:
                # Re-extraction resets approvals; old catalogs/attempts keep their snapshots.
                conn.execute("UPDATE datasets SET knowledge=?, term_version=term_version+1 WHERE dataset_id=? AND version=?",
                             (dump(knowledge), dataset_id, version))
            self.storage.event("extract_knowledge", f"{dataset_id}:{version}", "completed", knowledge)
            return knowledge
        except DomainError as exc:
            self.storage.event("extract_knowledge", f"{dataset_id}:{version}", "failed", {"reason": str(exc), "code": exc.code})
            raise

    def approve_term(self, dataset_id: str, version: int, term_id: str, aliases: list[str] | None = None) -> dict:
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT knowledge FROM datasets WHERE dataset_id=? AND version=?", (dataset_id, version)).fetchone()
            if not row:
                raise DomainError("Dataset revision not found", "not_found", 404)
            knowledge = json.loads(row["knowledge"])
            term = next((term for term in knowledge.get("terms", []) if term["id"] == term_id), None)
            if not term:
                raise DomainError("Term candidate not found in this dataset revision", "not_found", 404)
            term["approved"] = True
            term["approved_aliases"] = sorted({alias.strip() for alias in aliases or [] if alias.strip()})
            conn.execute("UPDATE datasets SET knowledge=?, term_version=term_version+1 WHERE dataset_id=? AND version=?",
                         (dump(knowledge), dataset_id, version))
            conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                         ("approve_term", f"{dataset_id}:{version}:{term_id}", "completed", dump(term)))
        return term

    def _new_catalog_snapshot(self, dataset_id: str, version: int, provenance: str) -> dict:
        revision = self._dataset(dataset_id, version)
        if not revision["knowledge"] and provenance != "manual":
            raise DomainError("Extract company knowledge before generating a catalog", "knowledge_not_ready", 409)
        catalog_id = str(uuid.uuid4())
        return {
            "dataset_id": dataset_id, "dataset_version": version,
            "corpus_version": f"{dataset_id}:{version}", "term_version": revision["term_version"],
            "criteria_version": catalog_id, "catalog_id": catalog_id,
            "principles_version": PRINCIPLES_VERSION, "documents": revision["documents"],
            "knowledge": approved_knowledge(revision["knowledge"]),
            "provenance": provenance,
            "exercises": [], "guard_errors": {}, "reviews": [], "passed_ids": [],
        }

    def _stage_catalog(self, snapshot: dict, proposal: CatalogProposal, operation: str) -> dict:
        catalog_id = snapshot["catalog_id"]
        dataset_id = snapshot["dataset_id"]
        version = snapshot["dataset_version"]
        ids = [exercise.id for exercise in proposal.exercises]
        if len(ids) != len(set(ids)):
            if snapshot["provenance"] == "manual":
                raise DomainError("Imported exercise IDs must be unique", "invalid_input", 422)
            raise ModelError("Generated exercise IDs must be unique", "invalid_model_response")
        for exercise in proposal.exercises:
            snapshot["guard_errors"][exercise.id] = exercise_errors(exercise, snapshot["documents"], snapshot["knowledge"])
            snapshot["exercises"].append({**exercise.model_dump(), "version": 1,
                                          "dataset_id": dataset_id, "dataset_version": version})
        with self.storage.transaction() as conn:
            generation = conn.execute("SELECT COUNT(*) FROM catalogs WHERE dataset_id=?", (dataset_id,)).fetchone()[0] + 1
            snapshot["catalog_version"] = generation
            for exercise in snapshot["exercises"]:
                exercise["version"] = generation
            conn.execute("INSERT INTO catalogs(id,dataset_id,dataset_version,status,snapshot) VALUES(?,?,?,?,?)",
                         (catalog_id, dataset_id, version, "generated", dump(snapshot)))
            conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                         (operation, catalog_id, "completed", dump({"dataset_id": dataset_id, "version": version,
                                                                    "provenance": snapshot["provenance"]})))
        return {"catalog_id": catalog_id, "status": "generated", "dataset_id": dataset_id,
                "dataset_version": version, "exercise_count": len(snapshot["exercises"])}

    def _catalog_failure(self, snapshot: dict, operation: str, exc: DomainError):
        snapshot["failure"] = {"reason": str(exc), "code": exc.code}
        with self.storage.transaction() as conn:
            conn.execute("INSERT INTO catalogs(id,dataset_id,dataset_version,status,snapshot) VALUES(?,?,?,?,?)",
                         (snapshot["catalog_id"], snapshot["dataset_id"], snapshot["dataset_version"], "failed", dump(snapshot)))
        self.storage.event(operation, snapshot["catalog_id"], "failed", snapshot["failure"])

    def generate_catalog(self, dataset_id: str, version: int) -> dict:
        snapshot = self._new_catalog_snapshot(dataset_id, version, "model")
        try:
            proposal: CatalogProposal = self._model("generate_catalog", snapshot)
            return self._stage_catalog(snapshot, proposal, "generate_catalog")
        except DomainError as exc:
            self._catalog_failure(snapshot, "generate_catalog", exc)
            raise

    def import_catalog(self, dataset_id: str, version: int, proposal: CatalogProposal | dict) -> dict:
        snapshot = self._new_catalog_snapshot(dataset_id, version, "manual")
        try:
            try:
                if isinstance(proposal, CatalogProposal):
                    proposal = proposal.model_dump()
                proposal = CatalogProposal.model_validate(proposal)
            except ValidationError as exc:
                raise DomainError("Imported catalog does not match the CatalogProposal schema", "invalid_input", 422) from exc
            # Manual content is staged only; it follows the same independent review and activation.
            return self._stage_catalog(snapshot, proposal, "import_catalog")
        except DomainError as exc:
            self._catalog_failure(snapshot, "import_catalog", exc)
            raise

    def _catalog(self, catalog_id: str) -> tuple[str, dict]:
        with closing(self.storage.connect()) as conn:
            row = conn.execute("SELECT * FROM catalogs WHERE id=?", (catalog_id,)).fetchone()
        if not row:
            raise DomainError("Catalog not found", "not_found", 404)
        return row["status"], json.loads(row["snapshot"])

    def review_catalog(self, catalog_id: str) -> dict:
        state, snapshot = self._catalog(catalog_id)
        if state != "generated":
            raise DomainError("Only a newly generated catalog can be reviewed", "catalog_state_conflict", 409)
        try:
            review: CatalogReview = self._model("review_catalog", snapshot)
            ids = [entry.exercise_id for entry in review.reviews]
            expected = {exercise["id"] for exercise in snapshot["exercises"]}
            if len(ids) != len(set(ids)) or set(ids) != expected:
                raise ModelError("Catalog review must cover every exercise exactly once", "invalid_model_response")
            for entry in review.reviews:
                deterministic_errors = snapshot["guard_errors"].get(entry.exercise_id, [])
                if deterministic_errors:
                    entry.passed = False
                    entry.reasons.extend(deterministic_errors)
                elif not entry.passed and not entry.reasons:
                    entry.reasons.append("Independent AI review rejected this exercise")
            snapshot["reviews"] = [entry.model_dump() for entry in review.reviews]
            snapshot["passed_ids"] = [entry.exercise_id for entry in review.reviews if entry.passed]
            status = "reviewed" if snapshot["passed_ids"] else "rejected"
            with self.storage.transaction() as conn:
                changed = conn.execute("UPDATE catalogs SET status=?,snapshot=? WHERE id=? AND status='generated'",
                                       (status, dump(snapshot), catalog_id)).rowcount
                if not changed:
                    raise DomainError("Catalog state changed during review", "catalog_state_conflict", 409)
            self.storage.event("review_catalog", catalog_id, status, snapshot["reviews"])
            return {"catalog_id": catalog_id, "status": status, "passed_count": len(snapshot["passed_ids"]),
                    "reviews": snapshot["reviews"]}
        except DomainError as exc:
            with self.storage.transaction() as conn:
                snapshot["failure"] = {"reason": str(exc), "code": exc.code}
                conn.execute("UPDATE catalogs SET status='failed',snapshot=? WHERE id=? AND status='generated'",
                             (dump(snapshot), catalog_id))
            self.storage.event("review_catalog", catalog_id, "failed", {"reason": str(exc), "code": exc.code})
            raise

    def activate_catalog(self, catalog_id: str) -> dict:
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT status,snapshot FROM catalogs WHERE id=?", (catalog_id,)).fetchone()
            if not row:
                raise DomainError("Catalog not found", "not_found", 404)
            snapshot = json.loads(row["snapshot"])
            if row["status"] != "reviewed" or not snapshot["passed_ids"]:
                raise DomainError("Only a nonempty independently reviewed catalog can be activated", "catalog_not_reviewed", 409)
            conn.execute("INSERT INTO active_catalog(singleton,catalog_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET catalog_id=excluded.catalog_id",
                         (catalog_id,))
            conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                         ("activate_catalog", catalog_id, "completed", dump({"dataset_id": snapshot["dataset_id"], "version": snapshot["dataset_version"]})))
        return {"catalog_id": catalog_id, "status": "active", "dataset_id": snapshot["dataset_id"],
                "dataset_version": snapshot["dataset_version"], "exercise_count": len(snapshot["passed_ids"])}

    def start_attempt(self, user_id: str, stage: int) -> dict:
        if not user_id or stage not in {1, 2}:
            raise DomainError("A user and STEP 1 or STEP 2 are required")
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT c.snapshot FROM active_catalog a JOIN catalogs c ON a.catalog_id=c.id WHERE a.singleton=1").fetchone()
            if not row:
                raise DomainError("No reviewed catalog is active. Import, generate, review and activate a dataset first.", "no_active_catalog", 503)
            catalog = json.loads(row["snapshot"])
            eligible = [exercise for exercise in catalog["exercises"]
                        if exercise["id"] in catalog["passed_ids"] and exercise["stage"] == stage]
            if not eligible:
                raise DomainError("The active catalog has no reviewed exercises for this step", "no_exercises", 409)
            exercise = secrets.choice(eligible)
            # Pin everything before returning the question, including the first submission.
            snapshot = {key: value for key, value in catalog.items()
                        if key not in {"exercises", "guard_errors", "reviews", "passed_ids"}}
            snapshot["exercise"] = exercise
            attempt_id = str(uuid.uuid4())
            conn.execute("INSERT INTO attempts(id,user_id,snapshot) VALUES(?,?,?)", (attempt_id, user_id, dump(snapshot)))
        return display(attempt_id, snapshot)

    @staticmethod
    def _owned_attempt(conn, attempt_id: str, user_id: str) -> dict:
        row = conn.execute("SELECT snapshot FROM attempts WHERE id=? AND user_id=?", (attempt_id, user_id)).fetchone()
        if not row:
            raise DomainError("Attempt not found", "not_found", 404)
        return json.loads(row["snapshot"])

    def get_attempt(self, attempt_id: str, user_id: str) -> dict:
        with closing(self.storage.connect()) as conn:
            snapshot = self._owned_attempt(conn, attempt_id, user_id)
        return display(attempt_id, snapshot)

    def _evaluation_round(self, context: dict, audit: dict, repair: dict | None = None):
        payload = {**context, **({"repair": repair} if repair else {})}
        proposal: EvaluationProposal = self._model("evaluate", payload, audit)
        errors = validate_decisions(context["exercise"], proposal)
        if errors:
            raise ModelError("; ".join(errors), "invalid_model_response")
        feedback = emitted_feedback(context["exercise"], proposal)
        audit["proposed_feedback"] = [item.model_dump() for item in feedback]
        exercise = context["exercise"]
        disclosed = {key: exercise[key] for key in
                     ("scenario", "requirements", "facts", "recipient", "recipient_group", "language")}
        proposed = {decision.criterion_id: decision.model_dump() for decision in proposal.decisions}
        reference_keys = {"defect", "correction", "reference_text"}
        semantic_context = {
            "review_target": "AI feedback quality, not whether the learner answer is correct",
            "learner_answer": context["answer"], "disclosed_exercise": disclosed,
            "criterion_checks": [
                {"criterion": {key: value for key, value in criterion.items() if key not in reference_keys},
                 "reference": {key: criterion[key] for key in reference_keys},
                 "proposed_decision": proposed[criterion["criterion_id"]]}
                for criterion in exercise["criteria"]
            ],
            "feedback_to_verify": audit["proposed_feedback"],
            "expected_criterion_ids": context["expected_criterion_ids"],
            "approved_knowledge": context["knowledge"], "relevant_source_documents": context["documents"],
        }
        # Fact reviewers see only the proposed corrections, never the answer or its defects.
        fact_context = {
            "review_target": "factual accuracy of suggested replacement wording only",
            "disclosed_exercise": disclosed, "approved_knowledge": context["knowledge"],
            "relevant_source_documents": context["documents"],
            "emitted_feedback_ids": [item.criterion_id for item in feedback],
            "feedback_to_verify": [{key: value for key, value in item.items() if key != "explanation"}
                                   for item in audit["proposed_feedback"]],
        }
        semantics: SemanticReview = self._model("review_feedback_semantics", semantic_context, audit)
        facts: FactsReview = self._model("review_feedback_facts", fact_context, audit)
        errors = feedback_review_errors(proposal, semantics, facts, feedback, answer=context["answer"])
        return proposal, feedback, errors

    def evaluate(self, user_id: str, attempt_id: str, request_id: str, answer: Answer) -> dict:
        answer = Answer.model_validate(answer)
        if not request_id or len(request_id) > 200:
            raise DomainError("request_id must contain 1 to 200 characters")
        canonical_answer = dump(answer.model_dump())
        # Bind the ID to its answer durably even if the later model transaction fails.
        with self.storage.transaction() as conn:
            self._owned_attempt(conn, attempt_id, user_id)
            binding = conn.execute("SELECT answer FROM evaluation_requests WHERE attempt_id=? AND request_id=?",
                                   (attempt_id, request_id)).fetchone()
            if binding and binding["answer"] != canonical_answer:
                raise DomainError("The same request ID was already used with a different answer", "request_conflict", 409)
            if not binding:
                conn.execute("INSERT INTO evaluation_requests(attempt_id,request_id,answer) VALUES(?,?,?)",
                             (attempt_id, request_id, canonical_answer))
        rounds, model_calls = [], []
        snapshot = None
        try:
            # One SQLite writer owns this request through all model calls. This deliberately
            # serializes MVP evaluations across processes and survives restart without leases.
            with self.storage.transaction() as conn:
                snapshot = self._owned_attempt(conn, attempt_id, user_id)
                existing = conn.execute("SELECT answer,result FROM submissions WHERE attempt_id=? AND request_id=?",
                                        (attempt_id, request_id)).fetchone()
                if existing:
                    if existing["answer"] != canonical_answer:
                        raise DomainError("The same request ID was already used with a different answer", "request_conflict", 409)
                    return json.loads(existing["result"])
                evidence_ids = set(snapshot["exercise"]["source_ids"])
                for criterion in snapshot["exercise"]["criteria"]:
                    evidence_ids.update(criterion["evidence_ids"])
                context = {**snapshot, "documents": retrieve(snapshot["documents"], list(evidence_ids)),
                           "answer": answer.model_dump(), "evaluation_target": "answer",
                           "expected_criterion_ids": [criterion["criterion_id"] for criterion in snapshot["exercise"]["criteria"]]}
                try:
                    repairs = min(1, max(0, int(os.environ.get("EVALUATION_REPAIR_ATTEMPTS", "1"))))
                except ValueError:
                    repairs = 1
                budget = self.provider.evaluation_budget() if hasattr(self.provider, "evaluation_budget") else nullcontext([])
                with budget as model_calls:
                    repair = None
                    for index in range(repairs + 1):
                        audit = {"round": index, "errors": []}
                        rounds.append(audit)
                        try:
                            proposal, feedback, errors = self._evaluation_round(context, audit, repair)
                            audit.update(errors=errors, status="rejected" if errors else "completed")
                        except DomainError as exc:
                            audit.update(errors=[str(exc)], status="failed", code=exc.code)
                            if exc.code != "invalid_model_response" or index >= repairs:
                                raise
                            errors = audit["errors"]
                        if not errors:
                            break
                        repair = {"round": index + 1, "review_failure_reasons": errors,
                                  "schema_errors": audit.get("schema_errors", {}),
                                  "previous_proposal": audit.get("proposal"),
                                  "previous_semantic_review": audit.get("semantic_review"),
                                  "previous_facts_review": audit.get("facts_review")}
                if errors:
                    result = EvaluationResult(attempt_id=attempt_id, request_id=request_id,
                                              status="insufficient_evidence",
                                              summary="AI 피드백과 검토 결과가 일치하지 않아 평가를 확정하지 못했습니다. 답안이 틀렸다는 뜻은 아닙니다. 재평가를 요청해 주세요.",
                                              feedback=[])
                else:
                    result = EvaluationResult(attempt_id=attempt_id, request_id=request_id,
                                              status="needs_revision" if any(item.category != "general" for item in feedback) else "match",
                                              summary=proposal.summary, feedback=feedback)
                conn.execute("INSERT INTO submissions(attempt_id,request_id,answer,result) VALUES(?,?,?,?)",
                             (attempt_id, request_id, canonical_answer, dump(result.model_dump())))
                conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                             ("evaluate", f"{attempt_id}:{request_id}", "rejected" if errors else "completed",
                              dump({"reasons": errors, "answer": answer.model_dump(), "proposal": proposal.model_dump(),
                                    "proposed_feedback": [item.model_dump() for item in feedback],
                                    "corpus_version": snapshot["corpus_version"], "term_version": snapshot["term_version"],
                                    "criteria_version": snapshot["criteria_version"],
                                    "evaluation_principles_version": PRINCIPLES_VERSION,
                                    "semantic_review": rounds[-1].get("semantic_review"), "facts_review": rounds[-1].get("facts_review"),
                                    "rounds": rounds, "model_calls": model_calls})))
                return result.model_dump()
        except DomainError as exc:
            if exc.status_code >= 500:
                self.storage.event("evaluate", f"{attempt_id}:{request_id}", "failed",
                                   {"reason": str(exc), "code": exc.code, "answer": answer.model_dump(),
                                    "rounds": rounds, "model_calls": model_calls,
                                    "evaluation_principles_version": PRINCIPLES_VERSION,
                                    **({key: snapshot[key] for key in ("corpus_version", "term_version", "criteria_version")}
                                       if snapshot else {})})
            raise

    def history(self, user_id: str) -> dict:
        with closing(self.storage.connect()) as conn:
            attempts = conn.execute("SELECT id,snapshot,created_at FROM attempts WHERE user_id=? ORDER BY created_at DESC,rowid DESC", (user_id,)).fetchall()
            items = []
            for attempt in attempts:
                submissions = conn.execute("SELECT * FROM submissions WHERE attempt_id=? ORDER BY created_at,rowid", (attempt["id"],)).fetchall()
                item = display(attempt["id"], json.loads(attempt["snapshot"]))
                item["submissions"] = [{"request_id": row["request_id"], "answer": json.loads(row["answer"]),
                                        "result": json.loads(row["result"]), "created_at": row["created_at"]} for row in submissions]
                items.append(item)
        return {"items": items}

    def review_export(self) -> dict:
        with closing(self.storage.connect()) as conn:
            datasets = [{"dataset_id": row["dataset_id"], "version": row["version"], "term_version": row["term_version"],
                         "documents": json.loads(row["documents"]), "knowledge": json.loads(row["knowledge"])}
                        for row in conn.execute("SELECT * FROM datasets ORDER BY dataset_id,version")]
            catalogs = [{"catalog_id": row["id"], "status": row["status"], "snapshot": json.loads(row["snapshot"])}
                        for row in conn.execute("SELECT * FROM catalogs ORDER BY created_at")]
            events = [{**dict(row), "detail": json.loads(row["detail"])} for row in conn.execute("SELECT * FROM events ORDER BY id")]
            attempts = [{"attempt_id": row["id"], "user_id": row["user_id"], "created_at": row["created_at"],
                         "snapshot": json.loads(row["snapshot"])} for row in conn.execute("SELECT * FROM attempts ORDER BY created_at")]
            submissions = [{**dict(row), "answer": json.loads(row["answer"]), "result": json.loads(row["result"])}
                           for row in conn.execute("SELECT * FROM submissions ORDER BY created_at")]
            requests = [{**dict(row), "answer": json.loads(row["answer"])}
                        for row in conn.execute("SELECT * FROM evaluation_requests ORDER BY created_at")]
            active = conn.execute("SELECT catalog_id FROM active_catalog WHERE singleton=1").fetchone()
        return {"active_catalog_id": active["catalog_id"] if active else None,
                "datasets": datasets, "catalogs": catalogs, "events": events,
                "attempts": attempts, "submissions": submissions, "evaluation_requests": requests}
