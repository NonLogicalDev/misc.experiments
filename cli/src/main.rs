use solidrecipe_core::{build, display_mesh, Result};
use std::{
    env, fs,
    fs::File,
    io::{BufWriter, Write},
};

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        return Err("usage: solidrecipe <graph.json> <mesh.obj>".into());
    }
    let graph = serde_json::from_slice(&fs::read(&args[1])?)?;
    let body = build(&graph)?;
    let volume = body.volume(1e-6)?;
    let mesh = display_mesh(&body, 100.0)?;
    let mut file = BufWriter::new(File::create(&args[2])?);
    for p in &mesh.positions {
        writeln!(file, "v {} {} {}", p.x, p.y, p.z)?;
    }
    for t in &mesh.triangles {
        writeln!(file, "f {} {} {}", t[0] + 1, t[1] + 1, t[2] + 1)?;
    }
    println!(
        "{}",
        serde_json::json!({"volume":volume,"vertices":mesh.positions.len(),"triangles":mesh.triangles.len()})
    );
    Ok(())
}
