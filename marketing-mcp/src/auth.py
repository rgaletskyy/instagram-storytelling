"""Google sign-in for the MCP endpoint, limited to an email allowlist.

Claude Desktop connects to a remote MCP server from Anthropic's side, so Cloud
Run's IAM cannot gate it: the server is public at the network level and this
module is the gate. A user signs in with Google once (FastMCP's OAuth proxy
runs the flow); every MCP request then carries a token that is checked here,
and an account outside ALLOWED_USERS is refused even after signing in.

The proxy's state -- Claude's client registration, sign-ins in flight, the
users' Google tokens -- lives in a Firestore database of its own, encrypted.
Its own, so the service account needs no access to the database holding the
knowledge base; Firestore, so it survives restarts and is shared between Cloud
Run instances (a sign-in may start on one and finish on another).
"""

from __future__ import annotations

import os

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider

REQUIRED_ENV = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MCP_BASE_URL",
    "MCP_JWT_SIGNING_KEY",
    "ALLOWED_USERS",
)
# The Firestore database for the proxy's state; never the knowledge base's.
AUTH_DATABASE_ENV = "AUTH_FIRESTORE_DATABASE"
DEFAULT_AUTH_DATABASE = "mcp-auth"


def parse_allowlist(value: str | None) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in (value or "").split(",") if e.strip())


def is_allowed(claims: dict, allowlist: frozenset[str]) -> bool:
    email = str(claims.get("email") or "").lower()
    return bool(email) and claims.get("email_verified") is True and email in allowlist


class AllowlistedGoogleProvider(GoogleProvider):
    """Google sign-in that lets only allowlisted, verified emails through."""

    def __init__(self, *, allowlist: frozenset[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._allowlist = allowlist

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = await super().load_access_token(token)
        if access is None or not is_allowed(access.claims or {}, self._allowlist):
            return None
        return access


def missing_settings() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def build_provider() -> AllowlistedGoogleProvider:
    """The configured provider; raises if a setting is missing."""
    from fastmcp.server.auth.jwt_issuer import derive_jwt_key
    from key_value.aio.stores.firestore import FirestoreStore
    from key_value.aio.stores.firestore.store import (
        FirestoreV1CollectionSanitizationStrategy,
        FirestoreV1KeySanitizationStrategy,
    )
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    missing = missing_settings()
    if missing:
        raise RuntimeError(f"MCP sign-in is not configured: set {', '.join(missing)}")
    allowlist = parse_allowlist(os.environ["ALLOWED_USERS"])
    signing_key = os.environ["MCP_JWT_SIGNING_KEY"]

    # The same key derivation FastMCP uses for its default store, so the
    # stored tokens are encrypted exactly as they would be on local disk.
    from cryptography.fernet import Fernet

    storage = FernetEncryptionWrapper(
        key_value=FirestoreStore(
            database=os.environ.get(AUTH_DATABASE_ENV, DEFAULT_AUTH_DATABASE),
            key_sanitization_strategy=FirestoreV1KeySanitizationStrategy(),
            collection_sanitization_strategy=FirestoreV1CollectionSanitizationStrategy(),
        ),
        fernet=Fernet(
            derive_jwt_key(high_entropy_material=signing_key, salt="fastmcp-storage-encryption-key")
        ),
        # A token encrypted under a rotated key reads as absent: the user signs in again.
        raise_on_decryption_error=False,
    )
    return AllowlistedGoogleProvider(
        allowlist=allowlist,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        base_url=os.environ["MCP_BASE_URL"],
        required_scopes=["openid", "email"],
        jwt_signing_key=signing_key,
        client_storage=storage,
    )
