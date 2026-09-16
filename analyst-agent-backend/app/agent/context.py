from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    """Which tenant, connection and run the agent is working for.

    The connector and catalog are deliberately not here. They stay bound into the closure
    `make_query_tool` builds, because a tool that has no way to reach another tenant's source is
    a stronger guarantee than one that is merely handed the right identifier.
    """

    tenant_id: str
    connection_id: str
    run_id: str
    thread_id: str
