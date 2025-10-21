//! pam-ussh-rs
//!
//! A PAM module for SSH certificate-based authentication using ssh-agent.

// External dependencies
use pam::constants::{PamFlag, PamResultCode};
use pam::module::{PamHandle, PamHooks};
use std::ffi::CStr;

// Local imports
use auth::{authenticate, AuthResult, Config};
use logging::pam_log_warn;

// Local modules
mod auth;
mod logging;
mod platform;

struct PamUssh;
pam::pam_hooks!(PamUssh);

impl PamHooks for PamUssh {
    fn sm_authenticate(pamh: &mut PamHandle, args: Vec<&CStr>, _flags: PamFlag) -> PamResultCode {
        platform::initialize_platform();

        // Get username from PAM
        let pam_user_name = match pamh.get_user(None) {
            Ok(u) => u,
            Err(e) => {
                pam_log_warn(&format!("unable to get PAM username: {:?}", e));
                return PamResultCode::PAM_USER_UNKNOWN;
            }
        };

        // Get system user info for PAM username
        let system_user_info = match auth::user_get_system_info(&pam_user_name) {
            Ok(u) => u,
            Err(e) => {
                pam_log_warn(&format!("unable to get system user info for PAM username '{}': {}", pam_user_name, e));
                return PamResultCode::PAM_USER_UNKNOWN;
            }
        };

        // Parse configuration from PAM arguments
        let config = match Config::from_cargs(args) {
            Ok(c) => c,
            Err(e) => {
                pam_log_warn(&format!("configuration error: {}", e));
                return PamResultCode::PAM_AUTH_ERR;
            }
        };

        // Check group membership if specified
        if let Some(ref group) = config.group {
            if !system_user_info.is_member_of_group(group) {
                pam_log_warn(&format!( "user not member of required group: {}", group));

                // Per original Go implementation, return success if group is set and user is not in group.
                // Only enforce this for users who are part of the group.
                return PamResultCode::PAM_SUCCESS;
            }
        } else {
            // No group requirement, skip check 
        }

        // Perform authentication
        match authenticate(&pam_user_name, &system_user_info, &config) {
            AuthResult::Success => PamResultCode::PAM_SUCCESS,
            AuthResult::Error => PamResultCode::PAM_AUTH_ERR,
        }
    }

    fn sm_setcred(_pamh: &mut PamHandle, _args: Vec<&CStr>, _flags: PamFlag) -> PamResultCode {
        platform::initialize_platform();
        PamResultCode::PAM_IGNORE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_parsing() {
        let args = vec![
            "ca_file=/etc/ssh/ca.pub".to_string(),
            "group=ssh-users".to_string(),
        ];

        let config = Config::from_args(&args).unwrap();
        assert_eq!(config.ca_file, "/etc/ssh/ca.pub");
        assert_eq!(config.group, "ssh-users");
    }
}
