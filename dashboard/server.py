"""Loopback-only GET dashboard. No orders, execution, migrations or remote assets."""

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dashboard.data import ResearchStore

STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}


def handler_for(store: ResearchStore):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body: bytes, mime="application/json", download=False):
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="forschungsbericht.md"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def error(self, status, message):
            self.send(status, json.dumps({"error": message}, ensure_ascii=False).encode())

        def do_GET(self):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if (self.headers.get("Host") not in hosts
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"
                    or self.headers.get("Origin", f"http://127.0.0.1:{port}") not in {f"http://{h}" for h in hosts}):
                self.error(403, "Nur lokaler Zugriff ist erlaubt.")
                return
            target = urlsplit(self.path)
            params = parse_qs(target.query, keep_blank_values=True)

            def parameter(name, default=""):
                values = params.get(name, [default])
                if len(values) != 1:
                    raise ValueError("Repeated parameter")
                return values[0]

            try:
                if target.path in STATIC:
                    name, mime = STATIC[target.path]
                    self.send(200, files("dashboard").joinpath("static", name).read_bytes(), mime)
                    return
                if target.path == "/api/catalog":
                    result = {"studies": store.catalog()[0]}
                elif target.path == "/api/run":
                    result = store.run(parameter("run"))
                elif target.path == "/api/trades":
                    result = store.trades(parameter("run"), int(parameter("page", "0")), parameter("outcome", "all"))
                elif target.path == "/api/signals":
                    result = store.signals(parameter("run"), int(parameter("page", "0")), parameter("decision", "all"), parameter("direction", "LONG"))
                elif target.path == "/api/report":
                    self.send(200, store.report(parameter("study")), "text/plain", download=True)
                    return
                else:
                    self.error(404, "Diese Ansicht wurde nicht gefunden.")
                    return
                self.send(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
            except KeyError:
                self.error(404, "Diese Auswertung wurde nicht gefunden.")
            except (ValueError, TypeError):
                self.error(400, "Auswahl oder Forschungsdaten sind ungültig. Bitte eine andere Auswertung wählen.")
            except (OSError, sqlite3.Error):
                self.error(503, "Forschungsdaten momentan nicht lesbar. Bitte erneut laden.")

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            self.error(405, "Diese Übersicht unterstützt ausschließlich lesenden Zugriff.")

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local read-only research dashboard")
    parser.add_argument("--research-root", type=Path, default=Path("data/research"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port in 1024..65535")
    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(ResearchStore(args.research_root))) as server:
            print(f"Forschungsübersicht: http://127.0.0.1:{args.port} (nur lesend)", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Dashboard konnte nicht starten: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
