{
    description = "strato-certbot development environment";

    inputs = {
        nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
        flake-utils.url = "github:numtide/flake-utils";
    };

    outputs =
        {
            self,
            nixpkgs,
            flake-utils,
        }:
        flake-utils.lib.eachDefaultSystem (
            system:
            let
                pkgs = import nixpkgs { inherit system; };
                buildInputs = with pkgs; [
                    python312
                    python312Packages.pyotp
                    python312Packages.beautifulsoup4
                ];
            in
            {
                devShell = pkgs.mkShell {
                    buildInputs = buildInputs;
                    shellHook = ''
                        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${pkgs.lib.makeLibraryPath buildInputs}"
                    '';
                };
            }
        );
}
