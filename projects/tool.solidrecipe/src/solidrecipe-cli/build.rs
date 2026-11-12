//! Embed the production viewer into the CLI at compile time.
//!
//! The web build is a separate step: invoking a package manager from Cargo would make builds
//! unexpectedly network-dependent. `make build` runs the steps in the correct order.
use std::{env, fs, path::Path};

fn collect(root: &Path, dir: &Path, files: &mut Vec<(String, String)>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(root, &path, files)?;
        } else if path.is_file() {
            let relative = path.strip_prefix(root).expect("asset is under viewer root");
            files.push((
                relative.to_string_lossy().replace('\\', "/"),
                path.to_string_lossy().into_owned(),
            ));
        }
    }
    Ok(())
}

fn main() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../solidrecipe-viewer/dist");
    println!("cargo:rerun-if-changed={}", root.display());
    if !root.join("index.html").is_file() {
        panic!("viewer build missing: run pnpm -C src/solidrecipe-viewer install and pnpm -C src/solidrecipe-viewer build before cargo build");
    }
    let mut files = Vec::new();
    collect(&root, &root, &mut files).expect("read viewer build");
    files.sort_unstable();
    let mut generated = String::from("static VIEWER_ASSETS: &[(&str, &[u8])] = &[\n");
    for (name, path) in files {
        generated.push_str(&format!("({name:?}, include_bytes!({path:?})),\n"));
    }
    generated.push_str("];\n");
    let output =
        Path::new(&env::var("OUT_DIR").expect("Cargo provides OUT_DIR")).join("viewer_assets.rs");
    fs::write(output, generated).expect("write embedded viewer asset list");
}
