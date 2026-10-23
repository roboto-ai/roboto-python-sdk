# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import hmac
import http
import http.server
import threading
import types
import typing
import urllib.parse

_CALLBACK_PATH = "/callback"

# Only IP-literal loopback is used (RFC 8252 section 8.3): "localhost" can resolve elsewhere, and binding
# 127.0.0.1 keeps the listener unreachable from other machines.
_LOOPBACK_HOST = "127.0.0.1"

# The web app's logo. Its letters are filled with currentColor, so the page's CSS colors them for each color scheme;
# the dot keeps the brand pink.
_LOGO = """<svg class="logo" role="img" aria-label="Roboto" viewBox="0 0 709 166" fill="none">
<g clip-path="url(#clip0_357_2738)">
<path d="M133.13 110.87C133.13 79.3302 156.26 56.2002 189.06 56.2002C221.86 56.2002 244.99 79.3302 244.99
110.87C244.99 142.41 221.86 165.54 189.06 165.54C156.26 165.54 133.13 142.41 133.13 110.87ZM219.55 110.87C219.55
92.5802 207.35 79.5402 189.06 79.5402C170.77 79.5402 158.36 92.5802 158.36 110.87C158.36 129.16 170.77 142.2 189.06
142.2C207.35 142.2 219.55 129.16 219.55 110.87Z" fill="currentColor"/>
<path d="M255.5 110.03V22.2598H280.52V74.0698C287.88 62.5098 300.29 56.1998 315.21 56.1998C340.44 56.1998 366.94
74.2798 366.94 109.82C366.94 142.83 343.81 165.54 310.8 165.54C277.79 165.54 255.5 143.67 255.5 110.03ZM341.71
110.87C341.71 92.5798 329.3 79.5398 311.01 79.5398C292.72 79.5398 280.52 92.5798 280.52 110.87C280.52 129.16 292.72
142.2 311.01 142.2C329.3 142.2 341.71 129.16 341.71 110.87Z" fill="currentColor"/>
<path d="M377.66 110.87C377.66 79.3302 400.79 56.2002 433.59 56.2002C466.39 56.2002 489.52 79.3302 489.52
110.87C489.52 142.41 466.39 165.54 433.59 165.54C400.79 165.54 377.66 142.41 377.66 110.87ZM464.08 110.87C464.08
92.5802 451.88 79.5402 433.59 79.5402C415.3 79.5402 402.89 92.5802 402.89 110.87C402.89 129.16 415.3 142.2 433.59
142.2C451.88 142.2 464.08 129.16 464.08 110.87Z" fill="currentColor"/>
<path d="M501.09 122.86V22.1401H526.11V58.9301H579.73V81.6401H526.11V122.85C526.11 136.73 533.26 142.19 543.56
142.19C553.86 142.19 561.01 136.93 561.01 122.85V120.12H586.03V122.85C586.03 151.66 568.79 165.53 543.55
165.53C518.31 165.53 501.08 151.65 501.08 122.85L501.09 122.86Z" fill="currentColor"/>
<path d="M596.34 110.87C596.34 79.3302 619.47 56.2002 652.27 56.2002C685.07 56.2002 708.2 79.3302 708.2 110.87C708.2
142.41 685.07 165.54 652.27 165.54C619.47 165.54 596.34 142.41 596.34 110.87ZM682.76 110.87C682.76 92.5802 670.56
79.5402 652.27 79.5402C633.98 79.5402 621.57 92.5802 621.57 110.87C621.57 129.16 633.98 142.2 652.27 142.2C670.56
142.2 682.76 129.16 682.76 110.87Z" fill="currentColor"/>
<path d="M0 54.35C0 54.35 6.14 0 61.1 0C95.35 0 122.09 26.22 122.09 60C122.09 77.04 111.77 101.13 93.3 112.23L125.2
163.34L94.56 163.2L62.94 113.08C62.94 113.08 60.4 107.35 62.66 101.93C65.07 96.14 69.1 94.39 71.84 93.6C73.86 93.02
95.84 86.4 95.84 60C95.84 42.35 80.34 25.84 60.69 25.84C37.27 25.84 26.38 47.86 26.38 54.36H0V54.35Z"
fill="currentColor"/>
<path d="M60.1 79.6199C70.2289 79.6199 78.44 71.4088 78.44 61.2799C78.44 51.151 70.2289 42.9399 60.1 42.9399C49.9711
42.9399 41.76 51.151 41.76 61.2799C41.76 71.4088 49.9711 79.6199 60.1 79.6199Z" fill="#DF6888"/>
<path d="M26.3901 70.2202H0.0700684V163.51H26.3901V70.2202Z" fill="currentColor"/>
</g>
<defs>
<clipPath id="clip0_357_2738">
<rect width="708.2" height="165.54" fill="white"/>
</clipPath>
</defs>
</svg>"""

# Colors match the web app's cards in its light and dark themes, picked by the browser's color-scheme preference. The
# page's Content-Security-Policy allows inline styles and nothing else, so the logo is inline SVG and the fonts are
# ones installed on the user's machine.
_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Roboto CLI</title>
<style>
:root {{ --page: #f7f8fa; --card: #fcfcfd; --border: #d9dade; --rule: #e0e1e4; --title: #1e1f23; --text: #333333;
  --logo-letters: #0e0f2f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --page: #202020; --card: #111112; --border: #3a3a3e; --rule: #313134; --title: #eeeeef; --text: #dddddd;
    --logo-letters: #ffffff; }}
}}
body {{ margin: 0; background: var(--page); color: var(--text); font: 16px/1.5 Roboto, Helvetica, Arial, sans-serif; }}
main {{ display: flex; flex-direction: column; align-items: center; gap: 2.5rem; padding: 5rem 1rem; }}
.logo {{ width: 12rem; height: auto; color: var(--logo-letters); }}
.card {{ box-sizing: border-box; width: 100%; max-width: 32rem; border: 1px solid var(--border); border-radius: 8px;
  background: var(--card); }}
.card h1 {{ margin: 0; padding: 1rem 1rem 0.75rem; color: var(--title); font-size: 1.125rem; font-weight: 600; }}
.card p {{ margin: 0; padding: 1rem; border-top: 1px solid var(--rule); }}
</style></head>
<body><main>
{logo}
<div class="card"><h1>{heading}</h1>{paragraph}</div>
</main></body></html>
"""


class LoginTimeoutError(Exception):
    """Raised when no accepted callback arrives before the timeout."""


@dataclasses.dataclass(frozen=True)
class CallbackResult:
    """Outcome of the web app's redirect: exactly one of ``code`` and ``error`` is set."""

    code: typing.Optional[str]
    """Authorization code to redeem for a token. None when the user denied the request."""

    error: typing.Optional[str]
    """Error reported by the web app, such as ``access_denied``. None on approval."""


class LoopbackCallbackServer:
    """HTTP listener on 127.0.0.1 for the web app's redirect after the user approves or denies the credential request.

    Accepts the first ``GET /callback`` whose ``state`` matches ``expected_state`` and rejects everything else,
    so a page in another tab that guesses the port cannot inject a code. The server never logs requests, since
    their query strings carry the authorization code. The port is bound on construction, so :py:attr:`redirect_uri`
    is usable before the listener starts. Use as a context manager: requests are served inside the ``with`` block and
    the listener stops on exit.

    Args:
        expected_state: Value the redirect must echo back in its ``state`` parameter.
        port: Port to bind. 0 lets the operating system pick a free one.
        request_timeout: Seconds a connection may take to send its request before it is dropped. Requests are
            served one at a time, so without this limit any local process could hold a connection open and keep
            the browser's redirect from ever being read.
    """

    def __init__(self, expected_state: str, port: int = 0, request_timeout: float = 5.0) -> None:
        self.__expected_state = expected_state
        self.__request_timeout = request_timeout
        self.__result: typing.Optional[CallbackResult] = None
        self.__received = threading.Event()
        self.__server = http.server.HTTPServer((_LOOPBACK_HOST, port), self.__handler_class())
        self.__thread = threading.Thread(target=self.__server.serve_forever, name="roboto-login-callback", daemon=True)

    @property
    def redirect_uri(self) -> str:
        """URL the web app sends the browser to once the user approves or denies the credential request."""
        port = self.__server.server_address[1]
        return f"http://{_LOOPBACK_HOST}:{port}{_CALLBACK_PATH}"

    def __enter__(self) -> "LoopbackCallbackServer":
        self.__thread.start()
        return self

    def __exit__(
        self,
        exc_type: typing.Optional[type[BaseException]],
        exc: typing.Optional[BaseException],
        tb: typing.Optional[types.TracebackType],
    ) -> None:
        self.__server.shutdown()
        self.__server.server_close()
        self.__thread.join()

    def wait_for_result(self, timeout: typing.Optional[float]) -> CallbackResult:
        """Block until an accepted callback arrives.

        Args:
            timeout: Seconds to wait. None waits indefinitely.

        Returns:
            The accepted callback's code, or the error the web app reported.

        Raises:
            LoginTimeoutError: No accepted callback arrived within ``timeout``.
        """
        if not self.__received.wait(timeout) or self.__result is None:
            raise LoginTimeoutError("The browser didn't send an approval or denial to this machine before the timeout.")
        return self.__result

    def __accept(self, query: dict[str, list[str]]) -> typing.Optional[CallbackResult]:
        """Record the callback if it is the first one with the expected state; return it, or None if rejected."""
        state = _single_value(query, "state")
        if state is None or not hmac.compare_digest(state.encode(), self.__expected_state.encode()):
            return None

        code = _single_value(query, "code")
        error = _single_value(query, "error")
        # HTTPServer handles one request at a time, so no other callback can slip in between this check and the set.
        if (code is None and error is None) or self.__result is not None:
            return None

        self.__result = CallbackResult(code=None if error else code, error=error)
        self.__received.set()
        return self.__result

    def __handler_class(self) -> type[http.server.BaseHTTPRequestHandler]:
        # Bound here: written inside Handler, `__accept` would be name-mangled to `_Handler__accept`.
        accept = self.__accept
        request_timeout = self.__request_timeout

        class Handler(http.server.BaseHTTPRequestHandler):
            # StreamRequestHandler applies this to each connection's socket; a timed-out read ends the request.
            timeout = request_timeout

            def do_GET(self) -> None:
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != _CALLBACK_PATH:
                    self.__respond(http.HTTPStatus.NOT_FOUND, "Not found", "")
                    return

                accepted = accept(urllib.parse.parse_qs(parsed.query))
                if accepted is None:
                    self.__respond(
                        http.HTTPStatus.BAD_REQUEST,
                        "Link not recognized",
                        "This link doesn't match the sign-in the Roboto CLI on this computer is waiting for, so "
                        + "the CLI ignored it. Check your terminal.",
                    )
                elif accepted.error:
                    self.__respond(http.HTTPStatus.OK, "Sign-in denied", "You can close this tab.")
                else:
                    self.__respond(
                        http.HTTPStatus.OK,
                        "Authorization code received",
                        "Your terminal shows whether the sign-in succeeded. You can close this tab.",
                    )

            def log_message(self, format: str, *args: typing.Any) -> None:
                # The default writes each request line, including the authorization code, to stderr.
                pass

            def __respond(self, status: http.HTTPStatus, heading: str, message: str) -> None:
                # An empty <p> would still draw its top border, so a page without a message gets no paragraph.
                paragraph = f"<p>{message}</p>" if message else ""
                body = _PAGE.format(logo=_LOGO, heading=heading, paragraph=paragraph).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _single_value(query: dict[str, list[str]], key: str) -> typing.Optional[str]:
    """Return the parameter's value if it appears exactly once and is non-empty, else None."""
    values = query.get(key, [])
    if len(values) != 1 or not values[0]:
        return None
    return values[0]
