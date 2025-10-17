mod language;

use clap::Parser;
use language::{PromQLBuilder, pretty_print};
use std::io::{self, Read};

#[derive(Parser)]
#[command(name = "promql-builder")]
#[command(about = "Convert Flux-like query syntax to PromQL", long_about = None)]
struct Cli {
    /// Input query string (if not provided, reads from stdin)
    query: Option<String>,

    /// Pretty print the output with indentation
    #[arg(short, long)]
    pretty: bool,
}

fn main() {
    let cli = Cli::parse();

    let query = match cli.query {
        Some(q) => q,
        None => {
            // Read from stdin
            let mut buffer = String::new();
            io::stdin()
                .read_to_string(&mut buffer)
                .expect("Failed to read from stdin");

            if buffer.trim().is_empty() {
                eprintln!("Error: No input provided");
                eprintln!("\nUsage: promql-builder [OPTIONS] [QUERY]");
                eprintln!("\nExamples:");
                eprintln!("  promql-builder '{{metric}} | $[1m] | rate($) | sum by(le, method, path) $'");
                eprintln!("  promql-builder 'let base = {{metric=\"test\"}}; $base | $[5m] | rate($)'");
                eprintln!("  promql-builder --pretty 'http_requests_total | $[5m] | rate($)'");
                eprintln!("  echo 'http_requests_total | $[5m] | rate($)' | promql-builder -p");
                std::process::exit(1);
            }

            buffer
        }
    };

    let mut builder = PromQLBuilder::new();

    match builder.build(&query) {
        Ok(result) => {
            if cli.pretty {
                println!("{}", pretty_print(&result));
            } else {
                println!("{}", result);
            }
        }
        Err(e) => {
            eprintln!("Error: {}", e);
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Debug, Deserialize)]
    struct TestCase {
        name: String,
        input: String,
        expected: String,
    }

    fn load_test_cases() -> Vec<TestCase> {
        let yaml_content = include_str!("../tests/test_cases.yaml");
        serde_yaml::from_str(yaml_content).expect("Failed to parse test_cases.yaml")
    }

    #[test]
    fn run_all_test_cases() {
        let test_cases = load_test_cases();
        eprintln!("Running {} test cases from YAML", test_cases.len());
        let mut failed_tests = Vec::new();

        for test_case in &test_cases {
            let mut builder = PromQLBuilder::new();
            let input = test_case.input.trim();
            let expected = test_case.expected.trim();

            match builder.build(input) {
                Ok(result) => {
                    if result != expected {
                        failed_tests.push(format!(
                            "Test '{}' failed:\n  Input: {}\n  Expected: {}\n  Got: {}",
                            test_case.name, input, expected, result
                        ));
                    }
                }
                Err(e) => {
                    failed_tests.push(format!(
                        "Test '{}' error:\n  Input: {}\n  Error: {}",
                        test_case.name, input, e
                    ));
                }
            }
        }

        if !failed_tests.is_empty() {
            panic!(
                "\n{} test(s) failed:\n\n{}",
                failed_tests.len(),
                failed_tests.join("\n\n")
            );
        }
    }
}
