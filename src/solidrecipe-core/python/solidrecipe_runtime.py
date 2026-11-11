"""Local, file-driven preview server. Model files are executed as Python code."""

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def evaluate_model(path, output, parameter_output=None):
    """Run one model in a child process and write its declared shape as a graph."""
    # Each evaluation owns its declarations and receives one immutable override snapshot.
    import solidrecipe as sr

    sr._begin_parameters(json.loads(os.environ.get("SOLIDRECIPE_PARAMETERS", "{}")))
    # Match normal Python script imports, so a model can import modules beside its source.
    # Only the selected model file is watched; imported helpers do not yet trigger a rebuild.
    sys.path.insert(0, str(path.resolve().parent))
    # Compile the current bytes directly; timestamp-based pyc caches can otherwise reuse
    # stale code after rapid edits of the same length.
    namespace = {"__name__": "__solidrecipe_model__", "__file__": str(path)}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    model = namespace.get("model")
    if model is None or not callable(getattr(model, "write_graph", None)):
        raise ValueError("Model file must define a solidrecipe shape named 'model'.")
    model.write_graph(output)
    if parameter_output is not None:
        parameter_output.write_text(
            json.dumps(sr._parameter_definitions(), allow_nan=False)
        )


class Preview:
    """Own the last successful mesh and serialize rebuilds for one watched source file."""

    def __init__(self, model, cli, temp):
        self.model, self.cli, self.temp = model, cli, Path(temp)
        self.lock = threading.Lock()
        self.dirty = threading.Event()
        self.overrides = {}
        self.presets_file = self.model.with_name(self.model.name + ".presets.json")
        self.snapshot = {
            "revision": 0,
            "name": model.name,
            "mesh": None,
            "error": None,
            "building": True,
            "parameters": [],
        }
        self.last_hash = None

    def watch(self):
        """Poll content rather than timestamps, including atomic editor saves."""
        while True:
            try:
                digest = hashlib.sha256(self.model.read_bytes()).digest()
                if digest != self.last_hash or self.dirty.is_set():
                    self.last_hash = digest
                    self.dirty.clear()
                    self.rebuild()
            except OSError as error:
                with self.lock:
                    self.snapshot.update(error=str(error), building=False)
                self.last_hash = None
            time.sleep(0.5)

    def rebuild(self):
        """Publish a new revision only after both model evaluation and tessellation succeed."""
        with self.lock:
            self.snapshot.update(error=None, building=True)
            overrides = self.overrides.copy()
        graph, mesh = self.temp / "graph.json", self.temp / "mesh.obj"
        parameter_output = self.temp / "parameters.json"
        try:
            # Isolate arbitrary model code and kernel evaluation so a failure cannot replace
            # the previous successful mesh or terminate the preview server.
            evaluation = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "solidrecipe_runtime",
                    "evaluate",
                    str(self.model),
                    str(graph),
                    str(parameter_output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    **os.environ,
                    "SOLIDRECIPE_CLI": str(self.cli),
                    "SOLIDRECIPE_PARAMETERS": json.dumps(overrides, allow_nan=False),
                },
            )
            # Forward successful inspection JSONL; capture errors for the viewer.
            if evaluation.stderr:
                sys.stderr.write(evaluation.stderr)
                sys.stderr.flush()
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
                    parameters=json.loads(parameter_output.read_text()),
                    mesh=result,
                    error=None,
                    building=False,
                )
        except (subprocess.SubprocessError, OSError) as error:
            message = getattr(error, "stderr", None) or str(error)
            with self.lock:
                self.snapshot.update(error=message.strip(), building=False)

    def read_presets(self):
        """Presets are a separate, human-readable sidecar beside the source model."""
        if not self.presets_file.exists():
            return {}
        data = json.loads(self.presets_file.read_text())
        if not isinstance(data, dict) or not all(
            isinstance(v, dict) for v in data.values()
        ):
            raise ValueError("Invalid parameter preset file")
        return data

    def save_preset(self, name, values):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Preset name must be 1–100 characters")
        if not isinstance(values, dict):
            raise ValueError("Preset values must be an object")
        # Validate JSON before touching the existing file, then replace it atomically.
        with self.lock:
            presets = self.read_presets()
            presets[name.strip()] = values
            contents = json.dumps(presets, indent=2, allow_nan=False) + "\n"
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.presets_file.parent, delete=False
            ) as temp:
                temporary = Path(temp.name)
                try:
                    temp.write(contents)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.replace(self.presets_file)
            finally:
                temporary.unlink(missing_ok=True)
        return presets


def serve(model, cli, assets, port, open_browser):
    """Serve only embedded viewer files and the selected model's preview on loopback."""
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
                # Reject unexpected hostnames and paths outside the extracted asset directory.
                if self.headers.get("Host", "").split(":")[0] not in (
                    "127.0.0.1",
                    "localhost",
                ):
                    self.send_error(403)
                    return
                path = urlsplit(self.path).path
                if path == "/api/presets":
                    try:
                        data = json.dumps(preview.read_presets()).encode()
                    except (OSError, ValueError) as error:
                        self.send_error(500, str(error))
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
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

            def do_POST(self):
                # Refuse cross-origin writes, including requests from unrelated local sites.
                host = self.headers.get("Host", "")
                if (
                    host
                    not in (
                        f"127.0.0.1:{server.server_port}",
                        f"localhost:{server.server_port}",
                    )
                    or self.headers.get("Origin") != f"http://{host}"
                ):
                    self.send_error(403)
                    return
                if (
                    self.headers.get("Content-Type", "").split(";")[0]
                    != "application/json"
                ):
                    self.send_error(415)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError("Invalid request length")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("Expected a JSON object")
                    path = urlsplit(self.path).path
                    if path == "/api/parameters":
                        values = payload.get("values")
                        if not isinstance(values, dict):
                            raise ValueError("Parameter values must be an object")
                        with preview.lock:
                            known = {p["name"] for p in preview.snapshot["parameters"]}
                            if not set(values).issubset(known):
                                raise ValueError("Unknown parameter")
                            preview.overrides = values.copy()
                            preview.snapshot.update(building=True, error=None)
                            preview.dirty.set()
                        result = {"ok": True}
                    elif path == "/api/presets":
                        result = preview.save_preset(
                            payload.get("name"), payload.get("values")
                        )
                    else:
                        self.send_error(404)
                        return
                    data = json.dumps(result, allow_nan=False).encode()
                except (OSError, ValueError, TypeError) as error:
                    self.send_error(400, str(error))
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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
    build.add_argument("parameter_output", type=Path, nargs="?")
    app = sub.add_parser("serve")
    app.add_argument("model", type=lambda p: Path(p).resolve())
    app.add_argument("cli", type=lambda p: Path(p).resolve())
    app.add_argument("assets", type=lambda p: Path(p).resolve())
    app.add_argument("--port", type=int, default=8765)
    app.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command == "evaluate":
        evaluate_model(args.model, args.output, args.parameter_output)
    else:
        serve(args.model, args.cli, args.assets, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
