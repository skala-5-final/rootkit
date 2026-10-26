"""작성: rootkit · 2026-10-23. Explicitly configured OpenAI-compatible JSON provider."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from .errors import ModelError
from .prompts import PRINCIPLES, SCHEMAS, TASKS


_deadline = ContextVar("rootkit_evaluation_deadline", default=None)
_model_calls = ContextVar("rootkit_model_calls", default=None)


def _number(name: str, default: float, maximum: float, *, minimum: float = 0, inclusive=False) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError as exc:
        raise ModelError(f"{name} must be a valid number", "model_not_configured") from exc
    if not math.isfinite(value) or value > maximum or (value < minimum if inclusive else value <= minimum):
        raise ModelError(f"{name} is outside the supported range", "model_not_configured")
    return value


def _remaining() -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ModelError("The evaluation time budget was exhausted", "evaluation_timeout")
    return remaining


@contextmanager
def evaluation_budget():
    """Share a bounded deadline and non-sensitive call trace across all evaluation jobs."""
    duration = _number("EVALUATION_TIMEOUT_SECONDS", 120, 180)
    previous = _deadline.get()
    deadline = time.monotonic() + duration
    calls = _model_calls.get()
    calls = calls if calls is not None else []
    deadline_token = _deadline.set(min(previous, deadline) if previous is not None else deadline)
    calls_token = _model_calls.set(calls)
    try:
        yield calls
    finally:
        _model_calls.reset(calls_token)
        _deadline.reset(deadline_token)


def strict_schema(schema: dict) -> dict:
    """Require every property while preserving Pydantic's explicit nullable unions."""
    schema = deepcopy(schema)

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for key, value in node.items():
                if key in {"properties", "$defs", "definitions", "patternProperties"}:
                    for child in value.values():
                        visit(child)
                else:
                    visit(value)

    visit(schema)
    return schema


def _trace(task, model, attempt, started, code=None):
    calls = _model_calls.get()
    if calls is not None:
        calls.append({"task": task, "model": model, "attempt": attempt,
                      "outcome": "error" if code else "success", "code": code,
                      "duration_ms": max(0, round((time.monotonic() - started) * 1000))})


class Provider(Protocol):
    def complete(self, task: str, payload: dict) -> dict: ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the API key or company documents to a redirect destination.
        raise urllib.error.HTTPError(req.full_url, code, "Provider redirects are disabled", headers, fp)


class HTTPProvider:
    def evaluation_budget(self):
        return evaluation_budget()

    def complete(self, task: str, payload: dict) -> dict:
        started = time.monotonic()
        model = ""
        try:
            settings = self._settings(task)
            model = settings["model"]
            _remaining()
        except ModelError as exc:
            _trace(task, model, 0, started, exc.code)
            raise
        schema = SCHEMAS[task].model_json_schema()
        response_format = {"type": "json_object"}
        if settings["response_format"] == "json_schema":
            schema = strict_schema(schema)
            response_format = {"type": "json_schema", "json_schema": {"name": task, "strict": True, "schema": schema}}
        body = {
            "messages": [
                {"role": "system", "content": PRINCIPLES + "\n" + TASKS[task]
                 + "\nRequired JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": response_format,
        }
        if settings["temperature"] is not None:
            body["temperature"] = settings["temperature"]
        models = [model] * (1 + settings["retries"])
        if settings["fallback"] and settings["fallback"] != model:
            models.append(settings["fallback"])
        for index, selected_model in enumerate(models, 1):
            call_started = time.monotonic()
            try:
                remaining = _remaining()
                timeout = min(settings["timeout"], remaining) if remaining is not None else settings["timeout"]
                result = self._request(task, selected_model, body, settings, timeout)
                _remaining()
            except ModelError as exc:
                if exc.code in {"model_rate_limited", "model_unavailable", "model_connection_error"}:
                    try:
                        _remaining()
                    except ModelError as timeout_error:
                        _trace(task, selected_model, index, call_started, timeout_error.code)
                        raise timeout_error from exc
                _trace(task, selected_model, index, call_started, exc.code)
                if exc.code not in {"model_rate_limited", "model_unavailable", "model_connection_error"} or index == len(models):
                    raise
                remaining = _remaining()
                time.sleep(min(0.1, remaining / 2) if remaining is not None else 0.1)
                continue
            _trace(task, selected_model, index, call_started)
            return result
        raise ModelError("AI request attempts were exhausted")

    @staticmethod
    def _settings(task):
        if task not in TASKS or task not in SCHEMAS:
            raise ModelError("Unknown AI task", "model_not_configured")
        key = os.environ.get("MODEL_API_KEY", "").strip()
        role = "MODEL_REVIEW_NAME" if task.startswith("review_") else "MODEL_EVALUATION_NAME" if task == "evaluate" else "MODEL_GENERATION_NAME"
        model = os.environ.get(role, "").strip() or os.environ.get("MODEL_NAME", "").strip()
        base = os.environ.get("MODEL_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if not key or key.lower() in {"change-me", "changeme", "your-api-key"} or not model:
            raise ModelError("MODEL_API_KEY and a model name for this task must be configured", "model_not_configured")
        try:
            parsed = urllib.parse.urlparse(base)
        except ValueError as exc:
            raise ModelError("MODEL_API_BASE_URL is invalid", "model_not_configured") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("MODEL_API_BASE_URL is invalid", "model_not_configured")
        response_format = os.environ.get("MODEL_RESPONSE_FORMAT", "json_object").strip()
        if response_format not in {"json_object", "json_schema"}:
            raise ModelError("MODEL_RESPONSE_FORMAT must be json_object or json_schema", "model_not_configured")
        retries = _number("MODEL_MAX_RETRIES", 1, 1, inclusive=True)
        if not retries.is_integer():
            raise ModelError("MODEL_MAX_RETRIES must be 0 or 1", "model_not_configured")
        catalog_task = task in {"generate_catalog", "review_catalog"}
        timeout = _number("MODEL_CATALOG_TIMEOUT_SECONDS", 90, 180) if catalog_task else _number("MODEL_TIMEOUT_SECONDS", 25, 60)
        temperature = _number("MODEL_TEMPERATURE", 0, 2, inclusive=True) if os.environ.get("MODEL_TEMPERATURE", "").strip() else None
        reasoning_setting = role.removesuffix("_NAME") + "_REASONING_EFFORT" if task == "evaluate" or task.startswith("review_") else None
        reasoning = os.environ.get(reasoning_setting, "").strip() if reasoning_setting else ""
        if reasoning and reasoning not in {"none", "low", "medium", "high", "xhigh"}:
            raise ModelError(f"{reasoning_setting} must be none, low, medium, high or xhigh", "model_not_configured")
        if reasoning not in {"", "none"} and temperature is not None:
            raise ModelError("Leave MODEL_TEMPERATURE empty when task reasoning is enabled", "model_not_configured")
        return {"key": key, "model": model, "base": base, "response_format": response_format,
                "temperature": temperature, "timeout": timeout, "retries": int(retries),
                "reasoning_effort": reasoning,
                "fallback": os.environ.get("MODEL_FALLBACK_NAME", "").strip()}

    @staticmethod
    def _request(task, model, body, settings, timeout):
        request_body = {**body, "model": model}
        if settings["reasoning_effort"] and model == settings["model"]:
            request_body["reasoning_effort"] = settings["reasoning_effort"]
        request = urllib.request.Request(
            settings["base"] + "/chat/completions", data=json.dumps(request_body).encode(),
            headers={"Authorization": f"Bearer {settings['key']}", "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ModelError("AI response exceeded size limit", "invalid_model_response")
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            if choice.get("message", {}).get("refusal"):
                raise ModelError("AI provider refused this request", "model_refusal")
            if choice.get("finish_reason") != "stop":
                raise ModelError("AI response was incomplete", "invalid_model_response")
            content = choice["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ModelError("AI response must be a JSON object", "invalid_model_response")
            return result
        except urllib.error.HTTPError as exc:
            # Provider response bodies can contain user content or secrets; do not log them.
            exc.close()
            code = ("model_rate_limited" if exc.code == 429 else "model_unavailable" if 500 <= exc.code <= 599
                    else "model_auth_error" if exc.code in {401, 403} else "model_not_found" if exc.code == 404
                    else "model_request_rejected")
            raise ModelError(f"AI provider returned HTTP {exc.code}", code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError("AI provider connection failed or timed out", "model_connection_error") from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError("AI provider returned invalid JSON or response schema", "invalid_model_response") from exc
