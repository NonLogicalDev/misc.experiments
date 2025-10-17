{
  description = "Uber Interview Validation Environment - Bazel Edition";

  inputs = {
    # Helper Packages to cut down on flake boilerplate.
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = inputs @ { flake-parts, nixpkgs, ...  }:
    flake-parts.lib.mkFlake {inherit inputs;} {
      # This tells flake-parts what systems to support (default set)
      systems = nixpkgs.lib.systems.flakeExposed;


      # The perSystem function is where we define outputs that should exist for each system
      perSystem = {
        config,      # The perSystem module config (allows accessing other perSystem outputs)
        self',       # The outputs of this flake for the current system (e.g., self'.packages, self'.devShells)
        inputs',     # The inputs of this flake scoped to the current system (e.g., inputs'.nixpkgs.legacyPackages)
        pkgs,        # The nixpkgs package set for the current system (automatically instantiated)
        system,      # The current system string (e.g., "x86_64-linux", "aarch64-darwin", "x86_64-darwin")
        ...
      }: {
        # Define the development shell (invoked by direnv to set up project dependencies, and env vars)
        devShells.default = pkgs.mkShell {
          packages = [
            # Environment deps:
            pkgs.just
            pkgs.direnv

            # Bazel - primary build system
            pkgs.bazel_7

            # Minimal Python for scaffolding scripts only
            pkgs.python3

            # uv for fast Python dependency management
            pkgs.uv

            # Development tools
            pkgs.git

            # Optional: system tools that Bazel might need
            pkgs.which
            pkgs.findutils
            pkgs.coreutils
          ];

          shellHook = ''
            echo "🚀 Quick Interview Environment Loaded (Bazel Edition)"
            echo "Build system: $(bazel version | head -n1)"
            echo "Python (for scaffolding): $(python --version)"
            echo ""
            echo "Available commands:"
            echo "  bazel run //interviews/<name>:solution     - Run interview solution"
            echo "  bazel build //interviews/<name>:solution   - Build interview solution"
            echo "  bazel test //interviews/<name>:test        - Run tests (if available)"
            echo ""
          '';
        };
      };
    };
}