//! Headless model evaluation and a local live viewer for Python model files.
use solidrecipe_core::{build, display_mesh, inspect, Result};
use std::{
    env, fs,
    fs::File,
    io::{BufWriter, Read, Write},
    path::Path,
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

// The web build and the two Python modules travel with the compiled executable. They are
// extracted only into a private temporary directory for the lifetime of the preview server.
include!(concat!(env!("OUT_DIR"), "/viewer_assets.rs"));
const PYTHON_API: &str = include_str!("../../solidrecipe-core/python/solidrecipe.py");
const PYTHON_RUNTIME: &str = include_str!("../../solidrecipe-core/python/solidrecipe_runtime.py");

/// Extract the embedded assets into a private directory owned by this process.
fn extract_resources() -> Result<tempfile::TempDir> {
    let root = tempfile::Builder::new().prefix("solidrecipe-").tempdir()?;
    // Set restrictive permissions before writing model support files or viewer assets.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    }
    fs::write(root.path().join("solidrecipe.py"), PYTHON_API)?;
    fs::write(root.path().join("solidrecipe_runtime.py"), PYTHON_RUNTIME)?;
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
        let exe = env::current_exe()?;
        // Resolve the model before starting uv; the caller's working directory owns this path.
        let model = fs::canonicalize(&args[2])?;
        let resources = extract_resources()?;
        // The preview child also receives Ctrl+C. Keep the parent alive until it exits so
        // TempDir can remove the extracted viewer and runtime instead of leaving them behind.
        let interrupted = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&interrupted);
        ctrlc::set_handler(move || flag.store(true, Ordering::SeqCst))?;
        let status = Command::new("uv")
            .args([
                "run",
                "--no-project",
                "python",
                "-m",
                "solidrecipe_runtime",
                "serve",
            ])
            .arg(model)
            .arg(&exe)
            .arg(resources.path().join("viewer"))
            .args(&args[3..])
            .env("PYTHONPATH", resources.path())
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .status()?;
        if !status.success() && !interrupted.load(Ordering::SeqCst) {
            return Err(format!("preview server exited with {status}").into());
        }
        return Ok(());
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
