//! Evaluate a small model graph using SolidCore. Display meshes are not CAD geometry.
use serde_json::Value;
use solidcore_ops::{boolean::boolean, make_box, make_cylinder, Body, BooleanOp};
use std::error::Error;

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
