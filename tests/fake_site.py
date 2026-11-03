"""A local web server that answers like MyAnimeList / Jikan-Edge from the saved fixtures."""

from __future__ import annotations

import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.conftest import read_fixture

MAL = "https://myanimelist.net"


class FakeSite:
    def __init__(self) -> None:
        self.routes: dict[str, list[tuple[int, dict[str, str], bytes]]] = defaultdict(list)
        self.requests: list[str] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                site.requests.append(self.path)
                answers = site.routes.get(self.path)
                if not answers:
                    status, headers, body = 404, {"Content-Type": "text/plain"}, b"not found"
                else:  # answers are used in order; the last one repeats
                    status, headers, body = answers.pop(0) if len(answers) > 1 else answers[0]
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def add(self, path: str, body: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        content_type = "application/json" if body.lstrip().startswith(("{", "[")) else "text/html; charset=utf-8"
        self.routes[path].append((status, {"Content-Type": content_type, **(headers or {})}, body.encode()))

    def add_fixture(self, path: str, fixture: str) -> None:
        """Serve a saved page, with links to MyAnimeList pointing at this server instead."""
        body = read_fixture(fixture)
        if fixture.startswith("html/"):
            body = body.replace(MAL, self.base)
        self.add(path, body)

    def setting_ini(self) -> str:
        return (f"[DATABASE]\nDatabaseName = anime.db\n[MAL]\nBaseUrl = {self.base}\n"
                f"[JIKAN_EDGE]\nBaseUrl = {self.base}/v1\n")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
