"""Tests for mshquery CLI entry point."""

import json
import subprocess
import sys


def run_mshquery(*args):
    """Run mshquery as a subprocess and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "mshquery", *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class TestCliBasics:
    def test_no_args_shows_usage(self):
        rc, out, err = run_mshquery()
        assert rc != 0

    def test_missing_file(self):
        rc, out, err = run_mshquery("/nonexistent/file.msh", "summary")
        assert rc == 1
        assert "Error" in err

    def test_help(self):
        rc, out, err = run_mshquery("--help")
        assert rc == 0
        assert "mshquery" in out


class TestCliCommands:
    def test_summary(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "summary")
        assert rc == 0
        data = json.loads(out)
        assert data["nodes"] == 5
        assert data["elements"] == 6

    def test_summary_text(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "summary", "--format", "text")
        assert rc == 0
        assert "nodes:" in out

    def test_info_node(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "info", "node", "1")
        assert rc == 0
        data = json.loads(out)
        assert data["id"] == 1

    def test_info_element(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "info", "element", "1")
        assert rc == 0
        data = json.loads(out)
        assert data["type"] == "vertex"

    def test_nodes(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "nodes")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 5

    def test_nodes_range(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "nodes", "--range", "1-3")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 3

    def test_select_nodes_at(self, msh_file):
        rc, out, err = run_mshquery(
            msh_file, "select", "nodes-at", "--x", "0.0", "--y", "0.0", "--z", "0.0"
        )
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 1

    def test_select_elements_with_node(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "select", "elements-with-node", "1")
        assert rc == 0
        data = json.loads(out)
        assert len(data) >= 1

    def test_select_elements_by_type(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "select", "elements-by-type", "line")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 4

    def test_groups(self, msh_file):
        rc, out, err = run_mshquery(msh_file, "groups")
        assert rc == 0
        data = json.loads(out)
        assert isinstance(data, list)

    def test_format_flag_position(self, msh_file):
        """--format should work after the subcommand."""
        rc, out, err = run_mshquery(
            msh_file, "nodes", "--range", "1-2", "--format", "json"
        )
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 2
