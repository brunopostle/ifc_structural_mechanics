"""Tests for the .dat file parser."""

import pytest
from conftest import SAMPLE_DAT_MINIMAL, SAMPLE_DAT_NO_CONVERGENCE

from ccxquery.parsers.dat_parser import parse_dat


class TestParseDat:
    def test_parses_without_error(self, dat_file):
        data = parse_dat(dat_file)
        assert "reactions" in data
        assert "totals" in data
        assert "status" in data


class TestReactions:
    def test_parses_node_reactions(self, dat_file):
        data = parse_dat(dat_file)
        reactions = data["reactions"]
        assert len(reactions) == 3  # nodes 1, 4, 5

    def test_reaction_values(self, dat_file):
        data = parse_dat(dat_file)
        reactions = data["reactions"]
        node1 = next(r for r in reactions if r["node"] == 1)
        assert node1["fx"] == pytest.approx(5000.0)
        assert node1["fy"] == pytest.approx(10000.0)
        assert node1["fz"] == pytest.approx(0.0)

    def test_multiple_reaction_nodes(self, dat_file):
        data = parse_dat(dat_file)
        reactions = data["reactions"]
        nodes = [r["node"] for r in reactions]
        assert 1 in nodes
        assert 4 in nodes
        assert 5 in nodes


class TestTotals:
    def test_parses_total_force(self, dat_file):
        data = parse_dat(dat_file)
        totals = data["totals"]
        assert totals is not None

    def test_total_force_values(self, dat_file):
        data = parse_dat(dat_file)
        totals = data["totals"]
        # Returns first total force block: FIX_LEFT set
        assert totals["fx"] == pytest.approx(5000.0)
        assert totals["fy"] == pytest.approx(10000.0)
        assert totals["fz"] == pytest.approx(0.0)

    def test_values_on_next_line(self, tmp_path):
        """Total force with values on the line after header + blank line."""
        dat = tmp_path / "totals.dat"
        dat.write_text(
            """\

                        S T E P       1

 total force (fx,fy,fz) for set ALL and time  0.1000000E+01

        1.23456E+03  7.89012E+02  3.45678E+01
"""
        )
        data = parse_dat(str(dat))
        assert data["totals"] is not None
        assert data["totals"]["fx"] == pytest.approx(1234.56)
        assert data["totals"]["fy"] == pytest.approx(789.012)
        assert data["totals"]["fz"] == pytest.approx(34.5678)

    def test_no_totals_in_empty(self, tmp_path):
        dat = tmp_path / "empty.dat"
        dat.write_text("")
        data = parse_dat(str(dat))
        assert data["totals"] is None


class TestStatus:
    def test_completed(self, dat_file):
        data = parse_dat(dat_file)
        assert data["status"] == "completed"

    def test_no_convergence(self, tmp_path):
        dat = tmp_path / "noconv.dat"
        dat.write_text(SAMPLE_DAT_NO_CONVERGENCE)
        data = parse_dat(str(dat))
        assert data["status"] == "no_convergence"

    def test_minimal_dat(self, tmp_path):
        """'S T E P' with spaces doesn't match 'step' — returns unknown."""
        dat = tmp_path / "minimal.dat"
        dat.write_text(SAMPLE_DAT_MINIMAL)
        data = parse_dat(str(dat))
        assert data["status"] == "unknown"

    def test_empty_file(self, tmp_path):
        dat = tmp_path / "empty.dat"
        dat.write_text("")
        data = parse_dat(str(dat))
        assert data["status"] == "unknown"

    def test_divergence(self, tmp_path):
        dat = tmp_path / "div.dat"
        dat.write_text("solution seems to diverge\n")
        data = parse_dat(str(dat))
        assert data["status"] == "divergence"

    def test_job_finished(self, tmp_path):
        dat = tmp_path / "done.dat"
        dat.write_text("job finished\n")
        data = parse_dat(str(dat))
        assert data["status"] == "completed"
