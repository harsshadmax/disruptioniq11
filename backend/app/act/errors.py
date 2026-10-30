class WorkflowError(Exception):
    status_code = 400

    def __init__(self, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.detail, self.extra = detail, extra or {}


class NotFound(WorkflowError):
    status_code = 404


class Forbidden(WorkflowError):
    status_code = 403


class Conflict(WorkflowError):
    status_code = 409


class Invalid(WorkflowError):
    status_code = 422
