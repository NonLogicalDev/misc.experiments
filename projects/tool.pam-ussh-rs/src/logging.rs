// Standard library imports
use std::sync::Mutex;

// External dependencies
use syslog::{Facility, Formatter3164, LoggerBackend};

static LOGGER: Mutex<Option<syslog::Logger<LoggerBackend, Formatter3164>>> = Mutex::new(None);
const LOG_PREFIX: &str = "[pam_ussh_rs]";

pub fn init_logger() {
    let mut logger = LOGGER.lock().unwrap();
    if logger.is_none() {
        let formatter = Formatter3164 {
            facility: Facility::LOG_AUTH,
            hostname: None,
            process: "pam-ussh".into(),
            pid: std::process::id(),
        };

        if let Ok(log) = syslog::unix(formatter) {
            *logger = Some(log);
        }
    }
}

pub fn pam_log_warn(message: &str) {
    init_logger();

    let mut logger = LOGGER.lock().unwrap();
    if let Some(ref mut log) = *logger {
        let _ = log.warning(&format!("{} {}", LOG_PREFIX, message));
    }

    // Also log to stderr for debugging
    eprintln!("{} [W] {}", LOG_PREFIX, message);
}

pub fn pam_log_info(message: &str) {
    init_logger();

    let mut logger = LOGGER.lock().unwrap();
    if let Some(ref mut log) = *logger {
        let _ = log.info(&format!("{} {}", LOG_PREFIX, message));
    }

    // Also log to stderr for debugging
    eprintln!("{} [I] {}", LOG_PREFIX, message);
}