//! Loopback preview server and rebuild coordinator. Python executes model source; Rust owns
//! watching, HTTP, presets, graph evaluation and tessellation. Failed builds keep the last mesh.
use crate::Result;
use pyo3::{
    prelude::*,
    types::{PyDict, PyModule},
};
use serde_json::{json, Value};
use solidrecipe_core::{build, display_mesh, inspect_graph as inspect_brep_graph, BuildCache};
use std::{
    collections::HashMap,
    ffi::OsString,
    fmt::Write as _,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

const POLL: Duration = Duration::from_millis(200);
const MAX_REQUEST: usize = 65_536;

/// In-process Python bridge; geometry remains owned and evaluated by the Rust core.
struct EmbeddedPython {
    runtime: Py<PyModule>,
}

#[pyfunction]
fn inspect_graph(graph: &str) -> PyResult<String> {
    let result = || -> Result<String> {
        let node = serde_json::from_str(graph)?;
        Ok(inspect_brep_graph(&node)?.to_string())
    };
    result().map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// Query prior geometry without serializing its full topology or spawning a process.
#[pyfunction]
fn measure_graph(graph: &str) -> PyResult<String> {
    let result = || -> Result<String> {
        let node = serde_json::from_str(graph)?;
        let body = build(&node)?;
        let (min, max) = body.bounds()?;
        Ok(json!({"bounds": {"min": min, "max": max}, "volume": body.volume(1e-6)?}).to_string())
    };
    result().map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

impl EmbeddedPython {
    fn new() -> std::result::Result<Self, String> {
        Python::attach(|py| -> PyResult<Self> {
            let api = PyModule::from_code(
                py,
                pyo3::ffi::c_str!(include_str!("../../solidrecipe-core/python/solidrecipe.py")),
                pyo3::ffi::c_str!("solidrecipe.py"),
                pyo3::ffi::c_str!("solidrecipe"),
            )?;
            api.setattr("_inspect_graph", wrap_pyfunction!(inspect_graph, &api)?)?;
            api.setattr("_measure_graph", wrap_pyfunction!(measure_graph, &api)?)?;
            let modules = py
                .import("sys")?
                .getattr("modules")?
                .cast_into::<PyDict>()?;
            modules.set_item("solidrecipe", &api)?;
            let runtime = PyModule::from_code(
                py,
                pyo3::ffi::c_str!(include_str!(
                    "../../solidrecipe-core/python/solidrecipe_runtime.py"
                )),
                pyo3::ffi::c_str!("solidrecipe_runtime.py"),
                pyo3::ffi::c_str!("solidrecipe_runtime"),
            )?;
            Ok(Self {
                runtime: runtime.unbind(),
            })
        })
        .map_err(|e| e.to_string())
    }

    fn evaluate(
        &self,
        path: &Path,
        source: &str,
        overrides: &Value,
        selected: Option<&str>,
    ) -> std::result::Result<Value, String> {
        let result = Python::attach(|py| -> PyResult<String> {
            self.runtime
                .bind(py)
                .getattr("evaluate_source")?
                .call1((
                    path.to_string_lossy().as_ref(),
                    source,
                    overrides.to_string(),
                    selected,
                ))?
                .extract()
        })
        .map_err(|e| e.to_string())?;
        serde_json::from_str(&result).map_err(|e| e.to_string())
    }
}

/// One complete, internally consistent result ready to publish to the viewer.
struct BuiltPreview {
    mesh: String,
    parameters: Value,
    cache: Value,
    outputs: Value,
    output: Value,
}

struct State {
    snapshot: Value,
    overrides: Value,
    dirty: bool,
    selected: Option<String>,
}

/// The server keeps paths and mutable state private to one model session.
struct Preview {
    model: PathBuf,
    state: Mutex<State>,
    stop: AtomicBool,
}

impl Preview {
    fn new(model: PathBuf) -> Result<Self> {
        let name = model
            .file_name()
            .ok_or("model has no file name")?
            .to_string_lossy();
        Ok(Self {
            model: model.clone(),
            state: Mutex::new(State {
                snapshot: json!({"revision": 0, "name": name, "mesh": null,
                "error": null, "building": true, "parameters": [], "outputs": [], "output": null}),
                overrides: json!({}),
                dirty: true,
                selected: None,
            }),
            stop: AtomicBool::new(false),
        })
    }

    fn preset_path(&self) -> PathBuf {
        let mut name: OsString = self.model.as_os_str().into();
        name.push(".presets.json");
        PathBuf::from(name)
    }

    fn read_presets(&self) -> std::result::Result<Value, String> {
        let path = self.preset_path();
        let bytes = match fs::read(path) {
            Ok(data) => data,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(json!({})),
            Err(e) => return Err(e.to_string()),
        };
        let value: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        if !value
            .as_object()
            .is_some_and(|v| v.values().all(Value::is_object))
        {
            return Err("Invalid parameter preset file".into());
        }
        Ok(value)
    }

    fn save_preset(
        &self,
        name: &str,
        values: &Value,
        output: &str,
    ) -> std::result::Result<Value, String> {
        let name = name.trim();
        if name.is_empty() || name.chars().count() > 100 || !values.is_object() {
            return Err("Invalid preset name or values".into());
        }
        // Serialize access to the read/modify/write sequence and replace atomically.
        let _guard = self.state.lock().map_err(|e| e.to_string())?;
        let mut presets = self.read_presets()?;
        presets
            .as_object_mut()
            .expect("validated object")
            .insert(name.into(), json!({"output": output, "values": values}));
        let mut bytes = serde_json::to_vec_pretty(&presets).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        let path = self.preset_path();
        let parent = path.parent().ok_or("preset has no parent")?;
        let mut temp = tempfile::NamedTempFile::new_in(parent).map_err(|e| e.to_string())?;
        temp.write_all(&bytes).map_err(|e| e.to_string())?;
        temp.persist(path).map_err(|e| e.to_string())?;
        Ok(presets)
    }

    fn watch(&self) {
        // Store the bytes actually evaluated, including missing files, so edits made
        // during a rebuild and later creation of a missing module are noticed.
        let mut watched: HashMap<PathBuf, Option<Vec<u8>>> = HashMap::new();
        watched.insert(self.model.clone(), None);
        let mut cache = BuildCache::default();
        let python = match EmbeddedPython::new() {
            Ok(python) => python,
            Err(error) => {
                let mut state = self.state.lock().expect("preview state");
                state.snapshot["error"] = json!(error);
                state.snapshot["building"] = json!(false);
                return;
            }
        };
        while !self.stop.load(Ordering::Relaxed) {
            let mut changed = false;
            for (path, previous) in &mut watched {
                let current = fs::read(path).ok();
                if current != *previous {
                    *previous = current;
                    changed = true;
                }
            }
            let job = {
                let mut state = self.state.lock().expect("preview state");
                if changed || state.dirty {
                    state.dirty = false;
                    state.snapshot["building"] = json!(true);
                    state.snapshot["error"] = Value::Null;
                    Some((state.overrides.clone(), state.selected.clone()))
                } else {
                    None
                }
            };
            if let Some((overrides, selected)) = job {
                // Keep the last successful preview on any Python or kernel failure.
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    self.rebuild(
                        &overrides,
                        selected.as_deref(),
                        &mut cache,
                        &python,
                        &mut watched,
                    )
                }))
                .unwrap_or_else(|_| Err("geometry build panicked".into()));
                let mut state = self.state.lock().expect("preview state");
                match result {
                    Ok(built) => {
                        let revision = state.snapshot["revision"].as_u64().unwrap_or(0) + 1;
                        state.snapshot["revision"] = json!(revision);
                        state.snapshot["mesh"] = json!(built.mesh);
                        state.snapshot["parameters"] = built.parameters;
                        state.snapshot["cache"] = built.cache;
                        state.snapshot["outputs"] = built.outputs;
                        state.snapshot["output"] = built.output;
                        state.snapshot["error"] = Value::Null;
                    }
                    Err(error) => state.snapshot["error"] = json!(error),
                }
                state.snapshot["building"] = json!(state.dirty);
            }
            thread::sleep(POLL);
        }
    }

    fn rebuild(
        &self,
        overrides: &Value,
        selected: Option<&str>,
        cache: &mut BuildCache,
        python: &EmbeddedPython,
        watched: &mut HashMap<PathBuf, Option<Vec<u8>>>,
    ) -> std::result::Result<BuiltPreview, String> {
        let source = fs::read_to_string(&self.model).map_err(|e| e.to_string())?;
        let result = python.evaluate(&self.model, &source, overrides, selected)?;
        if let Some(sources) = result["sources"].as_object() {
            *watched = sources
                .iter()
                .map(|(path, source)| {
                    (
                        PathBuf::from(path),
                        source.as_str().map(|s| s.as_bytes().to_vec()),
                    )
                })
                .collect();
        }
        if let Some(error) = result["error"].as_str() {
            return Err(error.to_owned());
        }
        let (body, stats) = cache.build(&result["graph"]).map_err(|e| e.to_string())?;
        let mesh = display_mesh(&body, 100.0).map_err(|e| e.to_string())?;
        let mut obj = String::new();
        for p in &mesh.positions {
            writeln!(obj, "v {} {} {}", p.x, p.y, p.z).map_err(|e| e.to_string())?;
        }
        for t in &mesh.triangles {
            writeln!(obj, "f {} {} {}", t[0] + 1, t[1] + 1, t[2] + 1).map_err(|e| e.to_string())?;
        }
        Ok(BuiltPreview {
            mesh: obj,
            parameters: result["parameters"].clone(),
            cache: json!({"hits": stats.hits, "misses": stats.misses}),
            outputs: result["outputs"].clone(),
            output: result["output"].clone(),
        })
    }
}

fn header<'a>(request: &'a Request, name: &'static str) -> Option<&'a str> {
    request
        .headers()
        .iter()
        .find(|h| h.field.equiv(name))
        .map(|h| h.value.as_str())
}

fn reply(request: Request, status: u16, mime: &str, body: Vec<u8>) {
    let content_type = Header::from_bytes("Content-Type", mime).expect("valid header");
    let no_cache = Header::from_bytes("Cache-Control", "no-store").expect("valid header");
    let _ = request.respond(
        Response::from_data(body)
            .with_status_code(StatusCode(status))
            .with_header(content_type)
            .with_header(no_cache),
    );
}

fn json_reply(request: Request, status: u16, value: &Value) {
    reply(
        request,
        status,
        "application/json",
        value.to_string().into_bytes(),
    );
}

fn handle(mut request: Request, preview: &Preview, assets: &Path, port: u16) {
    let host = header(&request, "Host").unwrap_or("").to_owned();
    if host != format!("127.0.0.1:{port}") && host != format!("localhost:{port}") {
        json_reply(request, 403, &json!({"error":"invalid host"}));
        return;
    }
    let path = request.url().split('?').next().unwrap_or("").to_owned();
    if request.method() == &Method::Get {
        if path == "/api/preview" {
            let value = preview
                .state
                .lock()
                .expect("preview state")
                .snapshot
                .clone();
            json_reply(request, 200, &value);
            return;
        }
        if path == "/api/presets" {
            match preview.read_presets() {
                Ok(v) => json_reply(request, 200, &v),
                Err(e) => json_reply(request, 500, &json!({"error":e})),
            }
            return;
        }
        let rel = if path == "/" {
            "index.html"
        } else {
            path.trim_start_matches('/')
        };
        let candidate = assets.join(rel).canonicalize();
        if let Ok(file) = candidate {
            if file.starts_with(assets) {
                if let Ok(data) = fs::read(&file) {
                    let mime = match file.extension().and_then(|e| e.to_str()) {
                        Some("html") => "text/html; charset=utf-8",
                        Some("js") => "text/javascript; charset=utf-8",
                        Some("css") => "text/css; charset=utf-8",
                        Some("svg") => "image/svg+xml",
                        Some("png") => "image/png",
                        _ => "application/octet-stream",
                    };
                    reply(request, 200, mime, data);
                    return;
                }
            }
        }
        json_reply(request, 404, &json!({"error":"not found"}));
        return;
    }
    if request.method() != &Method::Post {
        json_reply(request, 405, &json!({"error":"method not allowed"}));
        return;
    }
    if header(&request, "Origin") != Some(format!("http://{host}").as_str()) {
        json_reply(request, 403, &json!({"error":"invalid origin"}));
        return;
    }
    if !header(&request, "Content-Type")
        .is_some_and(|v| v.split(';').next() == Some("application/json"))
    {
        json_reply(request, 415, &json!({"error":"expected JSON"}));
        return;
    }
    let length = header(&request, "Content-Length")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(0);
    if length == 0 || length > MAX_REQUEST {
        json_reply(request, 400, &json!({"error":"invalid request length"}));
        return;
    }
    let mut bytes = Vec::with_capacity(length);
    if request
        .as_reader()
        .take(length as u64)
        .read_to_end(&mut bytes)
        .is_err()
        || bytes.len() != length
    {
        json_reply(request, 400, &json!({"error":"incomplete request"}));
        return;
    }
    let payload: Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(e) => {
            json_reply(request, 400, &json!({"error":e.to_string()}));
            return;
        }
    };
    let result = match path.as_str() {
        "/api/parameters" => {
            if let Some(values) = payload.get("values").and_then(Value::as_object) {
                let mut state = preview.state.lock().expect("preview state");
                let target = payload.get("output").and_then(Value::as_str);
                let known_output = target.is_none()
                    || state.snapshot["outputs"]
                        .as_array()
                        .is_some_and(|items| items.iter().any(|item| item.as_str() == target));
                let same_output = target.is_none() || state.snapshot["output"].as_str() == target;
                let known: Vec<_> = state.snapshot["parameters"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|p| p["name"].as_str())
                    .collect();
                if known_output
                    && (!same_output || values.keys().all(|key| known.contains(&key.as_str())))
                {
                    if let Some(output) = target {
                        state.selected = Some(output.to_owned());
                    }
                    state.overrides = json!(values);
                    state.dirty = true;
                    state.snapshot["building"] = json!(true);
                    state.snapshot["error"] = Value::Null;
                    Ok(json!({"ok":true}))
                } else {
                    Err("Unknown parameter".to_owned())
                }
            } else {
                Err("Parameter values must be an object".to_owned())
            }
        }
        "/api/output" => {
            if let Some(name) = payload["name"].as_str() {
                let mut state = preview.state.lock().expect("preview state");
                let known = state.snapshot["outputs"]
                    .as_array()
                    .is_some_and(|items| items.iter().any(|item| item.as_str() == Some(name)));
                if known {
                    state.selected = Some(name.to_owned());
                    // Values from another module need not have the same names or types.
                    state.overrides = json!({});
                    state.dirty = true;
                    state.snapshot["building"] = json!(true);
                    state.snapshot["error"] = Value::Null;
                    Ok(json!({"ok":true}))
                } else {
                    Err("Unknown output".to_owned())
                }
            } else {
                Err("Output name must be a string".to_owned())
            }
        }
        "/api/presets" => {
            let output = payload["output"].as_str().unwrap_or("default");
            preview.save_preset(
                payload["name"].as_str().unwrap_or(""),
                &payload["values"],
                output,
            )
        }
        _ => {
            json_reply(request, 404, &json!({"error":"not found"}));
            return;
        }
    };
    match result {
        Ok(v) => json_reply(request, 200, &v),
        Err(e) => json_reply(request, 400, &json!({"error":e})),
    }
}

/// Serve one model until Ctrl+C, then stop the worker before removing its temporary resources.
pub fn serve(model: PathBuf, resources: PathBuf, port: u16, open_browser: bool) -> Result<()> {
    let assets = resources.join("viewer").canonicalize()?;
    let server = Server::http(("127.0.0.1", port)).map_err(|e| e.to_string())?;
    let port = server
        .server_addr()
        .to_ip()
        .ok_or("expected TCP address")?
        .port();
    let preview = Arc::new(Preview::new(model)?);
    let flag = Arc::clone(&preview);
    ctrlc::set_handler(move || flag.stop.store(true, Ordering::Relaxed))?;
    let watcher = Arc::clone(&preview);
    let worker = thread::spawn(move || watcher.watch());
    let url = format!("http://127.0.0.1:{port}/");
    println!(
        "Watching {}\nViewer: {url}\nPress Ctrl+C to stop.",
        preview.model.display()
    );
    std::io::stdout().flush()?;
    if open_browser {
        open_url(&url);
    }
    while !preview.stop.load(Ordering::Relaxed) {
        if let Some(request) = server.recv_timeout(POLL)? {
            handle(request, &preview, &assets, port);
        }
    }
    let _ = worker.join();
    Ok(())
}

fn open_url(url: &str) {
    if let Err(error) = webbrowser::open(url) {
        eprintln!("Could not open the browser: {error}. Open {url} manually.");
    }
}
