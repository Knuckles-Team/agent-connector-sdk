"""Static and session credentials that re-read their secret once after a 401."""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator

import httpx

from agent_connector_sdk.auth.tokens import TokenRequestError
from agent_connector_sdk.auth.values import header_safe

__all__ = ["RotatingAuth", "SessionLoginAuth"]


class RotatingAuth(httpx.Auth):
    """Attaches a static credential and follows a rotated secret.

    ``read`` returns the current secret; ``apply`` writes it onto a request. A
    401 re-reads the secret and, only when it changed, retries the request once,
    so a credential rotated in OpenBao or the environment recovers without a
    restart and a wrong credential is not retried.
    """

    def __init__(
        self,
        read: Callable[[], str],
        apply: Callable[[httpx.Request, str], None],
        *,
        isolates_cookies: bool = False,
    ) -> None:
        self.isolates_cookies = isolates_cookies
        self._read = read
        self._apply = apply
        self._lock = threading.Lock()
        self._secret = header_safe(read(), what="credential")

    def __repr__(self) -> str:
        return "RotatingAuth(credential=<redacted>)"

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Attach the credential; on 401 retry once with a rotated secret."""
        with self._lock:
            used = self._secret
        self._apply(request, used)
        response = yield request
        if response.status_code != 401:
            return
        fresh = header_safe(self._read(), what="credential")
        with self._lock:
            self._secret = fresh
        if fresh != used:
            self._apply(request, fresh)
            yield request


class SessionLoginAuth(httpx.Auth):
    """Cookie-session login: POST credentials, reuse the cookie, re-login once.

    The session cookie is held in memory and attached by this class; it never
    reaches a log or an error. A 401 or 403 after a login clears the session and
    retries once with a fresh login.
    """

    def __init__(
        self,
        *,
        login_path: str,
        username: str,
        password: Callable[[], str],
        username_field: str = "username",
        password_field: str = "password",
    ) -> None:
        self._path = login_path
        self._username = header_safe(username, what="username")
        self._password = password
        self._fields = (username_field, password_field)
        self._cookie = ""
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "SessionLoginAuth(session=<redacted>)"

    def _login_request(self, request: httpx.Request) -> httpx.Request:
        form = {self._fields[0]: self._username, self._fields[1]: self._password()}
        return httpx.Request(
            "POST", request.url.copy_with(path=self._path, query=None), data=form
        )

    def _login(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        response = yield self._login_request(request)
        jar = httpx.Cookies()
        jar.extract_cookies(response)
        pairs = [f"{c.name}={c.value}" for c in jar.jar]
        if response.status_code >= 400 or not pairs:
            raise TokenRequestError("session login was rejected")
        with self._lock:
            self._cookie = "; ".join(pairs)

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Log in when there is no session, attach it, re-login once on 401/403."""
        if not self._cookie:
            yield from self._login(request)
        request.headers["Cookie"] = self._cookie
        response = yield request
        if response.status_code in (401, 403):
            with self._lock:
                self._cookie = ""
            yield from self._login(request)
            request.headers["Cookie"] = self._cookie
            yield request
