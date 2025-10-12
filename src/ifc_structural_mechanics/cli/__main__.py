"""
Entry point for running the CLI as a module.

This allows the CLI to be invoked as:
    python -m ifc_structural_mechanics.cli
"""

from .commands import cli

if __name__ == "__main__":
    cli()
