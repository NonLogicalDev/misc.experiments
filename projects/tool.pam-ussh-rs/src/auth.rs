// Standard library imports
use std::collections::HashSet;
use std::ffi::{CStr, OsStr};
use std::fs;
use std::io::{self, BufRead};
use std::path::{Path, PathBuf};
use std::rc::Rc;

// External dependencies
use rand::RngCore;
use signature::Verifier;
use ssh_agent_client_rs::{Client, Identity};
use ssh_key::{Certificate, PublicKey};
use uzers::os::unix::GroupExt;

// Local imports
use crate::logging::{pam_log_info, pam_log_warn};
use crate::platform;

const DEFAULT_USER_CA: &str = "/etc/ssh/trusted_user_ca";

#[derive(Debug, PartialEq)]
pub enum AuthResult {
    Success,
    Error,
}


/// Authenticate user via SSH agent certificates
pub fn authenticate(
    pam_user_name: &str,
    system_user_info: &SystemUserInfo,
    config: &Config,
) -> AuthResult {
    let auth_sock = match std::env::var("SSH_AUTH_SOCK") {
        Ok(sock) => sock,
        Err(_) => {
            pam_log_warn("No SSH_AUTH_SOCK environment variable");
            return AuthResult::Error;
        }
    };

    // Drop privileges to the target user
    let _guard = match platform::drop_privileges(system_user_info.uid) {
        Ok(g) => g,
        Err(e) => {
            pam_log_warn(&format!(
                "error dropping privileges to system user '{}' (uid {}): {}",
                system_user_info.user_name_str(),
                system_user_info.uid,
                e
            ));
            return AuthResult::Error;
        }
    };

    // Connect to SSH agent using ssh-agent-client-rs
    let mut client = match Client::connect(Path::new(&auth_sock)) {
        Ok(c) => c,
        Err(e) => {
            pam_log_warn(&format!("error connecting to SSH agent '{}': {}", auth_sock, e));
            return AuthResult::Error;
        }
    };

    // List identities from agent
    let identities = match client.list_all_identities() {
        Ok(ids) => ids,
        Err(e) => {
            pam_log_warn(&format!("error listing keys: {}", e));
            return AuthResult::Error;
        }
    };

    if identities.is_empty() {
        pam_log_warn("no certificates loaded in agent");
        return AuthResult::Error;
    }

    // Check each identity
    for identity in identities {
        // Only process certificates, skip regular public keys
        let cert = match &identity {
            Identity::Certificate(cert) => cert.as_ref(),
            Identity::PublicKey(_) => {
                // Not a certificate, just a regular key - skip
                continue;
            }
        };

        // Check if certificate is valid for this username
        if !cert.valid_principals().iter().any(|p| p == pam_user_name) {
            continue;
        }

        // Check if signed by trusted CA
        if !config.is_cert_signed_by_ca(cert) {
            pam_log_warn("certificate signed by unrecognized authority");
            continue;
        }

        // Verify the certificate's CA signature
        // This ensures the certificate was actually signed by the claimed CA
        if let Err(e) = cert.verify_signature() {
            pam_log_warn(&format!("certificate signature verification failed: {}", e));
            continue;
        }

        // Generate random challenge
        let mut challenge = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut challenge);

        // Request signature from agent to prove possession of private key
        let signature = match client.sign(cert.as_ref(), &challenge) {
            Ok(sig) => sig,
            Err(e) => {
                pam_log_warn(&format!("error signing challenge: {}", e));
                return AuthResult::Error;
            }
        };

        // Verify the signature using the certificate's public key
        // This proves the user has access to the private key via the SSH agent
        if let Err(e) = cert.public_key().verify(&challenge, &signature) {
            pam_log_warn(&format!("signature verification failed: {}", e));
            continue;
        }

        // Check principals if specified
        if !config.authorized_principals.is_empty() {
            let mut matched = false;
            for principal in cert.valid_principals() {
                if config.authorized_principals.contains(principal) {
                    pam_log_info(&format!(
                        "authentication succeeded for {}. matched principal {}, cert {}",
                        pam_user_name,
                        principal,
                        cert.serial()
                    ));
                    matched = true;
                    break;
                }
            }
            if matched {
                return AuthResult::Success;
            }
        } else {
            let first_principal = cert
                .valid_principals()
                .first()
                .map(|s| s.as_str())
                .unwrap_or("<none>");
            pam_log_info(&format!(
                "authentication succeeded for {} (cert {}, {})",
                pam_user_name,
                first_principal,
                cert.serial()
            ));
            return AuthResult::Success;
        }
    }

    pam_log_warn("no valid certificates found");
    AuthResult::Error
}

/// Represents the source of authorized principals configuration
#[derive(Debug, Clone, PartialEq)]
pub enum PrincipalSource {
    /// Principals specified directly as parameters
    Param(HashSet<String>),
    /// Principals loaded from a file
    File { path: PathBuf, principals: HashSet<String> },
}

/// Configuration for PAM SSH certificate authentication
#[derive(Debug, Clone)]
pub struct Config {
    /// Pre-loaded CA public keys
    pub ca_keys: HashSet<PublicKey>,
    /// Sources of CA keys (file paths)
    pub ca_key_sources: Vec<PathBuf>,
    /// Combined set of all authorized principals
    pub authorized_principals: HashSet<String>,
    /// Sources of authorized principals
    pub authorized_principal_sources: Vec<PrincipalSource>,
    /// Optional group name for authorization
    pub group: Option<String>,
}

/// Builder for constructing Config instances
#[derive(Debug, Default)]
pub struct ConfigBuilder {
    ca_key_sources: Vec<PathBuf>,
    principal_sources: Vec<PrincipalSource>,
    group: Option<String>,
}

impl ConfigBuilder {
    /// Create a new ConfigBuilder
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a CA key file source
    pub fn ca_key_file<P: Into<PathBuf>>(mut self, path: P) -> Self {
        self.ca_key_sources.push(path.into());
        self
    }

    /// Add multiple CA key file sources
    pub fn ca_key_files<I, P>(mut self, paths: I) -> Self
    where
        I: IntoIterator<Item = P>,
        P: Into<PathBuf>,
    {
        self.ca_key_sources.extend(paths.into_iter().map(|p| p.into()));
        self
    }

    /// Add authorized principals directly
    pub fn authorized_principals<I, S>(mut self, principals: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let principal_set: HashSet<String> = principals.into_iter().map(|s| s.into()).collect();
        if !principal_set.is_empty() {
            self.principal_sources.push(PrincipalSource::Param(principal_set));
        }
        self
    }

    /// Add authorized principals from a file
    pub fn authorized_principals_file<P: Into<PathBuf>>(mut self, path: P) -> Self {
        self.principal_sources.push(PrincipalSource::File {
            path: path.into(),
            principals: HashSet::new(), // Will be loaded during build
        });
        self
    }

    /// Set the group requirement
    pub fn group<S: Into<String>>(mut self, group: S) -> Self {
        self.group = Some(group.into());
        self
    }

    /// Load trusted CA public keys from a file
    fn load_ca_keys_from_file(ca_path: &str) -> Result<Vec<PublicKey>, String> {
        let contents =
            fs::read_to_string(ca_path)
            .map_err(|e| format!("error reading CA file '{}': {}", ca_path, e))?;

        let mut ca_keys = Vec::new();
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }

            match PublicKey::from_openssh(line) {
                Ok(key) => ca_keys.push(key),
                Err(e) => pam_log_warn(&format!("skipping bad public key in '{}': {}", ca_path, e)),
            }
        }

        if ca_keys.is_empty() {
            return Err(format!("no valid CA keys found in '{}'", ca_path));
        }

        Ok(ca_keys)
    }

    /// Load authorized principals from a file
    fn load_principals_from_file(path: &str) -> Result<HashSet<String>, String> {
        let file = fs::File::open(path)
            .map_err(|e| format!("error opening principals file '{}': {}", path, e))?;
        let reader = io::BufReader::new(file);
        let mut principals = HashSet::new();

        for line in reader.lines() {
            let line = line.map_err(|e| format!("error reading principals file '{}': {}", path, e))?;
            let trimmed = line.trim();
            if !trimmed.is_empty() && !trimmed.starts_with('#') {
                principals.insert(trimmed.to_string());
            }
        }

        Ok(principals)
    }

    /// Build the Config, loading all CA keys and principals
    pub fn build(mut self) -> Result<Config, String> {
        // If no CA sources specified, use default
        if self.ca_key_sources.is_empty() {
            self.ca_key_sources.push(PathBuf::from(DEFAULT_USER_CA));
        }

        // Load CA keys from all sources
        let mut ca_keys = HashSet::new();
        for ca_path in &self.ca_key_sources {
            let keys = Self::load_ca_keys_from_file(ca_path.to_str().ok_or("invalid CA path")?)?;
            ca_keys.extend(keys);
        }

        // Load principals from all sources
        let mut all_principals = HashSet::new();
        for source in &mut self.principal_sources {
            match source {
                PrincipalSource::Param(principals) => {
                    all_principals.extend(principals.iter().cloned());
                }
                PrincipalSource::File { path, principals } => {
                    let loaded = Self::load_principals_from_file(
                        path.to_str().ok_or("invalid principals file path")?
                    )?;
                    principals.extend(loaded.iter().cloned());
                    all_principals.extend(loaded);
                }
            }
        }

        Ok(Config {
            ca_keys,
            ca_key_sources: self.ca_key_sources,
            authorized_principals: all_principals,
            authorized_principal_sources: self.principal_sources,
            group: self.group,
        })
    }
}

impl Config {
    /// Check if a certificate is signed by a trusted CA
    pub fn is_cert_signed_by_ca(&self, cert: &Certificate) -> bool {
        let sig_key = cert.signature_key();

        for ca_key in &self.ca_keys {
            // Compare the key data of the signature key with the CA key
            if sig_key == ca_key.key_data() {
                return true;
            }
        }
        false
    }

    /// Parse configuration from C-style arguments
    pub fn from_cargs(args: Vec<&CStr>) -> Result<Self, String> {
        let args_vec: Vec<String> = args
            .iter()
            .filter_map(|cs| cs.to_str().ok().map(|s| s.to_string()))
            .collect();

        Config::from_args(&args_vec)
    }

    /// Parse configuration from string arguments
    pub fn from_args(args: &[String]) -> Result<Self, String> {
        let mut builder = ConfigBuilder::new();

        for arg in args {
            let parts: Vec<&str> = arg.splitn(2, '=').collect();
            if parts.len() != 2 {
                pam_log_warn(&format!("CONFIG: invalid argument format: {}", arg));
                continue;
            }

            match parts[0] {
                "ca_file" => {
                    builder = builder.ca_key_file(parts[1]);
                    pam_log_info(&format!("ca_file set to {}", parts[1]));
                }
                "group" => {
                    builder = builder.group(parts[1]);
                    pam_log_info(&format!("group set to {}", parts[1]));
                }
                "authorized_principals" => {
                    let principals: Vec<&str> = parts[1].split(',').collect();
                    builder = builder.authorized_principals(principals);
                    pam_log_info(&format!("authorized_principals set to {}", parts[1]));
                }
                "authorized_principals_file" => {
                    builder = builder.authorized_principals_file(parts[1]);
                    pam_log_info(&format!("authorized_principals_file set to {}", parts[1]));
                }
                _ => {
                    pam_log_warn(&format!("CONFIG: unknown option: {}", parts[0]));
                }
            }
        }

        builder.build()
    }
}

pub struct SystemUserInfo {
    pub uid: u32,
    pub user_name: Rc<OsStr>,

    pub gid: u32,
    pub group_name: Rc<OsStr>,
}

pub fn user_get_system_info(username: &str) -> Result<SystemUserInfo, String> {
    let user = uzers::get_user_by_name(username).ok_or_else(|| format!("user not found: {}", username))?;
    let group = uzers::get_group_by_gid(user.primary_group_id()).ok_or_else(|| format!("group not found: {}", user.primary_group_id()))?;

    let user_name = Rc::from(user.name());
    let group_name = Rc::from(group.name());

    Ok(SystemUserInfo {
        uid: u32::from(user.uid()),
        user_name,

        gid: u32::from(user.primary_group_id()),
        group_name,
    })
}

impl SystemUserInfo {
    pub fn user_name_str(&self) -> String {
        self.user_name.to_string_lossy().to_string()
    }

    pub fn group_name_str(&self) -> String {
        self.group_name.to_string_lossy().to_string()
    }

    pub fn is_member_of_group<T: AsRef<OsStr> + ?Sized>(&self, check_group_name: &T) -> bool {
        if check_group_name.as_ref().is_empty() {
            return false;
        }

        // Get the group by name
        let check_group = match uzers::get_group_by_name(check_group_name) {
            Some(g) => g,
            None => {
                pam_log_warn(&format!("group not found: {:?}", check_group_name.as_ref().to_string_lossy()));
                return false;
            }
        };

        // Check if the group is the same as the user's primary group
        if check_group.gid() == self.gid {
            return true;
        }

        // Otherwise, check if the user is in the group's member list
        check_group.members().iter().any(|member| member == &*self.user_name)
    }
}