"""Browser OAuth (PKCE) login and token lifecycle (SCION-CONNECTOR-CONTROL-R014.11).

Replaces ``agent_utilities.security.browser_auth`` for connectors that let an
operator sign in interactively (leanix). :func:`generate_pkce` makes an S256
verifier and challenge; :class:`BaseBrowserAuthManager` runs the loopback
authorization-code flow, exchanges and refreshes tokens, and keeps them in a
:class:`TokenStore`. The default :class:`FileTokenStore` writes one owner-only
(0600) JSON file per key under the connector config directory. Any object with
``get(key)`` and ``set(key, value)`` may be passed as ``secrets_client``.
The callback handler never logs the request line, which carries the code.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
import stat
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from agent_connector_sdk.config import setting

__all__ = [
    "BaseBrowserAuthManager",
    "BaseLoopbackCallbackHandler",
    "BaseLoopbackCallbackServer",
    "FileTokenStore",
    "TokenStore",
    "generate_pkce",
]

logger = logging.getLogger(__name__)


class TokenStore(Protocol):
    """Where a manager keeps its serialized token set."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class FileTokenStore:
    """Owner-only JSON files, one per key, under ``root``.

    ``root`` defaults to ``agent_connector_sdk.paths.config_dir()/oauth-tokens``.
    Filenames use a digest of the complete key. Legacy sanitized filenames are
    not read because different keys could have shared one file; users must
    sign in again after upgrading.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from agent_connector_sdk.paths import config_dir

            root = config_dir() / "oauth-tokens"
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> str | None:
        try:
            fd = os.open(self._path(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return None
                return handle.read()
        except OSError:
            return None

    def set(self, key: str, value: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self._path(key), flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("token path must be a regular file")
            os.fchmod(fd, 0o600)
            os.ftruncate(fd, 0)
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge using SHA-256 (S256)."""
    verifier = secrets.token_urlsafe(64)
    sha256_hash = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")
    return verifier, challenge


class BaseLoopbackCallbackServer(HTTPServer):
    """Configurable HTTPServer to store authorization code cleanly."""

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.auth_code: str | None = None
        self.expected_state: str | None = None


class BaseLoopbackCallbackHandler(BaseHTTPRequestHandler):
    """Callback request handler for standard OIDC code flow."""

    # Dynamic styling customization options
    redirect_path: str = "/callback"
    success_html: bytes = (
        b"<html><head><style>"
        b"body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        b"background-color: #0f1419; color: #fff; text-align: center; display: flex; "
        b"flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }"
        b".card { background-color: #15181c; border: 1px solid #2f3336; border-radius: 16px; "
        b"padding: 40px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); max-width: 480px; }"
        b"h1 { color: #1d9bf0; margin-top: 0; font-size: 28px; }"
        b"p { color: #8899a6; font-size: 16px; line-height: 1.5; }"
        b".icon { font-size: 48px; margin-bottom: 20px; color: #00ba7c; }"
        b"</style></head><body>"
        b"<div class='card'>"
        b"<div class='icon'>&#10004;</div>"
        b"<h1>Authentication Successful</h1>"
        b"<p>Your application has been authorized successfully. You can now close this tab and return to the terminal.</p>"
        b"</div>"
        b"</body></html>"
    )
    error_html: bytes = (
        b"<html><head><style>"
        b"body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        b"background-color: #0f1419; color: #fff; text-align: center; display: flex; "
        b"flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }"
        b".card { background-color: #15181c; border: 1px solid #2f3336; border-radius: 16px; "
        b"padding: 40px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); max-width: 480px; }"
        b"h1 { color: #f4212e; margin-top: 0; font-size: 28px; }"
        b"p { color: #8899a6; font-size: 16px; line-height: 1.5; }"
        b".icon { font-size: 48px; margin-bottom: 20px; color: #f4212e; }"
        b"</style></head><body>"
        b"<div class='card'>"
        b"<div class='icon'>&#10006;</div>"
        b"<h1>Authentication Failed</h1>"
        b"<p>Missing or invalid authorization parameters. Please try logging in again.</p>"
        b"</div>"
        b"</body></html>"
    )

    def log_message(self, format: str, *args: Any) -> None:
        # BUG-140: BaseHTTPRequestHandler's default log call passes the RAW
        # request line (`self.requestline`) as an arg — for this handler
        # that is the OAuth redirect URI, whose query string carries the
        # authorization `code` and CSRF `state` in the clear
        # (`GET /callback?code=...&state=... HTTP/1.1`). Forwarding
        # `format`/`args` verbatim into `logger.debug` (as this previously
        # did) logs both secrets the moment DEBUG logging is enabled. Never
        # log the request line/args; log only what we can derive safely
        # (method + path with the query string stripped).
        try:
            safe_path = urlparse(self.path).path
        except ValueError:
            safe_path = "<unparsable>"
        logger.debug(
            "Loopback OAuth callback request (method=%s path=%s)",
            self.command,
            safe_path,
        )

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == self.redirect_path:
            query_params = parse_qs(parsed_url.query, keep_blank_values=True)
            states = query_params.get("state", [])
            codes = query_params.get("code", [])
            server = self.server
            if (
                isinstance(server, BaseLoopbackCallbackServer)
                and server.expected_state
                and len(states) == 1
                and secrets.compare_digest(
                    states[0].encode("utf-8"), server.expected_state.encode("utf-8")
                )
                and len(codes) == 1
                and codes[0]
            ):
                server.auth_code = codes[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(self.success_html)
                return

            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(self.error_html)
            return

        self.send_response(404)
        self.end_headers()


class BaseBrowserAuthManager:
    """Generic base class managing browser-based OAuth PKCE authorization, storage, and refresh lifecycle."""

    def __init__(
        self,
        client_id: str,
        auth_endpoint: str,
        token_endpoint: str,
        scopes: str,
        secret_key: str,
        redirect_host: str = "127.0.0.1",
        redirect_port: int = 56122,
        redirect_path: str = "/callback",
        secrets_client: TokenStore | None = None,
        refresh_skew_seconds: int = 120,
        oidc_discovery_url: str | None = None,
        validate_endpoint_fn: Callable[[str, str], str] | None = None,
        extra_auth_params: dict[str, str] | None = None,
        extra_token_params: dict[str, str] | None = None,
        api_key_secret_key: str | None = None,
        api_key_env_var: str | None = None,
    ):
        self.client_id = client_id
        self.auth_endpoint = auth_endpoint
        self.token_endpoint = token_endpoint
        self.scopes = scopes
        self.secret_key = secret_key
        self.redirect_host = redirect_host
        self.redirect_port = redirect_port
        self.redirect_path = redirect_path
        self.secrets_client: TokenStore = secrets_client or FileTokenStore()
        self.refresh_skew_seconds = refresh_skew_seconds
        self.oidc_discovery_url = oidc_discovery_url
        self.validate_endpoint_fn = validate_endpoint_fn
        self.extra_auth_params = extra_auth_params or {}
        self.extra_token_params = extra_token_params or {}
        self.api_key_secret_key = api_key_secret_key
        self.api_key_env_var = api_key_env_var

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.redirect_host}:{self.redirect_port}{self.redirect_path}"

    def get_cached_tokens(self) -> dict[str, Any] | None:
        """Retrieve the stored token set."""
        raw = self.secrets_client.get(self.secret_key)
        if not raw:
            return None
        try:
            tokens: dict[str, Any] = json.loads(raw)
            return tokens
        except Exception as exc:
            logger.warning(
                "Failed to parse cached OAuth tokens for %r: %s", self.secret_key, exc
            )
            return None

    def save_tokens(self, tokens: dict[str, Any]) -> None:
        """Persist the token set."""
        self.secrets_client.set(self.secret_key, json.dumps(tokens))

    def _discover_endpoints(self) -> tuple[str, str]:
        """Perform OIDC Discovery to dynamically resolve auth and token endpoints if URL is configured."""
        if not self.oidc_discovery_url:
            return self.auth_endpoint, self.token_endpoint

        import httpx

        try:
            response = httpx.get(
                self.oidc_discovery_url,
                headers={"Accept": "application/json"},
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json()
            auth_ep = payload.get("authorization_endpoint", self.auth_endpoint)
            token_ep = payload.get("token_endpoint", self.token_endpoint)

            if self.validate_endpoint_fn:
                auth_ep = self.validate_endpoint_fn(auth_ep, "authorization_endpoint")
                token_ep = self.validate_endpoint_fn(token_ep, "token_endpoint")

            return auth_ep, token_ep
        except Exception as exc:
            logger.error(
                "OIDC discovery failed for %s: %s", self.oidc_discovery_url, exc
            )
            # Graceful fallback to initial values
            return self.auth_endpoint, self.token_endpoint

    def refresh_tokens(self, tokens: dict[str, Any]) -> dict[str, Any]:
        """Refresh an expiring or expired access token using refresh_token."""
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh_token found in credentials.")

        _, token_endpoint = self._discover_endpoints()
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        if self.extra_token_params:
            data.update(self.extra_token_params)

        import httpx

        try:
            response = httpx.post(
                token_endpoint,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=data,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.error(
                "OAuth token refresh failed for endpoint %r: %s", token_endpoint, exc
            )
            raise ValueError(f"Failed to refresh tokens: {exc}") from exc

        new_tokens = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", refresh_token),
            "expires_at": time.time() + float(payload.get("expires_in", 3600)),
        }
        self.save_tokens(new_tokens)
        return new_tokens

    def _resolve_api_key(self) -> str | None:
        """Return a configured direct API key, if this manager supports one."""
        if not (self.api_key_secret_key or self.api_key_env_var):
            return None
        stored = (
            self.secrets_client.get(self.api_key_secret_key)
            if self.api_key_secret_key
            else None
        )
        if stored:
            return stored
        return setting(self.api_key_env_var) if self.api_key_env_var else None

    def _load_or_login_tokens(self, auto_login: bool) -> dict[str, Any] | None:
        """Load cached OAuth tokens, optionally recovering through interactive login."""
        tokens = self.get_cached_tokens()
        if tokens or not auto_login:
            return tokens

        logger.info(
            "Cached tokens missing for %r. Triggering interactive login...",
            self.secret_key,
        )
        try:
            return self.login()
        except Exception as exc:
            logger.error("Interactive login flow auto-trigger failed: %s", exc)
            return None

    def _refresh_if_expiring(self, tokens: dict[str, Any]) -> dict[str, Any] | None:
        """Refresh tokens inside the configured skew window, failing closed."""
        expires_at = tokens.get("expires_at", 0.0)
        if time.time() + self.refresh_skew_seconds < expires_at:
            return tokens
        try:
            return self.refresh_tokens(tokens)
        except Exception as exc:
            logger.error("Proactive token refresh failed: %s", exc)
            return None

    def resolve_credentials(self, auto_login: bool = False) -> str | None:
        """Master credential resolver.

        Checks direct API Key overrides first. Otherwise resolves, validates, and
        proactively refreshes stored OAuth tokens.
        """
        api_key = self._resolve_api_key()
        if api_key:
            return api_key

        tokens = self._load_or_login_tokens(auto_login)
        if not tokens:
            return None
        tokens = self._refresh_if_expiring(tokens)
        if not tokens:
            return None
        return tokens.get("access_token")

    def _start_loopback_server(self, state: str) -> BaseLoopbackCallbackServer | None:
        """Start the callback server, falling back when the port is unavailable."""

        class CustomHandler(BaseLoopbackCallbackHandler):
            redirect_path = self.redirect_path

        try:
            server = BaseLoopbackCallbackServer(
                (self.redirect_host, self.redirect_port),
                CustomHandler,
            )
            server.expected_state = state
            server_thread = threading.Thread(target=server.handle_request, daemon=True)
            server_thread.start()
            logger.info("Started loopback HTTP server on port %d", self.redirect_port)
            return server
        except OSError as exc:
            logger.warning(
                "Unable to start loopback server on port %d: %s. Falling back to headless manual paste mode.",
                self.redirect_port,
                exc,
            )
            return None

    def _build_authorization_url(
        self, auth_endpoint: str, challenge: str, state: str | None = None
    ) -> str:
        """Build the authorization URL from the configured PKCE challenge."""
        authorize_params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.extra_auth_params:
            authorize_params.update(self.extra_auth_params)
        if state is not None:
            authorize_params["state"] = state
        return f"{auth_endpoint}?{urlencode(authorize_params)}"

    @staticmethod
    def _announce_authorization(auth_url: str) -> None:
        """Show the authorization URL and attempt to open it in a browser."""
        print("\n" + "=" * 80, file=sys.stderr)
        print("Interactive OAuth Authentication Setup", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        print(
            f"Please navigate to the following link to authenticate:\n\n{auth_url}\n",
            file=sys.stderr,
        )
        print("=" * 80 + "\n", file=sys.stderr)

        with contextlib.suppress(Exception):
            webbrowser.open(auth_url)

    @staticmethod
    def _wait_for_loopback_code(
        server: BaseLoopbackCallbackServer,
    ) -> str | None:
        """Wait briefly for the browser callback to populate the server."""
        wait_limit = 60.0
        start_time = time.time()
        print("Waiting for browser callback authorization...", file=sys.stderr)
        while time.time() - start_time < wait_limit:
            if server.auth_code:
                return server.auth_code
            time.sleep(0.5)
        return None

    @staticmethod
    def _read_manual_code_file() -> str:
        """Wait for and consume the full redirect supplied out of band."""
        from agent_connector_sdk.paths import config_dir

        auth_file_path = str(config_dir() / "browser_auth_code.txt")
        print(
            f"Non-TTY environment detected. Please write the full redirect URL to {auth_file_path}",
            file=sys.stderr,
        )
        print(f"Write the complete callback URL to {auth_file_path}.", file=sys.stderr)

        wait_limit = 300.0
        start_time = time.time()
        while time.time() - start_time < wait_limit:
            if os.path.exists(auth_file_path):
                with open(auth_file_path) as f:
                    code = f.read().strip()
                if code:
                    with contextlib.suppress(OSError):
                        os.remove(auth_file_path)
                    return code
            time.sleep(1.0)

        raise TimeoutError(
            f"Browser callback timed out. Authorization code was not provided in {auth_file_path}."
        )

    @staticmethod
    def _prompt_for_manual_code() -> str | None:
        """Prompt for the complete redirected URL on a TTY."""
        print(
            "Please open the URL above in your local browser, authorize, and then:",
            file=sys.stderr,
        )
        return input("Paste the complete redirected URL: ").strip()

    def _manual_authorization_code(self, redirect: str, state: str) -> str:
        """Refuse manual input unless the redirect and state match this login."""
        try:
            actual = urlparse(redirect)
            expected = urlparse(self.redirect_uri)
            query = parse_qs(actual.query, keep_blank_values=True)
        except ValueError as exc:
            raise ValueError("manual callback is invalid") from exc
        states = query.get("state", [])
        codes = query.get("code", [])
        if (
            (actual.scheme, actual.netloc, actual.path)
            != (expected.scheme, expected.netloc, expected.path)
            or actual.params
            or actual.fragment
            or "error" in query
            or len(states) != 1
            or not secrets.compare_digest(
                states[0].encode("utf-8"), state.encode("utf-8")
            )
            or len(codes) != 1
            or not codes[0]
        ):
            raise ValueError("manual callback is invalid")
        return codes[0]

    def _get_authorization_code(
        self, server: BaseLoopbackCallbackServer | None, state: str
    ) -> str | None:
        """Obtain a loopback code or validate a complete manual redirect."""
        auth_code = self._wait_for_loopback_code(server) if server else None
        if auth_code:
            return auth_code

        print("Loopback server timed out or is unavailable.", file=sys.stderr)
        redirect = (
            self._prompt_for_manual_code()
            if sys.stdin.isatty()
            else self._read_manual_code_file()
        )
        return self._manual_authorization_code(redirect, state) if redirect else None

    def _exchange_authorization_code(
        self,
        token_endpoint: str,
        auth_code: str,
        verifier: str,
        challenge: str,
    ) -> dict[str, Any]:
        """Exchange the authorization code and return the normalized token set."""
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.extra_token_params:
            data.update(self.extra_token_params)

        import httpx

        try:
            response = httpx.post(
                token_endpoint,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data=data,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.error(
                "Token exchange failed for endpoint %r: %s", token_endpoint, exc
            )
            raise ValueError(
                f"Failed to exchange authorization code for tokens: {exc}"
            ) from exc

        return {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", ""),
            "expires_at": time.time() + float(payload.get("expires_in", 3600)),
        }

    def login(self) -> dict[str, Any]:
        """Execute the interactive OAuth PKCE flow."""
        auth_endpoint, token_endpoint = self._discover_endpoints()
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(32)
        server = self._start_loopback_server(state)
        auth_url = self._build_authorization_url(auth_endpoint, challenge, state)
        self._announce_authorization(auth_url)
        auth_code = self._get_authorization_code(server, state)
        if not auth_code:
            raise ValueError("Authentication cancelled or code was not provided.")

        tokens = self._exchange_authorization_code(
            token_endpoint, auth_code, verifier, challenge
        )
        self.save_tokens(tokens)
        print("Successfully authenticated and stored credentials!\n", file=sys.stderr)
        return tokens
