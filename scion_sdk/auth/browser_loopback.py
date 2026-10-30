"""The loopback HTTP server and handler that receive the OAuth redirect."""

from __future__ import annotations

import logging
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("scion_sdk.auth.browser")


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
