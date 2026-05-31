"""Small stdlib HTTP API for the React UI.

This intentionally avoids adding a Python web-framework dependency during the
security-first React migration. It is a local development API, not a public
internet service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.api.project_service import (
    ProjectServiceError,
    handle_project_apply,
    handle_project_chat,
    list_project_bundle,
    list_projects_payload,
)
from app.llm.pool import get_pool

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class ApiHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local React API."""

    server_version = "CodeTeamApi/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib hook
        self._send_json({}, status=HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json({"status": "ok"})
            elif parsed.path == "/api/capabilities":
                self._send_json(capabilities_payload())
            elif parsed.path == "/api/projects":
                self._send_json({"projects": list_projects_payload()})
            elif parsed.path == "/api/project":
                query = parse_qs(parsed.query)
                path = _first_query_value(query, "path")
                self._send_json(list_project_bundle(path))
            elif parsed.path == "/api/fs/list":
                query = parse_qs(parsed.query)
                self._send_json(list_folders(_first_query_value(query, "path", "")))
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
        except ProjectServiceError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001 - API boundary
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/projects/open":
                path = str(payload.get("path") or "")
                self._send_json(list_project_bundle(path))
            elif parsed.path == "/api/project-chat":
                result = asyncio.run(
                    handle_project_chat(
                        project_path=str(payload.get("projectPath") or ""),
                        message=str(payload.get("message") or ""),
                        max_iterations=int(payload.get("maxIterations") or 3),
                        use_rag=bool(payload.get("useRag", True)),
                        code_backend=str(payload.get("codeBackend") or ""),
                        image_attachment=payload.get("image"),
                    )
                )
                self._send_json(result)
            elif parsed.path == "/api/project-apply":
                result = asyncio.run(
                    handle_project_apply(
                        project_path=str(payload.get("projectPath") or ""),
                        apply_token=str(payload.get("applyToken") or ""),
                    )
                )
                self._send_json(result)
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
        except ProjectServiceError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001 - API boundary
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the local API quieter than BaseHTTPRequestHandler defaults."""
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ProjectServiceError("JSON body must be an object.")
        return data

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "http://127.0.0.1:5173")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()
        if status != HTTPStatus.NO_CONTENT:
            self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)


def capabilities_payload() -> dict[str, Any]:
    """Report which code backends the UI may offer and the default."""
    from app.config import settings
    from app.llm.pool import anthropic_available

    anthropic = anthropic_available()
    default = "anthropic" if (settings.code_backend == "anthropic" and anthropic) else "ollama"
    return {"anthropicAvailable": anthropic, "defaultCodeBackend": default}


def list_folders(path: str) -> dict[str, Any]:
    """Return one level of local folders for the project picker."""
    current = Path(path).expanduser() if path else Path.home()
    current = current.resolve()
    if not current.exists() or not current.is_dir():
        raise ProjectServiceError(f"Folder does not exist: {current}")

    folders = []
    for child in sorted(current.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and not child.name.startswith("."):
            folders.append({"name": child.name, "path": str(child)})
        if len(folders) >= 200:
            break

    return {
        "current": str(current),
        "parent": str(current.parent) if current.parent != current else "",
        "folders": folders,
    }


def _first_query_value(
    query: dict[str, list[str]],
    key: str,
    default: str | None = None,
) -> str:
    values = query.get(key)
    if values and values[0]:
        return values[0]
    if default is not None:
        return default
    raise ProjectServiceError(f"Missing query parameter: {key}")


async def _warm_pool() -> None:
    """Build and warm the process-wide LLM pool once at server startup.

    The pool is a singleton reused by every request, so warming it here means
    request handlers never rebuild or re-warm it. Each request still runs in its
    own asyncio.run() loop; the pool's HTTP client is rebound per loop lazily.
    """
    pool = get_pool()
    await pool.warm_up()
    if pool.is_degraded:
        print(
            "WARNING: LLM pool is degraded; one or more core capabilities "
            "(chat/coder/reasoner) lack a healthy node. Is Ollama running?"
        )
    await pool.aclose()


def main() -> None:
    """Run the local API server."""
    parser = argparse.ArgumentParser(description="Run the Code Team local API.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    asyncio.run(_warm_pool())

    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    print(f"Code Team API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
