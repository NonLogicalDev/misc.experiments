use solidrecipe_core::{build, display_mesh, Result};
use std::{
    env, fs,
    fs::File,
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    process::Command,
};

fn project_root(exe: &Path) -> Result<PathBuf> {
    let cwd = env::current_dir()?;
    for start in [cwd.as_path(), exe] {
        for parent in start.ancestors() {
            if parent.join("pyproject.toml").is_file()
                && parent.join("src/solidrecipe-viewer").is_dir()
            {
                return Ok(parent.to_path_buf());
            }
        }
    }
    Err("cannot locate the solidrecipe project; run from the project directory".into())
}

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("serve") {
        if args.len() < 3 {
            return Err("usage: solidrecipe serve <model.py> [--port PORT] [--no-browser]".into());
        }
        let exe = env::current_exe()?;
        let root = project_root(&exe)?;
        let model = fs::canonicalize(&args[2])?;
        let mut command = Command::new("uv");
        command
            .arg("run")
            .arg("--project")
            .arg(&root)
            .args(["python", "-m", "solidrecipe_runtime", "serve"])
            .arg(model)
            .arg(&exe)
            .arg(root.join("src/solidrecipe-viewer/dist"));
        command.args(&args[3..]);
        let status = command.status()?;
        if !status.success() {
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
