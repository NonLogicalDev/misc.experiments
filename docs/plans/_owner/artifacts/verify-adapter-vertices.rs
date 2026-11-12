//! Read instrumented model graphs and inspect their actual B-rep vertices.
//!
//! This small research probe links against an existing project build. It does
//! not add an API or infer shared vertices from coincident coordinates.
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let input: serde_json::Value = serde_json::from_str(&line).unwrap();
        let body = solidrecipe_core::build(&input["graph"]).unwrap();
        let (record, _) = body.to_record().unwrap();
        let expected = input["corner"].as_array().unwrap();
        let matching: Vec<_> = record.vertices.iter().enumerate().filter(|(_, vertex)| {
            (0..3).all(|axis| (vertex.point[axis] - expected[axis].as_f64().unwrap()).abs() < 1e-6)
        }).map(|(index, _)| index).collect();
        let incidences: Vec<_> = matching.iter().map(|vertex| {
            let selected: Vec<_> = record.edges.iter().enumerate().filter(|(_, edge)| {
                edge.vertices.contains(&(*vertex as u32))
            }).collect();
            let edges: Vec<_> = selected.iter().map(|(index, _)| *index).collect();
            let faces: std::collections::BTreeSet<_> = selected.iter()
                .flat_map(|(_, edge)| edge.uses.iter().map(|usage| usage.face)).collect();
            serde_json::json!({"vertex": vertex, "edges": edges, "faces": faces})
        }).collect();
        println!("{}", serde_json::json!({"case": input["case"], "incidences": incidences}));
    }
}
