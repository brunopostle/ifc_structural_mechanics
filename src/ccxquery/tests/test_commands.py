"""Tests for ccxquery command modules."""

import math
import pytest
from ccxquery.parsers.inp_parser import parse_inp
from ccxquery.parsers.frd_parser import parse_frd
from ccxquery.parsers.dat_parser import parse_dat
from ccxquery import summary, sets, materials, sections as sections_mod, bcs, loads, steps, node, displacements, stresses, reactions, results, status


class TestSummaryInp:
    def test_node_count(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert result["nodes"] == 5

    def test_element_count(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert result["elements"] == 4

    def test_element_types(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert result["element_types"]["B31"] == 4

    def test_material_count(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert result["materials"] == 1

    def test_step_count(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert result["steps"] == 1

    def test_keywords_list(self, inp_file):
        s = parse_inp(inp_file)
        result = summary.summary_inp(s)
        assert isinstance(result["keywords"], list)
        assert "NODE" in result["keywords"]


class TestSummaryFrd:
    def test_node_count(self, frd_file):
        data = parse_frd(frd_file)
        result = summary.summary_frd(data)
        assert result["nodes"] == 5

    def test_result_blocks(self, frd_file):
        data = parse_frd(frd_file)
        result = summary.summary_frd(data)
        assert "DISP" in result["result_blocks"]
        assert "STRESS" in result["result_blocks"]
        assert result["result_blocks"]["DISP"]["node_count"] == 5


class TestSets:
    def test_list_all_sets(self, inp_file):
        s = parse_inp(inp_file)
        result = sets.list_sets(s)
        names = [r["name"] for r in result]
        assert "FIX_LEFT" in names
        assert "FIX_RIGHT" in names

    def test_filter_node_sets(self, inp_file):
        s = parse_inp(inp_file)
        result = sets.list_sets(s, set_type="node")
        for r in result:
            assert r["type"] == "node"

    def test_filter_element_sets(self, inp_file):
        s = parse_inp(inp_file)
        result = sets.list_sets(s, set_type="element")
        for r in result:
            assert r["type"] == "element"

    def test_show_set(self, inp_file):
        s = parse_inp(inp_file)
        result = sets.show_set(s, "FIX_LEFT")
        assert result["type"] == "node"
        assert result["ids"] == [1]

    def test_show_set_not_found(self, inp_file):
        s = parse_inp(inp_file)
        result = sets.show_set(s, "NONEXISTENT")
        assert "error" in result


class TestMaterials:
    def test_returns_materials(self, inp_file):
        s = parse_inp(inp_file)
        result = materials.materials(s)
        assert len(result) == 1
        assert result[0]["name"] == "STEEL"


class TestSections:
    def test_returns_sections(self, inp_file):
        s = parse_inp(inp_file)
        result = sections_mod.sections(s)
        assert len(result) == 1
        assert result[0]["type"] == "beam_section"


class TestBcs:
    def test_returns_bcs(self, inp_file):
        s = parse_inp(inp_file)
        result = bcs.bcs(s)
        assert len(result) == 2


class TestLoads:
    def test_returns_loads(self, inp_file):
        s = parse_inp(inp_file)
        result = loads.loads(s)
        assert len(result["concentrated_loads"]) == 1
        assert len(result["distributed_loads"]) == 1


class TestSteps:
    def test_returns_steps(self, inp_file):
        s = parse_inp(inp_file)
        result = steps.steps(s)
        assert len(result) == 1
        assert "STATIC" in result[0]["keywords"]


class TestNode:
    def test_node_info_from_inp(self, inp_file):
        s = parse_inp(inp_file)
        nodes = node.get_nodes_from_inp(s)
        result = node.node_info(1, nodes)
        assert result["id"] == 1
        assert result["x"] == 0.0

    def test_node_info_from_frd(self, frd_file):
        data = parse_frd(frd_file)
        nodes = node.get_nodes_from_frd(data)
        result = node.node_info(5, nodes)
        assert result["id"] == 5
        assert result["x"] == 4.0

    def test_node_not_found(self, inp_file):
        s = parse_inp(inp_file)
        nodes = node.get_nodes_from_inp(s)
        result = node.node_info(999, nodes)
        assert "error" in result

    def test_nodes_at(self, inp_file):
        s = parse_inp(inp_file)
        nodes = node.get_nodes_from_inp(s)
        result = node.nodes_at(nodes, x=0.0, y=0.0, z=0.0)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_nodes_at_partial_coords(self, inp_file):
        s = parse_inp(inp_file)
        nodes = node.get_nodes_from_inp(s)
        # All nodes have y=0, z=0
        result = node.nodes_at(nodes, y=0.0, z=0.0)
        assert len(result) == 5

    def test_nodes_at_no_match(self, inp_file):
        s = parse_inp(inp_file)
        nodes = node.get_nodes_from_inp(s)
        result = node.nodes_at(nodes, x=99.0)
        assert len(result) == 0


class TestDisplacements:
    def test_all_displacements(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_single_node(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data, node_id=5)
        assert result["node"] == 5
        assert result["D2"] == pytest.approx(-3.2e-3)

    def test_max_displacement(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data, show_max=True)
        assert result["node"] == 5  # Tip has largest displacement

    def test_min_displacement(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data, show_min=True)
        assert result["node"] == 1  # Fixed end has zero displacement

    def test_magnitude_calculated(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data, node_id=5)
        expected = math.sqrt(4e-4**2 + 3.2e-3**2)
        assert result["magnitude"] == pytest.approx(expected)

    def test_node_not_found(self, frd_file):
        data = parse_frd(frd_file)
        result = displacements.displacements(data, node_id=999)
        assert "error" in result


class TestStresses:
    def test_all_stresses(self, frd_file):
        data = parse_frd(frd_file)
        result = stresses.stresses(data)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_single_node(self, frd_file):
        data = parse_frd(frd_file)
        result = stresses.stresses(data, node_id=1)
        assert result["node"] == 1
        assert result["SXX"] == pytest.approx(1e6)

    def test_von_mises(self, frd_file):
        data = parse_frd(frd_file)
        result = stresses.stresses(data, node_id=1)
        # Pure uniaxial: von_mises = SXX
        assert result["von_mises"] == pytest.approx(1e6)

    def test_max_stress(self, frd_file):
        data = parse_frd(frd_file)
        result = stresses.stresses(data, show_max=True)
        assert result["node"] == 1  # Highest SXX

    def test_node_not_found(self, frd_file):
        data = parse_frd(frd_file)
        result = stresses.stresses(data, node_id=999)
        assert "error" in result

    def test_no_stress_data(self, tmp_path):
        frd = tmp_path / "no_stress.frd"
        frd.write_text("""\
    1C
    2C                             1                                     1
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -3
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -3
 9999
""")
        data = parse_frd(str(frd))
        result = stresses.stresses(data)
        assert "error" in result


class TestReactions:
    def test_returns_reactions(self, dat_file):
        data = parse_dat(dat_file)
        result = reactions.reactions(data)
        assert "reactions" in result
        assert "totals" in result

    def test_reaction_nodes(self, dat_file):
        data = parse_dat(dat_file)
        result = reactions.reactions(data)
        assert len(result["reactions"]) == 3
        nodes = [r["node"] for r in result["reactions"]]
        assert 1 in nodes


class TestResults:
    def test_lists_result_blocks(self, frd_file):
        data = parse_frd(frd_file)
        result = results.results(data)
        names = [r["name"] for r in result]
        assert "DISP" in names
        assert "STRESS" in names


class TestStatus:
    def test_completed(self, dat_file):
        data = parse_dat(dat_file)
        result = status.status(data)
        assert result["status"] == "completed"
