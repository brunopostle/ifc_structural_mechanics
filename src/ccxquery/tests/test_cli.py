"""Tests for ccxquery CLI entry point."""

import json
import subprocess
import sys
import pytest


def run_ccxquery(*args):
    """Run ccxquery as a subprocess and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "ccxquery", *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class TestCliBasics:
    def test_no_args_shows_usage(self):
        rc, out, err = run_ccxquery()
        assert rc != 0

    def test_missing_file(self):
        rc, out, err = run_ccxquery("/nonexistent/file.inp", "summary")
        assert rc == 1
        assert "Error" in err

    def test_help(self):
        rc, out, err = run_ccxquery("--help")
        assert rc == 0
        assert "ccxquery" in out


class TestCliInpCommands:
    def test_summary_json(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "summary")
        assert rc == 0
        data = json.loads(out)
        assert data["nodes"] == 5
        assert data["elements"] == 4

    def test_summary_text(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "summary", "--format", "text")
        assert rc == 0
        assert "nodes:" in out
        assert "elements:" in out

    def test_bcs(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "bcs")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 2

    def test_loads(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "loads")
        assert rc == 0
        data = json.loads(out)
        assert len(data["concentrated_loads"]) == 1

    def test_materials(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "materials")
        assert rc == 0
        data = json.loads(out)
        assert data[0]["name"] == "STEEL"

    def test_sections(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "sections")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 1

    def test_steps(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "steps")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 1

    def test_sets(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "sets")
        assert rc == 0
        data = json.loads(out)
        assert len(data) > 0

    def test_sets_filter_node(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "sets", "--type", "node")
        assert rc == 0
        data = json.loads(out)
        for s in data:
            assert s["type"] == "node"

    def test_set_by_name(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "set", "FIX_LEFT")
        assert rc == 0
        data = json.loads(out)
        assert data["ids"] == [1]

    def test_node(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "node", "1")
        assert rc == 0
        data = json.loads(out)
        assert data["id"] == 1
        assert data["x"] == 0.0

    def test_nodes_at(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "nodes-at", "--x", "0.0", "--y", "0.0", "--z", "0.0")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 1


class TestCliFrdCommands:
    def test_summary(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "summary")
        assert rc == 0
        data = json.loads(out)
        assert data["nodes"] == 5
        assert "DISP" in data["result_blocks"]

    def test_results(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "results")
        assert rc == 0
        data = json.loads(out)
        names = [r["name"] for r in data]
        assert "DISP" in names

    def test_displacements_all(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "displacements")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 5

    def test_displacements_max(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "displacements", "--max")
        assert rc == 0
        data = json.loads(out)
        assert data["node"] == 5

    def test_displacements_node(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "displacements", "--node", "3")
        assert rc == 0
        data = json.loads(out)
        assert data["node"] == 3

    def test_stresses(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "stresses")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 5

    def test_node_from_frd(self, frd_file):
        rc, out, err = run_ccxquery(frd_file, "node", "1")
        assert rc == 0
        data = json.loads(out)
        assert data["id"] == 1


class TestCliDatCommands:
    def test_reactions(self, dat_file):
        rc, out, err = run_ccxquery(dat_file, "reactions")
        assert rc == 0
        data = json.loads(out)
        assert "reactions" in data
        assert "totals" in data

    def test_status(self, dat_file):
        rc, out, err = run_ccxquery(dat_file, "status")
        assert rc == 0
        data = json.loads(out)
        assert data["status"] == "completed"


class TestCliSiblingResolution:
    def test_displacements_from_inp(self, analysis_dir):
        inp_path = str(analysis_dir / "analysis.inp")
        rc, out, err = run_ccxquery(inp_path, "displacements", "--max")
        assert rc == 0
        data = json.loads(out)
        assert "node" in data

    def test_reactions_from_inp(self, analysis_dir):
        inp_path = str(analysis_dir / "analysis.inp")
        rc, out, err = run_ccxquery(inp_path, "reactions")
        assert rc == 0
        data = json.loads(out)
        assert "totals" in data

    def test_bcs_from_frd(self, analysis_dir):
        frd_path = str(analysis_dir / "analysis.frd")
        rc, out, err = run_ccxquery(frd_path, "bcs")
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 2


class TestCliFormatFlag:
    def test_format_after_command(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "summary", "--format", "text")
        assert rc == 0
        assert "nodes:" in out

    def test_format_json_default(self, inp_file):
        rc, out, err = run_ccxquery(inp_file, "summary")
        assert rc == 0
        json.loads(out)  # Should be valid JSON
