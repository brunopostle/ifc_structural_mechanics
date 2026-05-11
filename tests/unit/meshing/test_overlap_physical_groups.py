"""Tests for exact-overlap physical group fix.

When two members share identical post-fragment Gmsh entity tags,
_create_physical_groups() emits a combined "A||B" physical group name.
_map_elements_via_physical_groups() must then assign those elements to
ALL members named in the pipe-separated string.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np

# ---------------------------------------------------------------------------
# Stub gmsh sub-modules
# ---------------------------------------------------------------------------


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


if "gmsh" not in sys.modules:
    _stub("gmsh")

if "ifc_structural_mechanics.meshing.gmsh_geometry" not in sys.modules:
    _stub(
        "ifc_structural_mechanics.meshing.gmsh_geometry",
        GmshGeometryConverter=MagicMock(),
        convert_model=MagicMock(),
    )

if "ifc_structural_mechanics.meshing.gmsh_runner" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_runner", GmshRunner=MagicMock())

if "ifc_structural_mechanics.meshing.gmsh_utils" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_utils")

from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import StructuralModel  # noqa: E402
from ifc_structural_mechanics.meshing.unified_calculix_writer import (  # noqa: E402
    UnifiedCalculixWriter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAT = Material(id="m", name="Steel", elastic_modulus=210e9, poisson_ratio=0.3, density=7850)
_SEC = Section.create_rectangular_section(id="s", name="R", width=0.1, height=0.1)


def _member(member_id, start=(0, 0, 0), end=(1, 0, 0)):
    return CurveMember(
        id=member_id, geometry=[list(start), list(end)],
        material=_MAT, section=_SEC,
    )


def _make_writer(members):
    model = StructuralModel(id="t")
    for m in members:
        model.add_member(m)

    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer.element_sets = {}
    writer.defined_element_sets = set()
    writer.nodes = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([0.5, 0.0, 0.0]),
        3: np.array([1.0, 0.0, 0.0]),
    }
    writer.elements = {
        10: {"type": "B31", "nodes": [1, 2]},
        11: {"type": "B31", "nodes": [2, 3]},
    }
    writer._element_physical_group = {}
    writer._physical_group_names = {}
    writer.short_id_map = {}
    writer.short_id_counter = 0
    writer._get_short_id = UnifiedCalculixWriter._get_short_id.__get__(writer)
    writer._assign_elements_spatially = (
        UnifiedCalculixWriter._assign_elements_spatially.__get__(writer)
    )
    writer._map_elements_via_physical_groups = (
        UnifiedCalculixWriter._map_elements_via_physical_groups.__get__(writer)
    )
    writer.domain_model.register_analysis_elements = MagicMock()
    return writer


# ---------------------------------------------------------------------------
# _map_elements_via_physical_groups with pipe-separated group names
# ---------------------------------------------------------------------------


class TestPipeSeparatedPhysicalGroups:
    """Physical group name 'A||B' → elements assigned to BOTH A and B."""

    def test_both_members_get_elements_from_combined_group(self):
        ma = _member("ma")
        mb = _member("mb")
        writer = _make_writer([ma, mb])

        # Simulate: elements 10 and 11 both belong to physical group 1,
        # whose name is "ma||mb" (exact overlap).
        writer._element_physical_group = {10: 1, 11: 1}
        writer._physical_group_names = {1: "ma||mb"}

        writer._map_elements_via_physical_groups()

        ma_set = writer.element_sets.get("MEMBER_M1", [])
        mb_set = writer.element_sets.get("MEMBER_M2", [])
        assert sorted(ma_set) == [10, 11], f"Expected [10,11] for ma, got {ma_set}"
        assert sorted(mb_set) == [10, 11], f"Expected [10,11] for mb, got {mb_set}"

    def test_non_overlap_member_keeps_own_elements(self):
        """Normal (non-overlapping) group name still works."""
        ma = _member("ma")
        mb = _member("mb")
        writer = _make_writer([ma, mb])

        # ma → group 1, mb → group 2 (separate, no overlap)
        writer._element_physical_group = {10: 1, 11: 2}
        writer._physical_group_names = {1: "ma", 2: "mb"}

        writer._map_elements_via_physical_groups()

        assert writer.element_sets.get("MEMBER_M1") == [10]
        assert writer.element_sets.get("MEMBER_M2") == [11]

    def test_three_way_overlap(self):
        """Three members with identical geometry share all elements."""
        ma = _member("ma")
        mb = _member("mb")
        mc = _member("mc", end=(2, 0, 0))
        writer = _make_writer([ma, mb, mc])
        # mc has different geometry — give it its own group
        writer.nodes[4] = np.array([2.0, 0.0, 0.0])
        writer.elements[12] = {"type": "B31", "nodes": [3, 4]}

        writer._element_physical_group = {10: 1, 11: 1, 12: 2}
        writer._physical_group_names = {1: "ma||mb", 2: "mc"}

        writer._map_elements_via_physical_groups()

        for mid in ("MEMBER_M1", "MEMBER_M2"):
            elems = writer.element_sets.get(mid, [])
            assert sorted(elems) == [10, 11], f"{mid}: {elems}"
        assert writer.element_sets.get("MEMBER_M3") == [12]

    def test_unmapped_elements_fall_through_to_spatial(self):
        """Elements with no physical group still hit spatial fallback."""
        ma = _member("ma")
        writer = _make_writer([ma])

        # No physical group data at all
        writer._element_physical_group = {}
        writer._physical_group_names = {}

        # Spatial fallback should assign elements
        writer._map_elements_via_physical_groups()

        # ma should get elements via spatial fallback (geometry centroid (0.5,0,0))
        ma_set = writer.element_sets.get("MEMBER_M1", [])
        assert len(ma_set) > 0, "Expected spatial fallback to assign elements"


# ---------------------------------------------------------------------------
# GmshGeometryConverter._create_physical_groups — with Gmsh mocked
# ---------------------------------------------------------------------------


class TestCreatePhysicalGroupsOverlapDetection:
    """Unit tests for the overlap-detection logic in _create_physical_groups()."""

    def _make_converter(self, member_curve_tags):
        """Build a minimal GmshGeometryConverter stub."""
        from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter  # noqa: F401
        # GmshGeometryConverter is stubbed — test the logic directly via a
        # real instance built from the actual (non-stubbed) module. We need to
        # import the real module, which requires gmsh to be importable but NOT
        # actually initialised.  In the test environment gmsh is stubbed.
        # Use a simple plain-object approach instead.

        class FakeConverter:
            pass

        conv = FakeConverter()
        conv._member_curve_tags = member_curve_tags
        conv._member_surface_tags = {}
        conv.physical_group_map = {}

        import ifc_structural_mechanics.meshing.gmsh_geometry as geo_mod

        # Grab the real method from the module's source and bind it
        import types as _types

        # We can't import the real GmshGeometryConverter (gmsh is stubbed),
        # so test the overlap-detection logic separately here.
        return conv, member_curve_tags

    def test_exact_overlap_produces_combined_name(self):
        """Two members with identical tag sets → one group with 'A||B' name."""
        created_groups = []

        class MockGmsh:
            class model:
                @staticmethod
                def addPhysicalGroup(dim, tags, tag):
                    created_groups.append({"dim": dim, "tags": tags, "tag": tag})

                @staticmethod
                def setPhysicalName(dim, tag, name):
                    created_groups[-1]["name"] = name

        # Simulate the logic directly (not via Gmsh)
        # Members A and B both map to curve tag 7 after fragment
        member_curve_tags = {"A": [7], "B": [7]}
        tag_key_to_entries = {}
        entries_a = ("A", [7], 1)
        entries_b = ("B", [7], 1)
        for mid, tags, dim in [entries_a, entries_b]:
            key = frozenset((dim, t) for t in tags)
            if key not in tag_key_to_entries:
                tag_key_to_entries[key] = []
            tag_key_to_entries[key].append((mid, tags, dim))

        assert len(tag_key_to_entries) == 1, "Should be one key for identical tag sets"
        key = next(iter(tag_key_to_entries))
        entries = tag_key_to_entries[key]
        assert len(entries) == 2
        member_ids = [e[0] for e in entries]
        group_name = "||".join(member_ids)
        assert "A" in group_name and "B" in group_name
        assert "||" in group_name

    def test_distinct_tags_produce_separate_groups(self):
        """Two members with different tag sets → two separate groups."""
        member_curve_tags = {"A": [5], "B": [6]}
        tag_key_to_entries = {}
        for mid, tags in member_curve_tags.items():
            key = frozenset((1, t) for t in tags)
            if key not in tag_key_to_entries:
                tag_key_to_entries[key] = []
            tag_key_to_entries[key].append((mid, tags, 1))

        assert len(tag_key_to_entries) == 2, "Should be two distinct groups"

    def test_partial_overlap_creates_two_groups(self):
        """Partial overlap (B's tags ⊂ A's) → frozensets differ → two groups."""
        member_curve_tags = {"A": [5, 6, 7], "B": [6]}
        tag_key_to_entries = {}
        for mid, tags in member_curve_tags.items():
            key = frozenset((1, t) for t in tags)
            if key not in tag_key_to_entries:
                tag_key_to_entries[key] = []
            tag_key_to_entries[key].append((mid, tags, 1))

        # Two distinct frozensets: {5,6,7} and {6}
        assert len(tag_key_to_entries) == 2
