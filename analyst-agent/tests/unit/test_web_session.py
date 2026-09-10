"""The browser session, driven against a fake Playwright so no browser is needed.

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
PAYLOAD = [{"vehicleno": "KA01", "soc": 82}, {"vehicleno": "KA02", "soc": 61}]


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


class FakePage:
    def __init__(self, context, responses, password_fields):
        self._context = context
        self._responses = responses
        self._password_fields = password_fields
        self._handlers = []
        self.url = ""
        self.filled = []
        self.pressed = []
        self.keyboard = FakeKeyboard(self)

    def on(self, event, handler):
        self._handlers.append(handler)

    def goto(self, url, **kwargs):
        self.url = url
        for response in self._responses:
            for handler in self._handlers:
                handler(response)

    def locator(self, selector):
        return FakeLocator(self._password_fields)

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, ms):
        pass


class FakeContext:
    def __init__(self, browser, storage_state, responses, password_fields):
        self.browser = browser
        self.storage_state_arg = storage_state
        self._responses = responses
        self._password_fields = password_fields

    def new_page(self):
        return FakePage(self, self._responses, self._password_fields)

    def storage_state(self, path):
        self.browser.driver.saved.append(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cookies": [{"name": "session", "value": "x"}]}, f)


class FakeBrowser:
    def __init__(self, driver):
        self.driver = driver
        self.closed = False

    def new_context(self, storage_state=None):
        self.driver.opened_from.append(storage_state)
        return FakeContext(self, storage_state, self.driver.responses, self.driver.password_fields)

    def close(self):
        self.closed = True


class FakeDriver:
    """Stands in for `sync_playwright()`."""

    def __init__(self, responses, password_fields=0):
        self.responses = responses
        self.password_fields = password_fields
        self.opened_from: list = []
        self.saved: list = []
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

    monkeypatch.setattr(get_settings(), "session_store_dir", str(tmp_path), raising=False)
    return tmp_path


def _install(monkeypatch, driver):
    monkeypatch.setattr(web_session, "sync_playwright", lambda: driver)
    return driver


class TestSessionIsolation:
    def test_each_tenant_gets_its_own_state_file(self, sessions_dir):
        a = session_path("t_a", "c1")
        b = session_path("t_b", "c1")

        assert a != b
        assert a.parent.name == "t_a" and b.parent.name == "t_b"

    def test_one_tenants_session_is_never_opened_for_another(self, sessions_dir, monkeypatch):
        driver = _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 1))

        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")
        fetch_dashboard_json("t_b", "c1", SECRET, "/api/")

        assert driver.opened_from == [None, None], "neither tenant had a session yet"
        assert {str(session_path("t_a", "c1")), str(session_path("t_b", "c1"))} == set(driver.saved)

    def test_a_saved_session_is_reused_and_suppresses_the_login(self, sessions_dir, monkeypatch):
        session_path("t_a", "c1").write_text("{}", encoding="utf-8")
        driver = _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 0))

        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        assert driver.opened_from == [str(session_path("t_a", "c1"))]
        assert driver.saved == [], "a reused session must not be rewritten"

    def test_an_expired_session_logs_in_again_and_saves_state(self, sessions_dir, monkeypatch):
        session_path("t_a", "c1").write_text("{}", encoding="utf-8")
        driver = _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 1))

        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        assert driver.saved == [str(session_path("t_a", "c1"))]


class TestCapture:
    def test_only_matching_json_responses_are_read(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch,
            FakeDriver(
                [
                    FakeResponse("/static/app.js", None, "text/javascript"),
                    FakeResponse("/api/other", [{"ignored": 1}]),
                    FakeResponse("/login", PAYLOAD, "text/html"),
                    FakeResponse("/api/fleet", PAYLOAD),
                ],
                0,
            ),
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/fleet") == PAYLOAD

    def test_the_last_matching_response_wins(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch,
            FakeDriver([FakeResponse("/api/x", [{"n": 1}]), FakeResponse("/api/x", [{"n": 2}])], 0),
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == [{"n": 2}]

    def test_an_unreadable_body_is_skipped_rather_than_fatal(self, sessions_dir, monkeypatch):
        _install(
            monkeypatch,
            FakeDriver([FakeResponse("/api/x", None), FakeResponse("/api/y", PAYLOAD)], 0),
        )
        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == PAYLOAD

    def test_nothing_captured_names_the_match_string(self, sessions_dir, monkeypatch):
        _install(monkeypatch, FakeDriver([FakeResponse("/static/x.js", None, "text/js")], 0))

        with pytest.raises(DashboardUnavailable, match="/nope/"):
            fetch_dashboard_json("t_a", "c1", SECRET, "/nope/")


class TestPayloadShapes:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ([{"a": 1}], [{"a": 1}]),
            ({"data": [{"a": 1}]}, [{"a": 1}]),
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
        _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 0))

        assert fetch_dashboard_json("t_a", "c1", SECRET, "/api/") == PAYLOAD


class TestSecrets:
    def test_no_credential_reaches_a_log_line(self, sessions_dir, monkeypatch):
        _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 1))

        with structlog.testing.capture_logs() as logs:
            fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        blob = json.dumps(logs)
        assert SECRET["password"] not in blob
        assert SECRET["username"] not in blob
        assert any(entry["event"] == "web.login" for entry in logs)

    def test_the_login_fills_the_credentials_it_was_given(self, sessions_dir, monkeypatch):
        _install(monkeypatch, FakeDriver([FakeResponse("/api/fleet", PAYLOAD)], 1))
        captured: list = []
        original = FakeContext.new_page

        def spy(self):
            page = original(self)
            captured.append(page)
            return page

        monkeypatch.setattr(FakeContext, "new_page", spy)
        fetch_dashboard_json("t_a", "c1", SECRET, "/api/")

        filled = dict(captured[0].filled)
        assert SECRET["username"] in filled.values()
        assert SECRET["password"] in filled.values()
        assert captured[0].pressed == ["Enter"]
