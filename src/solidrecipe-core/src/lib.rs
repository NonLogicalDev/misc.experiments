//! Evaluate a small model graph using SolidCore. Display meshes are not CAD geometry.
mod provenance;
pub mod rich_history;
use serde_json::Value;
use solidcore_ops::{make_box, make_cylinder, Body};
use solidcore_record::brep::{Curve, Loop, Surface};
use std::{
    collections::{HashMap, HashSet},
    error::Error,
};

/// Propagate kernel, graph, and tessellation errors to the calling interface.
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;

/// Rebuild a sketch from authored curves and select one closed region.
fn sketch_region(node: &Value) -> Result<solidcore_record::Region2> {
    use solidcore_record::{Seg2, Vec2};
    use solidcraft_sketch::{find_profiles_checked, CurveKind, Sketch};
    let mut sketch = Sketch::new();
    let curves = node["curves"].as_array().ok_or("expected sketch curves")?;
    for value in curves {
        let curve: Seg2 = serde_json::from_value(value.clone())?;
        match curve {
            Seg2::Line { a, b } => {
                sketch.add_line(a, b, None, None, None)?;
            }
            Seg2::Arc {
                center,
                radius,
                start,
                sweep,
            } => {
                if !start.is_finite()
                    || !sweep.is_finite()
                    || !radius.is_finite()
                    || radius <= 0.0
                    || sweep.abs() < 1e-12
                    || sweep.abs() > std::f64::consts::TAU + 1e-12
                {
                    return Err("invalid sketch arc".into());
                }
                if (sweep.abs() - std::f64::consts::TAU).abs() < 1e-12 {
                    sketch.add_circle(center, radius, None, None)?;
                } else {
                    let at = |t: f64| {
                        Vec2::new(center.x + radius * t.cos(), center.y + radius * t.sin())
                    };
                    let (a, b) = if sweep > 0.0 {
                        (at(start), at(start + sweep))
                    } else {
                        (at(start + sweep), at(start))
                    };
                    sketch.add_arc(center, a, b, [None; 3], None)?;
                }
            }
            Seg2::Cubic { p0, p1, p2, p3 } => {
                let mut pts = Vec::new();
                for p in [p0, p1, p2, p3] {
                    pts.push(sketch.add_point(p, None)?);
                }
                sketch.add_curve(
                    CurveKind::Spline {
                        pts,
                        control: true,
                        degree: 3,
                        periodic: false,
                        nurbs: None,
                    },
                    None,
                )?;
            }
            _ => return Err("unsupported sketch curve".into()),
        }
    }
    if let Some(offsets) = node.get("offsets").and_then(Value::as_array) {
        for offset in offsets {
            let distance = offset["distance"]
                .as_f64()
                .ok_or("invalid offset distance")?;
            if !distance.is_finite() || distance == 0.0 {
                return Err("invalid offset distance".into());
            }
            let indices = offset["curves"].as_array().ok_or("invalid offset chain")?;
            let mut chain = Vec::new();
            let mut source = Vec::new();
            for index in indices {
                let i = index.as_u64().ok_or("invalid offset source")? as usize;
                let seg: Seg2 = serde_json::from_value(
                    curves.get(i).ok_or("offset source out of range")?.clone(),
                )?;
                let forward = !matches!(seg, Seg2::Arc { sweep, .. } if sweep < 0.0);
                chain.push((i, forward));
                source.push(seg);
            }
            if source.is_empty() {
                return Err("offset chain is empty".into());
            }
            match source.as_slice() {
                [Seg2::Line { a, b }] => {
                    let dx = b.x - a.x;
                    let dy = b.y - a.y;
                    let length = dx.hypot(dy);
                    if length <= 1e-12 {
                        return Err("cannot offset a zero-length line".into());
                    }
                    let shift = Vec2::new(-dy * distance / length, dx * distance / length);
                    sketch.add_line(*a + shift, *b + shift, None, None, None)?;
                }
                [Seg2::Arc {
                    center,
                    radius,
                    sweep,
                    ..
                }] if (sweep.abs() - std::f64::consts::TAU).abs() < 1e-12 => {
                    let radius = radius - distance * sweep.signum();
                    sketch.add_circle(*center, radius, None, None)?;
                }
                [Seg2::Cubic { .. }] => {
                    sketch.offset_freeform(chain[0].0, chain[0].1, distance)?;
                }
                _ => {
                    sketch.offset_freeform_chain(&chain, distance)?;
                }
            }
        }
    }
    let point: Vec2 = serde_json::from_value(node["point"].clone())?;
    if !point.is_finite() {
        return Err("profile selection point must be finite".into());
    }
    let found = find_profiles_checked(&sketch);
    if found.incomplete {
        return Err("sketch region search exceeded its complexity limit".into());
    }
    let matches: Vec<_> = found
        .profiles
        .iter()
        .filter(|profile| profile.contains(point))
        .collect();
    if matches.len() != 1 {
        return Err(format!(
            "profile point matched {} closed regions; expected exactly one",
            matches.len()
        )
        .into());
    }
    // Containment is sampled. Reject points on or extremely close to a boundary.
    let eps = 1e-7 * (1.0_f64.max(point.x.abs()).max(point.y.abs()));
    let profile = matches[0];
    for (dx, dy) in [(eps, 0.0), (-eps, 0.0), (0.0, eps), (0.0, -eps)] {
        if !profile.contains(Vec2::new(point.x + dx, point.y + dy)) {
            return Err("profile point is on or too close to a region boundary".into());
        }
    }
    Ok(profile.region.clone())
}

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

/// Build a solid from one explicitly authored planar region. The graph retains
/// its profile data, but this operation does not yet assign identities to the
/// resulting faces or claim profile-segment provenance.
fn extrude_profile(node: &Value) -> Result<Body> {
    let plane = if let Some(name) = node["plane"].as_str() {
        solidcore_record::Plane::named(name).ok_or("unknown profile plane")?
    } else {
        serde_json::from_value::<solidcore_record::Plane>(node["plane"].clone())?
    };
    let x = [plane.x.x, plane.x.y, plane.x.z];
    let y = [plane.y.x, plane.y.y, plane.y.z];
    let origin = [plane.origin.x, plane.origin.y, plane.origin.z];
    let dot = |a: [f64; 3], b: [f64; 3]| a.iter().zip(b).map(|(u, v)| u * v).sum::<f64>();
    if !origin.into_iter().chain(x).chain(y).all(f64::is_finite)
        || (dot(x, x) - 1.0).abs() > 1e-9
        || (dot(y, y) - 1.0).abs() > 1e-9
        || dot(x, y).abs() > 1e-9
    {
        return Err("profile plane axes must be finite and orthonormal".into());
    }
    let distance = node["distance"]
        .as_f64()
        .ok_or("invalid extrusion distance")?;
    if !distance.is_finite() || distance <= 0.0 {
        return Err("extrusion distance must be finite and positive".into());
    }
    let region: solidcore_record::Region2 = if node.get("curves").is_some() {
        sketch_region(node)?
    } else {
        serde_json::from_value(node["region"].clone())?
    };
    Ok(solidcore_ops::prism::extrude_planar_regions(
        &plane,
        &[region],
        0.0,
        distance,
    )?)
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
fn select_blend_edges(
    body: &Body,
    record: &solidcore_record::brep::Brep,
    order: &solidcore_ops::Order,
    node: &Value,
) -> Result<(solidcore_ops::Order, Vec<usize>)> {
    let tolerance = node["tolerance"].as_f64().ok_or("invalid edge tolerance")?;
    if !tolerance.is_finite() || tolerance <= 0.0 {
        return Err("edge tolerance must be finite and positive".into());
    }
    let points = node["points"].as_array().ok_or("expected edge points")?;
    if points.is_empty() {
        return Err("at least one edge point is required".into());
    }
    let mut selected = Vec::with_capacity(points.len());
    for point in points {
        let point = vector(point)?;
        let mut matches = Vec::new();
        for index in 0..record.edges.len() {
            if let Some(found) = body.edge_closest_point(order, index, point)? {
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
    Ok((order.clone(), selected))
}

/// Resolve stable identities in the evaluated operand, never an index from a
/// separately evaluated inspection. Split, merged, missing and duplicate picks
/// all fail instead of selecting an arbitrary descendant.
fn select_blend_refs(
    body: &Body,
    record: &solidcore_record::brep::Brep,
    order: &solidcore_ops::Order,
    report: &Value,
    node: &Value,
) -> Result<(solidcore_ops::Order, Vec<usize>)> {
    if node.get("edge_identities").is_none() {
        return select_blend_edges(body, record, order, node);
    }
    if node.get("points").is_some() || node.get("tolerance").is_some() {
        return Err("choose either edge identities or edge points".into());
    }
    let refs = node["edge_identities"]
        .as_array()
        .filter(|refs| !refs.is_empty())
        .ok_or("expected at least one edge identity")?;
    let edges = report["edges"]
        .as_array()
        .ok_or("missing operand edge report")?;
    if edges.len() != order.edges.len() {
        return Err("operand edge report does not match body".into());
    }
    let mut selected = Vec::new();
    for identity in refs {
        if identity["kind"] != "edge" {
            return Err("expected an edge identity".into());
        }
        let mut matches = Vec::new();
        for (index, edge) in edges.iter().enumerate() {
            let mut ids = Vec::new();
            carry_identities(&mut ids, edge);
            if ids.contains(identity) {
                matches.push((index, ids.len()));
            }
        }
        if matches.is_empty() {
            let known = report["tracked_identities"]
                .as_array()
                .is_some_and(|ids| ids.contains(identity));
            return Err(if known {
                "edge identity has no surviving tracked descendant; deleted or untracked"
            } else {
                "edge identity is unknown or unavailable"
            }
            .into());
        }
        if matches.len() > 1 {
            return Err("edge identity is split or ambiguous".into());
        }
        let (index, origins) = matches[0];
        if origins != 1 || edges[index]["merged"] == true {
            return Err("edge identity is merged with other identities".into());
        }
        if selected.contains(&index) {
            return Err("edge selected more than once".into());
        }
        selected.push(index);
    }
    Ok((order.clone(), selected))
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
    record: solidcore_record::brep::Brep,
    order: solidcore_ops::Order,
    report: Value,
}

impl Evaluated {
    /// Copy for consuming operations and map the report using the kernel's copy map.
    fn copy(&self) -> Result<Self> {
        let (body, mapped_order) = self.body.copy_with_order(&self.order)?;
        let (record, target_order) = body.to_record()?;
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
        let current = inspect_record(&body, &record, &target_order)?;
        for group in ["faces", "edges"] {
            for (index, entity) in current[group]
                .as_array()
                .ok_or("missing copied topology")?
                .iter()
                .enumerate()
            {
                let identity = report[group][index]["identity"].clone();
                let identities = report[group][index]["identities"].clone();
                let merged = report[group][index]["merged"].clone();
                let origin_status = report[group][index]["origin_status"].clone();
                report[group][index] = entity.clone();
                if !identity.is_null() {
                    report[group][index]["identity"] = identity;
                }
                if !identities.is_null() {
                    report[group][index]["identities"] = identities;
                }
                if merged == true {
                    report[group][index]["merged"] = merged;
                }
                if !origin_status.is_null() {
                    report[group][index]["origin_status"] = origin_status;
                }
            }
        }
        Ok(Self {
            body,
            record,
            order: target_order,
            report,
        })
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
        let result = inspect_tracked(node, self, stats)?;
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
    inspect_record(body, &record, &order)
}

fn inspect_record(
    body: &Body,
    record: &solidcore_record::brep::Brep,
    order: &solidcore_ops::Order,
) -> Result<Value> {
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
            "midpoint": body.edge_middle(order, index)?,
            "length": body.edge_length(order, index, 1e-6)?,
            "adjacent_faces": faces,
        }));
    }
    let mut faces = Vec::with_capacity(record.faces.len());
    for (index, face) in record.faces.iter().enumerate() {
        // A failed optional measurement remains visible instead of hiding the entire body.
        let area = body.face_area(order, index, 1e-6);
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
        "edges": edges, "faces": faces, "tracked_identities": [],
    }))
}

/// Inspect a graph and report named identities carried by kernel provenance.
///
/// Indices are local to this result. A missing tracked descendant can have been
/// deleted or lost to an untracked operation; generated entities have no stable ID.
pub fn inspect_graph(node: &Value) -> Result<Value> {
    Ok(BuildCache::default().build_tracked(node)?.0.report)
}

fn inspect_tracked(
    node: &Value,
    cache: &mut BuildCache,
    stats: &mut CacheStats,
) -> Result<Evaluated> {
    if node["kind"] == "instance" {
        let Evaluated {
            body,
            record,
            order,
            mut report,
        } = cache.evaluate(&node["body"], stats)?;
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
        for identity in report["tracked_identities"]
            .as_array_mut()
            .ok_or("missing tracked identities")?
        {
            let object = identity.as_object_mut().ok_or("invalid tracked identity")?;
            object
                .entry("instance".to_owned())
                .or_insert_with(|| Value::Array(Vec::new()))
                .as_array_mut()
                .ok_or("invalid instance identity")?
                .insert(0, name.into());
        }
        return Ok(Evaluated {
            body,
            record,
            order,
            report,
        });
    }
    if let Some(kind @ ("fillet" | "chamfer")) = node["kind"].as_str() {
        let Evaluated {
            body: input,
            record: input_record,
            order: input_order,
            report: input_report,
        } = cache.evaluate(&node["body"], stats)?;
        let (order, selected) =
            select_blend_refs(&input, &input_record, &input_order, &input_report, node)?;
        let size = node["size"].as_f64().ok_or("invalid blend size")?;
        let (body, history) =
            provenance::blend(input, &input_record, &order, &selected, kind, size)?;
        let mut report = inspect_record(&body, &history.record, &history.order)?;
        apply_history(&mut report, &history, &[input_report]);
        return Ok(Evaluated {
            body,
            record: history.record,
            order: history.order,
            report,
        });
    }
    if let Some(kind @ ("subtract" | "union" | "intersect")) = node["kind"].as_str() {
        let Evaluated {
            body: left,
            record: left_record,
            order: left_order,
            report: left_report,
        } = cache.evaluate(&node["left"], stats)?;
        let Evaluated {
            body: right,
            record: right_record,
            order: right_order,
            report: right_report,
        } = cache.evaluate(&node["right"], stats)?;
        let operands = [left_report, right_report];
        let op = match kind {
            "subtract" => solidcore_ops::BooleanOp::Subtract,
            "union" => solidcore_ops::BooleanOp::Union,
            _ => solidcore_ops::BooleanOp::Intersect,
        };
        let (body, history) = provenance::boolean(
            left,
            &left_record,
            &left_order,
            right,
            &right_record,
            &right_order,
            op,
        )?;
        let mut report = inspect_record(&body, &history.record, &history.order)?;
        apply_history(&mut report, &history, &operands);
        return Ok(Evaluated {
            body,
            record: history.record,
            order: history.order,
            report,
        });
    }
    if let Some(kind @ ("translate" | "scale")) = node["kind"].as_str() {
        let Evaluated {
            body,
            order: old_order,
            report: old_report,
            ..
        } = cache.evaluate(&node["body"], stats)?;
        let body = transform_body(body, node, kind)?;
        let (record, order) = body.to_record()?;
        let new_order = &order;
        let mut report = inspect_record(&body, &record, &order)?;
        report["identity_status"] = old_report["identity_status"].clone();
        report["tracked_identities"] = old_report["tracked_identities"].clone();
        if old_report["identity_status"] == "exact_named_box"
            || old_report["identity_status"] == "exact_named_cylinder"
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
                report["faces"][new]["merged"] = old_report["faces"][old]["merged"].clone();
                report["faces"][new]["origin_status"] =
                    old_report["faces"][old]["origin_status"].clone();
            }
            for (old, entity) in old_order.edges.iter().enumerate() {
                let new = new_order
                    .edges
                    .iter()
                    .position(|candidate| candidate == entity)
                    .ok_or("transform changed edge handles; refusing identities")?;
                report["edges"][new]["identity"] = old_report["edges"][old]["identity"].clone();
                report["edges"][new]["identities"] = old_report["edges"][old]["identities"].clone();
                report["edges"][new]["merged"] = old_report["edges"][old]["merged"].clone();
                report["edges"][new]["origin_status"] =
                    old_report["edges"][old]["origin_status"].clone();
            }
        }
        return Ok(Evaluated {
            body,
            record,
            order,
            report,
        });
    }
    let body = match node["kind"].as_str() {
        Some("box") => make_box(vector(&node["origin"])?, vector(&node["size"])?)?,
        Some("cylinder") => make_cylinder(
            vector(&node["origin"])?,
            node["radius"].as_f64().ok_or("invalid cylinder radius")?,
            node["height"].as_f64().ok_or("invalid cylinder height")?,
        )?,
        Some("extrude") => extrude_profile(node)?,
        _ => return Err("unknown node".into()),
    };
    let (record, order) = body.to_record()?;
    let mut report = inspect_record(&body, &record, &order)?;
    report["identity_status"] = Value::String("unavailable".into());
    let Some(name) = node["metadata"]["id"]
        .as_str()
        .filter(|name| !name.is_empty())
    else {
        return Ok(Evaluated {
            body,
            record,
            order,
            report,
        });
    };
    if node["kind"] == "cylinder" {
        seed_cylinder_identities(&mut report, &record, node, name)?;
        return Ok(Evaluated {
            body,
            record,
            order,
            report,
        });
    }
    if node["kind"].as_str() != Some("box") {
        return Ok(Evaluated {
            body,
            record,
            order,
            report,
        });
    }
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
    let mut tracked = Vec::new();
    for group in ["faces", "edges"] {
        for entity in report[group].as_array().ok_or("missing topology report")? {
            carry_identities(&mut tracked, entity);
        }
    }
    report["tracked_identities"] = Value::Array(tracked);
    report["identity_status"] = Value::String("exact_named_box".into());
    Ok(Evaluated {
        body,
        record,
        order,
        report,
    })
}

/// Seed only the analytic cap, side, and circular rim identities of a freshly
/// constructed cylinder. Its representation seam has no authored identity.
fn seed_cylinder_identities(
    report: &mut Value,
    record: &solidcore_record::brep::Brep,
    node: &Value,
    name: &str,
) -> Result<()> {
    let origin = vector(&node["origin"])?;
    let radius = node["radius"].as_f64().ok_or("invalid cylinder radius")?;
    let height = node["height"].as_f64().ok_or("invalid cylinder height")?;
    let tolerance = radius.abs().max(height.abs()).max(1.0) * 1e-8;
    let near = |a: f64, b: f64| a.is_finite() && b.is_finite() && (a - b).abs() <= tolerance;
    let parallel_xy = |a: &[f64; 3]| a[2].is_finite() && a[2].abs() <= 1e-10;
    if height <= 2.0 * tolerance
        || radius <= tolerance
        || record.faces.len() != 3
        || record.edges.len() != 3
    {
        return Err("named cylinder topology is unsupported or ambiguous".into());
    }
    let mut roles = Vec::new();
    for face in &record.faces {
        let role = match &face.surface {
            Surface::Cylinder {
                frame,
                radius: actual,
            } if near(*actual, radius)
                && near(frame.origin[0], origin[0])
                && near(frame.origin[1], origin[1])
                && parallel_xy(&frame.x_axis)
                && parallel_xy(&frame.y_axis) =>
            {
                "side"
            }
            Surface::Plane {
                origin: point,
                u_axis,
                v_axis,
            } if parallel_xy(u_axis) && parallel_xy(v_axis) && near(point[2], origin[2]) => "base",
            Surface::Plane {
                origin: point,
                u_axis,
                v_axis,
            } if parallel_xy(u_axis)
                && parallel_xy(v_axis)
                && near(point[2], origin[2] + height) =>
            {
                "top"
            }
            _ => return Err("named cylinder face is unsupported or ambiguous".into()),
        };
        if roles.contains(&role) {
            return Err("named cylinder face roles are ambiguous".into());
        }
        roles.push(role);
    }
    let mut rims = HashSet::new();
    for (index, edge) in record.edges.iter().enumerate() {
        if edge.uses.len() != 2 {
            return Err("named cylinder edge uses are unsupported or ambiguous".into());
        }
        let mut adjacent = Vec::new();
        for usage in &edge.uses {
            let role = *roles
                .get(usage.face as usize)
                .ok_or("invalid cylinder edge adjacency")?;
            if !adjacent.contains(&role) {
                adjacent.push(role);
            }
        }
        adjacent.sort_unstable();
        let rim = match adjacent.as_slice() {
            ["base", "side"] => Some(("base", origin[2])),
            ["side", "top"] => Some(("top", origin[2] + height)),
            ["side"] => None,
            _ => return Err("named cylinder edge adjacency is unsupported or ambiguous".into()),
        };
        if let Some((role, z)) = rim {
            match &edge.curve {
                Curve::Circle {
                    frame,
                    radius: actual,
                } if near(*actual, radius)
                    && near(frame.origin[0], origin[0])
                    && near(frame.origin[1], origin[1])
                    && near(frame.origin[2], z)
                    && parallel_xy(&frame.x_axis)
                    && parallel_xy(&frame.y_axis)
                    && edge.vertices[0] == edge.vertices[1] => {}
                _ => return Err("named cylinder rim is unsupported or ambiguous".into()),
            }
            if !rims.insert(role) {
                return Err("named cylinder rims are ambiguous".into());
            }
            report["edges"][index]["identity"] =
                serde_json::json!({"feature":name,"kind":"edge","roles":adjacent});
        }
    }
    if rims.len() != 2 {
        return Err("named cylinder rims are incomplete".into());
    }
    for (index, role) in roles.iter().enumerate() {
        report["faces"][index]["identity"] =
            serde_json::json!({"feature":name,"kind":"face","role":role});
    }
    let mut tracked = Vec::new();
    for group in ["faces", "edges"] {
        for entity in report[group].as_array().ok_or("missing topology report")? {
            carry_identities(&mut tracked, entity);
        }
    }
    report["tracked_identities"] = Value::Array(tracked);
    report["identity_status"] = "exact_named_cylinder".into();
    Ok(())
}

/// Compose each kernel-reported origin into this graph node's entity identities.
fn apply_history(report: &mut Value, history: &provenance::History, operands: &[Value]) {
    let mut tracked = Vec::new();
    for operand in operands {
        if let Some(identities) = operand["tracked_identities"].as_array() {
            for identity in identities {
                if !tracked.contains(identity) {
                    tracked.push(identity.clone());
                }
            }
        }
    }
    report["tracked_identities"] = Value::Array(tracked);
    for (group, origins) in [("faces", &history.faces), ("edges", &history.edges)] {
        for (index, origins) in origins.iter().enumerate() {
            let mut identities = Vec::new();
            let mut merged = origins.len() > 1;
            let mut untracked = origins.is_empty();
            for &(operand, source) in origins {
                let entity = &operands[operand][group][source];
                carry_identities(&mut identities, entity);
                merged |= entity["merged"] == true;
                untracked |= entity["origin_status"] == "generated or untracked";
            }
            attach_identities(&mut report[group][index], identities);
            if untracked {
                report[group][index]["origin_status"] = "generated or untracked".into();
            }
            if merged {
                report[group][index]["merged"] = true.into();
            }
        }
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
    display_mesh_record(&record, size).map(|(mesh, _)| mesh)
}

/// Produce display geometry and inspection from the same body record and order.
/// Face and edge indexes in the resulting mesh and report are revision-scoped;
/// a separately constructed record is not an identity mapping. Inspection can
/// fail independently of tessellation; retain the display mesh in that case.
pub fn display_mesh_with_inspection(
    body: &Body,
    size: f64,
) -> Result<(solidcore_tess::Mesh, std::result::Result<Value, String>)> {
    let (record, order) = body.to_record()?;
    let report = inspect_record(body, &record, &order).map_err(|error| error.to_string());
    let (mesh, stats) = display_mesh_record(&record, size)?;
    // The planner can return an empty plan for an unmeshed face without the
    // evaluator refusing it. Do not certify a complete selectable topology from
    // that partial display, or from edges that could not be sampled at all.
    Ok((mesh, require_complete_selection(report, &stats)))
}

/// Selection requires every face and edge to have a display representation.
fn require_complete_selection(
    report: std::result::Result<Value, String>,
    stats: &solidcore_tess::PlanStats,
) -> std::result::Result<Value, String> {
    if !stats.unmeshed.is_empty() || !stats.unsampled_edges.is_empty() {
        Err(format!(
            "selectable topology incomplete: {} unmeshed faces, {} unsampled edges",
            stats.unmeshed.len(),
            stats.unsampled_edges.len()
        ))
    } else {
        report
    }
}

fn display_mesh_record(
    record: &solidcore_record::brep::Brep,
    size: f64,
) -> Result<(solidcore_tess::Mesh, solidcore_tess::PlanStats)> {
    let tolerance = solidcore_tess::MeshTolerance::display_of(size);
    let (plan, stats) = solidcore_tess::plan(record, &tolerance, size)?;
    let (mesh, refused) = plan.evaluate();
    if !refused.is_empty() {
        return Err(format!("meshing refused {} faces", refused.len()).into());
    }
    Ok((mesh, stats))
}

#[cfg(test)]
mod tests {

    use super::*;
    use serde_json::json;

    #[test]
    fn incomplete_tessellation_does_not_certify_selection() {
        let mut stats = solidcore_tess::PlanStats::default();
        assert!(require_complete_selection(Ok(json!({})), &stats).is_ok());
        stats.unmeshed.push(solidcore_tess::RefusedFace {
            face: 3,
            reason: "unsupported".into(),
        });
        assert!(require_complete_selection(Ok(json!({})), &stats)
            .unwrap_err()
            .contains("1 unmeshed faces"));
        stats.unmeshed.clear();
        stats.unsampled_edges.push(solidcore_tess::RefusedEdge {
            edge: 4,
            reason: "unsupported".into(),
        });
        assert!(require_complete_selection(Ok(json!({})), &stats)
            .unwrap_err()
            .contains("1 unsampled edges"));
    }

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
    fn named_cylinder_seeds_survive_parameter_edits_and_transforms() -> Result<()> {
        let cylinder = |radius, height| json!({"kind":"cylinder", "origin":[1,2,3], "radius":radius, "height":height, "metadata":{"id":"bore"}});
        let a = inspect_graph(&cylinder(2, 5))?;
        let b = inspect_graph(&cylinder(4, 7))?;
        let moved =
            inspect_graph(&json!({"kind":"translate", "body":cylinder(2, 5), "offset":[10,0,-1]}))?;
        for group in ["faces", "edges"] {
            let ids = |report: &Value| -> HashSet<String> {
                report[group]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|e| !e["identity"].is_null())
                    .map(|e| e["identity"].to_string())
                    .collect()
            };
            assert_eq!(ids(&a), ids(&b));
            assert_eq!(ids(&a), ids(&moved));
            assert_eq!(ids(&a).len(), if group == "faces" { 3 } else { 2 });
        }
        assert_eq!(a["identity_status"], "exact_named_cylinder");
        assert_eq!(a["tracked_identities"].as_array().unwrap().len(), 5);
        assert_eq!(
            a["edges"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|e| e["identity"].is_null())
                .count(),
            1
        );
        Ok(())
    }

    #[test]
    fn named_cylinder_rejects_ambiguous_or_unsupported_topology() -> Result<()> {
        let node = json!({"kind":"cylinder", "origin":[1,2,3], "radius":2, "height":5, "metadata":{"id":"bore"}});
        let body = make_cylinder([1.0, 2.0, 3.0], 2.0, 5.0)?;
        let (mut record, order) = body.to_record()?;
        let mut report = inspect_record(&body, &record, &order)?;
        record.faces[1] = record.faces[2].clone();
        assert!(seed_cylinder_identities(&mut report, &record, &node, "bore").is_err());
        let (mut record, _) = body.to_record()?;
        record.edges.pop();
        assert!(seed_cylinder_identities(&mut report, &record, &node, "bore").is_err());
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
    fn intersection_tracks_both_operand_faces() -> Result<()> {
        let a = json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"a"}});
        let b = json!({"kind":"box", "origin":[5,2,-1], "size":[10,5,12], "metadata":{"id":"b"}});
        let report = inspect_graph(&json!({"kind":"intersect", "left":a, "right":b}))?;
        for feature in ["a", "b"] {
            assert!(
                report["faces"].as_array().unwrap().iter().any(|face| {
                    let mut ids = Vec::new();
                    carry_identities(&mut ids, face);
                    ids.iter().any(|id| id["feature"] == feature)
                }),
                "intersection must retain faces from {feature}"
            );
        }
        Ok(())
    }

    #[test]
    fn shared_instanced_branches_and_parameter_edits_resolve_on_actual_body() -> Result<()> {
        let model = |size| {
            let part = json!({"kind":"box", "origin":[0,0,0], "size":[size,10,10], "metadata":{"id":"part"}, "occurrence":1});
            let stock = json!({"kind":"instance", "name":"stock", "body":part, "occurrence":2});
            let tool = json!({"kind":"instance", "name":"tool", "body":part, "occurrence":3});
            json!({"kind":"subtract", "left":stock, "right":{"kind":"translate", "body":tool, "offset":[5,2,-1], "occurrence":4}, "occurrence":5})
        };
        let identity = json!({"feature":"part", "kind":"edge", "roles":["x_min","y_min"], "instance":["stock"]});
        let mut cache = BuildCache::default();
        for size in [10, 12] {
            let graph = model(size);
            let (result, _) = cache.build_tracked(&graph)?;
            assert!(result.report["tracked_identities"]
                .as_array()
                .unwrap()
                .iter()
                .any(|id| id["instance"] == json!(["tool"])));
            let blend =
                json!({"kind":"fillet", "body":graph, "edge_identities":[identity], "size":0.25});
            let (result, _) = cache.build_tracked(&blend)?;
            assert!(result.report["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| face["origin_status"] == "generated or untracked"));
            // The cached copy must retain explicit uncertainty about untagged entities.
            let (cached, stats) = cache.build_tracked(&blend)?;
            assert_eq!(stats.hits, 1);
            assert!(cached.report["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| face["origin_status"] == "generated or untracked"));
        }
        Ok(())
    }

    #[test]
    fn chained_boolean_preserves_untracked_origin_uncertainty() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        let rounded = json!({"kind":"fillet", "body":stock, "points":[[0,0,5]], "tolerance":0.01, "size":0.5});
        let cutter = json!({"kind":"box", "origin":[8,8,-1], "size":[4,4,12]});
        let mut cache = BuildCache::default();
        let (input, _) = cache.build_tracked(&rounded)?;
        let (tool, _) = cache.build_tracked(&cutter)?;
        let untracked: Vec<usize> = input.report["faces"]
            .as_array()
            .unwrap()
            .iter()
            .enumerate()
            .filter_map(|(i, face)| {
                (face["origin_status"] == "generated or untracked").then_some(i)
            })
            .collect();
        assert!(
            !untracked.is_empty(),
            "blend must produce a face without an established origin"
        );
        let inputs = [input.report, tool.report];
        let (body, history) = provenance::boolean(
            input.body,
            &input.record,
            &input.order,
            tool.body,
            &tool.record,
            &tool.order,
            solidcore_ops::BooleanOp::Subtract,
        )?;
        let mut result = inspect_record(&body, &history.record, &history.order)?;
        apply_history(&mut result, &history, &inputs);
        let carried: Vec<usize> = history
            .faces
            .iter()
            .enumerate()
            .filter_map(|(i, origins)| {
                origins
                    .iter()
                    .any(|(operand, source)| *operand == 0 && untracked.contains(source))
                    .then_some(i)
            })
            .collect();
        assert!(
            !carried.is_empty(),
            "the boolean must retain a face from the blend"
        );
        for index in carried {
            assert_eq!(
                result["faces"][index]["origin_status"],
                "generated or untracked"
            );
        }
        Ok(())
    }

    #[test]
    fn downstream_blend_reports_split_missing_and_unknown_identities() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        let edge = json!({"feature":"stock", "kind":"edge", "roles":["x_min","y_min"]});
        let cut = |tool| json!({"kind":"subtract", "left":stock, "right":tool});
        let slab = json!({"kind":"box", "origin":[-1,-1,4], "size":[12,12,2]});
        let split =
            json!({"kind":"fillet", "body":cut(slab), "edge_identities":[edge], "size":0.25});
        assert!(build(&split)
            .unwrap_err()
            .to_string()
            .contains("split or ambiguous"));
        let bottom = json!({"kind":"box", "origin":[-1,-1,-1], "size":[12,12,6]});
        let removed = json!({"feature":"stock", "kind":"edge", "roles":["y_min","z_min"]});
        let missing =
            json!({"kind":"fillet", "body":cut(bottom), "edge_identities":[removed], "size":0.25});
        assert!(build(&missing)
            .unwrap_err()
            .to_string()
            .contains("deleted or untracked"));
        let unknown = json!({"kind":"fillet", "body":stock, "edge_identities":[{"feature":"unknown", "kind":"edge", "roles":["x_min","y_min"]}], "size":0.25});
        assert!(build(&unknown)
            .unwrap_err()
            .to_string()
            .contains("unknown or unavailable"));
        Ok(())
    }

    #[test]
    fn boolean_union_reports_merged_face_and_edge_origins() -> Result<()> {
        let a = json!({"kind":"box", "origin":[0,0,0], "size":[1,1,1], "metadata":{"id":"a"}});
        let b = json!({"kind":"box", "origin":[1,0,0], "size":[1,1,1], "metadata":{"id":"b"}});
        let report = inspect_graph(&json!({"kind":"union", "left":a, "right":b}))?;
        for group in ["faces", "edges"] {
            assert!(
                report[group].as_array().unwrap().iter().any(|entity| {
                    entity["identities"].as_array().is_some_and(|ids| {
                        ids.iter().any(|id| id["feature"] == "a")
                            && ids.iter().any(|id| id["feature"] == "b")
                    })
                }),
                "union must report merged {group} origins"
            );
        }
        Ok(())
    }

    #[test]
    fn merge_with_unnamed_geometry_stays_ambiguous() -> Result<()> {
        let a = json!({"kind":"box", "origin":[0,0,0], "size":[1,1,1], "metadata":{"id":"a"}});
        let b = json!({"kind":"box", "origin":[1,0,0], "size":[1,1,1]});
        let union = json!({"kind":"union", "left":a, "right":b});
        let translated = json!({"kind":"translate", "body":union, "offset":[0,0,1]});
        let mut cache = BuildCache::default();
        for _ in 0..2 {
            let (result, _) = cache.build_tracked(&translated)?;
            let edge = result.report["edges"]
                .as_array()
                .unwrap()
                .iter()
                .find(|edge| {
                    edge["merged"] == true
                        && edge["identities"]
                            .as_array()
                            .is_some_and(|ids| ids.len() == 1)
                })
                .expect("named and unnamed edges merge");
            let identity = edge["identities"][0].clone();
            assert!(select_blend_refs(
                &result.body,
                &result.record,
                &result.order,
                &result.report,
                &json!({"edge_identities":[identity]})
            )
            .is_err());
        }
        Ok(())
    }

    #[test]
    fn known_identity_without_a_tracked_descendant_remains_in_inventory() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        let cutter = json!({"kind":"box", "origin":[-1,-1,-1], "size":[12,12,6]});
        let graph = json!({"kind":"instance", "name":"part", "body":{"kind":"subtract", "left":stock, "right":cutter}});
        let mut cache = BuildCache::default();
        for _ in 0..2 {
            let (result, _) = cache.build_tracked(&graph)?;
            let identity =
                json!({"feature":"stock", "kind":"face", "role":"z_min", "instance":["part"]});
            assert!(result.report["tracked_identities"]
                .as_array()
                .unwrap()
                .contains(&identity));
            assert!(!result.report["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| {
                    let mut ids = Vec::new();
                    carry_identities(&mut ids, face);
                    ids.contains(&identity)
                }));
        }
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
    fn identity_blends_select_the_evaluated_operand_edge() -> Result<()> {
        let stock =
            json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10], "metadata":{"id":"stock"}});
        let report = inspect_graph(&stock)?;
        let edge = report["edges"]
            .as_array()
            .unwrap()
            .iter()
            .find(|edge| edge["identity"]["roles"] == json!(["x_min", "y_min"]))
            .unwrap();
        let identity = edge["identity"].clone();
        for kind in ["fillet", "chamfer"] {
            let by_id =
                json!({"kind":kind, "body":stock, "edge_identities":[identity], "size":0.5});
            let by_point = json!({"kind":kind, "body":stock, "points":[[0,0,5]], "tolerance":0.01, "size":0.5});
            let result = inspect_graph(&by_id)?;
            let point_result = inspect_graph(&by_point)?;
            assert!(
                (result["volume"].as_f64().unwrap() - point_result["volume"].as_f64().unwrap())
                    .abs()
                    < 1e-7
            );
            assert!(result["faces"]
                .as_array()
                .unwrap()
                .iter()
                .any(|face| face["identity"]["feature"] == "stock"));
            let mut duplicate = by_id.clone();
            duplicate["edge_identities"] = json!([identity, identity]);
            assert!(build(&duplicate).is_err());
            let mut missing = by_id.clone();
            missing["edge_identities"][0]["feature"] = json!("missing");
            assert!(build(&missing).is_err());
            let mut mixed = by_id.clone();
            mixed["points"] = json!([[0, 0, 5]]);
            assert!(build(&mixed).is_err());
        }
        let body = build(&stock)?;
        let mut split = report.clone();
        split["edges"][1]["identity"] = identity.clone();
        assert!(select_blend_refs(
            &body,
            &body.to_record()?.0,
            &body.to_record()?.1,
            &split,
            &json!({"edge_identities":[identity]})
        )
        .is_err());
        let mut merged = report.clone();
        let index = edge["index"].as_u64().unwrap() as usize;
        merged["edges"][index]["identities"] =
            json!([identity, {"feature":"other", "kind":"edge", "roles":["x_min", "y_min"]}]);
        assert!(select_blend_refs(
            &body,
            &body.to_record()?.0,
            &body.to_record()?.1,
            &merged,
            &json!({"edge_identities":[identity]})
        )
        .is_err());
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
    fn provenance_audit_refusal_preserves_previous_cache() -> Result<()> {
        let graph = |height| json!({"kind":"subtract", "left":{"kind":"box", "origin":[0,0,0], "size":[12,30,10]}, "right":{"kind":"box", "origin":[-1,5,2], "size":[9,20,height]}});
        let mut cache = BuildCache::default();
        let (before, _) = cache.build(&graph(4.6))?;
        // A nested scope is refused by the kernel audit. This exercises cache
        // recovery without pretending to inject an attribute callback failure.
        let (_, failed) = solidcore_ops::provenance::with_failure_audit(|| {
            assert!(cache.build(&graph(4.7)).is_err());
        })?;
        assert!(failed);
        let (after, stats) = cache.build(&graph(4.6))?;
        assert_eq!(stats.hits, 1);
        assert!((before.volume(1e-6)? - after.volume(1e-6)?).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn boolean_refuses_failure_from_an_operand_attribute_and_keeps_cache() -> Result<()> {
        use solidcore_ops::provenance::{self, Provenance, FIRST_ID};
        use std::sync::{
            atomic::{AtomicUsize, Ordering},
            Arc,
        };
        #[derive(Clone, Debug)]
        struct RefuseNestedAudit(Arc<AtomicUsize>);
        impl PartialEq for RefuseNestedAudit {
            fn eq(&self, other: &Self) -> bool {
                Arc::ptr_eq(&self.0, &other.0)
            }
        }
        impl Provenance for RefuseNestedAudit {
            const ID: u64 = FIRST_ID + 82;
            fn split(&self, _: Option<&Self>) -> Option<Self> {
                // The callback deliberately ignores the nested-scope failure.
                if provenance::with_failure_audit(|| ()).is_err() {
                    self.0.fetch_add(1, Ordering::SeqCst);
                }
                Some(self.clone())
            }
            fn merge(&self, _: Option<&Self>) -> Option<Self> {
                Some(self.clone())
            }
            fn coincident(&self, _: Option<&Self>) -> Option<Self> {
                Some(self.clone())
            }
        }
        let stock = json!({"kind":"box", "origin":[0,0,0], "size":[10,10,10]});
        let cutter = json!({"kind":"box", "origin":[5,2,-1], "size":[10,5,12]});
        let graph = json!({"kind":"subtract", "left":stock, "right":cutter});
        let calls = Arc::new(AtomicUsize::new(0));
        let mut cache = BuildCache::default();
        let (before, _) = cache.build(&stock)?;
        let entry = cache
            .bodies
            .get(&cache_key(&stock)?)
            .ok_or("missing stock cache entry")?;
        let marker = RefuseNestedAudit(calls.clone());
        provenance::write_provenance(
            &entry.body,
            &entry.record,
            &entry.order,
            &vec![marker.clone(); entry.record.faces.len()],
            &vec![marker; entry.record.edges.len()],
        )?;
        let error = cache
            .build(&graph)
            .err()
            .ok_or("expected audit refusal")?
            .to_string();
        assert!(error.contains("kernel provenance is incomplete"), "{error}");
        assert!(
            calls.load(Ordering::SeqCst) > 0,
            "the actual operand's split callback must run"
        );
        let (after, stats) = cache.build(&stock)?;
        assert_eq!(stats.hits, 1);
        assert!((before.volume(1e-6)? - after.volume(1e-6)?).abs() < 1e-6);
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

    #[test]
    fn box_triangle_sides_map_to_their_actual_brep_edges() -> Result<()> {
        let body = build(&json!({"kind":"box", "origin":[0,0,0], "size":[12,30,10]}))?;
        let mesh = display_mesh(&body, 100.0)?;
        assert_eq!(mesh.tri_edge.len(), mesh.triangles.len());
        assert_eq!(mesh.tri_edge_segment.len(), mesh.triangles.len());
        assert_eq!(mesh.boundary_complete.len(), 6);
        assert!(mesh.boundary_complete.iter().all(|complete| *complete));
        let mut observed = std::collections::HashSet::new();
        let mut coverage =
            std::collections::HashMap::<(u32, u32), std::collections::HashSet<usize>>::new();
        for (((triangle, face), sides), segments) in mesh
            .triangles
            .iter()
            .zip(&mesh.tri_face)
            .zip(&mesh.tri_edge)
            .zip(&mesh.tri_edge_segment)
        {
            for (side, edge) in sides.iter().enumerate() {
                if let Some(edge) = edge {
                    let points = &mesh.edges[*edge as usize];
                    let a = mesh.positions[triangle[side] as usize];
                    let b = mesh.positions[triangle[(side + 1) % 3] as usize];
                    let ordinal = segments[side].expect("edge side has segment ordinal") as usize;
                    let p = &points[ordinal..=ordinal + 1];
                    assert!((p[0] == a && p[1] == b) || (p[0] == b && p[1] == a));
                    assert!(mesh.edge_faces[*edge as usize].contains(face));
                    assert!(coverage.entry((*face, *edge)).or_default().insert(ordinal));
                    observed.insert(*edge);
                }
            }
        }
        assert_eq!(observed.len(), 12);
        for (edge, faces) in mesh.edge_faces.iter().enumerate() {
            for face in faces {
                let ordinals = &coverage[&(*face, edge as u32)];
                assert_eq!(ordinals.len(), mesh.edges[edge].len() - 1);
                assert!((0..mesh.edges[edge].len() - 1).all(|ordinal| ordinals.contains(&ordinal)));
            }
        }
        Ok(())
    }

    #[test]
    fn unsupported_boundary_does_not_claim_interior_sides() -> Result<()> {
        let body = build(&json!({"kind":"cylinder", "origin":[0,0,0], "radius":3, "height":7}))?;
        let mesh = display_mesh(&body, 100.0)?;
        assert!(mesh.boundary_complete.iter().any(|complete| !complete));
        assert_eq!(mesh.tri_edge.len(), mesh.triangles.len());
        assert_eq!(mesh.tri_edge_segment.len(), mesh.triangles.len());
        for ((face, sides), segments) in mesh
            .tri_face
            .iter()
            .zip(&mesh.tri_edge)
            .zip(&mesh.tri_edge_segment)
        {
            if !mesh.boundary_complete[*face as usize] {
                assert_eq!(*sides, [None; 3]);
                assert_eq!(*segments, [None; 3]);
            }
        }
        Ok(())
    }
}
