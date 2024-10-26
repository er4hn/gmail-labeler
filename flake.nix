{
  description = "A Python project using Gmail APIs with Black, Pylint, and jsonschema";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonPackages = pkgs.python3Packages;
      in
      {
        devShell = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3
            pythonPackages.google-auth
            pythonPackages.google-auth-oauthlib
            pythonPackages.google-auth-httplib2
            pythonPackages.google-api-python-client
            pythonPackages.black
            pythonPackages.pylint
            pythonPackages.jsonschema
            # Add any other dependencies your project needs
          ];
          shellHook = ''
            echo "Gmail API Python project environment"
            echo "Python version: $(python --version)"
            echo "Black version: $(black --version)"
            echo "Pylint version: $(pylint --version)"
            echo "jsonschema version: $(python -c 'import jsonschema; print(f"jsonschema version: {jsonschema.__version__}")')"
            
            # You can add aliases or other setup commands here
            alias format="black ."
            alias lint="pylint --disable=C,R **/*.py"
          '';
        };
      });
}
