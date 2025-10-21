//! Linux-specific glue for the PAM module.

use nix::sys::prctl;

/// Human-readable label for diagnostics and logging.
pub const TARGET_LABEL: &str = "linux";

/// Hook for Linux-only initialization.
///
/// Sets up security hardening:
/// - Disables ptrace to prevent debugging/inspection of this PAM module
/// - Prevents core dumps which could leak sensitive data
#[inline]
pub fn initialize_platform() {
    // Attempt to apply security hardening
    if let Err(e) = apply_security_hardening() {
        // In release builds we intentionally swallow the error to avoid bubbling up
        // PAM failures, but during development we surface it for visibility.
        #[cfg(debug_assertions)]
        eprintln!("pam-ussh (linux): failed to apply security hardening: {}", e);
    }
}

/// Apply Linux-specific security hardening measures
fn apply_security_hardening() -> Result<(), String> {
    // Disable ptrace - prevents debuggers from attaching to this process
    // This is important for a PAM module that may handle sensitive authentication data
    disable_ptrace()?;

    // Disable core dumps - prevents sensitive data from being written to disk
    disable_core_dumps()?;

    Ok(())
}

/// Disable ptrace on this process to prevent debugging/inspection
fn disable_ptrace() -> Result<(), String> {
    // PR_SET_DUMPABLE with value 0 prevents ptrace from attaching
    // This is equivalent to macOS's PT_DENY_ATTACH
    prctl::set_dumpable(false)
        .map_err(|e| format!("failed to disable ptrace: {}", e))?;

    Ok(())
}

/// Disable core dumps for this process
fn disable_core_dumps() -> Result<(), String> {
    // Set resource limit for core dumps to 0
    use nix::sys::resource::{setrlimit, Resource};

    // RLIMIT_CORE = 4 on Linux
    // Set both soft and hard limit to 0
    setrlimit(Resource::RLIMIT_CORE, 0, 0)
        .map_err(|e| format!("failed to disable core dumps: {}", e))?;

    Ok(())
}
