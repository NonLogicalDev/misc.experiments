"""
Bazel rules for Uber interview environment
Provides standardized build and run targets for all supported languages
"""

load("@rules_python//python:defs.bzl", "py_binary")
load("@rules_go//go:def.bzl", "go_binary")
load("@rules_java//java:defs.bzl", "java_binary")  
load("@rules_rust//rust:defs.bzl", "rust_binary")
load("@rules_cc//cc:defs.bzl", "cc_binary")
load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

#load("@rules_sh//shell:sh_binary.bzl", "sh_binary")

def python_interview(name, main_file = "main.py", deps = [], **kwargs):
    """Creates a Python interview solution target with standardized commands."""
    
    py_binary(
        name = "solution",
        srcs = [main_file],
        deps = deps + ["@pip//numpy", "@pip//pandas", "@pip//scipy", "@pip//matplotlib"],
        main = main_file,
        **kwargs
    )
    
    # Run with input file support
    sh_binary(
        name = "solution_with_input",
        srcs = ["//tools/bazel:run_with_input.sh"],
        args = ["$(location :solution)"],
        data = [":solution"] + native.glob(["input.txt"], allow_empty = True),
    )

def cpp_interview(name, main_file = "main.cpp", deps = [], **kwargs):
    """Creates a C++ interview solution target with standardized commands."""
    
    cc_binary(
        name = "solution",
        srcs = [main_file],
        deps = deps,
        **kwargs
    )
    
    # Run with input file support
    sh_binary(
        name = "solution_with_input",
        srcs = ["//tools/bazel:run_with_input.sh"],
        args = ["$(location :solution)"],
        data = [":solution"] + native.glob(["input.txt"], allow_empty = True),
    )

def go_interview(name, main_file = "main.go", deps = [], **kwargs):
    """Creates a Go interview solution target with standardized commands."""
    
    go_binary(
        name = "solution",
        srcs = [main_file],
        deps = deps,
        **kwargs
    )
    
    # Run with input file support  
    sh_binary(
        name = "solution_with_input",
        srcs = ["//tools/bazel:run_with_input.sh"],
        args = ["$(location :solution)"],
        data = [":solution"] + native.glob(["input.txt"], allow_empty = True),
    )

def java_interview(name, main_class = "Main", srcs = None, deps = [], **kwargs):
    """Creates a Java interview solution target with standardized commands."""
    
    if srcs == None:
        srcs = native.glob(["*.java"])
    
    java_binary(
        name = "solution", 
        srcs = srcs,
        main_class = main_class,
        deps = deps + ["@maven//:junit_junit", "@maven//:org_hamcrest_hamcrest_core"],
        **kwargs
    )
    
    # Run with input file support
    sh_binary(
        name = "solution_with_input", 
        srcs = ["//tools/bazel:run_with_input.sh"],
        args = ["$(location :solution)"],
        data = [":solution"] + native.glob(["input.txt"], allow_empty = True),
    )

def rust_interview(name, main_file = "main.rs", deps = [], edition = "2021", **kwargs):
    """Creates a Rust interview solution target with standardized commands."""
    
    rust_binary(
        name = "solution",
        srcs = [main_file],
        deps = deps + ["@crates//:serde", "@crates//:serde_json", "@crates//:itertools"],
        edition = edition,
        **kwargs
    )
    
    # Run with input file support
    sh_binary(
        name = "solution_with_input",
        srcs = ["//tools/bazel:run_with_input.sh"], 
        args = ["$(location :solution)"],
        data = [":solution"] + native.glob(["input.txt"], allow_empty = True),
    )