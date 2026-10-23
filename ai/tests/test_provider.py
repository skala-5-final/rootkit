"""작성: rootkit · 2026-10-23. Provider transport failures must never become fake success."""

from io import BytesIO
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from app.errors import ModelError
from app.provider import HTTPProvider, NoRedirect, evaluation_budget, strict_schema
from app.prompts import SCHEMAS
from tests.helpers import catalog, catalog_review, facts, feedback, knowledge, semantics


def response(value):
    return BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}).encode())


def http_error(status):
    return urllib.error.HTTPError("https://model.invalid", status, "synthetic failure", {}, BytesIO(b"private-provider-error"))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {
            "MODEL_API_KEY": "test-only-key", "MODEL_NAME": "test-only-model",
            "MODEL_API_BASE_URL": "https://model.invalid/v1",
            "MODEL_GENERATION_NAME": "", "MODEL_EVALUATION_NAME": "", "MODEL_REVIEW_NAME": "",
            "MODEL_EVALUATION_REASONING_EFFORT": "", "MODEL_REVIEW_REASONING_EFFORT": "",
            "MODEL_FALLBACK_NAME": "", "MODEL_RESPONSE_FORMAT": "json_object", "MODEL_TEMPERATURE": "",
            "MODEL_TIMEOUT_SECONDS": "25", "MODEL_CATALOG_TIMEOUT_SECONDS": "90",
            "MODEL_MAX_RETRIES": "1", "EVALUATION_TIMEOUT_SECONDS": "120",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.provider = HTTPProvider()

    def test_missing_api_key_and_model_are_explicit_configuration_errors(self):
        for values in [{"MODEL_API_KEY": ""}, {"MODEL_API_KEY": "change-me"}, {"MODEL_NAME": ""}]:
            with self.subTest(values=values), patch.dict("os.environ", values), patch("urllib.request.build_opener") as transport:
                with self.assertRaises(ModelError) as failure:
                    self.provider.complete("extract_knowledge", {})
                self.assertEqual(failure.exception.code, "model_not_configured")
                transport.assert_not_called()

    def test_json_payload_and_schema_are_sent_to_the_configured_provider(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"terms":[],"patterns":[]}'}}]}
        transport = MagicMock()
        transport.open.return_value = BytesIO(json.dumps(response).encode())
        with patch("urllib.request.build_opener", return_value=transport) as factory:
            result = self.provider.complete("extract_knowledge", {"documents": [{"body": "가상 자료"}]})
        self.assertEqual(result, {"terms": [], "patterns": []})
        self.assertIsInstance(factory.call_args.args[0], NoRedirect)
        request = transport.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://model.invalid/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "test-only-model")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", payload)
        self.assertIn("Required JSON Schema", payload["messages"][0]["content"])
        self.assertEqual(json.loads(payload["messages"][1]["content"])["documents"][0]["body"], "가상 자료")

    def test_http_timeout_and_invalid_responses_fail_without_exposing_provider_body(self):
        failures = [
            urllib.error.HTTPError("https://model.invalid", 429, "rate limited", {}, BytesIO(b"secret-user-input")),
            urllib.error.URLError("connection unavailable"), TimeoutError(),
        ]
        for error in failures:
            transport = MagicMock()
            transport.open.side_effect = error
            with self.subTest(error=error), patch("urllib.request.build_opener", return_value=transport):
                with self.assertRaises(ModelError) as failure:
                    self.provider.complete("extract_knowledge", {})
                self.assertNotIn("secret-user-input", str(failure.exception))
                self.assertEqual(failure.exception.status_code, 503)
            if isinstance(error, urllib.error.HTTPError):
                error.close()
        for envelope in [b"invalid json", b'{"choices":[]}',
                         b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}',
                         b'{"choices":[{"finish_reason":"stop","message":{"content":"[]"}}]}']:
            transport = MagicMock()
            transport.open.return_value = BytesIO(envelope)
            with self.subTest(envelope=envelope), patch("urllib.request.build_opener", return_value=transport):
                with self.assertRaises(ModelError):
                    self.provider.complete("extract_knowledge", {})

    def test_redirects_are_refused_before_forwarding_credentials_or_company_content(self):
        request = urllib.request.Request("https://model.invalid/v1/chat/completions", data=b"private fixture content", headers={"Authorization": "Bearer test-only-key"})
        handler = NoRedirect()
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status), self.assertRaises(urllib.error.HTTPError) as failure:
                handler.redirect_request(request, None, status, "redirect", {"Location": "https://other.invalid"}, "https://other.invalid")
            self.assertEqual(failure.exception.code, status)
            failure.exception.close()

    def test_task_specific_models_route_generation_evaluation_and_independent_review(self):
        configured = {"MODEL_GENERATION_NAME": "generator", "MODEL_EVALUATION_NAME": "evaluator", "MODEL_REVIEW_NAME": "reviewer"}
        tasks = {"extract_knowledge": (knowledge(), "generator"), "generate_catalog": (catalog(), "generator"),
                 "evaluate": (feedback(), "evaluator"), "review_catalog": (catalog_review(), "reviewer"),
                 "review_feedback_semantics": (semantics(), "reviewer"), "review_feedback_facts": (facts(), "reviewer")}
        with patch.dict("os.environ", configured):
            for task, (value, expected) in tasks.items():
                transport = MagicMock()
                transport.open.return_value = response(value)
                with self.subTest(task=task), patch("urllib.request.build_opener", return_value=transport):
                    self.assertEqual(self.provider.complete(task, {}), value)
                body = json.loads(transport.open.call_args.args[0].data)
                self.assertEqual(body["model"], expected)
                self.assertEqual(transport.open.call_args.kwargs["timeout"], 90 if task in {"generate_catalog", "review_catalog"} else 25)

    def test_strict_schema_requires_all_properties_and_preserves_nullable_fields(self):
        transport = MagicMock()
        transport.open.return_value = response(catalog())
        with patch.dict("os.environ", {"MODEL_RESPONSE_FORMAT": "json_schema", "MODEL_TEMPERATURE": "0"}), patch("urllib.request.build_opener", return_value=transport):
            self.provider.complete("generate_catalog", {})
        body = json.loads(transport.open.call_args.args[0].data)
        self.assertEqual(body["temperature"], 0)
        schema_format = body["response_format"]
        self.assertEqual(schema_format["type"], "json_schema")
        self.assertTrue(schema_format["json_schema"]["strict"])
        schema = schema_format["json_schema"]["schema"]

        def check(node):
            if isinstance(node, dict):
                self.assertNotIn("default", node)
                if node.get("type") == "object":
                    self.assertEqual(node["required"], list(node["properties"]))
                    self.assertIs(node["additionalProperties"], False)
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for item in node:
                    check(item)

        check(schema)
        self.assertIn({"type": "null"}, schema["$defs"]["ExerciseDraft"]["properties"]["original"]["anyOf"])
        self.assertIn("default", SCHEMAS["generate_catalog"].model_json_schema()["$defs"]["ExerciseDraft"]["properties"]["original"])
        field_named_default = {"type": "object", "properties": {"default": {"type": "string", "default": "value"}}}
        self.assertIn("default", strict_schema(field_named_default)["properties"])

    def test_invalid_settings_fail_before_any_network_request(self):
        configurations = [{"MODEL_RESPONSE_FORMAT": "unexpected"}, {"MODEL_TEMPERATURE": "NaN"},
                          {"MODEL_TEMPERATURE": "-1"}, {"MODEL_TEMPERATURE": "2.1"},
                          {"MODEL_TIMEOUT_SECONDS": "0"}, {"MODEL_TIMEOUT_SECONDS": "61"},
                          {"MODEL_MAX_RETRIES": "2"}, {"MODEL_MAX_RETRIES": "0.5"},
                          {"MODEL_API_BASE_URL": "https://example.invalid?secret=query"}]
        for values in configurations:
            with self.subTest(values=values), patch.dict("os.environ", values), patch("urllib.request.build_opener") as network:
                with self.assertRaises(ModelError) as failure:
                    self.provider.complete("extract_knowledge", {})
                self.assertEqual(failure.exception.code, "model_not_configured")
                network.assert_not_called()
        for key, value in [("MODEL_CATALOG_TIMEOUT_SECONDS", "181"), ("EVALUATION_TIMEOUT_SECONDS", "181")]:
            with self.subTest(key=key), patch.dict("os.environ", {key: value}), self.assertRaises(ModelError):
                if key == "EVALUATION_TIMEOUT_SECONDS":
                    with evaluation_budget():
                        pass
                else:
                    self.provider.complete("generate_catalog", {})

    def test_auth_request_and_missing_model_http_errors_never_retry_or_fallback(self):
        for status in (400, 401, 403, 404):
            transport = MagicMock()
            transport.open.side_effect = http_error(status)
            with self.subTest(status=status), patch.dict("os.environ", {"MODEL_FALLBACK_NAME": "backup"}), patch("urllib.request.build_opener", return_value=transport), patch("app.provider.time.sleep") as sleep:
                with self.provider.evaluation_budget() as calls, self.assertRaises(ModelError):
                    self.provider.complete("extract_knowledge", {"body": "private-company-document"})
                self.assertEqual(transport.open.call_count, 1)
                self.assertEqual(len(calls), 1)
                sleep.assert_not_called()
                self.assertNotIn("test-only-key", json.dumps(calls))
                self.assertNotIn("private-company-document", json.dumps(calls))

    def test_transient_failure_retries_same_model_once_then_explicit_fallback_once(self):
        transport = MagicMock()
        transport.open.side_effect = [http_error(429), http_error(503), response(knowledge())]
        with patch.dict("os.environ", {"MODEL_FALLBACK_NAME": "backup"}), patch("urllib.request.build_opener", return_value=transport), patch("app.provider.time.sleep") as sleep:
            with self.provider.evaluation_budget() as calls:
                self.assertEqual(self.provider.complete("extract_knowledge", {}), knowledge())
        used = [json.loads(call.args[0].data)["model"] for call in transport.open.call_args_list]
        self.assertEqual(used, ["test-only-model", "test-only-model", "backup"])
        self.assertEqual([item["code"] for item in calls], ["model_rate_limited", "model_unavailable", None])
        self.assertEqual([item["attempt"] for item in calls], [1, 2, 3])
        self.assertTrue(all(call.args[0] <= 0.5 for call in sleep.call_args_list))
        self.assertTrue(all(set(item) == {"task", "model", "attempt", "outcome", "code", "duration_ms"} for item in calls))

    def test_all_transient_failures_are_bounded_and_retry_can_be_disabled(self):
        for settings, count in [({"MODEL_FALLBACK_NAME": "backup"}, 3), ({"MODEL_MAX_RETRIES": "0"}, 1), ({"MODEL_FALLBACK_NAME": "test-only-model"}, 2)]:
            transport = MagicMock()
            transport.open.side_effect = urllib.error.URLError("temporary network failure")
            with self.subTest(settings=settings), patch.dict("os.environ", settings), patch("urllib.request.build_opener", return_value=transport), patch("app.provider.time.sleep"):
                with self.assertRaises(ModelError) as failure:
                    self.provider.complete("extract_knowledge", {})
                self.assertEqual(failure.exception.code, "model_connection_error")
                self.assertEqual(transport.open.call_count, count)

    def test_invalid_json_schema_finish_or_refusal_never_trigger_fallback(self):
        cases = [
            (b"invalid JSON", "invalid_model_response"),
            (json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": '[]'}}]}).encode(), "invalid_model_response"),
            (json.dumps({"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]}).encode(), "invalid_model_response"),
            (json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "private refusal text"}}]}).encode(), "model_refusal"),
        ]
        for raw, code in cases:
            transport = MagicMock()
            transport.open.return_value = BytesIO(raw)
            with self.subTest(code=code, raw=raw), patch.dict("os.environ", {"MODEL_FALLBACK_NAME": "backup"}), patch("urllib.request.build_opener", return_value=transport):
                with self.assertRaises(ModelError) as failure:
                    self.provider.complete("extract_knowledge", {})
                self.assertEqual(failure.exception.code, code)
                self.assertEqual(transport.open.call_count, 1)
                self.assertNotIn("private refusal text", str(failure.exception))

    def test_review_rejection_is_returned_unchanged_without_retrying_for_approval(self):
        rejected = facts(False)
        transport = MagicMock()
        transport.open.return_value = response(rejected)
        with patch.dict("os.environ", {"MODEL_REVIEW_NAME": "reviewer", "MODEL_FALLBACK_NAME": "backup"}), patch("urllib.request.build_opener", return_value=transport):
            self.assertEqual(self.provider.complete("review_feedback_facts", {}), rejected)
        self.assertEqual(transport.open.call_count, 1)

    def test_explicit_role_reasoning_is_only_sent_to_corresponding_primary_model(self):
        settings = {"MODEL_EVALUATION_NAME": "gpt-5.4-mini", "MODEL_EVALUATION_REASONING_EFFORT": "medium",
                    "MODEL_REVIEW_NAME": "gpt-5.4-mini", "MODEL_REVIEW_REASONING_EFFORT": "high", "MODEL_FALLBACK_NAME": "gpt-4o-mini"}
        with patch.dict("os.environ", settings):
            for task, value in [("extract_knowledge", knowledge()), ("generate_catalog", catalog()), ("evaluate", feedback()),
                                ("review_catalog", catalog_review()), ("review_feedback_semantics", semantics()), ("review_feedback_facts", facts())]:
                transport = MagicMock()
                transport.open.return_value = response(value)
                with self.subTest(task=task), patch("urllib.request.build_opener", return_value=transport):
                    self.provider.complete(task, {})
                body = json.loads(transport.open.call_args.args[0].data)
                self.assertNotIn("temperature", body)
                if task.startswith("review_"):
                    self.assertEqual(body["reasoning_effort"], "high")
                elif task == "evaluate":
                    self.assertEqual(body["reasoning_effort"], "medium")
                else:
                    self.assertNotIn("reasoning_effort", body)
            for task, value, effort in [("evaluate", feedback(), "medium"), ("review_feedback_facts", facts(), "high")]:
                transport = MagicMock()
                transport.open.side_effect = [http_error(503), http_error(503), response(value)]
                with self.subTest(task=task), patch("urllib.request.build_opener", return_value=transport), patch("app.provider.time.sleep"):
                    self.provider.complete(task, {})
                bodies = [json.loads(call.args[0].data) for call in transport.open.call_args_list]
                self.assertEqual([body.get("reasoning_effort") for body in bodies], [effort, effort, None])
                self.assertEqual(bodies[-1]["model"], "gpt-4o-mini")

    def test_invalid_or_temperature_conflicting_role_reasoning_is_configuration_error(self):
        for task, key in [("evaluate", "MODEL_EVALUATION_REASONING_EFFORT"), ("review_feedback_semantics", "MODEL_REVIEW_REASONING_EFFORT")]:
            for settings in [{key: "unexpected"}, {key: "low", "MODEL_TEMPERATURE": "0"}]:
                with self.subTest(task=task, settings=settings), patch.dict("os.environ", settings), patch("urllib.request.build_opener") as network:
                    with self.assertRaises(ModelError) as failure:
                        self.provider.complete(task, {})
                    self.assertEqual(failure.exception.code, "model_not_configured")
                    network.assert_not_called()

    def test_evaluation_deadline_bounds_request_and_resets_context_after_timeout(self):
        clock = [0.0]
        transport = MagicMock()

        def slow_request(*args, **kwargs):
            clock[0] += 0.4
            raise TimeoutError()

        transport.open.side_effect = slow_request
        with patch.dict("os.environ", {"EVALUATION_TIMEOUT_SECONDS": "0.3", "MODEL_FALLBACK_NAME": "backup"}), patch("app.provider.time.monotonic", side_effect=lambda: clock[0]), patch("app.provider.time.sleep") as sleep, patch("urllib.request.build_opener", return_value=transport):
            with self.provider.evaluation_budget() as calls, self.assertRaises(ModelError) as failure:
                self.provider.complete("evaluate", {"private": "not traced"})
            self.assertEqual(failure.exception.code, "evaluation_timeout")
            self.assertEqual(transport.open.call_count, 1)
            self.assertLessEqual(transport.open.call_args.kwargs["timeout"], 0.3)
            self.assertEqual(calls[0]["code"], "evaluation_timeout")
            sleep.assert_not_called()
            transport.open.side_effect = None
            transport.open.return_value = response(knowledge())
            self.provider.complete("extract_knowledge", {})
            self.assertEqual(transport.open.call_args.kwargs["timeout"], 25)
            self.assertEqual(len(calls), 1)

    def test_deadline_is_shared_across_jobs_and_retry_backoff(self):
        clock = [0.0]
        transport = MagicMock()
        outcomes = [urllib.error.URLError("transient"), feedback(), semantics()]

        def request(*args, **kwargs):
            outcome = outcomes.pop(0)
            clock[0] += 0.03
            if isinstance(outcome, Exception):
                raise outcome
            return response(outcome)

        transport.open.side_effect = request
        with patch.dict("os.environ", {"EVALUATION_TIMEOUT_SECONDS": "0.3"}), patch("app.provider.time.monotonic", side_effect=lambda: clock[0]), patch("app.provider.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch("urllib.request.build_opener", return_value=transport):
            with evaluation_budget() as calls:
                self.provider.complete("evaluate", {})
                self.provider.complete("review_feedback_semantics", {})
        timeouts = [call.kwargs["timeout"] for call in transport.open.call_args_list]
        self.assertAlmostEqual(timeouts[0], 0.3)
        self.assertLess(timeouts[1], timeouts[0])
        self.assertLess(timeouts[2], timeouts[1])
        self.assertEqual([call["task"] for call in calls], ["evaluate", "evaluate", "review_feedback_semantics"])


if __name__ == "__main__":
    unittest.main()
