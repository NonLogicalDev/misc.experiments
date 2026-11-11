//! Headless model evaluation and a local live viewer for Python model files.
mod preview;
use solidrecipe_core::{build, display_mesh, inspect, Result};
use std::{
    env, fs,
    fs::File,
    io::{BufWriter, Read, Write},
    path::Path,
};

// Viewer assets and the Python frontend are embedded in the binary. Only viewer assets are
// extracted into a private temporary directory for the preview server.
include!(concat!(env!("OUT_DIR"), "/viewer_assets.rs"));

/// Extract the embedded assets into a private directory owned by this process.
fn extract_resources() -> Result<tempfile::TempDir> {
    let root = tempfile::Builder::new().prefix("solidrecipe-").tempdir()?;
    // Set restrictive permissions before writing model support files or viewer assets.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    }
    for (name, bytes) in VIEWER_ASSETS {
        let path = root.path().join("viewer").join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, bytes)?;
    }
    Ok(root)
}

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("inspect-graph") {
        if args.len() != 2 {
            return Err("usage: solidrecipe inspect-graph < graph.json".into());
        }
        let mut input = String::new();
        std::io::stdin().read_to_string(&mut input)?;
        let graph = serde_json::from_str(&input)?;
        println!("{}", inspect(&build(&graph)?)?);
        return Ok(());
    }
    if args.get(1).map(String::as_str) == Some("serve") {
        if args.len() < 3 {
            return Err("usage: solidrecipe serve <model.py> [--port PORT] [--no-browser]".into());
        }
        // Resolve the model relative to the caller before starting the preview.
        let model = fs::canonicalize(&args[2])?;
        let resources = extract_resources()?;
        let mut port = 8765;
        let mut open_browser = true;
        let mut options = args[3..].iter();
        while let Some(option) = options.next() {
            match option.as_str() {
                "--no-browser" => open_browser = false,
                "--port" => port = options.next().ok_or("missing port")?.parse()?,
                _ => return Err(format!("unknown option: {option}").into()),
            }
        }
        return preview::serve(model, resources.path().to_path_buf(), port, open_browser);
    }
    if args.len() != 3 {
        return Err("usage: solidrecipe <graph.json> <mesh.obj> | solidrecipe serve <model.py> [--port PORT] [--no-browser]".into());
    }
    let graph = serde_json::from_slice(&fs::read(&args[1])?)?;
    let body = build(&graph)?;
    let volume = body.volume(1e-6)?;
    let mesh = display_mesh(&body, 100.0)?;
    let mut file = BufWriter::new(File::create(Path::new(&args[2]))?);
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
