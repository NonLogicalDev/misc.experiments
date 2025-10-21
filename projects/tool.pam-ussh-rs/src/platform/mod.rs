//! Platform-specific facilities.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::initialize_platform;

#[cfg(target_os = "macos")]
mod darwin;
#[cfg(target_os = "macos")]
pub use darwin::initialize_platform;

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
compile_error!("pam-ussh-rs currently supports only Linux and macOS targets.");

use nix::unistd::{geteuid, seteuid, Uid};
use std::io;

pub struct PrivilegeGuard {
    original_euid: Uid,
}

impl Drop for PrivilegeGuard {
    fn drop(&mut self) {
        // Restore original privileges
        let _ = seteuid(self.original_euid);
    }
}

/// Drop privileges to the specified UID, returns a guard that restores privileges on drop
pub fn drop_privileges(uid: u32) -> Result<PrivilegeGuard, io::Error> {
    let original_euid = geteuid();

    // Only drop privileges if we're running as root or with elevated privileges
    if original_euid.as_raw() == 0 || original_euid != Uid::from_raw(uid) {
        seteuid(Uid::from_raw(uid))
            .map_err(|e| io::Error::new(io::ErrorKind::PermissionDenied, e))?;
    }

    Ok(PrivilegeGuard { original_euid })
}