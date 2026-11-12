//! Kernel-provided operation history, mapped through checked record boundaries.
//!
//! Entity indices are local to each record. They may cross an import only when
//! every numbered vertex, edge, and face still refers to the same topology.
use crate::{Body, Result};
use solidcore_record::brep::{Brep, Loop};
use solidcraft_kernel::{history::History, BoolOp};

/// Verify numbered topology, including face incidence, rather than comparing
/// serialized records whose surface parameterizations may legitimately differ.
fn same_numbering(a: &Brep, b: &Brep) -> bool {
    if a.vertices.len() != b.vertices.len()
        || a.edges.len() != b.edges.len()
        || a.faces.len() != b.faces.len()
    {
        return false;
    }
    let vertices = a
        .vertices
        .iter()
        .zip(&b.vertices)
        .all(|(x, y)| (0..3).all(|axis| (x.point[axis] - y.point[axis]).abs() <= 1e-7));
    let edges = a
        .edges
        .iter()
        .zip(&b.edges)
        .all(|(x, y)| x.vertices == y.vertices);
    let faces = a.faces.iter().zip(&b.faces).all(|(x, y)| {
        if x.loops.len() != y.loops.len() {
            return false;
        }
        x.loops.iter().zip(&y.loops).all(|(a, b)| match (a, b) {
            (Loop::Vertex { vertex: a }, Loop::Vertex { vertex: b }) => a == b,
            (Loop::Edges { edges: a }, Loop::Edges { edges: b }) => {
                let mut a: Vec<_> = a.iter().map(|e| e.edge).collect();
                let mut b: Vec<_> = b.iter().map(|e| e.edge).collect();
                a.sort_unstable();
                b.sort_unstable();
                a == b
            }
            _ => false,
        })
    });
    vertices && edges && faces
}

/// Import a body into the history-aware kernel; refuse any renumbering.
fn to_craft(body: &Body) -> Result<solidcraft_kernel::Body> {
    let (record, _) = body.to_record()?;
    let native = solidcraft_smlib::Brep::from_record(&record, true)?;
    let result = solidcraft_kernel::body_from_smlib(&native)?;
    if !same_numbering(&record, result.record()) {
        return Err("kernel import changed topology numbering".into());
    }
    Ok(result)
}

/// Evaluate a Boolean and obtain its exact, operand-indexed kernel history.
pub(crate) fn boolean(left: &Body, right: &Body, op: BoolOp) -> Result<(Body, History)> {
    let a = to_craft(left)?;
    let b = to_craft(right)?;
    let result = solidcraft_kernel::boolean(&a, &b, op)?.ok_or("empty result")?;
    let history = result
        .history()
        .ok_or("kernel did not return Boolean history")?
        .clone();
    Ok((from_craft(&result)?, history))
}

/// Export a history-bearing result only when its numbered entities stay aligned.
fn from_craft(result: &solidcraft_kernel::Body) -> Result<Body> {
    let (body, _) = Body::from_record(result.record(), true)?;
    let (record, _) = body.to_record()?;
    if !same_numbering(result.record(), &record) {
        return Err("kernel export changed topology numbering".into());
    }
    Ok(body)
}

/// Blend an input body and retain the operation's face and edge history.
pub(crate) fn blend(
    body: &Body,
    kind: &str,
    points: &[[f64; 3]],
    size: f64,
) -> Result<(Body, History)> {
    let input = to_craft(body)?;
    let points: Vec<solidcore_record::Vec3> = points.iter().copied().map(Into::into).collect();
    let result = if kind == "fillet" {
        solidcraft_kernel::fillet(&input, &points, size)?
    } else {
        solidcraft_kernel::chamfer(&input, &points, size)?
    };
    let history = result
        .history()
        .ok_or("kernel did not return blend history")?
        .clone();
    Ok((from_craft(&result)?, history))
}

#[cfg(test)]
mod tests {
    use super::*;
    use solidcraft_kernel::history::{Change, FaceOrigin};

    #[test]
    fn boolean_reports_both_operand_origins_and_split_faces() -> Result<()> {
        let a = solidcore_ops::make_box([0., 0., 0.], [10., 10., 10.])?;
        let b = solidcore_ops::make_box([5., 2., -1.], [10., 5., 12.])?;
        let (out, h) = boolean(&a, &b, BoolOp::Cut)?;
        assert_eq!(out.to_record()?.0.faces.len(), h.faces.len());
        assert!(h.faces.iter().any(|f| f.change == Change::Split));
        assert!(h
            .faces
            .iter()
            .flat_map(|f| &f.origins)
            .any(|o| matches!(o, FaceOrigin::Face { operand: 0, .. })));
        assert!(h
            .faces
            .iter()
            .flat_map(|f| &f.origins)
            .any(|o| matches!(o, FaceOrigin::Face { operand: 1, .. })));
        Ok(())
    }
}
