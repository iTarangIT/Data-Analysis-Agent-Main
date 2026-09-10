class DomainError(Exception):
    status_code = 400


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class GuardRejected(DomainError):
    """SQL failed the safety guard."""

    status_code = 422


class BudgetExceeded(DomainError):
    status_code = 429


class RateLimited(DomainError):
    """Too many runs, as opposed to too many tokens. The client should retry shortly, where
    `BudgetExceeded` means wait until tomorrow, so the two stay distinct despite sharing 429."""

    status_code = 429
