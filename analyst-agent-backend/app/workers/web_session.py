"""One tenant's browser session against their own dashboard.

Session state is persisted per tenant and per connection, so two tenants signed into the same
dashboard never share cookies. That separation is the whole point of the file: it is what
phase 3's done-line checks.

The sign-in flow was measured against Intellicar rather than guessed. The dashboard has no
inline login form: it shows one button, which opens a popup to a separate single sign-on host
that asks for an identifier, then a password, then closes itself and hands a token back to the
window that opened it. Driving that sign-in page directly mints a token nothing consumes, so
the popup has to be opened from the dashboard.
"""

import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Response, sync_playwright

from app.config import get_settings
from app.logging import log

# All the site-specific knowledge is these three selectors and nothing else.
LOGIN_BUTTON = "button:visible:has-text('Login')"
IDENTIFIER_FIELD = "input:visible >> nth=0"
PASSWORD_FIELD = "input[type=password]:visible"


class DashboardUnavailable(RuntimeError):
    """The dashboard could not be reached, signed into, or returned no data.

    Defined here rather than in `app.services.errors` because `workers/` is a leaf: importing
    upward from a connector's dependency would invert the layering. `services.runs` maps it.
    """


def session_path(tenant_id: str, connection_id: str) -> Path:
    root = Path(get_settings().session_store_dir) / tenant_id
    # Owner-only matters on the VPS, where these files sit beside other services. It is a no-op
    # on Windows, which is why the directory is per tenant rather than relying on the mode.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / f"{connection_id}.json"


def fetch_dashboard_json(
    tenant_id: str, connection_id: str, secret: dict[str, str], data_url_match: str
) -> list[dict[str, Any]]:
    """Sign in if needed and return the rows behind the dashboard.

    Playwright's sync API refuses to start on a thread that already has a running event loop,
    and this is called from inside `agent.stream`, which runs on one. Hence the worker thread.
    The context is copied because thread-pool submission does not carry contextvars, and
    without it the browser thread's log lines would lose their tenant and run ids.
    """
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright") as pool:
        return pool.submit(
            ctx.run, _open_and_capture, tenant_id, connection_id, secret, data_url_match
        ).result()


def _capture(response: Response, data_url_match: str, out: list[Any]) -> None:
    if data_url_match not in response.url:
        return
    if "json" not in (response.header_value("content-type") or ""):
        return
    # A matching URL whose body cannot be read is another endpoint, not a failure.
    with suppress(Exception):
        out.append(response.json())


def _login(page: Page, secret: dict[str, str], timeout_ms: int) -> None:
    """Sign in through the popup the dashboard opens.

    The popup closing is the success signal: it means the token reached the opener. A rejected
    credential leaves it open, which is why that is what the failures below detect.
    """
    with page.expect_popup(timeout=timeout_ms) as popup_info:
        page.click(LOGIN_BUTTON)
    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

    popup.fill(IDENTIFIER_FIELD, secret["username"])
    popup.keyboard.press("Enter")
    try:
        popup.wait_for_selector(PASSWORD_FIELD, timeout=timeout_ms)
    except Exception as e:
        raise DashboardUnavailable("the dashboard did not accept that username") from e

    popup.fill(PASSWORD_FIELD, secret["password"])
    popup.keyboard.press("Enter")
    try:
        popup.wait_for_event("close", timeout=timeout_ms)
    except Exception as e:
        raise DashboardUnavailable("the dashboard did not accept those credentials") from e


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "results", "records"):
            if isinstance(payload.get(key), list):
                return [r for r in payload[key] if isinstance(r, dict)]
        return [payload]
    return []


def _wait_for_data(page: Page, captured: list[Any], timeout_ms: int, settle_ms: int) -> None:
    """Wait only as long as the data actually takes, then briefly for a larger one behind it."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not captured and time.monotonic() < deadline:
        page.wait_for_timeout(250)
    if captured:
        page.wait_for_timeout(settle_ms)


def _open_and_capture(
    tenant_id: str, connection_id: str, secret: dict[str, str], data_url_match: str
) -> list[dict[str, Any]]:
    s = get_settings()
    state = session_path(tenant_id, connection_id)
    captured: list[Any] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=s.playwright_headless)
        context = browser.new_context(storage_state=str(state) if state.exists() else None)
        page = context.new_page()
        page.on("response", lambda r: _capture(r, data_url_match, captured))
        page.goto(secret["url"], wait_until="domcontentloaded", timeout=s.web_nav_timeout_ms)
        _wait_for_data(page, captured, s.web_data_timeout_ms, s.web_settle_ms)

        # A saved session that still works fetches the data on that first load. Only when it
        # does not is a sign-in needed.
        if not captured and page.locator(LOGIN_BUTTON).count():
            _login(page, secret, s.web_nav_timeout_ms)
            context.storage_state(path=str(state))
            log.info("web.login", connection_id=connection_id)

            # The dashboard reloads itself once the popup hands back the token. Navigating at
            # that same moment aborts its navigation with ERR_ABORTED, so wait for it first and
            # only load the page if it does not do so on its own.
            _wait_for_data(page, captured, s.web_data_timeout_ms, s.web_settle_ms)
            if not captured:
                page.goto(
                    secret["url"], wait_until="domcontentloaded", timeout=s.web_nav_timeout_ms
                )
                _wait_for_data(page, captured, s.web_data_timeout_ms, s.web_settle_ms)
        else:
            log.debug("web.session_reused", connection_id=connection_id)

        browser.close()

    if not captured:
        raise DashboardUnavailable(
            f"no dashboard data matched {data_url_match!r}; check the connection's data_url_match"
        )
    return _rows(captured[-1])
