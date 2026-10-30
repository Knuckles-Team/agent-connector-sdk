"""The interactive authorization-code steps of the browser OAuth flow."""

from __future__ import annotations

import contextlib
import logging
import secrets
import sys
import threading
import time
import webbrowser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from scion_sdk.auth.browser_loopback import (
    BaseLoopbackCallbackHandler,
    BaseLoopbackCallbackServer,
)
from scion_sdk.auth.browser_support import _consume_code_file

logger = logging.getLogger("scion_sdk.auth.browser")


class _AuthorizationCodeFlow:
    """Loopback and manual authorization-code acquisition for a browser manager."""

    client_id: str
    scopes: str
    redirect_host: str
    redirect_port: int
    redirect_path: str
    extra_auth_params: dict[str, str]
    extra_token_params: dict[str, str]

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.redirect_host}:{self.redirect_port}{self.redirect_path}"

    def _start_loopback_server(self, state: str) -> BaseLoopbackCallbackServer | None:
        """Start the callback server, falling back when the port is unavailable."""

        class CustomHandler(BaseLoopbackCallbackHandler):
            redirect_path = self.redirect_path

        try:
            server = BaseLoopbackCallbackServer(
                (self.redirect_host, self.redirect_port),
                CustomHandler,
            )
        except OSError as exc:
            logger.warning(
                "Unable to start loopback server on port %d: %s. Falling back to headless manual paste mode.",
                self.redirect_port,
                exc,
            )
            return None
        server.expected_state = state
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()
        logger.info("Started loopback HTTP server on port %d", self.redirect_port)
        return server

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
        from scion_sdk.paths import config_dir

        auth_file_path = str(config_dir() / "browser_auth_code.txt")
        print(
            f"Non-TTY environment detected. Please write the full redirect URL to {auth_file_path}",
            file=sys.stderr,
        )
        print(f"Write the complete callback URL to {auth_file_path}.", file=sys.stderr)

        wait_limit = 300.0
        start_time = time.time()
        while time.time() - start_time < wait_limit:
            code = _consume_code_file(auth_file_path)
            if code:
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
