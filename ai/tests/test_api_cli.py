"""작성: rootkit · 2026-10-23. HTTP auth boundaries and executable CLI workflows."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.cli import main
from app.main import create_app
from app.service import Service
from app.storage import Storage
from tests.helpers import FIXTURES, ScriptedProvider, catalog, catalog_review, documents, facts, feedback, knowledge, semantics


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = Storage(Path(self.directory.name) / "test.sqlite3")
        self.provider = ScriptedProvider()
        self.service = Service(self.storage, self.provider)
        self.environment = patch.dict("os.environ", {"AI_API_TOKEN": "test-internal-token"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = TestClient(create_app(self.service))
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer test-internal-token"}

    def queue_catalog(self, label="a", passed=True):
        self.provider.add("extract_knowledge", knowledge(label))
        self.provider.add("generate_catalog", catalog(label))
        self.provider.add("review_catalog", catalog_review(label, passed))

    def activate(self):
        self.queue_catalog()
        self.service.import_dataset("A", documents())
        self.service.extract_knowledge("A", 1)
        created = self.service.generate_catalog("A", 1)
        self.service.review_catalog(created["catalog_id"])
        self.service.activate_catalog(created["catalog_id"])

    def cli(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(list(arguments), service=self.service)
        return code, json.loads(output.getvalue() or error.getvalue())

    def test_internal_endpoints_require_bearer_authentication(self):
        endpoints = [
            ("POST", "/api/v1/attempts", {"user_id": "alice", "stage": 2}),
            ("GET", "/api/v1/attempts/unknown?user_id=alice", None),
            ("GET", "/api/v1/history?user_id=alice", None),
            ("POST", "/api/v1/evaluations", {"user_id": "alice", "attempt_id": "unknown", "request_id": "r1", "answer": {"subject": "검토 요청", "body": "가상 답안"}}),
        ]
        for method, endpoint, body in endpoints:
            for headers in [{}, {"Authorization": "Bearer wrong-token"}]:
                with self.subTest(endpoint=endpoint, headers=headers):
                    response = self.client.request(method, endpoint, headers=headers, json=body)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json()["code"], "unauthorized")

    def test_missing_token_configuration_is_not_reported_as_an_unauthenticated_success(self):
        with patch.dict("os.environ", {"AI_API_TOKEN": ""}):
            response = self.client.post("/api/v1/attempts", headers=self.headers, json={"user_id": "alice", "stage": 2})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "service_not_configured")
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_api_ownership_retry_conflict_and_public_response_shapes(self):
        self.activate()
        response = self.client.post("/api/v1/attempts", headers=self.headers, json={"user_id": "alice", "stage": 2})
        self.assertEqual(response.status_code, 200)
        attempt = response.json()
        self.assertNotIn("criteria", attempt["exercise"])
        self.assertNotIn("reviews", attempt["exercise"])
        self.assertNotIn("knowledge", attempt)
        attempt_id = attempt["attempt_id"]
        self.assertEqual(self.client.get(f"/api/v1/attempts/{attempt_id}?user_id=mallory", headers=self.headers).status_code, 404)
        submission = {"user_id": "alice", "attempt_id": attempt_id, "request_id": "api-retry", "answer": {"subject": "검토 요청", "body": "출고 준비표를 검토해 주세요."}}
        self.assertEqual(self.client.post("/api/v1/evaluations", headers=self.headers, json={**submission, "user_id": "mallory"}).status_code, 404)
        self.provider.add("evaluate", feedback())
        self.provider.add("review_feedback_semantics", semantics())
        self.provider.add("review_feedback_facts", facts())
        first = self.client.post("/api/v1/evaluations", headers=self.headers, json=submission)
        self.assertEqual(first.status_code, 200)
        self.assertIsNone(first.json()["total"])
        self.assertEqual(first.json()["status"], "needs_revision")
        self.assertEqual(self.client.post("/api/v1/evaluations", headers=self.headers, json=submission).json(), first.json())
        self.assertEqual(self.provider.count("evaluate"), 1)
        submission["answer"]["body"] = "다른 답안"
        conflict = self.client.post("/api/v1/evaluations", headers=self.headers, json=submission)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "request_conflict")
        self.assertEqual(self.client.get("/api/v1/history?user_id=mallory", headers=self.headers).json(), {"items": []})
        history = self.client.get("/api/v1/history?user_id=alice", headers=self.headers).json()
        self.assertEqual(history["items"][0]["attempt_id"], attempt_id)
        self.assertNotIn("criteria", history["items"][0]["exercise"])

    def test_client_supplied_criteria_approval_and_review_fields_are_rejected(self):
        for extra in [{"criteria": []}, {"approved": True}, {"review_status": "passed"}, {"dataset_id": "B"}]:
            response = self.client.post("/api/v1/attempts", headers=self.headers, json={"user_id": "alice", "stage": 2, **extra})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), {"error": "Invalid request fields", "code": "invalid_input"})
        self.assertEqual(self.provider.calls, [])

    def test_cli_registration_approval_catalog_review_activation_and_export(self):
        code, imported = self.cli("import", "--dataset", "A", "--file", str(FIXTURES / "dataset-a.jsonl"))
        self.assertEqual(code, 0)
        self.assertEqual(imported["version"], 1)
        self.provider.add("extract_knowledge", knowledge())
        self.assertEqual(self.cli("terms", "extract", "--dataset", "A", "--version", "1")[0], 0)
        code, candidate = self.cli("terms", "list", "--dataset", "A", "--version", "1")
        self.assertFalse(candidate["terms"][0]["approved"])
        code, approved = self.cli("terms", "approve", "--dataset", "A", "--version", "1", "--term-id", "a-term", "--alias", "검토표")
        self.assertEqual(code, 0)
        self.assertEqual(approved["approved_aliases"], ["검토표"])
        self.provider.add("generate_catalog", catalog())
        code, created = self.cli("catalog", "generate", "--dataset", "A", "--version", "1")
        self.assertEqual(code, 0)
        catalog_id = created["catalog_id"]
        self.assertEqual(self.cli("catalog", "activate", "--catalog", catalog_id)[0], 1)
        self.provider.add("review_catalog", catalog_review())
        self.assertEqual(self.cli("catalog", "review", "--catalog", catalog_id)[1]["passed_count"], 2)
        self.assertEqual(self.cli("catalog", "activate", "--catalog", catalog_id)[0], 0)
        self.assertEqual(self.cli("catalog", "show", "--catalog", catalog_id)[1]["status"], "reviewed")
        self.assertEqual(self.cli("status")[1]["active_catalog_id"], catalog_id)
        export = Path(self.directory.name) / "review.json"
        self.assertEqual(self.cli("reviews", "export", "--output", str(export))[0], 0)
        saved = json.loads(export.read_text())
        self.assertEqual(saved["active_catalog_id"], catalog_id)
        self.assertTrue(saved["datasets"][0]["documents"])
        self.assertTrue(saved["catalogs"][0]["snapshot"]["reviews"])

    def test_cli_replace_failure_preserves_a_then_success_activates_b(self):
        self.activate()
        active_a = self.cli("status")[1]["active_catalog_id"]
        self.queue_catalog("b", passed=False)
        code, failure = self.cli("replace", "--dataset", "B", "--file", str(FIXTURES / "dataset-b.jsonl"))
        self.assertEqual(code, 1)
        self.assertEqual(failure["code"], "catalog_not_reviewed")
        self.assertEqual(self.cli("status")[1]["active_catalog_id"], active_a)
        self.queue_catalog("b")
        code, replaced = self.cli("replace", "--dataset", "B", "--file", str(FIXTURES / "dataset-b.jsonl"))
        self.assertEqual(code, 0)
        self.assertEqual(replaced["dataset_id"], "B")
        self.assertEqual(replaced["dataset_version"], 2)
        self.assertNotEqual(replaced["catalog_id"], active_a)

    def test_cli_append_and_failed_missing_configuration_are_executable_subprocesses(self):
        database = Path(self.directory.name) / "cli.sqlite3"
        command = [sys.executable, "-m", "app.cli", "--db", str(database)]
        environment = {**os.environ, "MODEL_API_KEY": "", "MODEL_NAME": "fixture-model"}
        root = Path(__file__).resolve().parents[1]
        imported = subprocess.run(command + ["import", "--dataset", "A", "--file", str(FIXTURES / "dataset-a.jsonl")], cwd=root, env=environment, capture_output=True, text=True)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(json.loads(imported.stdout)["document_count"], 5)
        appended = subprocess.run(command + ["append", "--dataset", "A", "--file", str(FIXTURES / "dataset-b.jsonl")], cwd=root, env=environment, capture_output=True, text=True)
        self.assertEqual(appended.returncode, 0, appended.stderr)
        self.assertEqual(json.loads(appended.stdout)["document_count"], 10)
        failed = subprocess.run(command + ["terms", "extract", "--dataset", "A", "--version", "2"], cwd=root, env=environment, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stderr)["code"], "model_not_configured")


if __name__ == "__main__":
    unittest.main()
