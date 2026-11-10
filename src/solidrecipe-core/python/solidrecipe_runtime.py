"""Local, file-driven preview server. Model files are executed as Python code."""

import argparse
import hashlib
import json
import mimetypes
import runpy
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def evaluate_model(path, output):
    namespace = runpy.run_path(str(path))
    model = namespace.get("model")
    if model is None or not callable(getattr(model, "write_graph", None)):
        raise ValueError("Model file must define a solidrecipe shape named 'model'.")
    model.write_graph(output)


class Preview:
    def __init__(self, model, cli, temp):
        self.model, self.cli, self.temp = model, cli, Path(temp)
        self.lock = threading.Lock()
        self.snapshot = {
            "revision": 0,
            "name": model.name,
            "mesh": None,
            "error": None,
            "building": True,
        }
        self.last_hash = None

    def watch(self):
        while True:
            try:
                digest = hashlib.sha256(self.model.read_bytes()).digest()
                if digest != self.last_hash:
                    self.last_hash = digest
                    self.rebuild()
            except OSError as error:
                with self.lock:
                    self.snapshot.update(error=str(error), building=False)
                self.last_hash = None
            time.sleep(0.5)

    def rebuild(self):
        with self.lock:
            self.snapshot.update(error=None, building=True)
        graph, mesh = self.temp / "graph.json", self.temp / "mesh.obj"
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "solidrecipe_runtime",
                    "evaluate",
                    str(self.model),
                    str(graph),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            subprocess.run(
                [str(self.cli), str(graph), str(mesh)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = mesh.read_text()
            with self.lock:
                self.snapshot.update(
                    revision=self.snapshot["revision"] + 1,
                    mesh=result,
                    error=None,
                    building=False,
                )
        except (subprocess.SubprocessError, OSError) as error:
            message = getattr(error, "stderr", None) or str(error)
            with self.lock:
                self.snapshot.update(error=message.strip(), building=False)


def serve(model, cli, assets, port, open_browser):
    if not model.is_file():
        raise FileNotFoundError(f"Model file not found: {model}")
    if not (assets / "index.html").is_file():
        raise FileNotFoundError(
            f"Viewer build not found in {assets}; run pnpm install and pnpm build in src/solidrecipe-viewer."
        )
    with tempfile.TemporaryDirectory(prefix="solidrecipe-preview-") as temp:
        preview = Preview(model, cli, temp)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Host", "").split(":")[0] not in (
                    "127.0.0.1",
                    "localhost",
                ):
                    self.send_error(403)
                    return
                path = urlsplit(self.path).path
                if path == "/api/preview":
                    with preview.lock:
                        data = json.dumps(preview.snapshot).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                rel = "index.html" if path == "/" else path.lstrip("/")
                file = (assets / rel).resolve()
                if not file.is_relative_to(assets) or not file.is_file():
                    self.send_error(404)
                    return
                data = file.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=preview.watch, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Watching {model}\nViewer: {url}\nPress Ctrl+C to stop.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("evaluate")
    build.add_argument("model", type=Path)
    build.add_argument("output", type=Path)
    app = sub.add_parser("serve")
    app.add_argument("model", type=lambda p: Path(p).resolve())
    app.add_argument("cli", type=lambda p: Path(p).resolve())
    app.add_argument("assets", type=lambda p: Path(p).resolve())
    app.add_argument("--port", type=int, default=8765)
    app.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command == "evaluate":
        evaluate_model(args.model, args.output)
    else:
        serve(args.model, args.cli, args.assets, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
