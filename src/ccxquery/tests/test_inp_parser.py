"""Tests for the .inp file parser."""

import pytest
from ccxquery.parsers.inp_parser import (
    parse_inp,
    get_sections_by_keyword,
    parse_nodes,
    parse_elements,
    parse_node_sets,
    parse_element_sets,
    parse_materials,
    parse_boundary_conditions,
    parse_cloads,
    parse_dloads,
    parse_steps,
    parse_sections,
)


class TestParseInp:
    def test_parses_keyword_sections(self, inp_file):
        sections = parse_inp(inp_file)
        assert len(sections) > 0
        keywords = [s["keyword"] for s in sections]
        assert "NODE" in keywords
        assert "ELEMENT" in keywords
        assert "MATERIAL" in keywords

    def test_skips_comments(self, inp_file):
        sections = parse_inp(inp_file)
        keywords = [s["keyword"] for s in sections]
        # ** lines should not appear as keywords
        for kw in keywords:
            assert not kw.startswith("*")

    def test_keyword_params(self, inp_file):
        sections = parse_inp(inp_file)
        elem_sections = get_sections_by_keyword(sections, "ELEMENT")
        assert len(elem_sections) == 1
        assert elem_sections[0]["params"]["TYPE"] == "B31"
        assert elem_sections[0]["params"]["ELSET"] == "ELSET_B31"

    def test_section_has_line_number(self, inp_file):
        sections = parse_inp(inp_file)
        for s in sections:
            assert "line" in s
            assert isinstance(s["line"], int)
            assert s["line"] >= 1

    def test_data_lines_collected(self, inp_file):
        sections = parse_inp(inp_file)
        node_section = get_sections_by_keyword(sections, "NODE")[0]
        assert len(node_section["data"]) == 5


class TestParseNodes:
    def test_parses_all_nodes(self, inp_file):
        sections = parse_inp(inp_file)
        nodes = parse_nodes(sections)
        assert len(nodes) == 5
        assert 1 in nodes
        assert 5 in nodes

    def test_node_coordinates(self, inp_file):
        sections = parse_inp(inp_file)
        nodes = parse_nodes(sections)
        assert nodes[1] == (0.0, 0.0, 0.0)
        assert nodes[5] == (4.0, 0.0, 0.0)
        assert nodes[3] == (2.0, 0.0, 0.0)


class TestParseElements:
    def test_parses_all_elements(self, inp_file):
        sections = parse_inp(inp_file)
        elements = parse_elements(sections)
        assert len(elements) == 4

    def test_element_fields(self, inp_file):
        sections = parse_inp(inp_file)
        elements = parse_elements(sections)
        e1 = elements[0]
        assert e1["id"] == 1
        assert e1["type"] == "B31"
        assert e1["elset"] == "ELSET_B31"
        assert e1["connectivity"] == [1, 2]

    def test_element_connectivity(self, inp_file):
        sections = parse_inp(inp_file)
        elements = parse_elements(sections)
        e4 = elements[3]
        assert e4["id"] == 4
        assert e4["connectivity"] == [4, 5]


class TestParseNodeSets:
    def test_plain_nset(self, inp_file):
        sections = parse_inp(inp_file)
        nsets = parse_node_sets(sections)
        assert "FIX_LEFT" in nsets
        assert nsets["FIX_LEFT"] == [1]

    def test_generate_nset(self, inp_file):
        sections = parse_inp(inp_file)
        nsets = parse_node_sets(sections)
        assert "FIX_RIGHT" in nsets
        assert nsets["FIX_RIGHT"] == [4, 5]


class TestParseElementSets:
    def test_plain_elset(self, inp_file):
        sections = parse_inp(inp_file)
        elsets = parse_element_sets(sections)
        assert "ALL_ELEMENTS" in elsets
        assert elsets["ALL_ELEMENTS"] == [1, 2, 3, 4]

    def test_generate_elset(self, inp_file):
        sections = parse_inp(inp_file)
        elsets = parse_element_sets(sections)
        assert "ALL_ELEMENTS" in elsets
        assert len(elsets["ALL_ELEMENTS"]) == 4


class TestParseMaterials:
    def test_material_name(self, inp_file):
        sections = parse_inp(inp_file)
        mats = parse_materials(sections)
        assert len(mats) == 1
        assert mats[0]["name"] == "STEEL"

    def test_elastic_properties(self, inp_file):
        sections = parse_inp(inp_file)
        mats = parse_materials(sections)
        elastic = mats[0]["properties"]["elastic"]
        assert elastic["youngs_modulus"] == 2.1e+11
        assert elastic["poissons_ratio"] == 0.3

    def test_density(self, inp_file):
        sections = parse_inp(inp_file)
        mats = parse_materials(sections)
        assert mats[0]["properties"]["density"] == 7850.0


class TestParseBoundaryConditions:
    def test_parses_bcs(self, inp_file):
        sections = parse_inp(inp_file)
        bcs = parse_boundary_conditions(sections)
        assert len(bcs) == 2

    def test_bc_fields(self, inp_file):
        sections = parse_inp(inp_file)
        bcs = parse_boundary_conditions(sections)
        bc_left = bcs[0]
        assert bc_left["target"] == "FIX_LEFT"
        assert bc_left["first_dof"] == 1
        assert bc_left["last_dof"] == 6


class TestParseCloads:
    def test_parses_cloads(self, inp_file):
        sections = parse_inp(inp_file)
        cloads = parse_cloads(sections)
        assert len(cloads) == 1
        assert cloads[0]["node"] == "5"
        assert cloads[0]["dof"] == 2
        assert cloads[0]["magnitude"] == -10000.0


class TestParseDloads:
    def test_parses_dloads(self, inp_file):
        sections = parse_inp(inp_file)
        dloads = parse_dloads(sections)
        assert len(dloads) == 1
        assert dloads[0]["element"] == "1"
        assert dloads[0]["type"] == "P1"
        assert dloads[0]["magnitude"] == 500.0


class TestParseSteps:
    def test_parses_steps(self, inp_file):
        sections = parse_inp(inp_file)
        steps = parse_steps(sections)
        assert len(steps) == 1

    def test_step_keywords(self, inp_file):
        sections = parse_inp(inp_file)
        steps = parse_steps(sections)
        kws = steps[0]["keywords"]
        assert "STATIC" in kws
        assert "CLOAD" in kws
        assert "NODE FILE" in kws


class TestParseSections:
    def test_beam_section(self, inp_file):
        sections = parse_inp(inp_file)
        secs = parse_sections(sections)
        assert len(secs) == 1
        assert secs[0]["type"] == "beam_section"
        assert secs[0]["params"]["MATERIAL"] == "STEEL"
        assert secs[0]["params"]["SECTION"] == "RECT"
