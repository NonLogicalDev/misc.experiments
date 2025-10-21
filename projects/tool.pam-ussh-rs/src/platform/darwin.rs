//! macOS-specific glue for the PAM module.

/// Human-readable label for diagnostics and logging.
pub const TARGET_LABEL: &str = "darwin";

/// Placeholder hook for macOS-only initialization.
#[inline]
pub fn initialize_platform() {
    if let Err(err) = deny_ptrace_attach() {
        // In release builds we intentionally swallow the error to avoid bubbling up
        // PAM failures, but during development we surface it for visibility.
        #[cfg(debug_assertions)]
        eprintln!("pam-ussh (darwin): failed to disable ptrace: {err}");
    }
}

fn deny_ptrace_attach() -> Result<(), std::io::Error> {
    // PT_DENY_ATTACH disallows debuggers or dtrace from attaching to the process.
    let rc = unsafe { libc::ptrace(libc::PT_DENY_ATTACH, 0, std::ptr::null_mut(), 0) };
    if rc == -1 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}
