{
  description = "NIX Discreete Env Template";

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

            # Version Managers:
            pkgs.mise # -> generic language version manager
            pkgs.uv   # -> python package manager
          ];

          shellHook = ''
          eval "$(mise activate bash)"
          '';
        };
      };
    };
}
