"""Tests for the .frd file parser."""

import pytest

from ccxquery.parsers.frd_parser import (
    get_displacements,
    get_node_coords,
    get_result_blocks,
    get_stresses,
    parse_frd,
)


class TestParseFrd:
    def test_parses_nodes(self, frd_file):
        data = parse_frd(frd_file)
        nodes = data["nodes"]
        assert len(nodes) == 5
        assert 1 in nodes
        assert 5 in nodes

    def test_node_coordinates(self, frd_file):
        data = parse_frd(frd_file)
        nodes = data["nodes"]
        assert nodes[1] == (0.0, 0.0, 0.0)
        assert nodes[3] == (2.0, 0.0, 0.0)
        assert nodes[5] == (4.0, 0.0, 0.0)

    def test_parses_result_blocks(self, frd_file):
        data = parse_frd(frd_file)
        blocks = list(data["results"].keys())
        assert "DISP" in blocks
        assert "STRESS" in blocks


class TestGetNodeCoords:
    def test_returns_node_dict(self, frd_file):
        data = parse_frd(frd_file)
        nodes = get_node_coords(data)
        assert isinstance(nodes, dict)
        assert len(nodes) == 5


class TestGetResultBlocks:
    def test_lists_blocks(self, frd_file):
        data = parse_frd(frd_file)
        blocks = get_result_blocks(data)
        assert "DISP" in blocks
        assert "STRESS" in blocks


class TestGetDisplacements:
    def test_returns_displacement_data(self, frd_file):
        data = parse_frd(frd_file)
        disp = get_displacements(data)
        assert disp is not None
        assert len(disp) == 5

    def test_fixed_node_zero_disp(self, frd_file):
        data = parse_frd(frd_file)
        disp = get_displacements(data)
        # Node 1 is fixed
        assert disp[1] == [0.0, 0.0, 0.0]

    def test_loaded_node_has_displacement(self, frd_file):
        data = parse_frd(frd_file)
        disp = get_displacements(data)
        # Node 5 has max displacement
        assert len(disp[5]) == 3
        assert disp[5][1] == pytest.approx(-3.2e-3)

    def test_displacement_components(self, frd_file):
        data = parse_frd(frd_file)
        block = data["results"]["DISP"]
        assert "D1" in block["components"]
        assert "D2" in block["components"]
        assert "D3" in block["components"]


class TestGetStresses:
    def test_returns_stress_data(self, frd_file):
        data = parse_frd(frd_file)
        stress = get_stresses(data)
        assert stress is not None
        assert len(stress) == 5

    def test_stress_values(self, frd_file):
        data = parse_frd(frd_file)
        stress = get_stresses(data)
        # Node 1: SXX = 1e6
        assert stress[1][0] == pytest.approx(1e6)

    def test_stress_components(self, frd_file):
        data = parse_frd(frd_file)
        block = data["results"]["STRESS"]
        expected = ["SXX", "SYY", "SZZ", "SXY", "SYZ", "SZX"]
        assert block["components"] == expected

    def test_no_stresses_returns_none(self, tmp_path):
        """FRD file with only displacements returns None for stresses."""
        frd = tmp_path / "no_stress.frd"
        frd.write_text(
            """\
    1C
    2C                             2                                     1
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 1.00000E+00 0.00000E+00 0.00000E+00
 -3
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 1.00000E-03 0.00000E+00 0.00000E+00
 -3
 9999
"""
        )
        data = parse_frd(str(frd))
        assert get_stresses(data) is None
        assert get_displacements(data) is not None


class TestConcatenatedValues:
    """Test parsing of FRD files where values run together (no spaces)."""

    def test_negative_sign_concatenation(self, tmp_path):
        """Values like '2.80000E-04-1.20000E-03' should parse correctly."""
        frd = tmp_path / "concat.frd"
        frd.write_text(
            """\
    1C
    2C                             2                                     1
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 1.00000E+00 0.00000E+00 0.00000E+00
 -3
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 2.80000E-04-1.20000E-03 5.00000E-05
 -3
 9999
"""
        )
        data = parse_frd(str(frd))
        disp = get_displacements(data)
        assert disp is not None
        assert disp[2][0] == pytest.approx(2.8e-4)
        assert disp[2][1] == pytest.approx(-1.2e-3)
        assert disp[2][2] == pytest.approx(5e-5)
