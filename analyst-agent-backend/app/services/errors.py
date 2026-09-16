class DomainError(Exception):
    status_code = 400


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class Unauthorized(DomainError):
    """Bad credentials, as opposed to a missing or malformed bearer, which `deps` raises as an
    HTTPException. Both are 401, but only this one renders as {"error": ...}."""

    status_code = 401


class Conflict(DomainError):
    status_code = 409


class SourceUnavailable(DomainError):
    """A customer's database could not be reached. Not a bad request: nothing the caller sent
    was wrong, and the same call will work once the source is back."""

    status_code = 503


class GuardRejected(DomainError):
    """SQL failed the safety guard."""

    status_code = 422


class BudgetExceeded(DomainError):
    status_code = 429


class RateLimited(DomainError):
    """Too many runs, as opposed to too many tokens. The client should retry shortly, where
    `BudgetExceeded` means wait until tomorrow, so the two stay distinct despite sharing 429."""

    status_code = 429
