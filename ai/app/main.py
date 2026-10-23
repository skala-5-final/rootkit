"""작성: rootkit · 2026-10-23. Internal API; identities are supplied by authenticated Next.js."""

import hmac
import os
import sqlite3

from fastapi import Depends, FastAPI, Header, Query
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse

from .errors import DomainError
from .models import (AttemptRequest, AttemptResponse, EvaluationRequest,
                     EvaluationResult, HistoryResponse)
from .service import Service
from .storage import Storage


def create_app(service: Service | None = None) -> FastAPI:
    application = FastAPI(title="rootkit internal RAG", docs_url=None, redoc_url=None, openapi_url=None)
    application.state.service = service

    def get_service():
        if application.state.service is None:
            application.state.service = Service(Storage())
        return application.state.service

    def authenticate(authorization: str | None = Header(default=None)):
        token = os.environ.get("AI_API_TOKEN", "").strip()
        if not token or token.lower() in {"change-me", "changeme", "your-token"}:
            raise DomainError("Internal API token is not configured", "service_not_configured", 503)
        if not authorization or not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise DomainError("Invalid internal API authentication", "unauthorized", 401)

    @application.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc), "code": exc.code})

    @application.exception_handler(RequestValidationError)
    async def request_error(_request, _exc):
        return JSONResponse(status_code=422, content={"error": "Invalid request fields", "code": "invalid_input"})

    @application.exception_handler(sqlite3.OperationalError)
    async def storage_error(_request, _exc):
        return JSONResponse(status_code=503, content={"error": "Storage is temporarily unavailable", "code": "storage_unavailable"})

    @application.exception_handler(ResponseValidationError)
    async def response_error(_request, _exc):
        return JSONResponse(status_code=503, content={"error": "Stored response is invalid", "code": "invalid_response"})

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.post("/api/v1/attempts", dependencies=[Depends(authenticate)], response_model=AttemptResponse)
    def start_attempt(request: AttemptRequest, current: Service = Depends(get_service)):
        return current.start_attempt(request.user_id, request.stage)

    @application.get("/api/v1/attempts/{attempt_id}", dependencies=[Depends(authenticate)], response_model=AttemptResponse)
    def get_attempt(attempt_id: str, user_id: str = Query(min_length=1, max_length=200), current: Service = Depends(get_service)):
        return current.get_attempt(attempt_id, user_id)

    @application.post("/api/v1/evaluations", dependencies=[Depends(authenticate)], response_model=EvaluationResult)
    def evaluate(request: EvaluationRequest, current: Service = Depends(get_service)):
        return current.evaluate(request.user_id, request.attempt_id, request.request_id, request.answer)

    @application.get("/api/v1/history", dependencies=[Depends(authenticate)], response_model=HistoryResponse)
    def history(user_id: str = Query(min_length=1, max_length=200), current: Service = Depends(get_service)):
        return current.history(user_id)

    return application


app = create_app()
