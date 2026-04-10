"""Tests for overlapping-member spatial fallback and section deduplication."""

import io
import logging
from unittest.mock import MagicMock

import numpy as np

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _make_curve_member(id_, start, end, mat=None, sec=None):
    if mat is None:
        mat = Material(
            id="mat1",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )
    if sec is None:
        sec = Section.create_rectangular_section(
            id="sec1", name="R", width=0.1, height=0.2
        )
    return CurveMember(id=id_, geometry=[start, end], material=mat, section=sec)


def _make_writer_with_two_members(member_a, member_b):
    """Build a writer stub with two members and no actual mesh."""
    model = StructuralModel(id="test")
    model.add_member(member_a)
    model.add_member(member_b)

    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer.element_sets = {}
    writer.defined_element_sets = set()
    writer.nodes = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([1.0, 0.0, 0.0]),
        3: np.array([0.5, 0.0, 0.0]),
    }
    writer.elements = {
        10: {"type": "B31", "nodes": [1, 2]},
        11: {"type": "B31", "nodes": [2, 3]},
    }
    writer._get_short_id = lambda mid: mid[:8].replace("-", "")
    writer._assign_elements_spatially = (
        UnifiedCalculixWriter._assign_elements_spatially.__get__(writer)
    )
    return writer


class TestSpatialFallback:
    """_assign_elements_spatially() with allow_sharing flag."""

    def test_no_sharing_leaves_empty_member(self):
        """Without sharing, a member whose elements are all assigned stays empty."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member(
            "member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]
        )  # overlapping
        writer = _make_writer_with_two_members(ma, mb)

        # Assign all elements to member_a first
        assigned = {10, 11}
        writer.element_sets["MEMBER_member_a"] = [10, 11]
        writer.defined_element_sets.add("MEMBER_member_a")
        writer.domain_model.register_analysis_elements = MagicMock()

        writer._assign_elements_spatially([mb], assigned, allow_sharing=False)

        assert "MEMBER_member_b" not in writer.element_sets

    def test_sharing_gives_overlapping_member_elements(self):
        """With sharing, an overlapping member gets the same elements."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member("member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        writer = _make_writer_with_two_members(ma, mb)

        assigned = {10, 11}
        writer.element_sets["MEMBER_member_a"] = [10, 11]
        writer.defined_element_sets.add("MEMBER_member_a")
        writer.domain_model.register_analysis_elements = MagicMock()

        writer._assign_elements_spatially([mb], assigned, allow_sharing=True)

        assert "MEMBER_member_b" in writer.element_sets
        assert len(writer.element_sets["MEMBER_member_b"]) > 0

    def test_sharing_logs_warning(self, caplog):
        """allow_sharing=True logs a warning about shared elements."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member("member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        writer = _make_writer_with_two_members(ma, mb)

        assigned = {10, 11}
        writer.element_sets["MEMBER_member_a"] = [10, 11]
        writer.defined_element_sets.add("MEMBER_member_a")
        writer.domain_model.register_analysis_elements = MagicMock()

        with caplog.at_level(logging.WARNING):
            writer._assign_elements_spatially([mb], assigned, allow_sharing=True)

        assert any("sharing" in r.message.lower() for r in caplog.records)


class TestSectionDeduplication:
    """_write_sections() deduplication guard for overlapping members."""

    def test_duplicate_section_skipped(self, caplog):
        """When two members share elements, only the first section is written."""
        model = StructuralModel(id="test")
        mat = Material(
            id="m1", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        )
        sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.1, height=0.2
        )
        ma = CurveMember(
            id="ma", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
        )
        mb = CurveMember(
            id="mb", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
        )
        model.add_member(ma)
        model.add_member(mb)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.element_sets = {
            "MEMBER_ma": [10, 11],
            "MEMBER_mb": [10, 11],  # same elements — overlap
        }
        writer.defined_element_sets = {"MEMBER_ma", "MEMBER_mb"}
        writer._get_short_id = lambda mid: mid
        writer._split_beam_sets_by_orientation = MagicMock(return_value={})
        writer._get_beam_normal = MagicMock(return_value=(0.0, 1.0, 0.0))
        writer._write_beam_section_for_set = MagicMock()
        writer._write_sections = UnifiedCalculixWriter._write_sections.__get__(writer)

        buf = io.StringIO()
        with caplog.at_level(logging.WARNING):
            writer._write_sections(buf)

        # Only one section should have been written (ma); mb is skipped
        assert writer._write_beam_section_for_set.call_count == 1
        assert any(
            "overlap" in r.message.lower() or "already" in r.message.lower()
            for r in caplog.records
        )
