"""The sign-in gate: settings, and the allowlist applied to every token."""

import pytest

import auth

ALLOWED = frozenset({"anna@gmail.com"})


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"email": "Anna@Gmail.com", "email_verified": True}, True),
        # As Google's tokeninfo endpoint actually sends it.
        ({"email": "anna@gmail.com", "email_verified": "true"}, True),
        ({"email": "anna@gmail.com", "email_verified": "false"}, False),
        ({"email": "anna@gmail.com", "email_verified": False}, False),
        ({"email": "anna@gmail.com"}, False),
        ({"email": "eve@gmail.com", "email_verified": True}, False),
        ({}, False),
    ],
)
def test_only_verified_allowlisted_emails_pass(claims, expected):
    assert auth.is_allowed(claims, ALLOWED) is expected


def test_the_allowlist_ignores_case_and_blanks():
    assert auth.parse_allowlist(" Anna@Gmail.com , ,b@x.ua") == {"anna@gmail.com", "b@x.ua"}
    assert auth.parse_allowlist(None) == frozenset()


def test_a_missing_setting_stops_the_provider_from_being_built(monkeypatch):
    for name in auth.REQUIRED_ENV:
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("MCP_JWT_SIGNING_KEY")
    with pytest.raises(RuntimeError, match="MCP_JWT_SIGNING_KEY"):
        auth.build_provider()


class _Access:
    def __init__(self, claims):
        self.claims = claims


async def test_a_signed_in_account_off_the_allowlist_is_refused(monkeypatch):
    async def upstream(self, token):
        return _Access({"email": token, "email_verified": "true"})

    monkeypatch.setattr(auth.GoogleProvider, "load_access_token", upstream)
    provider = object.__new__(auth.AllowlistedGoogleProvider)
    provider._allowlist = ALLOWED
    assert await provider.load_access_token("anna@gmail.com") is not None
    assert await provider.load_access_token("eve@gmail.com") is None


async def test_a_refusal_is_logged_with_the_email_and_reason(monkeypatch, capsys):
    async def upstream(self, token):
        return _Access({"email": "eve@gmail.com", "email_verified": "true"})

    monkeypatch.setattr(auth.GoogleProvider, "load_access_token", upstream)
    provider = object.__new__(auth.AllowlistedGoogleProvider)
    provider._allowlist = ALLOWED
    await provider.load_access_token("t")
    logged = capsys.readouterr().err
    assert "eve@gmail.com" in logged and "not in ALLOWED_USERS" in logged
