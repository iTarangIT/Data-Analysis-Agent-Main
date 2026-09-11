"""The browser session, driven against a fake Playwright so no browser is needed.

The fake models the flow measured against the real dashboard: no inline form, a Login button
that opens a popup, an identifier step, then a password step, then the popup closes itself.

The assertions that matter are about tenant isolation: which state file a context is opened
from, and that one tenant's file is never read for another. That is phase 3's done-line, made
runnable in CI.
"""

import asyncio
import json

import pytest
import structlog

from app.workers import web_session
from app.workers.web_session import DashboardUnavailable, fetch_dashboard_json, session_path

SECRET = {"url": "https://dash.example/fleet", "username": "u@example", "password": "hunter2"}
PAYLOAD = {"status": "SUCCESS", "data": [{"groupid": 1, "groupname": "Fleet A"}], "err": None}
ROWS = [{"groupid": 1, "groupname": "Fleet A"}]


class FakeResponse:
    def __init__(self, url: str, payload, content_type: str = "application/json"):
        self.url = url
        self._payload = payload
        self._content_type = content_type

    def header_value(self, name: str) -> str:
        return self._content_type

    def json(self):
        if self._payload is None:
            raise ValueError("body unavailable")
        return self._payload


class FakeLocator:
    def __init__(self, n: int):
        self._n = n

    def count(self) -> int:
        return self._n


class FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key: str) -> None:
        self._page.pressed.append(key)
        self._page.on_submit()


class FakePopup:
    """The sign-in window. It closes itself once a correct password is submitted, which is what
    the real one does when it hands the token back to its opener."""

    def __init__(self, driver):
        self.driver = driver
        self.filled: list[tuple[str, str]] = []
        self.pressed: list[str] = []
        self.keyboard = FakeKeyboard(self)
        self._step = "identifier"
        self._closed = False

    def on_submit(self) -> None:
        if self._step == "identifier" and self.driver.username_ok:
            self._step = "password"
        elif self._step == "password" and self.driver.password_ok:
            self._closed = True
            self.driver.signed_in = True

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def wait_for_selector(self, selector, timeout=None):
        if self._step != "password":
            raise TimeoutError("no password field appeared")

    def wait_for_event(self, event, timeout=None):
        if not self._closed:
            raise TimeoutError("the popup stayed open")

    def is_closed(self):
        return self._closed


class _PopupHandle:
    def __init__(self, popup):
        self.value = popup


class _PopupContext:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        handle = _PopupHandle(FakePopup(self.page.driver))
        self.page.popup = handle.value
        return handle

    def __exit__(self, *args):
        return False


class FakePage:
    def __init__(self, context):
        self.context = context
        self.driver = context.driver
        self._handlers = []
        self.url = ""
        self.popup = None
        self.clicked: list[str] = []

    def on(self, event, handler):
        self._handlers.append(handler)

    def goto(self, url, **kwargs):
        self.url = url
        # The dashboard only fetches its data once the session is authenticated.
        if self.driver.signed_in:
            for response in self.driver.responses:
                for handler in self._handlers:
                    handler(response)

    def locator(self, selector):
        return FakeLocator(0 if self.driver.signed_in else 1)

    def expect_popup(self, timeout=None):
        return _PopupContext(self)

    def click(self, selector):
        self.clicked.append(selector)

    def wait_for_timeout(self, ms):
        pass


class FakeContext:
    def __init__(self, browser, storage_state):
        self.browser = browser
        self.driver = browser.driver
        self.storage_state_arg = storage_state

    def new_page(self):
        page = FakePage(self)
        self.driver.pages.append(page)
        return page

    def storage_state(self, path):
        self.driver.saved.append(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cookies": [{"name": "session", "value": "x"}]}, f)


class FakeBrowser:
    def __init__(self, driver):
        self.driver = driver
        self.closed = False

    def new_context(self, storage_state=None):
        self.driver.opened_from.append(storage_state)
        # A saved session means the dashboard already trusts this browser.
        if storage_state is not None and self.driver.session_still_valid:
            self.driver.signed_in = True
        return FakeContext(self, storage_state)

    def close(self):
        self.closed = True


class FakeDriver:
    """Stands in for `sync_playwright()`."""

    def __init__(self, responses, session_still_valid=True, username_ok=True, password_ok=True):
        self.responses = responses
        self.session_still_valid = session_still_valid
        self.username_ok = username_ok
        self.password_ok = password_ok
        self.signed_in = False
        self.opened_from: list = []
        self.saved: list = []
        self.pages: list = []
        self.chromium = self

    def launch(self, headless=True):
        return FakeBrowser(self)

    def __enter__(self):
        # Playwright's sync API raises here when the calling thread has a running loop. The
        # fake enforces the same rule, so a regression that drops the worker thread fails.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self
        raise RuntimeError("Sync API inside the asyncio loop is not supported")

    def __exit__(self, *args):
        return False


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "session_store_dir", str(tmp_path), raising=False)
    # The real default polls for 25 seconds before giving up on the data.
    monkeypatch.setattr(s, "web_data_timeout_ms", 50, raising=False)
    monkeypatch.setattr(s, "web_settle_ms", 0, raising=False)
    return tmp_path


def _install(monkeypatch, driver):
    monkeypatch.setattr(web_session, "sync_playwright", lambda: driver)
    return driver


def _ok(**kwargs):
    return FakeDriver([FakeResponse("/api/group/listevgroups", PAYLOAD)], **kwargs)


class TestSessionIsolation:
    def test_each_tenant_gets_its_own_state_file(self, sessions_dir):
        a = session_path("t_a", "c1")
        b = session_path("t_b", "c1")

        assert a != b
        assert a.parent.name == "t_a" and b.parent.name == "t_b"

    def test_one_tenants_session_is_never_opened_for_another(self, sessions_dir, monkeypatch):
        driver = _install(monkeypatch, _ok())

        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")
        driver.signed_in = False
        fetch_dashboard_json("t_b", "c1", SECRET, "/api/")

        assert driver.opened_from == [None, None], "neither tenant had a session yet"
        assert {str(session_path("t_a", "c1")), str(session_path("t_b", "c1"))} == set(driver.saved)

    def test_a_saved_session_is_reused_and_suppresses_the_login(self, sessions_dir, monkeypatch):
        session_path("t_a", "c1").write_text("{}", encoding="utf-8")
        driver = _install(monkeypatch, _ok())

        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == ROWS

        assert driver.opened_from == [str(session_path("t_a", "c1"))]
        assert driver.saved == [], "a reused session must not be rewritten"
        assert driver.pages[0].clicked == [], "no Login click on a session that still works"

    def test_an_expired_session_logs_in_again_and_saves_state(self, sessions_dir, monkeypatch):
        session_path("t_a", "c1").write_text("{}", encoding="utf-8")
        driver = _install(monkeypatch, _ok(session_still_valid=False))

        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == ROWS

        assert driver.saved == [str(session_path("t_a", "c1"))]
        assert driver.pages[0].clicked, "an expired session must trigger the Login click"


class TestLogin:
    def test_it_signs_in_through_the_popup(self, sessions_dir, monkeypatch):
        driver = _install(monkeypatch, _ok())

        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        popup = driver.pages[0].popup
        assert [v for _, v in popup.filled] == [SECRET["username"], SECRET["password"]]
        assert popup.pressed == ["Enter", "Enter"], "each step is submitted with Enter"
        assert popup.is_closed(), "the popup closing is what proves the token got back"

    def test_a_rejected_username_says_so(self, sessions_dir, monkeypatch):
        _install(monkeypatch, _ok(username_ok=False))

        with pytest.raises(DashboardUnavailable, match="username"):
            fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

    def test_a_rejected_password_says_so(self, sessions_dir, monkeypatch):
        _install(monkeypatch, _ok(password_ok=False))

        with pytest.raises(DashboardUnavailable, match="credentials"):
            fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

    def test_a_failed_login_saves_no_session(self, sessions_dir, monkeypatch):
        driver = _install(monkeypatch, _ok(password_ok=False))

        with pytest.raises(DashboardUnavailable):
            fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        assert driver.saved == []
        assert not session_path("t_a", "c1").exists()


class TestCapture:
    def test_only_matching_json_responses_are_read(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch,
            FakeDriver(
                [
                    FakeResponse("/static/app.js", None, "text/javascript"),
                    FakeResponse("/api/other", {"data": [{"ignored": 1}]}),
                    FakeResponse("/login", PAYLOAD, "text/html"),
                    FakeResponse("/api/group/listevgroups", PAYLOAD),
                ]
            ),
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/group/listevgroups") == ROWS

    def test_the_last_matching_response_wins(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch,
            FakeDriver(
                [
                    FakeResponse("/api/x", {"data": [{"n": 1}]}),
                    FakeResponse("/api/x", {"data": [{"n": 2}]}),
                ]
            ),
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == [{"n": 2}]

    def test_an_unreadable_body_is_skipped_rather_than_fatal(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch, FakeDriver([FakeResponse("/api/x", None), FakeResponse("/api/y", PAYLOAD)])
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == ROWS

    def test_nothing_captured_names_the_match_string(self, sessions_dir, monkeypatch):
        _install(monkeypatch, FakeDriver([FakeResponse("/static/x.js", None, "text/js")]))

        with pytest.raises(DashboardUnavailable, match="/nope/"):
            fetch_dashboard_json("t_a", "c1", SECRET, "/nope/")


class TestPayloadShapes:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ([{"a": 1}], [{"a": 1}]),
            # The shape every Intellicar endpoint returns.
            ({"status": "SUCCESS", "data": [{"a": 1}], "err": None}, [{"a": 1}]),
            ({"rows": [{"a": 1}]}, [{"a": 1}]),
            ({"a": 1}, [{"a": 1}]),
            ([1, 2, 3], []),
        ],
    )
    def test_rows_are_unwrapped(self, payload, expected):
        assert web_session._rows(payload) == expected


class TestItDoesNotRunOnTheEventLoop:
    """Playwright's sync API refuses to start on a thread with a running loop, so the browser
    has to leave the loop thread. Without the worker thread this test fails, and so does every
    live run."""

    async def test_it_works_from_inside_a_running_loop(self, sessions_dir, monkeypatch):
        _install(monkeypatch, _ok())

        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == ROWS


class TestSecrets:
    def test_no_credential_reaches_a_log_line(self, sessions_dir, monkeypatch):
        _install(monkeypatch, _ok())

        with structlog.testing.capture_logs() as logs:
            fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        blob = json.dumps(logs)
        assert SECRET["password"] not in blob
        assert SECRET["username"] not in blob
        assert any(entry["event"] == "web.login" for entry in logs)
