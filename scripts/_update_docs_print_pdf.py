from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_get_json(url: str):
    with urlopen(url) as resp:  # noqa: S310 (local devtools endpoint)
        data = resp.read().decode("utf-8")
    return json.loads(data)


def _wait_for_devtools(port: int, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_exc: Exception | None = None

    while time.time() < deadline:
        try:
            _http_get_json(f"http://127.0.0.1:{port}/json/version")
            return
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            time.sleep(0.05)

    raise RuntimeError(f"DevTools endpoint did not come up on port {port}: {last_exc}")


async def _print_pdf_via_cdp(*, ws_url: str, html_url: str, pdf_path: Path, footer_label: str) -> None:
    try:
        import websockets  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Missing Python package 'websockets'. Install it into the repo venv via scripts/update-docs.ps1"
        ) from exc

    msg_id = 0

    pending: dict[int, asyncio.Future] = {}

    async def request(ws, method: str, params: dict | None = None) -> dict:
        nonlocal msg_id
        msg_id += 1
        request_id = msg_id

        fut = asyncio.get_running_loop().create_future()
        pending[request_id] = fut

        payload = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        await ws.send(json.dumps(payload))

        resp = await fut
        if not isinstance(resp, dict):
            raise RuntimeError(f"Unexpected CDP response type: {type(resp)}")
        return resp
    load_event = asyncio.Event()

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        async def reader():
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in pending:
                    fut = pending.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)
                    continue

                if msg.get("method") == "Page.loadEventFired":
                    load_event.set()

        async def wait_ready_state_complete(timeout_s: float = 30.0) -> None:
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                resp = await request(
                    ws,
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                try:
                    value = (
                        resp.get("result", {})
                        .get("result", {})
                        .get("value")
                    )
                except Exception:
                    value = None

                if value == "complete":
                    return

                await asyncio.sleep(0.05)

            # Fall back: proceed anyway.
            return

        reader_task = asyncio.create_task(reader())
        try:
            for m in ["Page.enable", "Runtime.enable"]:
                await request(ws, m)

            # The browser is launched directly on html_url; wait for readyState.
            try:
                await asyncio.wait_for(load_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            await wait_ready_state_complete(timeout_s=30)

            footer_template = (
                "<div style=\"font-size:9px; width:100%; padding-right:12px; text-align:right;\">"
                + footer_label
                + " - <span class='pageNumber'></span> of <span class='totalPages'></span></div>"
            )

            resp = await request(
                ws,
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "displayHeaderFooter": True,
                    "headerTemplate": "<div></div>",
                    "footerTemplate": footer_template,
                    "marginTop": 0.4,
                    "marginBottom": 0.6,
                    "marginLeft": 0.4,
                    "marginRight": 0.4,
                    "preferCSSPageSize": True,
                },
            )

            result = resp.get("result") or {}
            data_b64 = result.get("data")
            if not data_b64:
                raise RuntimeError(f"Page.printToPDF returned no data: {resp}")

            pdf_bytes = base64.b64decode(data_b64)
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(pdf_bytes)
        finally:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task


def _as_file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _get_page_ws_url_for_url(port: int, url: str) -> str:
    targets = _http_get_json(f"http://127.0.0.1:{port}/json/list")
    if not isinstance(targets, list):
        raise RuntimeError(f"Unexpected /json/list response: {targets}")

    for t in targets:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "page":
            continue
        if t.get("url") != url:
            continue
        if t.get("webSocketDebuggerUrl"):
            return str(t["webSocketDebuggerUrl"])

    # Fallback: return the first page target.
    for t in targets:
        if isinstance(t, dict) and t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return str(t["webSocketDebuggerUrl"])

    raise RuntimeError(f"No debuggable page target found in /json/list: {targets}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", required=True, help="Path to msedge.exe or chrome.exe")
    parser.add_argument("--html", required=True, help="Path to generated HTML file")
    parser.add_argument("--pdf", required=True, help="Path to output PDF file")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)

    args = parser.parse_args()

    browser = str(args.browser)
    html_path = Path(args.html)
    pdf_path = Path(args.pdf)

    if not html_path.exists():
        raise SystemExit(f"HTML not found: {html_path}")

    port = _pick_free_port()
    user_data_dir = Path(tempfile.mkdtemp(prefix="faceforge-docs-pdf-"))

    html_url = _as_file_url(html_path)

    # Label in footer: "<DocTitle>.<DocExtension> - <PageNumber> of <PageCount>"
    footer_label = pdf_path.name

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={str(user_data_dir)}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                html_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _wait_for_devtools(port, timeout_s=float(args.timeout_seconds))

        ws_url = _get_page_ws_url_for_url(port, html_url)

        # Run the CDP print.
        asyncio.run(
            _print_pdf_via_cdp(ws_url=ws_url, html_url=html_url, pdf_path=pdf_path, footer_label=footer_label)
        )
        return 0
    finally:
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=3)

        try:
            for root, dirs, files in os.walk(user_data_dir, topdown=False):
                for name in files:
                    with contextlib.suppress(Exception):
                        Path(root, name).unlink()
                for name in dirs:
                    with contextlib.suppress(Exception):
                        Path(root, name).rmdir()
            with contextlib.suppress(Exception):
                user_data_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
