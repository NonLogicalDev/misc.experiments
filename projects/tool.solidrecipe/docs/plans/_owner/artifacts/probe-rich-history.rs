//! Reproduce a real operation-local history that cannot be flattened.
//!
//! This is a diagnostic against an existing `solidcraft-kernel` build, not the
//! SolidRecipe evaluator. See `run-rich-history-probe.sh` for the exact rlibs
//! used. The existing rlibs may predate current vendor source changes.

use solidcore_record::brep::{
    history::{Change, EdgeOrigin, FaceOrigin},
    Surface,
};
use solidcore_record::Vec3;
use solidcraft_kernel::{blend_edges, boolean, box_solid, fillet, sphere, BoolOp};
use std::collections::BTreeSet;

fn main() {
    let stock = box_solid(Vec3::new(0., 0., 0.), Vec3::new(12., 10., 5.)).unwrap();
    let tool = box_solid(Vec3::new(3., 3., -1.), Vec3::new(7., 7., 6.)).unwrap();
    let cut = boolean(&stock, &tool, BoolOp::Cut).unwrap().unwrap();
    let cut_history = cut.history().expect("cut did not report history");
    let point = Vec3::new(5., 3., 5.);
    let selected = blend_edges(&cut, &[point]).unwrap();
    assert_eq!(selected.len(), 1, "expected one cut edge at the test point");
    let cut_edge = selected[0];
    let meetings: Vec<_> = cut_history
        .edges
        .iter()
        .enumerate()
        .filter(|(_, e)| {
            e.origins
                .iter()
                .any(|origin| matches!(origin, EdgeOrigin::Meet { .. }))
        })
        .collect();
    assert_eq!(
        meetings.len(),
        8,
        "expected four top and four bottom meetings"
    );
    assert!(meetings.iter().any(|(i, _)| *i == cut_edge));

    let blended = fillet(&cut, &[point], 0.2).unwrap();
    let blend_history = blended.history().expect("blend did not report history");
    assert!(
        blend_history.faces.iter().any(|f| {
            f.change == Change::Generated
                && f.origins.contains(&FaceOrigin::Edge {
                    operand: 0,
                    edge: cut_edge,
                })
        }),
        "no generated face references the selected intersection edge"
    );
    let mut flattened = blend_history.clone();
    let error = flattened.substitute(0, cut_history).unwrap_err();
    assert!(error
        .to_string()
        .contains("a blend of an edge the inner operation generated"));
    assert_eq!(
        &flattened, blend_history,
        "failed flattening must not mutate the history"
    );
    println!("8 cut meetings; generated blend traces to cut edge {cut_edge}; flattening refused without mutation");

    // A curved, non-prismatic Boolean verifies source-face meeting history on
    // a different operation path than the axis-aligned rectangular through cut.
    let block = box_solid(Vec3::new(0., 0., 0.), Vec3::new(10., 10., 10.)).unwrap();
    let ball = sphere(Vec3::new(10., 10., 10.), 4.).unwrap();
    let curved = boolean(&block, &ball, BoolOp::Cut).unwrap().unwrap();
    let history = curved.history().expect("sphere cut did not report history");
    history
        .check_counts(
            (curved.record().faces.len(), curved.record().edges.len()),
            &[
                (block.record().faces.len(), block.record().edges.len()),
                (ball.record().faces.len(), ball.record().edges.len()),
            ],
        )
        .unwrap();
    let sphere_result_faces: Vec<_> = history
        .faces
        .iter()
        .enumerate()
        .filter_map(|(i, f)| {
            f.origins
                .iter()
                .any(|o| matches!(o, FaceOrigin::Face { operand: 1, .. }))
                .then_some(i)
        })
        .collect();
    assert_eq!(
        sphere_result_faces.len(),
        1,
        "expected one sphere-derived face"
    );
    let sphere_face = sphere_result_faces[0];
    assert!(
        matches!(
            curved.record().faces[sphere_face].surface,
            Surface::Sphere { .. }
        ),
        "the sphere-derived result face must retain its spherical surface"
    );
    let meetings: Vec<_> = history
        .edges
        .iter()
        .enumerate()
        .flat_map(|(index, edge)| edge.origins.iter().map(move |origin| (index, edge, origin)))
        .filter_map(|(index, edge, origin)| match origin {
            EdgeOrigin::Meet { a, b } => Some((index, edge, a.single(), b.single())),
            _ => None,
        })
        .collect();
    assert_eq!(
        meetings.len(),
        3,
        "sphere corner cut should meet three block faces"
    );
    assert!(
        meetings.iter().all(|(_, _, a, b)| matches!(
            (a, b),
            (
                Some(FaceOrigin::Face { operand: 0, .. }),
                Some(FaceOrigin::Face { operand: 1, .. })
            )
        )),
        "every cut meeting should preserve distinct block and sphere source sides"
    );
    let mut block_sources = BTreeSet::new();
    let mut sphere_sources = BTreeSet::new();
    for (index, edge, a, b) in meetings {
        let (
            Some(FaceOrigin::Face {
                face: block_face, ..
            }),
            Some(FaceOrigin::Face {
                face: ball_face, ..
            }),
        ) = (a, b)
        else {
            panic!("missing input-face origins");
        };
        block_sources.insert(block_face);
        sphere_sources.insert(ball_face);
        let record_faces: BTreeSet<_> = curved.record().edges[index]
            .uses
            .iter()
            .map(|u| u.face as usize)
            .collect();
        assert_eq!(record_faces, edge.faces.iter().copied().collect());
        assert_eq!(record_faces.len(), 2);
        assert!(record_faces.contains(&sphere_face));
    }
    assert_eq!(
        block_sources.len(),
        3,
        "three different block faces meet the sphere"
    );
    assert_eq!(
        sphere_sources.len(),
        1,
        "all three edges meet the same source sphere face"
    );
    let sphere_source = *sphere_sources.iter().next().unwrap();
    assert!(matches!(
        ball.record().faces[sphere_source].surface,
        Surface::Sphere { .. }
    ));
    println!("sphere corner cut: 1 spherical result face and 3 block/sphere source-face meetings");
}
