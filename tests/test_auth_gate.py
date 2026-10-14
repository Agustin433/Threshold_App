from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules import auth

ROOT = Path(__file__).resolve().parents[1]

_FULL_AUTH = {
    "redirect_uri": "http://localhost:8501/oauth2callback",
    "cookie_secret": "s3cret",
    "client_id": "id.apps.googleusercontent.com",
    "client_secret": "client-secret",
    "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
}


class _Stopped(Exception):
    pass


def _fake_st(*, logged_in: bool, claims: dict | None = None, auth_section: dict | None = None) -> MagicMock:
    fake = MagicMock()
    fake.stop.side_effect = _Stopped
    fake.button.return_value = False
    fake.user.get.side_effect = {"is_logged_in": logged_in, **(claims or {})}.get
    fake.secrets.get.side_effect = {"auth": auth_section}.get
    return fake


class AllowedEmailsTests(unittest.TestCase):
    def test_list_is_normalized(self):
        with patch.object(auth, "_read_secret", return_value=[" Coach@Gmail.com ", ""]):
            self.assertEqual(auth.allowed_emails(), {"coach@gmail.com"})

    def test_comma_string_from_env(self):
        with patch.object(auth, "_read_secret", return_value="a@x.com, B@y.com"):
            self.assertEqual(auth.allowed_emails(), {"a@x.com", "b@y.com"})

    def test_missing_means_nobody(self):
        with patch.object(auth, "_read_secret", return_value=None):
            self.assertEqual(auth.allowed_emails(), set())

    def test_is_email_allowed_is_case_insensitive_and_rejects_empty(self):
        allowed = {"coach@gmail.com"}
        self.assertTrue(auth.is_email_allowed("COACH@gmail.com", allowed))
        self.assertFalse(auth.is_email_allowed("", allowed))
        self.assertFalse(auth.is_email_allowed(None, allowed))
        self.assertFalse(auth.is_email_allowed("otro@gmail.com", allowed))


class AuthConfiguredTests(unittest.TestCase):
    def test_requires_every_setting(self):
        for missing in auth.REQUIRED_AUTH_SETTINGS:
            partial = {k: v for k, v in _FULL_AUTH.items() if k != missing}
            with patch.object(auth, "st", _fake_st(logged_in=False, auth_section=partial)):
                self.assertFalse(auth.auth_configured(), missing)
        with patch.object(auth, "st", _fake_st(logged_in=False, auth_section=_FULL_AUTH)):
            self.assertTrue(auth.auth_configured())

    def test_secrets_error_counts_as_not_configured(self):
        fake = _fake_st(logged_in=False)
        fake.secrets.get.side_effect = FileNotFoundError("no secrets.toml")
        with patch.object(auth, "st", fake):
            self.assertFalse(auth.auth_configured())


class RequireLoginTests(unittest.TestCase):
    def _run(self, fake, *, disabled=False, allowed=frozenset({"coach@gmail.com"})):
        with patch.object(auth, "st", fake), patch.object(auth, "auth_disabled", return_value=disabled), patch.object(
            auth, "allowed_emails", return_value=set(allowed)
        ):
            auth.require_login()

    def test_fails_closed_without_auth_config(self):
        fake = _fake_st(logged_in=True, claims={"email": "coach@gmail.com"}, auth_section=None)
        with self.assertRaises(_Stopped):
            self._run(fake)

    def test_fails_closed_without_allowed_emails(self):
        fake = _fake_st(logged_in=True, claims={"email": "coach@gmail.com"}, auth_section=_FULL_AUTH)
        with self.assertRaises(_Stopped):
            self._run(fake, allowed=frozenset())

    def test_anonymous_user_is_stopped(self):
        fake = _fake_st(logged_in=False, auth_section=_FULL_AUTH)
        with self.assertRaises(_Stopped):
            self._run(fake)
        fake.login.assert_not_called()

    def test_login_button_triggers_st_login(self):
        fake = _fake_st(logged_in=False, auth_section=_FULL_AUTH)
        fake.button.return_value = True
        with self.assertRaises(_Stopped):
            self._run(fake)
        fake.login.assert_called_once_with()

    def test_email_not_in_allowlist_is_stopped(self):
        fake = _fake_st(logged_in=True, claims={"email": "intruso@gmail.com"}, auth_section=_FULL_AUTH)
        with self.assertRaises(_Stopped):
            self._run(fake)

    def test_unverified_email_is_stopped_even_if_listed(self):
        fake = _fake_st(
            logged_in=True,
            claims={"email": "coach@gmail.com", "email_verified": False},
            auth_section=_FULL_AUTH,
        )
        with self.assertRaises(_Stopped):
            self._run(fake)

    def test_allowed_user_passes(self):
        fake = _fake_st(
            logged_in=True,
            claims={"email": "Coach@Gmail.com", "email_verified": True},
            auth_section=_FULL_AUTH,
        )
        self._run(fake)
        fake.stop.assert_not_called()

    def test_disabled_flag_skips_gate(self):
        fake = _fake_st(logged_in=False, auth_section=None)
        self._run(fake, disabled=True, allowed=frozenset())
        fake.stop.assert_not_called()


class AuthDisabledTests(unittest.TestCase):
    def test_truthy_values(self):
        for value in (True, "true", "1", "SI", " yes "):
            with patch.object(auth, "_read_secret", return_value=value):
                self.assertTrue(auth.auth_disabled(), value)
        for value in (None, False, "", "false", "0"):
            with patch.object(auth, "_read_secret", return_value=value):
                self.assertFalse(auth.auth_disabled(), value)


class StreamlitRuntimeTests(unittest.TestCase):
    """Corre la puerta real dentro de Streamlit (sin mocks de st)."""

    _SCRIPT = (
        "import streamlit as st\n"
        "from modules.auth import require_login\n"
        "require_login()\n"
        "st.write('DATOS PROTEGIDOS')\n"
    )

    def _app(self):
        from streamlit.testing.v1 import AppTest

        return AppTest.from_string(self._SCRIPT, default_timeout=30)

    def test_anonymous_session_sees_login_and_no_data(self):
        at = self._app()
        at.secrets["auth"] = dict(_FULL_AUTH)
        at.secrets["ALLOWED_EMAILS"] = ["coach@gmail.com"]
        with patch.object(auth, "auth_disabled", return_value=False):
            at.run()
        self.assertFalse(at.exception)
        rendered = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("DATOS PROTEGIDOS", rendered)
        self.assertIn("auth_login", [b.key for b in at.button])

    def test_missing_config_blocks(self):
        at = self._app()
        with patch.object(auth, "auth_disabled", return_value=False):
            at.run()
        rendered = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("DATOS PROTEGIDOS", rendered)
        self.assertTrue(at.error)


class EntrypointOrderTests(unittest.TestCase):
    def _first_line(self, source: str, pattern: str) -> int:
        for number, line in enumerate(source.splitlines(), start=1):
            if re.match(pattern, line):
                return number
        self.fail(f"no se encontro {pattern!r}")

    def test_app_gates_before_any_data_access(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        gate = self._first_line(source, r"^require_login\(\)")
        self.assertLess(self._first_line(source, r"^st\.set_page_config\("), gate)
        for call in (
            r"^ensure_local_store_hydrated\(\)",
            r"^hydrate_remote_datasets\(\)",
            r"^hydrate_evaluations_from_store\(\)",
            r"^with st\.sidebar:",
        ):
            self.assertLess(gate, self._first_line(source, call), call)

    def test_every_page_gates_before_loading_state(self):
        pages = sorted((ROOT / "pages").glob("*.py"))
        self.assertTrue(pages)
        for page in pages:
            source = page.read_text(encoding="utf-8")
            gate = self._first_line(source, r"^require_login\(\)")
            self.assertLess(gate, self._first_line(source, r"^ensure_page_state\("), page.name)


if __name__ == "__main__":
    unittest.main()
