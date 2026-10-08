"""Domain errors. API handlers translate these into clean HTTP responses (never stack traces)."""


class GrowthOSError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(GrowthOSError):
    status_code = 404
    code = "not_found"


class ConflictError(GrowthOSError):
    status_code = 409
    code = "conflict"


class InvalidStateError(GrowthOSError):
    status_code = 409
    code = "invalid_state"


class SendBlockedError(GrowthOSError):
    """Raised when can_send() refuses an email. details['reasons'] lists every failed rule."""

    status_code = 409
    code = "send_blocked"


class AgentFailedError(GrowthOSError):
    status_code = 502
    code = "agent_failed"


class ExternalServiceError(GrowthOSError):
    status_code = 502
    code = "external_service_error"
