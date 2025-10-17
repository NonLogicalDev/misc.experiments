## Interview Validation Setup

- This is a setup for validating interviews we conduct at Uber.
- We are using **Bazel with bzlmod** as the primary build system for all interview languages.
- We use nix + nix-direnv to setup Bazel and essential system dependencies.
  - All nix code is in the `.nix` directory.
  - We use nix flakes with flake-parts.
- **Migration**: Converted from Justfile to Bazel for better dependency management, hermetic builds, and scalability.

## Interview Languages

Currently implemented and supported languages:
- **Python** - with numpy, pandas, scipy, matplotlib (via uv-managed dependencies)
- **Go** - with Go toolchain via Bazel
- **Java** - using OpenJDK via Bazel
- **Rust** - with Rust toolchain via Bazel
- **C++** - with clang/gcc via Bazel built-in rules

Planned for future implementation:
- Javascript/Typescript (using deno)

## System Architecture

### Interview Creation
- `just new_python <name>` - Creates Python interview
- `just new_go <name>` - Creates Go interview  
- `just new_java <name>` - Creates Java interview
- `just new_rust <name>` - Creates Rust interview
- `just new_cpp <name>` - Creates C++ interview
- `just list` - Lists all interviews

### Directory Structure
```
interviews/
└── {epoch}_{name}/
    ├── BUILD.bazel (Bazel build configuration)
    └── main.{ext} (solution file)
```

### Bazel Build System
- `MODULE.bazel` - bzlmod configuration for all language dependencies
- `.bazelrc` - Bazel configuration for consistent builds
- `tools/bazel/interview_rules.bzl` - Shared Bazel rules for all languages
- `tools/python/requirements_lock.txt` - Python dependencies
- `tools/rust/Cargo.toml` - Rust dependencies

### Common Commands (per interview)
From interview directory or using full path:
- `bazel build :solution` - Compile/prepare solution
- `bazel run :solution` - Execute solution  
- `bazel run :solution_with_input` - Execute with input.txt if exists
- `bazel clean` - Remove build artifacts
- `bazel test :test` - Run tests (if available)

From root directory:
- `bazel run //interviews/{epoch}_{name}:solution`
- `bazel run //interviews/{epoch}_{name}:solution_with_input`

### Dependency Management
Automated dependency updates via Bazel:
- `bazel run //tools:update_python_deps` - Update Python requirements lock file using uv
- `bazel run //tools:update_rust_deps` - Update Rust Cargo.lock file using cargo
- `bazel run //tools:update_all_deps` - Update all language dependencies

### Build System
- Bazel manages all build artifacts in `bazel-bin/`, `bazel-out/`, etc.
- Hermetic builds ensure reproducibility across environments
- Parallel compilation and caching for faster builds
- Language-specific toolchains managed by Bazel rules

### Templates
Located in `.templates/{language}/`:
- `BUILD.bazel` with language-specific interview rules
- Boilerplate code file (`main.py`, `main.go`, `Main.java`, `main.rs`)
