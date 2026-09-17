from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Who a request acts for, once `app.api.deps.current_tenant` has resolved the account."""

    tenant_id: str
    user_id: str
