"""Give a live run the database, but only once the dashboard has actually failed it.

A question routed to the dashboard has nowhere to go when the browser cannot sign in or the
dashboard shows nothing, and refusing there is a poor answer when the database holds the same
measurement from an hour ago. Handing the agent both tools from the start is the obvious fix
and the wrong one: `app/agent/router.py` binds a run to one source precisely so the agent
cannot offer to consult something it has no tool for, and a second tool present from the
outset undoes that.

So the tool appears at the moment it becomes true. Until the dashboard has been called and
come back empty or broken, the agent sees one source and behaves exactly as before. After
that it sees two, and is told to say which one it fell back to.

Doing this inside the agent's own loop rather than by running a second agent afterwards is
what keeps one answer, one `token` event and one coherent conversation thread. A second run
would stream the dashboard's failure to the customer as a finished answer and then overwrite
it.
"""

from typing import Any

import structlog
from langchain.agents.middleware import ModelRequest, wrap_model_call
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agent.prompts import FALLBACK_CAPABILITY, SQL_CAPABILITY
from app.agent.tools import WEB_TOOL_NAME

log = structlog.get_logger(__name__)


def dashboard_gave_nothing(messages: list[Any]) -> bool:
    """Whether the dashboard has already been asked and produced nothing usable.

    Reads the artifact rather than the text the model saw, because the artifact is where the
    tool records what actually happened: an `error` key when the browser failed, and the rows
    themselves otherwise. An empty result and a failed one are the same thing here, and both
    are indistinguishable to a customer waiting for a number.
    """
    for message in messages:
        if isinstance(message, ToolMessage) and message.name == WEB_TOOL_NAME:
            artifact = message.artifact or {}
            if artifact.get("error") or not artifact.get("rows"):
                return True
    return False


def unlock_database(sql_tool: BaseTool, system_prompt: str):
    """Middleware that reveals `sql_tool` to a web run once the dashboard has let it down.

    The tool has to be registered with the agent up front, because the tool node can only
    execute something it was built with. But registering it also puts it in front of the
    model from the first turn, which is exactly what `app/agent/router.py` binds a run to one
    source to prevent. So the default is to take it back out of what the model is shown, and
    the fallback is to leave it in.
    """
    already = False

    @wrap_model_call(name="fallback_to_database", tools=[sql_tool])
    def middleware(request: ModelRequest, handler):
        nonlocal already
        if not dashboard_gave_nothing(request.state["messages"]):
            hidden = [t for t in request.tools if getattr(t, "name", None) != sql_tool.name]
            return handler(request.override(tools=hidden))

        if not already:
            already = True
            log.info("run.fallback", to="database")
        return handler(request.override(system_message=SystemMessage(system_prompt)))

    return middleware


def capability() -> str:
    return FALLBACK_CAPABILITY.format(sql=SQL_CAPABILITY)
