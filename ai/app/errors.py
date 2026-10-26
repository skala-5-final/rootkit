"""Domain errors with safe, stable public error codes."""


class DomainError(Exception):
    def __init__(self, message: str, code: str = "invalid_input", status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ModelError(DomainError):
    def __init__(self, message="AI model request failed", code="model_error"):
        super().__init__(message, code, 503)
