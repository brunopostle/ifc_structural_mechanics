"""Tests for the physical groups of members that overlap.

Where members share Gmsh entities after fragment(),
_create_physical_groups() names the group "A||B" (checked with Gmsh itself in
tests/integration/test_physical_group_mapping.py).
_map_elements_via_physical_groups() must then assign those elements to
ALL members named in the pipe-separated string.
"""

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

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

from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
from ifc_structural_mechanics.meshing.mesh_mapper import MeshMapper  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import MeshingError  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAT = Material(
    id="m", name="Steel", elastic_modulus=210e9, poisson_ratio=0.3, density=7850
)
_SEC = Section.create_rectangular_section(id="s", name="R", width=0.1, height=0.1)


def _member(member_id, start=(0, 0, 0), end=(1, 0, 0)):
    return CurveMember(
        id=member_id,
        geometry=[list(start), list(end)],
        material=_MAT,
        section=_SEC,
    )


_NODES = {
    1: np.array([0.0, 0.0, 0.0]),
    2: np.array([0.5, 0.0, 0.0]),
    3: np.array([1.0, 0.0, 0.0]),
}
_ELEMENTS = {
    10: {"type": "B31", "nodes": [1, 2]},
    11: {"type": "B31", "nodes": [2, 3]},
}


def _make_mapper(
    members,
    element_physical_group=None,
    physical_group_names=None,
    nodes=None,
    elements=None,
):
    """Build a MeshMapper with the given members and optional mesh state."""
    model = StructuralModel(id="t")
    for m in members:
        model.add_member(m)
    model.register_analysis_elements = MagicMock()

    # Short-id helper reused from UnifiedCalculixWriter for consistent MEMBER_Mx names
    short_id_map = {}
    counter = [0]

    def get_short_id(member_id):
        if member_id not in short_id_map:
            counter[0] += 1
            short_id_map[member_id] = f"M{counter[0]}"
        return short_id_map[member_id]

    return MeshMapper(
        elements=elements if elements is not None else dict(_ELEMENTS),
        nodes=nodes if nodes is not None else dict(_NODES),
        domain_model=model,
        element_physical_group=element_physical_group or {},
        physical_group_names=physical_group_names or {},
        get_short_id=get_short_id,
    )


# ---------------------------------------------------------------------------
# _map_elements_via_physical_groups with pipe-separated group names
# ---------------------------------------------------------------------------


class TestPipeSeparatedPhysicalGroups:
    """Physical group name 'A||B' → elements assigned to BOTH A and B."""

    def test_both_members_get_elements_from_combined_group(self):
        ma = _member("ma")
        mb = _member("mb")
        mapper = _make_mapper(
            [ma, mb],
            element_physical_group={10: 1, 11: 1},
            physical_group_names={1: "ma||mb"},
        )
        mapper._map_via_physical_groups()

        ma_set = mapper.element_sets.get("MEMBER_M1", [])
        mb_set = mapper.element_sets.get("MEMBER_M2", [])
        assert sorted(ma_set) == [10, 11], f"Expected [10,11] for ma, got {ma_set}"
        assert sorted(mb_set) == [10, 11], f"Expected [10,11] for mb, got {mb_set}"

    def test_non_overlap_member_keeps_own_elements(self):
        """Normal (non-overlapping) group name still works."""
        ma = _member("ma")
        mb = _member("mb")
        mapper = _make_mapper(
            [ma, mb],
            element_physical_group={10: 1, 11: 2},
            physical_group_names={1: "ma", 2: "mb"},
        )
        mapper._map_via_physical_groups()

        assert mapper.element_sets.get("MEMBER_M1") == [10]
        assert mapper.element_sets.get("MEMBER_M2") == [11]

    def test_three_way_overlap(self):
        """Three members with identical geometry share all elements."""
        ma = _member("ma")
        mb = _member("mb")
        mc = _member("mc", end=(2, 0, 0))
        extra_nodes = {**_NODES, 4: np.array([2.0, 0.0, 0.0])}
        extra_elems = {**_ELEMENTS, 12: {"type": "B31", "nodes": [3, 4]}}
        mapper = _make_mapper(
            [ma, mb, mc],
            element_physical_group={10: 1, 11: 1, 12: 2},
            physical_group_names={1: "ma||mb", 2: "mc"},
            nodes=extra_nodes,
            elements=extra_elems,
        )
        mapper._map_via_physical_groups()

        for mid in ("MEMBER_M1", "MEMBER_M2"):
            elems = mapper.element_sets.get(mid, [])
            assert sorted(elems) == [10, 11], f"{mid}: {elems}"
        assert mapper.element_sets.get("MEMBER_M3") == [12]

    def test_member_with_no_elements_stops_the_analysis(self):
        """A member the mesh has nothing for is not given what lies near it."""
        ma, mb = _member("ma"), _member("mb", start=(0, 1, 0), end=(1, 1, 0))
        mapper = _make_mapper(
            [ma, mb],
            element_physical_group={10: 1, 11: 1},
            physical_group_names={1: "ma"},
        )
        with pytest.raises(MeshingError, match="mb"):
            mapper._map_via_physical_groups()
