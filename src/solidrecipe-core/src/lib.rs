//! Evaluate a small model graph using SolidCore. Display meshes are not CAD geometry.
use serde_json::Value;
use solidcore_ops::{boolean::boolean, make_box, Body, BooleanOp};
use std::error::Error;

pub type Result<T> = std::result::Result<T, Box<dyn Error>>;

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

/// Evaluate the graph into a SolidCore B-rep.
pub fn build(node: &Value) -> Result<Body> {
    match node["kind"].as_str() {
        Some("box") => Ok(make_box(vector(&node["origin"])?, vector(&node["size"])?)?),
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

/// Tessellate a B-rep for display, refusing an incomplete mesh.
pub fn display_mesh(body: &Body, size: f64) -> Result<solidcore_tess::Mesh> {
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
    fn evaluates_a_slot_and_its_display_mesh() -> Result<()> {
        let graph = json!({"kind":"subtract", "left":{"kind":"box", "origin":[0,0,0], "size":[12,30,10]}, "right":{"kind":"box", "origin":[-1,5,2], "size":[9,20,4.6]}});
        let body = build(&graph)?;
        assert!((body.volume(1e-6)? - 2864.0).abs() < 1e-6);
        let mesh = display_mesh(&body, 100.0)?;
        assert!(!mesh.triangles.is_empty());
        Ok(())
    }
}
