"""Tests for intermediate support point seeding in GmshGeometryConverter.

When a support connection is at a position strictly inside a curve member
(not at an endpoint), _seed_support_points() must detect this and add a
Gmsh point there so fragment() can split the curve, guaranteeing a mesh node.

We test the geometry helper (_point_on_segment) and the seeding logic without
a real Gmsh installation by mocking the Gmsh API.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub gmsh and force-load the REAL gmsh_geometry module.
#
# Other test files (e.g. test_hinge_from_releases.py) stub out the
# ifc_structural_mechanics.meshing.gmsh_geometry module as a MagicMock so
# that unified_calculix_writer can be imported without a live Gmsh binary.
# That stub is cached in sys.modules.  We must remove it before importing the
# real module here, otherwise GmshGeometryConverter would be a MagicMock and
# all calls would silently return truthy values rather than real results.
# ---------------------------------------------------------------------------


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Ensure gmsh itself is a stub (MagicMock-based) so OCC API calls don't fail.
if "gmsh" not in sys.modules:
    _stub("gmsh")
# Add the sub-objects the real gmsh_geometry module calls.
import gmsh as _gmsh_mod  # noqa: E402  (already in sys.modules after stub)

if not hasattr(_gmsh_mod, "model"):
    _gmsh_mod.model = MagicMock()
if not hasattr(_gmsh_mod.model, "occ"):
    _gmsh_mod.model.occ = MagicMock()

# Runner / utils stubs (only if not already present)
if "ifc_structural_mechanics.meshing.gmsh_runner" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_runner", GmshRunner=MagicMock())
if "ifc_structural_mechanics.meshing.gmsh_utils" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_utils")

# Force the REAL gmsh_geometry module to be loaded (remove any earlier stub).
sys.modules.pop("ifc_structural_mechanics.meshing.gmsh_geometry", None)

from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_connection import (  # noqa: E402
    PointConnection,
)
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
from ifc_structural_mechanics.meshing.gmsh_geometry import (  # noqa: E402
    GmshGeometryConverter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_point_on_segment = GmshGeometryConverter._point_on_segment

_MAT = Material(
    id="m", name="S", elastic_modulus=210e9, poisson_ratio=0.3, density=7850
)
_SEC = Section.create_rectangular_section(id="s", name="R", width=0.1, height=0.1)


def _member(mid, start, end):
    return CurveMember(
        id=mid, geometry=[list(start), list(end)], material=_MAT, section=_SEC
    )


# ---------------------------------------------------------------------------
# _point_on_segment — geometry helper
# ---------------------------------------------------------------------------


class TestPointOnSegment:
    def _p(self, coords):
        return np.array(coords, dtype=float)

    def test_midpoint_is_on_segment(self):
        assert _point_on_segment(
            self._p([0.5, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_point_at_start_is_not_strictly_inside(self):
        assert not _point_on_segment(
            self._p([0, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_point_at_end_is_not_strictly_inside(self):
        assert not _point_on_segment(
            self._p([1, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_point_off_line_returns_false(self):
        assert not _point_on_segment(
            self._p([0.5, 0.5, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_point_beyond_end_returns_false(self):
        assert not _point_on_segment(
            self._p([1.5, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_point_before_start_returns_false(self):
        assert not _point_on_segment(
            self._p([-0.1, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_3d_segment_midpoint(self):
        a = self._p([1, 1, 0])
        b = self._p([3, 3, 0])
        mid = (a + b) / 2
        assert _point_on_segment(mid, a, b)

    def test_3d_segment_off_axis(self):
        a = self._p([0, 0, 0])
        b = self._p([1, 1, 1])
        mid = np.array([0.5, 0.5, 0.5])
        assert _point_on_segment(mid, a, b)

    def test_point_very_close_to_endpoint_not_inside(self):
        # 0.1 mm from start — within tol/ab_len boundary, so not strictly inside
        assert not _point_on_segment(
            self._p([1e-5, 0, 0]), self._p([0, 0, 0]), self._p([1, 0, 0])
        )

    def test_zero_length_segment_returns_false(self):
        assert not _point_on_segment(
            self._p([0.5, 0, 0]), self._p([0, 0, 0]), self._p([0, 0, 0])
        )


# ---------------------------------------------------------------------------
# _seed_support_points — integration with domain model
# ---------------------------------------------------------------------------


class TestSeedSupportPoints:
    """Tests _seed_support_points() using a mocked Gmsh addPoint."""

    @pytest.fixture(autouse=True)
    def mock_gmsh_model(self):
        # When real gmsh is in sys.modules (loaded by test_gmsh_utils.py earlier),
        # the conditional stub at module level doesn't replace model/occ.  Patch
        # model for the duration of these tests so OCC calls don't fail.
        with patch.object(_gmsh_mod, "model", MagicMock()):
            yield

    def _make_converter(self):
        conv = GmshGeometryConverter.__new__(GmshGeometryConverter)
        conv._curve_point_registry = {}
        conv._surface_point_registry = {}
        conv._member_point_tags = {}
        conv._member_curve_tags = {}
        conv._member_surface_tags = {}
        conv._member_mesh_sizes = {}
        conv._all_curve_dim_tags = []
        conv._all_surface_dim_tags = []
        conv._fragment_map = None
        return conv

    def _add_point_return(self, counter=None):
        """Return a side_effect that yields sequential integers."""
        c = [100]

        def side_effect(x, y, z):
            val = c[0]
            c[0] += 1
            return val

        return side_effect

    def _pinned_conn(self, conn_id, position, member_id="m1"):
        """A point connection with a rigid stiffness (acts as a support)."""
        from ifc_structural_mechanics.domain.structural_connection import (
            PointConnection,
        )

        conn = PointConnection(conn_id, list(position))
        # Add enough members to pass validation
        conn.connect_member(member_id)
        conn.connect_member(f"dummy_member_1_{conn_id}")
        # Set translational stiffness (True = fixed) so get_constrained_dofs returns DOFs

        conn.set_stiffness_properties({"dx": 1e20, "dy": 1e20, "dz": 1e20})
        return conn

    def test_intermediate_support_is_seeded(self):
        """Support at midpoint of beam → point seeded, tag returned."""
        conv = self._make_converter()

        model = StructuralModel(id="t")
        model.add_member(_member("m1", [0, 0, 0], [6, 0, 0]))
        conn = self._pinned_conn("c1", [3, 0, 0])  # midpoint
        model.connections.append(conn)

        # gmsh.model.occ.addPoint is a MagicMock — it returns a MagicMock
        # but that's fine; we only care that ONE tag is appended.
        tags = conv._seed_support_points(model)

        assert len(tags) == 1

    def test_endpoint_support_is_not_seeded(self):
        """Support at exact member endpoint → already in registry, not re-seeded."""
        conv = self._make_converter()
        # Pre-register the endpoint (as if member geometry was already created)
        from ifc_structural_mechanics.meshing.gmsh_geometry import COORD_PRECISION

        key = (
            round(0.0, COORD_PRECISION),
            round(0.0, COORD_PRECISION),
            round(0.0, COORD_PRECISION),
        )
        conv._curve_point_registry[key] = 5  # already registered

        model = StructuralModel(id="t")
        model.add_member(_member("m1", [0, 0, 0], [6, 0, 0]))
        conn = self._pinned_conn("c1", [0, 0, 0])  # AT endpoint
        model.connections.append(conn)

        tags = conv._seed_support_points(model)
        assert tags == []

    def test_no_constrained_dofs_not_seeded(self):
        """Connection without constrained DOFs (pure geometric) → not seeded."""
        conv = self._make_converter()
        model = StructuralModel(id="t")
        model.add_member(_member("m1", [0, 0, 0], [6, 0, 0]))

        # Connection with no stiffness → get_constrained_dofs returns []
        conn = PointConnection("c1", [3, 0, 0])
        conn.connect_member("m1")
        conn.connect_member("dummy_member_1_c1")
        model.connections.append(conn)

        tags = conv._seed_support_points(model)
        assert tags == []

    def test_support_off_beam_not_seeded(self):
        """Support position not on any member curve → nothing seeded."""
        conv = self._make_converter()
        model = StructuralModel(id="t")
        model.add_member(_member("m1", [0, 0, 0], [6, 0, 0]))
        conn = self._pinned_conn("c1", [3, 1, 0])  # 1 m off the beam
        model.connections.append(conn)

        tags = conv._seed_support_points(model)
        assert tags == []

    def test_two_separate_intermediate_supports_both_seeded(self):
        """Two independent intermediate supports → two points seeded."""
        conv = self._make_converter()
        model = StructuralModel(id="t")
        model.add_member(_member("m1", [0, 0, 0], [10, 0, 0]))
        model.connections.append(self._pinned_conn("c1", [2, 0, 0]))
        model.connections.append(self._pinned_conn("c2", [7, 0, 0]))

        counter = [100]

        def mock_add_point(x, y, z):
            val = counter[0]
            counter[0] += 1
            return val

        with patch("gmsh.model.occ.addPoint", side_effect=mock_add_point):
            tags = conv._seed_support_points(model)

        assert len(tags) == 2
        assert len(set(tags)) == 2  # distinct tags
