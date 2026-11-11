//! Evaluate a small model graph using SolidCore. Display meshes are not CAD geometry.
use serde_json::Value;
use solidcore_ops::{
    blend_ordered, boolean::boolean, make_box, make_cylinder, Blend, Body, BooleanOp, Corners,
};
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
    match node["kind"].as_str() {
        Some("box") => Ok(make_box(vector(&node["origin"])?, vector(&node["size"])?)?),
        Some("cylinder") => Ok(make_cylinder(
            vector(&node["origin"])?,
            node["radius"].as_f64().ok_or("invalid cylinder radius")?,
            node["height"].as_f64().ok_or("invalid cylinder height")?,
        )?),
        Some(kind @ ("translate" | "scale")) => transform_body(build(&node["body"])?, node, kind),
        Some(kind @ ("fillet" | "chamfer")) => blend_edges(build(&node["body"])?, node, kind),
        Some(kind @ ("subtract" | "union" | "intersect")) => {
            let op = match kind {
                "subtract" => BooleanOp::Subtract,
                "union" => BooleanOp::Union,
                _ => BooleanOp::Intersect,
            };
            boolean(build(&node["left"])?, build(&node["right"])?, op)?
                .ok_or_else(|| "empty result".into())
        }
        _ => Err("unknown node".into()),
    }
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

/// Apply a real kernel blend to uniquely identified edges on this evaluated body.
fn blend_edges(body: Body, node: &Value, kind: &str) -> Result<Body> {
    let tolerance = node["tolerance"].as_f64().ok_or("invalid edge tolerance")?;
    let size = node["size"].as_f64().ok_or("invalid blend size")?;
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
    let blend = if kind == "fillet" {
        Blend::Round
    } else {
        Blend::Chamfer
    };
    blend_ordered(
        &body,
        &order,
        blend,
        &selected,
        &[size],
        &[],
        Corners::Filled,
        Default::default(),
    )?;
    Ok(body)
}

/// In-memory B-rep cache keyed by the full serialized expression subtree.
///
/// This tracks geometry equivalence, not persistent feature identity. Operands are copied
/// because SolidCore booleans consume their inputs. Only nodes reachable from the most recent
/// successful graph are retained, so interactive edits cannot grow the cache indefinitely.
#[derive(Default)]
pub struct BuildCache {
    bodies: HashMap<String, Body>,
}

/// Cache reuse counts for a single rebuild, useful for performance diagnostics.
#[derive(Default, Debug, PartialEq, Eq)]
pub struct CacheStats {
    pub hits: usize,
    pub misses: usize,
}

impl BuildCache {
    /// Build a graph, reusing unchanged subtrees and leaving the previous cache on failure.
    pub fn build(&mut self, node: &Value) -> Result<(Body, CacheStats)> {
        let mut reachable = HashSet::new();
        collect_keys(node, &mut reachable)?;
        let before: HashSet<_> = self.bodies.keys().cloned().collect();
        let mut stats = CacheStats::default();
        let result = self.evaluate(node, &mut stats);
        match result {
            Ok(body) => {
                self.bodies.retain(|key, _| reachable.contains(key));
                Ok((body, stats))
            }
            Err(error) => {
                self.bodies.retain(|key, _| before.contains(key));
                Err(error)
            }
        }
    }

    fn evaluate(&mut self, node: &Value, stats: &mut CacheStats) -> Result<Body> {
        let key = serde_json::to_string(node)?;
        if let Some(body) = self.bodies.get(&key) {
            stats.hits += 1;
            return Ok(body.copy()?);
        }
        stats.misses += 1;
        let body = match node["kind"].as_str() {
            Some(kind @ ("translate" | "scale")) => {
                transform_body(self.evaluate(&node["body"], stats)?, node, kind)?
            }
            Some(kind @ ("fillet" | "chamfer")) => {
                blend_edges(self.evaluate(&node["body"], stats)?, node, kind)?
            }
            Some(kind @ ("subtract" | "union" | "intersect")) => {
                let op = match kind {
                    "subtract" => BooleanOp::Subtract,
                    "union" => BooleanOp::Union,
                    _ => BooleanOp::Intersect,
                };
                boolean(
                    self.evaluate(&node["left"], stats)?,
                    self.evaluate(&node["right"], stats)?,
                    op,
                )?
                .ok_or("empty result")?
            }
            _ => build(node)?,
        };
        self.bodies.insert(key, body.copy()?);
        Ok(body)
    }
}

/// A cache hit at an ancestor must not discard its descendants: a later edit may need them.
fn collect_keys(node: &Value, keys: &mut HashSet<String>) -> Result<()> {
    keys.insert(serde_json::to_string(node)?);
    if matches!(
        node["kind"].as_str(),
        Some("fillet" | "chamfer" | "translate" | "scale")
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
    let (_, report) = inspect_tracked(node)?;
    Ok(report)
}

fn inspect_tracked(node: &Value) -> Result<(Body, Value)> {
    if let Some(kind @ ("translate" | "scale")) = node["kind"].as_str() {
        let (body, old_report) = inspect_tracked(&node["body"])?;
        let (_, old_order) = body.to_record()?;
        let body = transform_body(body, node, kind)?;
        let (_, new_order) = body.to_record()?;
        let mut report = inspect(&body)?;
        report["identity_status"] = old_report["identity_status"].clone();
        if old_report["identity_status"] == "exact_named_box" {
            for (old, entity) in old_order.faces.iter().enumerate() {
                let new = new_order
                    .faces
                    .iter()
                    .position(|candidate| candidate == entity)
                    .ok_or("transform changed face handles; refusing identities")?;
                report["faces"][new]["identity"] = old_report["faces"][old]["identity"].clone();
            }
            for (old, entity) in old_order.edges.iter().enumerate() {
                let new = new_order
                    .edges
                    .iter()
                    .position(|candidate| candidate == entity)
                    .ok_or("transform changed edge handles; refusing identities")?;
                report["edges"][new]["identity"] = old_report["edges"][old]["identity"].clone();
            }
        }
        return Ok((body, report));
    }
    let body = build(node)?;
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
        assert_eq!(cut["identity_status"], "unavailable");
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
