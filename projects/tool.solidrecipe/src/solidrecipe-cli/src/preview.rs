//! Loopback preview server and rebuild coordinator. Python executes model source; Rust owns
//! watching, HTTP, presets, graph evaluation and tessellation. Failed builds keep the last mesh.
use crate::Result;
use pyo3::{
    prelude::*,
    types::{PyDict, PyModule},
};
use serde_json::{json, Value};
use solidrecipe_core::{
    build, display_mesh_with_inspection, inspect_graph as inspect_brep_graph, BuildCache,
};
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
    inspection: Value,
    topology: Value,
    selection_error: Value,
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
        // The random temporary name distinguishes revision 1 of this server from
        // revision 1 after restart. The file is immediately removed on drop.
        let session_file = tempfile::Builder::new()
            .prefix("solidrecipe-preview-")
            .tempfile()?;
        let session = session_file
            .path()
            .file_name()
            .ok_or("preview session has no name")?
            .to_string_lossy()
            .to_string();
        drop(session_file);
        let name = model
            .file_name()
            .ok_or("model has no file name")?
            .to_string_lossy();
        Ok(Self {
            model: model.clone(),
            state: Mutex::new(State {
                snapshot: json!({"session": session, "revision": 0, "name": name, "mesh": null,
                "error": null, "building": true, "parameters": [], "outputs": [], "output": null,
                "inspection": null, "topology": null, "selection_error": null, "highlights": {"faces": [], "edges": []}, "selection_revision": 0}),
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
                        state.snapshot["inspection"] = built.inspection;
                        state.snapshot["topology"] = built.topology;
                        state.snapshot["selection_error"] = built.selection_error;
                        // Indices describe the previous result only. Invalidate them atomically
                        // with the new body, even when its visual shape happens to be identical.
                        state.snapshot["highlights"] = json!({"faces": [], "edges": []});
                        state.snapshot["selection_revision"] =
                            json!(state.snapshot["selection_revision"].as_u64().unwrap_or(0) + 1);
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
        let (mesh, inspected) =
            display_mesh_with_inspection(&body, 100.0).map_err(|e| e.to_string())?;
        let (inspection, topology, selection_error) = match inspected {
            Ok(inspection) => match display_topology(&mesh, &inspection) {
                Ok(topology) => (inspection, topology, Value::Null),
                Err(error) => (inspection, Value::Null, json!(error)),
            },
            Err(error) => (Value::Null, Value::Null, json!(error)),
        };
        let obj = display_obj(&mesh)?;
        Ok(BuiltPreview {
            mesh: obj,
            inspection,
            topology,
            selection_error,
            parameters: result["parameters"].clone(),
            cache: json!({"hits": stats.hits, "misses": stats.misses}),
            outputs: result["outputs"].clone(),
            output: result["output"].clone(),
        })
    }
}

/// Keep the kernel's per-face surface normals: mesh vertices are shared within
/// each face but not across faces, so sharp boundaries retain separate normals.
/// OBJ vertex and normal indices both refer to the same position in those arrays.
fn display_obj(mesh: &solidcore_tess::Mesh) -> std::result::Result<String, String> {
    if mesh.normals.len() != mesh.positions.len() {
        return Err("display normals do not match vertices".into());
    }
    let mut obj = String::new();
    for p in &mesh.positions {
        writeln!(obj, "v {} {} {}", p.x, p.y, p.z).map_err(|e| e.to_string())?;
    }
    for n in &mesh.normals {
        writeln!(obj, "vn {} {} {}", n.x, n.y, n.z).map_err(|e| e.to_string())?;
    }
    for t in &mesh.triangles {
        if t.iter()
            .any(|index| *index as usize >= mesh.positions.len())
        {
            return Err("invalid display vertex".into());
        }
        let [a, b, c] = t.map(|index| index + 1);
        writeln!(obj, "f {a}//{a} {b}//{b} {c}//{c}").map_err(|e| e.to_string())?;
    }
    Ok(obj)
}

/// Produce selectable geometry only when it maps completely to the inspected
/// record. An unsupported mapping disables picking but keeps the display mesh.
fn display_topology(
    mesh: &solidcore_tess::Mesh,
    inspection: &Value,
) -> std::result::Result<Value, String> {
    let face_count = inspection["faces"]
        .as_array()
        .ok_or("missing inspected faces")?
        .len();
    let edge_count = inspection["edges"]
        .as_array()
        .ok_or("missing inspected edges")?
        .len();
    if mesh.triangles.len() != mesh.tri_face.len()
        || mesh.edges.len() != edge_count
        || mesh.display_only_edges
    {
        return Err("display topology does not match inspected body".into());
    }
    let mut face_triangles: Vec<Vec<Value>> = vec![Vec::new(); face_count];
    // Missing/inconsistent mapping cannot change the face/edge indices or block
    // the viewer. Treat it as unknown so the frontend uses the polyline fallback.
    let mapping_aligned = mesh.tri_edge.len() == mesh.triangles.len()
        && mesh.tri_edge_segment.len() == mesh.triangles.len()
        && mesh.boundary_complete.len() == face_count;
    let mut face_complete = if mapping_aligned {
        mesh.boundary_complete.clone()
    } else {
        vec![false; face_count]
    };
    let mut face_edge_ids: Vec<Vec<[Option<u32>; 3]>> = vec![Vec::new(); face_count];
    let mut face_segment_ids: Vec<Vec<[Option<u32>; 3]>> = vec![Vec::new(); face_count];
    for (triangle_index, (triangle, face)) in mesh.triangles.iter().zip(&mesh.tri_face).enumerate()
    {
        let vertices = triangle
            .iter()
            .map(|index| {
                mesh.positions
                    .get(*index as usize)
                    .copied()
                    .ok_or("invalid display vertex")
            })
            .collect::<std::result::Result<Vec<_>, _>>()?;
        face_triangles
            .get_mut(*face as usize)
            .ok_or("invalid display face")?
            .push(json!(vertices));
        let face_index = *face as usize;
        let mut ids = if mapping_aligned {
            mesh.tri_edge[triangle_index]
        } else {
            [None; 3]
        };
        let mut segments = if mapping_aligned {
            mesh.tri_edge_segment[triangle_index]
        } else {
            [None; 3]
        };
        // An edge identifier is only usable if this same inspected face uses it.
        // This catches malformed or stale mappings without inventing a relation.
        let incident = inspection["faces"][face_index]["edges"]
            .as_array()
            .ok_or("missing inspected face edges")?;
        if (0..3).any(|side| match (ids[side], segments[side]) {
            (None, None) => false,
            (Some(edge), Some(segment)) => {
                let polyline = mesh.edges.get(edge as usize);
                let endpoints = polyline.and_then(|points| {
                    points
                        .get(segment as usize)
                        .zip(points.get(segment as usize + 1))
                });
                let first = vertices[side];
                let second = vertices[(side + 1) % 3];
                !incident
                    .iter()
                    .any(|candidate| candidate.as_u64() == Some(u64::from(edge)))
                    || !endpoints.is_some_and(|(a, b)| {
                        (*a == first && *b == second) || (*a == second && *b == first)
                    })
            }
            _ => true,
        }) {
            face_complete[face_index] = false;
            ids = [None; 3];
            segments = [None; 3];
        }
        face_edge_ids[face_index].push(ids);
        face_segment_ids[face_index].push(segments);
    }
    // Never expose partial labels as a complete set of boundary edges.
    for ((complete, ids), segments) in face_complete
        .iter()
        .zip(&mut face_edge_ids)
        .zip(&mut face_segment_ids)
    {
        if !complete {
            ids.fill([None; 3]);
            segments.fill([None; 3]);
        }
    }
    Ok(json!({
        "faces": face_triangles.into_iter().zip(face_edge_ids).zip(face_segment_ids).zip(face_complete).enumerate().map(|(index, (((triangles, edge_ids), segment_ids), boundary_complete))| json!({"index": index, "triangles": triangles, "edge_ids": edge_ids, "segment_ids": segment_ids, "boundary_complete": boundary_complete})).collect::<Vec<_>>(),
        "edges": mesh.edges.iter().enumerate().map(|(index, points)| json!({"index": index, "points": points})).collect::<Vec<_>>(),
    }))
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

/// Resolve snapshot-local indices against the topology published with that snapshot.
/// Validate both groups before replacing the existing selection so an invalid request
/// cannot leave a partially updated highlight. These numbers are not persistent IDs.
fn selected_geometry(topology: &Value, payload: &Value) -> std::result::Result<Value, String> {
    let mut result = serde_json::Map::new();
    for group in ["faces", "edges"] {
        let candidates = topology[group]
            .as_array()
            .ok_or("Topology is unavailable")?;
        let indices = payload[group]
            .as_array()
            .ok_or(format!("{group} must be an array"))?;
        let mut chosen = Vec::with_capacity(indices.len());
        let mut seen = std::collections::HashSet::new();
        for value in indices {
            let index = value
                .as_u64()
                .and_then(|n| usize::try_from(n).ok())
                .ok_or(format!("Invalid {group} index"))?;
            if !seen.insert(index) {
                return Err(format!("Duplicate {group} index"));
            }
            let item = candidates
                .get(index)
                .ok_or(format!("Unknown {group} index {index}"))?;
            if item["index"].as_u64() != Some(index as u64) {
                return Err("Topology index mismatch".into());
            }
            chosen.push(item.clone());
        }
        result.insert(group.to_owned(), Value::Array(chosen));
    }
    Ok(Value::Object(result))
}

/// Change highlights only if the complete request refers to this exact result.
fn update_highlights(snapshot: &mut Value, payload: &Value) -> std::result::Result<Value, String> {
    if payload["session"].as_str().is_none()
        || payload["session"] != snapshot["session"]
        || payload["revision"].as_u64().is_none()
        || payload["revision"] != snapshot["revision"]
        || snapshot["topology"].is_null()
    {
        return Err("Stale or unavailable model revision".to_owned());
    }
    let selection = selected_geometry(&snapshot["topology"], payload)?;
    snapshot["highlights"] = selection;
    snapshot["selection_revision"] =
        json!(snapshot["selection_revision"].as_u64().unwrap_or(0) + 1);
    Ok(json!({"ok": true, "selection_revision": snapshot["selection_revision"]}))
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
        "/api/highlights" => {
            let mut state = preview.state.lock().expect("preview state");
            update_highlights(&mut state.snapshot, &payload)
        }
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

#[cfg(test)]
mod selection_tests {
    use super::*;

    #[test]
    fn obj_preserves_surface_normals_and_rejects_inconsistent_meshes() {
        let mut mesh = solidcore_tess::Mesh::default();
        mesh.positions = vec![
            [0., 0., 0.].into(),
            [1., 0., 0.].into(),
            [0., 1., 0.].into(),
        ];
        mesh.normals = vec![[0., 0., 1.].into(); 3];
        mesh.triangles = vec![[0, 1, 2]];
        let obj = display_obj(&mesh).unwrap();
        assert_eq!(
            obj.lines().filter(|line| line.starts_with("vn ")).count(),
            3
        );
        assert!(obj.contains("f 1//1 2//2 3//3\n"));
        mesh.normals.pop();
        assert!(display_obj(&mesh).is_err());
    }

    #[test]
    fn display_topology_pairs_triangle_sides_with_their_snapshot_faces() {
        let mut mesh = solidcore_tess::Mesh::default();
        mesh.positions = vec![
            [0., 0., 0.].into(),
            [1., 0., 0.].into(),
            [0., 1., 0.].into(),
            [0., 0., 1.].into(),
        ];
        mesh.triangles = vec![[0, 1, 2], [0, 1, 3]];
        mesh.tri_face = vec![1, 0];
        mesh.tri_edge = vec![[Some(0), None, Some(1)], [Some(0), None, None]];
        mesh.tri_edge_segment = vec![[Some(0), None, Some(0)], [Some(0), None, None]];
        mesh.boundary_complete = vec![true, true];
        mesh.edges = vec![
            vec![mesh.positions[0], mesh.positions[1]],
            vec![mesh.positions[2], mesh.positions[0]],
        ];
        let inspection = json!({"faces": [{"edges": [0]}, {"edges": [0, 1]}], "edges": [{}, {}]});
        let topology = display_topology(&mesh, &inspection).unwrap();
        assert_eq!(topology["faces"][0]["edge_ids"], json!([[0, null, null]]));
        assert_eq!(topology["faces"][1]["edge_ids"], json!([[0, null, 1]]));
        assert_eq!(topology["faces"][1]["segment_ids"], json!([[0, null, 0]]));
        assert_eq!(topology["faces"][1]["boundary_complete"], true);
        assert_eq!(topology["faces"][1]["triangles"][0][2], json!([0., 1., 0.]));

        // A label from an unrelated face must never be accepted as complete.
        mesh.tri_edge[1] = [Some(1), None, None];
        let invalid = display_topology(&mesh, &inspection).unwrap();
        assert_eq!(invalid["faces"][0]["boundary_complete"], false);
        assert_eq!(invalid["faces"][0]["edge_ids"], json!([[null, null, null]]));
        assert_eq!(
            invalid["faces"][0]["segment_ids"],
            json!([[null, null, null]])
        );
        assert_eq!(invalid["faces"][1]["boundary_complete"], true);

        // A missing mapping is unknown for every face, but the existing viewer
        // still receives the mesh and B-rep edge polylines for fallback.
        mesh.tri_edge.pop();
        let missing = display_topology(&mesh, &inspection).unwrap();
        assert_eq!(missing["faces"][1]["boundary_complete"], false);
        assert_eq!(missing["faces"][1]["edge_ids"], json!([[null, null, null]]));
        assert_eq!(
            missing["faces"][1]["segment_ids"],
            json!([[null, null, null]])
        );
        assert_eq!(missing["edges"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn highlights_require_valid_distinct_indices_in_both_groups() {
        let topology = json!({"faces": [{"index":0,"triangles":[]},{"index":1,"triangles":[]}], "edges": [{"index":0,"points":[]}]});
        let selected = selected_geometry(&topology, &json!({"faces":[1], "edges":[0]})).unwrap();
        assert_eq!(selected["faces"][0]["index"], 1);
        assert_eq!(selected["edges"][0]["index"], 0);
        assert!(selected_geometry(&topology, &json!({"faces":[1], "edges":[1]})).is_err());
        assert!(selected_geometry(&topology, &json!({"faces":[0,0], "edges":[]})).is_err());
        assert!(selected_geometry(&topology, &json!({"faces":[], "edges":[-1]})).is_err());
        assert!(selected_geometry(&topology, &json!({"faces":[]})).is_err());
    }

    #[test]
    fn rejected_revision_or_selection_preserves_existing_highlights() {
        let mut snapshot = json!({"session":"test", "revision": 2, "selection_revision": 4, "highlights": {"faces": [], "edges": []}, "topology": {"faces": [{"index":0,"triangles":[]}], "edges": []}});
        let original = snapshot.clone();
        assert!(update_highlights(
            &mut snapshot,
            &json!({"session":"test", "revision": 1, "faces": [0], "edges": []})
        )
        .is_err());
        assert_eq!(snapshot, original);
        assert!(update_highlights(
            &mut snapshot,
            &json!({"session":"test", "revision": 2, "faces": [0], "edges": [0]})
        )
        .is_err());
        assert_eq!(snapshot, original);
        assert!(update_highlights(
            &mut snapshot,
            &json!({"session":"old", "revision": 2, "faces": [0], "edges": []})
        )
        .is_err());
        assert_eq!(snapshot, original);
        assert!(update_highlights(
            &mut snapshot,
            &json!({"session":"test", "revision": 2, "faces": [0], "edges": []})
        )
        .is_ok());
        assert_eq!(snapshot["selection_revision"], 5);
        assert_eq!(snapshot["highlights"]["faces"][0]["index"], 0);
    }
}
