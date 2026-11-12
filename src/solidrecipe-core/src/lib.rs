//! Evaluate a small model graph using SolidCore. Display meshes are not CAD geometry.
mod provenance;
use serde_json::Value;
use solidcore_ops::{make_box, make_cylinder, Body};
use solidcore_record::brep::Loop;
use std::{
    collections::{HashMap, HashSet},
    error::Error,
};

/// Propagate kernel, graph, and tessellation errors to the calling interface.
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;

/// Parse the graph's three-dimensional coordinates without silently accepting bad data.
fn vector(v: &Value) -> Result<[f64; 3]> {
    let a = v.as_array().ok_or("expected array")?;
    if a.len() != 3 {
        return Err("expected three coordinates".into());
    }
    Ok([
        a[0].as_f64().ok_or("not a number")?,
        a[1].as_f64().ok_or("not a number")?,
        a[2].as_f64().ok_or("not a number")?,
    ])
}

/// Evaluate a prototype expression graph into a SolidCore B-rep.
///
/// Operands are evaluated independently because SolidCore booleans consume their input bodies.
/// An empty Boolean result is reported as an error; the current graph API has no empty-shape type.
pub fn build(node: &Value) -> Result<Body> {
    Ok(BuildCache::default().build(node)?.0)
}

/// Transform an independently built body; SolidCore uses row-vector affine matrices.
fn transform_body(body: Body, node: &Value, kind: &str) -> Result<Body> {
    let mut matrix = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ];
    if kind == "translate" {
        let [x, y, z] = vector(&node["offset"])?;
        matrix[3] = [x, y, z, 1.0];
    } else {
        let [x, y, z] = vector(&node["factors"])?;
        matrix[0][0] = x;
        matrix[1][1] = y;
        matrix[2][2] = z;
    }
    body.transform(&matrix)?;
    Ok(body)
}

/// A point is accepted only if exactly one edge lies within the requested tolerance.
fn select_blend_edges(body: &Body, node: &Value) -> Result<(solidcore_ops::Order, Vec<usize>)> {
    let tolerance = node["tolerance"].as_f64().ok_or("invalid edge tolerance")?;
    if !tolerance.is_finite() || tolerance <= 0.0 {
        return Err("edge tolerance must be finite and positive".into());
    }
    let points = node["points"].as_array().ok_or("expected edge points")?;
    if points.is_empty() {
        return Err("at least one edge point is required".into());
    }
    let (record, order) = body.to_record()?;
    let mut selected = Vec::with_capacity(points.len());
    for point in points {
        let point = vector(point)?;
        let mut matches = Vec::new();
        for index in 0..record.edges.len() {
            if let Some(found) = body.edge_closest_point(&order, index, point)? {
                if found.distance <= tolerance {
                    matches.push(index);
                }
            }
        }
        if matches.len() != 1 {
            return Err(format!(
                "edge point {point:?} matched {} edges within {tolerance} mm; expected exactly one",
                matches.len()
            )
            .into());
        }
        if selected.contains(&matches[0]) {
            return Err("edge selected more than once".into());
        }
        selected.push(matches[0]);
    }
    Ok((order, selected))
}

/// In-memory B-rep cache keyed by the full serialized expression subtree.
///
/// This tracks geometry equivalence, not persistent feature identity. Operands are copied
/// because SolidCore booleans consume their inputs. Only nodes reachable from the most recent
/// successful graph are retained, so interactive edits cannot grow the cache indefinitely.
#[derive(Default)]
pub struct BuildCache {
    bodies: HashMap<String, Evaluated>,
}

/// Cache reuse counts for a single rebuild, useful for performance diagnostics.
#[derive(Default, Debug, PartialEq, Eq)]
pub struct CacheStats {
    pub hits: usize,
    pub misses: usize,
}

/// Geometry and its topology report must travel together: report indices name
/// entities in this body's record, not entities in an independently evaluated graph.
struct Evaluated {
    body: Body,
    report: Value,
}

impl Evaluated {
    /// Copy for consuming operations and map the report using the kernel's copy map.
    fn copy(&self) -> Result<Self> {
        let (_, source_order) = self.body.to_record()?;
        let (body, mapped_order) = self.body.copy_with_order(&source_order)?;
        let (_, target_order) = body.to_record()?;
        let mut report = self.report.clone();
        for (group, mapping) in [
            (
                "faces",
                mapped_order
                    .faces
                    .iter()
                    .map(|item| target_order.faces.iter().position(|target| target == item))
                    .collect::<Vec<_>>(),
            ),
            (
                "edges",
                mapped_order
                    .edges
                    .iter()
                    .map(|item| target_order.edges.iter().position(|target| target == item))
                    .collect::<Vec<_>>(),
            ),
        ] {
            let old = report[group]
                .as_array()
                .ok_or("missing topology report")?
                .clone();
            if old.len() != mapping.len() {
                return Err("copy changed topology count".into());
            }
            let mut new = vec![Value::Null; old.len()];
            for (index, destination) in mapping.into_iter().enumerate() {
                let destination = destination.ok_or("copy lost topology correspondence")?;
                if destination >= new.len() || !new[destination].is_null() {
                    return Err("copy has ambiguous topology correspondence".into());
                }
                new[destination] = old[index].clone();
                new[destination]["index"] = destination.into();
            }
            report[group] = Value::Array(new);
        }
        // Incidence and measurement fields are regenerated against the copied body's order.
        let current = inspect(&body)?;
        for group in ["faces", "edges"] {
            for (index, entity) in current[group]
                .as_array()
                .ok_or("missing copied topology")?
                .iter()
                .enumerate()
            {
                let identity = report[group][index]["identity"].clone();
                let identities = report[group][index]["identities"].clone();
                report[group][index] = entity.clone();
                if !identity.is_null() {
                    report[group][index]["identity"] = identity;
                }
                if !identities.is_null() {
                    report[group][index]["identities"] = identities;
                }
            }
        }
        Ok(Self { body, report })
    }
}

impl BuildCache {
    /// Build a graph, reusing unchanged subtrees and leaving the previous cache on failure.
    pub fn build(&mut self, node: &Value) -> Result<(Body, CacheStats)> {
        let (result, stats) = self.build_tracked(node)?;
        Ok((result.body, stats))
    }

    fn build_tracked(&mut self, node: &Value) -> Result<(Evaluated, CacheStats)> {
        validate_graph_names(node)?;
        let mut reachable = HashSet::new();
        collect_keys(node, &mut reachable)?;
        let before: HashSet<_> = self.bodies.keys().cloned().collect();
        let mut stats = CacheStats::default();
        match self.evaluate(node, &mut stats) {
            Ok(result) => {
                self.bodies.retain(|key, _| reachable.contains(key));
                Ok((result, stats))
            }
            Err(error) => {
                self.bodies.retain(|key, _| before.contains(key));
                Err(error)
            }
        }
    }

    fn evaluate(&mut self, node: &Value, stats: &mut CacheStats) -> Result<Evaluated> {
        let key = cache_key(node)?;
        if let Some(result) = self.bodies.get(&key) {
            stats.hits += 1;
            return result.copy();
        }
        stats.misses += 1;
        let (body, report) = inspect_tracked(node, self, stats)?;
        let result = Evaluated { body, report };
        self.bodies.insert(key, result.copy()?);
        Ok(result)
    }
}

/// Validate authored names before evaluating or reusing any cached subtree.
/// An occurrence token establishes sharing only within this serialized graph; it
/// is never incorporated into a persistent topology identity.
fn validate_graph_names(root: &Value) -> Result<()> {
    fn visit(
        node: &Value,
        scope: &mut Vec<String>,
        names: &mut HashMap<(Vec<String>, String), Option<u64>>,
        occurrences: &mut HashMap<u64, Value>,
    ) -> Result<()> {
        let occurrence = if node.get("occurrence").is_some() {
            Some(
                node["occurrence"]
                    .as_u64()
                    .ok_or("invalid occurrence token")?,
            )
        } else {
            None
        };
        if let Some(token) = occurrence {
            if let Some(previous) = occurrences.get(&token) {
                if previous != node {
                    return Err("occurrence token identifies different graph nodes".into());
                }
            } else {
                occurrences.insert(token, node.clone());
            }
        }
        let instance = node["kind"] == "instance";
        let name = if instance {
            Some(
                node["name"]
                    .as_str()
                    .filter(|name| !name.trim().is_empty())
                    .ok_or("instance name must be nonempty")?,
            )
        } else {
            match node["metadata"].get("id") {
                Some(value) => Some(
                    value
                        .as_str()
                        .filter(|name| !name.trim().is_empty())
                        .ok_or("feature name must be nonempty")?,
                ),
                None => None,
            }
        };
        if let Some(name) = name {
            let key = (scope.clone(), name.to_owned());
            if let Some(previous) = names.get(&key) {
                // Legacy graphs lack a sharing token, so two declarations cannot
                // safely be assumed to be the same authored feature.
                if occurrence.is_none() || *previous != occurrence {
                    return Err(format!(
                        "duplicate feature or instance name {name:?} in scope {scope:?}"
                    )
                    .into());
                }
            } else {
                names.insert(key, occurrence);
            }
        }
        if instance {
            scope.push(name.expect("validated instance name").to_owned());
        }
        match node["kind"].as_str() {
            Some("instance" | "translate" | "scale" | "fillet" | "chamfer") => {
                visit(&node["body"], scope, names, occurrences)?
            }
            Some("subtract" | "union" | "intersect") => {
                visit(&node["left"], scope, names, occurrences)?;
                visit(&node["right"], scope, names, occurrences)?;
            }
            _ => {}
        }
        if instance {
            scope.pop();
        }
        Ok(())
    }
    visit(
        root,
        &mut Vec::new(),
        &mut HashMap::new(),
        &mut HashMap::new(),
    )
}

/// Occurrences only validate sharing within this graph. Remove them from cache
/// keys so a rebuilt Python graph can reuse the same authored geometry and IDs.
/// Only graph nodes are traversed: an unrelated metadata field named occurrence
/// remains part of the key.
fn cache_key(node: &Value) -> Result<String> {
    fn without_occurrences(node: &Value) -> Value {
        let mut node = node.clone();
        if let Some(object) = node.as_object_mut() {
            object.remove("occurrence");
            let children: &[&str] = match object.get("kind").and_then(Value::as_str) {
                Some("instance" | "translate" | "scale" | "fillet" | "chamfer") => &["body"],
                Some("subtract" | "union" | "intersect") => &["left", "right"],
                _ => &[],
            };
            for child in children {
                if let Some(value) = object.get_mut(*child) {
                    *value = without_occurrences(value);
                }
            }
        }
        node
    }
    Ok(serde_json::to_string(&without_occurrences(node))?)
}

/// A cache hit at an ancestor must not discard its descendants: a later edit may need them.
fn collect_keys(node: &Value, keys: &mut HashSet<String>) -> Result<()> {
    keys.insert(cache_key(node)?);
    if matches!(
        node["kind"].as_str(),
        Some("fillet" | "chamfer" | "translate" | "scale" | "instance")
    ) {
        collect_keys(&node["body"], keys)?;
    } else if matches!(
        node["kind"].as_str(),
        Some("subtract" | "union" | "intersect")
    ) {
        collect_keys(&node["left"], keys)?;
        collect_keys(&node["right"], keys)?;
    }
    Ok(())
}

/// Describe a built B-rep for inspection; record indices apply only to this result.
pub fn inspect(body: &Body) -> Result<Value> {
    let (record, order) = body.to_record()?;
    let (min, max) = body.bounds()?;
    let mut edges = Vec::with_capacity(record.edges.len());
    for (index, edge) in record.edges.iter().enumerate() {
        // Indexes follow this record's canonical order, not a persistent naming scheme.
        let faces: Vec<_> = edge.uses.iter().map(|use_| use_.face).collect();
        edges.push(serde_json::json!({
            "index": index,
            "curve": edge.curve,
            "interval": edge.interval,
            "start": record.vertices[edge.vertices[0] as usize].point,
            "end": record.vertices[edge.vertices[1] as usize].point,
            "midpoint": body.edge_middle(&order, index)?,
            "length": body.edge_length(&order, index, 1e-6)?,
            "adjacent_faces": faces,
        }));
    }
    let mut faces = Vec::with_capacity(record.faces.len());
    for (index, face) in record.faces.iter().enumerate() {
        // A failed optional measurement remains visible instead of hiding the entire body.
        let area = body.face_area(&order, index, 1e-6);
        let (area, area_error) = match area {
            Ok(value) => (Some(value), None),
            Err(error) => (None, Some(error.to_string())),
        };
        let edges: Vec<_> = record
            .edges
            .iter()
            .enumerate()
            .filter_map(|(edge_index, edge)| {
                edge.uses
                    .iter()
                    .any(|use_| use_.face as usize == index)
                    .then_some(edge_index)
            })
            .collect();
        faces.push(serde_json::json!({"index": index, "surface": face.surface,
            "area": area, "area_error": area_error, "edges": edges}));
    }
    Ok(serde_json::json!({
        "schema": "solidrecipe.inspect.v1", "units": "mm", "indices": "temporary",
        "bounds": {"min": min, "max": max}, "volume": body.volume(1e-6)?,
        "edges": edges, "faces": faces,
    }))
}

/// Inspect a named box with stable semantic face and edge identities.
///
/// Identities survive box dimension changes and checked affine transformations. Boolean
/// and blend operations explicitly report unavailable until provenance is implemented.
pub fn inspect_graph(node: &Value) -> Result<Value> {
    Ok(BuildCache::default().build_tracked(node)?.0.report)
}

fn inspect_tracked(
    node: &Value,
    cache: &mut BuildCache,
    stats: &mut CacheStats,
) -> Result<(Body, Value)> {
    if node["kind"] == "instance" {
        let Evaluated { body, mut report } = cache.evaluate(&node["body"], stats)?;
        let name = node["name"]
            .as_str()
            .filter(|name| !name.trim().is_empty())
            .ok_or("instance name must be nonempty")?;
        for group in ["faces", "edges"] {
            for entity in report[group]
                .as_array_mut()
                .ok_or("missing topology report")?
            {
                for key in ["identity", "identities"] {
                    let add_scope = |identity: &mut Value| -> Result<()> {
                        if identity.is_null() {
                            return Ok(());
                        }
                        let object = identity
                            .as_object_mut()
                            .ok_or("invalid topology identity")?;
                        let path = object
                            .entry("instance".to_owned())
                            .or_insert_with(|| Value::Array(Vec::new()));
                        path.as_array_mut()
                            .ok_or("invalid instance identity")?
                            .insert(0, name.into());
                        Ok(())
                    };
                    if key == "identities" {
                        if let Some(ids) = entity[key].as_array_mut() {
                            for identity in ids {
                                add_scope(identity)?;
                            }
                        }
                    } else {
                        add_scope(&mut entity[key])?;
                    }
                }
            }
        }
        return Ok((body, report));
    }
    if let Some(kind @ ("fillet" | "chamfer")) = node["kind"].as_str() {
        let Evaluated {
            body: input,
            report: input_report,
        } = cache.evaluate(&node["body"], stats)?;
        // Keep selection stricter than the kernel's nearest-edge picker.
        select_blend_edges(&input, node)?;
        let points = node["points"]
            .as_array()
            .ok_or("expected edge points")?
            .iter()
            .map(vector)
            .collect::<Result<Vec<_>>>()?;
        let size = node["size"].as_f64().ok_or("invalid blend size")?;
        let (body, history) = provenance::blend(&input, kind, &points, size)?;
        let mut report = inspect(&body)?;
        apply_history(&mut report, &history, &[input_report]);
        return Ok((body, report));
    }
    if let Some(kind @ ("subtract" | "union" | "intersect")) = node["kind"].as_str() {
        let Evaluated {
            body: left,
            report: left_report,
        } = cache.evaluate(&node["left"], stats)?;
        let Evaluated {
            body: right,
            report: right_report,
        } = cache.evaluate(&node["right"], stats)?;
        let operands = [left_report, right_report];
        let op = match kind {
            "subtract" => solidcraft_kernel::BoolOp::Cut,
            "union" => solidcraft_kernel::BoolOp::Union,
            _ => solidcraft_kernel::BoolOp::Intersect,
        };
        let (body, history) = provenance::boolean(&left, &right, op)?;
        let mut report = inspect(&body)?;
        apply_history(&mut report, &history, &operands);
        return Ok((body, report));
    }
    if let Some(kind @ ("translate" | "scale")) = node["kind"].as_str() {
        let Evaluated {
            body,
            report: old_report,
        } = cache.evaluate(&node["body"], stats)?;
        let (_, old_order) = body.to_record()?;
        let body = transform_body(body, node, kind)?;
        let (_, new_order) = body.to_record()?;
        let mut report = inspect(&body)?;
        report["identity_status"] = old_report["identity_status"].clone();
        if old_report["identity_status"] == "exact_named_box"
            || old_report["identity_status"] == "kernel_history"
        {
            for (old, entity) in old_order.faces.iter().enumerate() {
                let new = new_order
                    .faces
                    .iter()
                    .position(|candidate| candidate == entity)
                    .ok_or("transform changed face handles; refusing identities")?;
                report["faces"][new]["identity"] = old_report["faces"][old]["identity"].clone();
                report["faces"][new]["identities"] = old_report["faces"][old]["identities"].clone();
            }
            for (old, entity) in old_order.edges.iter().enumerate() {
                let new = new_order
                    .edges
                    .iter()
                    .position(|candidate| candidate == entity)
                    .ok_or("transform changed edge handles; refusing identities")?;
                report["edges"][new]["identity"] = old_report["edges"][old]["identity"].clone();
                report["edges"][new]["identities"] = old_report["edges"][old]["identities"].clone();
            }
        }
        return Ok((body, report));
    }
    let body = match node["kind"].as_str() {
        Some("box") => make_box(vector(&node["origin"])?, vector(&node["size"])?)?,
        Some("cylinder") => make_cylinder(
            vector(&node["origin"])?,
            node["radius"].as_f64().ok_or("invalid cylinder radius")?,
            node["height"].as_f64().ok_or("invalid cylinder height")?,
        )?,
        _ => return Err("unknown node".into()),
    };
    let mut report = inspect(&body)?;
    report["identity_status"] = Value::String("unavailable".into());
    let Some(name) = node["metadata"]["id"]
        .as_str()
        .filter(|name| !name.is_empty())
    else {
        return Ok((body, report));
    };
    if node["kind"].as_str() != Some("box") {
        return Ok((body, report));
    }
    let (record, _) = body.to_record()?;
    if record.faces.len() != 6 || record.edges.len() != 12 {
        return Err("named box has unexpected topology; refusing identities".into());
    }
    let origin = vector(&node["origin"])?;
    let size = vector(&node["size"])?;
    let labels = [["x_min", "x_max"], ["y_min", "y_max"], ["z_min", "z_max"]];
    let scale = size.iter().fold(1.0_f64, |a, x| a.max(x.abs()));
    let tolerance = scale * 1e-8;
    let mut roles = Vec::new();
    for face in &record.faces {
        let vertices: Vec<_> = face
            .loops
            .iter()
            .flat_map(|boundary| match boundary {
                Loop::Edges { edges } => edges
                    .iter()
                    .flat_map(|edge| record.edges[edge.edge as usize].vertices)
                    .collect::<Vec<_>>(),
                Loop::Vertex { vertex } => vec![*vertex],
            })
            .collect();
        let mut matches = Vec::new();
        for (axis, axis_labels) in labels.iter().enumerate() {
            for (side, label) in axis_labels.iter().enumerate() {
                let coordinate = origin[axis] + if side == 0 { 0.0 } else { size[axis] };
                if !vertices.is_empty()
                    && vertices.iter().all(|v| {
                        (record.vertices[*v as usize].point[axis] - coordinate).abs() <= tolerance
                    })
                {
                    matches.push(*label);
                }
            }
        }
        if matches.len() != 1 || roles.contains(&matches[0]) {
            return Err("named box face roles are not unique; refusing identities".into());
        }
        roles.push(matches[0]);
    }
    for (index, role) in roles.iter().enumerate() {
        report["faces"][index]["identity"] =
            serde_json::json!({"feature":name, "kind":"face", "role":role});
    }
    let mut seen = HashSet::new();
    for (index, edge) in record.edges.iter().enumerate() {
        let mut adjacent: Vec<_> = edge
            .uses
            .iter()
            .map(|usage| roles[usage.face as usize])
            .collect();
        adjacent.sort_unstable();
        adjacent.dedup();
        if adjacent.len() != 2 || !seen.insert(adjacent.clone()) {
            return Err("named box edge roles are not unique; refusing identities".into());
        }
        report["edges"][index]["identity"] =
            serde_json::json!({"feature":name, "kind":"edge", "roles":adjacent});
    }
    report["identity_status"] = Value::String("exact_named_box".into());
    Ok((body, report))
}

/// Compose each kernel-reported origin into this graph node's entity identities.
fn apply_history(
    report: &mut Value,
    history: &solidcraft_kernel::history::History,
    operands: &[Value],
) {
    use solidcraft_kernel::history::{EdgeOrigin, FaceOrigin};
    for (index, face) in history.faces.iter().enumerate() {
        let mut identities = Vec::new();
        for origin in &face.origins {
            if let FaceOrigin::Face { operand, face } = *origin {
                carry_identities(&mut identities, &operands[operand]["faces"][face]);
            }
        }
        attach_identities(&mut report["faces"][index], identities);
    }
    for (index, edge) in history.edges.iter().enumerate() {
        let mut identities = Vec::new();
        for origin in &edge.origins {
            if let EdgeOrigin::Edge { operand, edge } = *origin {
                carry_identities(&mut identities, &operands[operand]["edges"][edge]);
            }
        }
        attach_identities(&mut report["edges"][index], identities);
    }
    report["identity_status"] = Value::String("kernel_history".into());
}

/// Compose the source identity set through a kernel-reported origin.
fn carry_identities(out: &mut Vec<Value>, entity: &Value) {
    if let Some(ids) = entity["identities"].as_array() {
        for id in ids {
            if !out.contains(id) {
                out.push(id.clone());
            }
        }
    } else if !entity["identity"].is_null() && !out.contains(&entity["identity"]) {
        out.push(entity["identity"].clone());
    }
}

/// Retain all origins; the singular field remains compatible for one source.
fn attach_identities(entity: &mut Value, ids: Vec<Value>) {
    if ids.len() == 1 {
        entity["identity"] = ids[0].clone();
    }
    if !ids.is_empty() {
        entity["identities"] = Value::Array(ids);
    }
}

/// Tessellate a B-rep for display, refusing an incomplete mesh.
pub fn display_mesh(body: &Body, size: f64) -> Result<solidcore_tess::Mesh> {
    // Tessellation consumes the neutral record representation for display. The original body
    // remains the geometry authority; a partially meshed result must not look successful.
    let (record, _) = body.to_record()?;
    let tolerance = solidcore_tess::MeshTolerance::display_of(size);
    let (plan, _) = solidcore_tess::plan(&record, &tolerance, size)?;
    let (mesh, refused) = plan.evaluate();
    if !refused.is_empty() {
        return Err(format!("meshing refused {} faces", refused.len()).into());
    }
    Ok(mesh)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn probe_kernel_entity_order_through_affine_transform() -> Result<()> {
        let body = make_box([0.0, 0.0, 0.0], [2.0, 3.0, 4.0])?;
        let (_, before) = body.to_record()?;
        body.transform(&[
            [2.0, 0.0, 0.0, 0.0],
            [0.0, 3.0, 0.0, 0.0],
            [0.0, 0.0, 4.0, 0.0],
            [5.0, -2.0, 10.0, 1.0],
        ])?;
        let (_, after) = body.to_record()?;
        assert_eq!(before.faces.len(), after.faces.len());
        assert_eq!(before.edges.len(), after.edges.len());
        for face in before.faces {
            assert!(after.faces.contains(&face));
        }
        for edge in before.edges {
            assert!(after.edges.contains(&edge));
        }
        Ok(())
    }

    #[test]
    fn named_box_topology_keeps_semantic_ids_across_dimension_changes() -> Result<()> {
        let box_at =
            |size| json!({"kind":"box", "origin":[0,0,0], "size":size, "metadata":{"id":"stock"}});
        let first = inspect_graph(&box_at([2, 3, 4]))?;
        let second = inspect_graph(&box_at([4, 6, 8]))?;
        assert_eq!(first["identity_status"], "exact_named_box");
        for group in ["faces", "edges"] {
            let ids = |report: &Value| -> HashSet<String> {
                report[group]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|item| item["identity"].to_string())
                    .collect()
            };
            assert_eq!(ids(&first), ids(&second));
            assert_eq!(ids(&first).len(), if group == "faces" { 6 } else { 12 });
        }
        let transformed = inspect_graph(
            &json!({"kind":"translate", "body":{"kind":"scale", "body":box_at([2,3,4]), "factors":[2,3,4]}, "offset":[1,0,0]}),
        )?;
        assert_eq!(transformed["identity_status"], "exact_named_box");
        for group in ["faces", "edges"] {
            let ids = |report: &Value| -> HashSet<String> {
                report[group]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|item| item["identity"].to_string())
                    .collect()
            };
            assert_eq!(ids(&first), ids(&transformed));
        }
        let cut = inspect_graph(
            &json!({"kind":"subtract", "left":box_at([2,3,4]), "right":{"kind":"box", "origin":[0,0,0], "size":[1,1,1]}}),
        )?;
        assert_eq!(cut["identity_status"], "kernel_history");
        Ok(())
    }

    #[test]
    fn boolean_graph_propagates_and_splits_identity() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        let cutter =
            json!({"kind":"box", "origin":[5,2,-1], "size":[10,5,12], "metadata":{"id":"cutter"}});
        let graph = json!({"kind":"subtract", "left":stock, "right":cutter});
        let output = inspect_graph(&graph)?;
        let mut counts: HashMap<String, usize> = HashMap::new();
        for face in output["faces"].as_array().unwrap() {
            if let Some(ids) = face["identities"].as_array() {
                for id in ids {
                    *counts.entry(id.to_string()).or_default() += 1;
                }
            }
        }
        assert!(counts.keys().any(|s| s.contains("stock")));
        assert!(counts.keys().any(|s| s.contains("cutter")));
        assert!(
            counts.values().any(|n| *n > 1),
            "split face must retain all descendants"
        );
        Ok(())
    }

    #[test]
    fn blends_propagate_surviving_face_identities() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        for kind in ["fillet", "chamfer"] {
            let graph = json!({"kind":kind, "body":stock, "points":[[0,0,5]], "size":0.5, "tolerance":0.01});
            let report = inspect_graph(&graph)?;
            assert_eq!(report["identity_status"], "kernel_history");
            assert!(report["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| face["identity"]["feature"] == "stock"));
        }
        Ok(())
    }

    #[test]
    fn places_and_scales_geometry_without_modifying_its_cached_source() -> Result<()> {
        let stock = json!({"kind":"box", "origin":[0,0,0], "size":[2,3,4]});
        let scaled = json!({"kind":"scale", "body":stock, "factors":[2,3,4]});
        let moved = json!({"kind":"translate", "body":scaled, "offset":[5,-2,10]});
        let mut cache = BuildCache::default();
        let (body, _) = cache.build(&moved)?;
        let (min, max) = body.bounds()?;
        for (got, expected) in min.iter().zip([5.0, -2.0, 10.0]) {
            assert!((got - expected).abs() < 1e-6);
        }
        for (got, expected) in max.iter().zip([9.0, 7.0, 26.0]) {
            assert!((got - expected).abs() < 1e-6);
        }
        assert!((body.volume(1e-6)? - 576.0).abs() < 1e-5);
        let (original, stats) = cache.build(&stock)?;
        assert_eq!(stats.hits, 1);
        assert!((original.volume(1e-6)? - 24.0).abs() < 1e-6);
        let zero = json!({"kind":"scale", "body":stock, "factors":[1,0,1]});
        assert!(build(&zero).is_err());
        Ok(())
    }

    #[test]
    fn blends_unique_edges_and_rejects_ambiguous_picks() -> Result<()> {
        let block = json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10]});
        for kind in ["fillet", "chamfer"] {
            let graph = json!({"kind":kind, "body":block, "points":[[0,0,5]], "size":1.0, "tolerance":0.01});
            let rounded = build(&graph)?;
            assert!(rounded.volume(1e-6)? < 1000.0);
            assert!(!display_mesh(&rounded, 100.0)?.triangles.is_empty());
            let mut cache = BuildCache::default();
            let (cached, _) = cache.build(&graph)?;
            assert!((cached.volume(1e-6)? - rounded.volume(1e-6)?).abs() < 1e-6);
        }
        let bad = json!({"kind":"fillet", "body":block, "points":[[0,0,0]], "size":1.0, "tolerance":0.01});
        assert!(build(&bad).is_err()); // A vertex belongs to more than one edge.
        Ok(())
    }

    #[test]
    fn evaluates_round_screw_hole() -> Result<()> {
        let graph = json!({"kind":"subtract", "left":{"kind":"box", "origin":[0,0,0], "size":[10,10,5]}, "right":{"kind":"cylinder", "origin":[5,5,-1], "radius":1.75, "height":7}});
        let body = build(&graph)?;
        // This analytic volume checks the cylinder's radius, axis and through-cut.
        let expected = 500.0 - std::f64::consts::PI * 1.75_f64.powi(2) * 5.0;
        assert!((body.volume(1e-6)? - expected).abs() < 1e-3);
        assert!(!display_mesh(&body, 100.0)?.triangles.is_empty());
        Ok(())
    }

    #[test]
    fn instances_scope_identity_and_validate_shared_names() -> Result<()> {
        let stock = json!({"kind":"box", "origin":[0,0,0], "size":[2,3,4], "metadata":{"id":"stock"}, "occurrence":1});
        let inner = json!({"kind":"instance", "name":"inner", "body":stock, "occurrence":2});
        let outer = json!({"kind":"instance", "name":"outer", "body":inner, "occurrence":3});
        let mut cache = BuildCache::default();
        for _ in 0..2 {
            let (result, _) = cache.build_tracked(&outer)?;
            assert_eq!(
                result.report["faces"][0]["identity"]["instance"],
                json!(["outer", "inner"])
            );
            assert!(result.report["faces"][0]["identity"]
                .get("occurrence")
                .is_none());
        }
        let shared = json!({"kind":"union", "left":stock, "right":stock, "occurrence":4});
        validate_graph_names(&shared)?;
        let mut different = shared.clone();
        different["right"]["occurrence"] = json!(5);
        assert!(validate_graph_names(&different).is_err());
        different["right"]["occurrence"] = json!(1);
        different["right"]["size"] = json!([3, 3, 4]);
        assert!(validate_graph_names(&different).is_err());
        let legacy = json!({"kind":"union", "left":{"kind":"box", "metadata":{"id":"same"}}, "right":{"kind":"box", "metadata":{"id":"same"}}});
        assert!(validate_graph_names(&legacy).is_err());
        let distinct_scopes = json!({"kind":"union", "left":{"kind":"instance", "name":"a", "body":stock, "occurrence":6}, "right":{"kind":"instance", "name":"b", "body":stock, "occurrence":7}, "occurrence":8});
        validate_graph_names(&distinct_scopes)?;
        Ok(())
    }

    #[test]
    fn cache_reuses_regenerated_occurrences_but_validates_first() -> Result<()> {
        let stock = json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock", "occurrence":"authored"}, "occurrence":1});
        let cutter = json!({"kind":"box", "origin":[5,2,-1], "size":[10,5,12], "metadata":{"id":"cutter"}, "occurrence":2});
        let graph = json!({"kind":"subtract", "left":stock, "right":cutter, "occurrence":3});
        let mut cache = BuildCache::default();
        let (first, _) = cache.build_tracked(&graph)?;
        let mut rebuilt = graph.clone();
        rebuilt["occurrence"] = json!(30);
        rebuilt["left"]["occurrence"] = json!(10);
        rebuilt["right"]["occurrence"] = json!(20);
        let (second, stats) = cache.build_tracked(&rebuilt)?;
        assert_eq!(stats.hits, 1);
        assert_eq!(first.report, second.report);
        // A cached result must not bypass graph validation when tokens conflict.
        rebuilt["right"]["occurrence"] = json!(10);
        assert!(cache.build_tracked(&rebuilt).is_err());
        // Authored metadata is not an ephemeral graph token.
        rebuilt["right"]["occurrence"] = json!(20);
        rebuilt["left"]["metadata"]["occurrence"] = json!("different");
        assert_ne!(cache_key(&graph)?, cache_key(&rebuilt)?);

        let instance = json!({"kind":"instance", "name":"shared", "body":stock, "occurrence":40});
        let shared = json!({"kind":"subtract", "left":instance, "right":{"kind":"translate", "body":instance, "offset":[5,0,0], "occurrence":41}, "occurrence":42});
        cache.build_tracked(&shared)?;
        let mut duplicate = shared.clone();
        duplicate["right"]["body"]["occurrence"] = json!(43);
        assert_eq!(cache_key(&shared)?, cache_key(&duplicate)?);
        assert!(cache.build_tracked(&duplicate).is_err());
        Ok(())
    }

    #[test]
    fn cached_topology_report_tracks_its_copied_body() -> Result<()> {
        let graph = json!({"kind":"subtract", "left":{"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}}, "right":{"kind":"box", "origin":[5,2,-1], "size":[10,5,12]}});
        let mut cache = BuildCache::default();
        for expected_hits in [0, 1] {
            let (result, stats) = cache.build_tracked(&graph)?;
            assert_eq!(stats.hits, expected_hits);
            let measured = inspect(&result.body)?;
            for group in ["faces", "edges"] {
                for (reported, actual) in result.report[group]
                    .as_array()
                    .unwrap()
                    .iter()
                    .zip(measured[group].as_array().unwrap())
                {
                    for (key, value) in actual.as_object().unwrap() {
                        assert_eq!(
                            &reported[key], value,
                            "{group} {key} must describe the cached body"
                        );
                    }
                }
            }
            assert!(result.report["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| face["identity"]["feature"] == "stock"
                    || face["identities"]
                        .as_array()
                        .is_some_and(|ids| ids.iter().any(|id| id["feature"] == "stock"))));
        }
        Ok(())
    }

    #[test]
    fn cache_reuses_unchanged_branches_and_recovers_after_failure() -> Result<()> {
        let box_node = json!({"kind":"box", "origin":[0,0,0], "size":[12,30,10]});
        let slot = |height| json!({"kind":"box", "origin":[-1,5,2], "size":[9,20,height]});
        let graph = |height| json!({"kind":"subtract", "left":box_node, "right":slot(height)});
        let mut cache = BuildCache::default();
        let (first, cold) = cache.build(&graph(4.6))?;
        assert_eq!(cold.hits, 0);
        let (same, warm) = cache.build(&graph(4.6))?;
        assert_eq!(warm.hits, 1);
        assert!((first.volume(1e-6)? - same.volume(1e-6)?).abs() < 1e-6);
        let (changed, stats) = cache.build(&graph(4.7))?;
        assert_eq!(stats.hits, 1); // The unmodified stock box survived the root cache hit.
        let fresh = build(&graph(4.7))?;
        assert!((changed.volume(1e-6)? - fresh.volume(1e-6)?).abs() < 1e-6);
        assert!(cache.build(&json!({"kind":"unknown"})).is_err());
        let (_, recovered) = cache.build(&graph(4.7))?;
        assert_eq!(recovered.hits, 1);
        Ok(())
    }

    #[test]
    fn evaluates_a_slot_and_its_display_mesh() -> Result<()> {
        let graph = json!({"kind":"subtract", "left":{"kind":"box", "origin":[0,0,0], "size":[12,30,10]}, "right":{"kind":"box", "origin":[-1,5,2], "size":[9,20,4.6]}});
        let body = build(&graph)?;
        // The cutter overlaps 8 × 20 × 4.6 of the 12 × 30 × 10 block.
        assert!((body.volume(1e-6)? - 2864.0).abs() < 1e-6);
        let mesh = display_mesh(&body, 100.0)?;
        assert!(!mesh.triangles.is_empty());
        Ok(())
    }
}
