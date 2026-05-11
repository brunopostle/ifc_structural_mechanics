"""Tests for _detect_mechanism_risk() in UnifiedCalculixWriter.

The heuristic warns when:
  (1) all supports fix only DOF 1-3 (no rotational restraint), AND
  (2) no moment-resisting member connections exist, AND
  (3) at least one lateral (non-gravity) load is present.
"""

import sys
import types
from unittest.mock import MagicMock

import numpy as np

# ---------------------------------------------------------------------------
# Stubs so unified_calculix_writer can be imported without Gmsh / libGLU
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

from ifc_structural_mechanics.domain.load import PointLoad, LoadGroup  # noqa: E402
from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_connection import PointConnection  # noqa: E402
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import StructuralModel  # noqa: E402
from ifc_structural_mechanics.meshing.unified_calculix_writer import UnifiedCalculixWriter  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAT = Material(id="m", name="S", elastic_modulus=210e9, poisson_ratio=0.3, density=7850)
_SEC = Section.create_rectangular_section(id="s", name="R", width=0.1, height=0.1)


def _member(mid, start=(0, 0, 0), end=(0, 0, 3)):
    return CurveMember(id=mid, geometry=[list(start), list(end)], material=_MAT, section=_SEC)


def _pinned_support(conn_id, position, member_id="col"):
    """Translational-only support (DOF 1-3), no rotational fixity."""
    conn = PointConnection(conn_id, list(position))
    conn.connect_member(member_id)
    conn.connect_member(f"dummy_member_{conn_id}")
    conn.set_stiffness_properties({"dx": 1e20, "dy": 1e20, "dz": 1e20})
    return conn


def _fixed_support(conn_id, position, member_id="col"):
    """Fully fixed support (DOF 1-6)."""
    conn = PointConnection(conn_id, list(position))
    conn.connect_member(member_id)
    conn.connect_member(f"dummy_member_{conn_id}")
    conn.set_stiffness_properties(
        {"dx": 1e20, "dy": 1e20, "dz": 1e20, "drx": 1e20, "dry": 1e20, "drz": 1e20}
    )
    return conn


def _lateral_load(load_id, position, fx=1000.0):
    """Horizontal point load in X direction."""
    return PointLoad(
        id=load_id, position=list(position), magnitude=fx, direction=[1.0, 0.0, 0.0]
    )


def _gravity_load(load_id, position, fz=-1000.0):
    """Vertical (gravity) point load in -Z direction."""
    return PointLoad(
        id=load_id, position=list(position), magnitude=abs(fz), direction=[0.0, 0.0, -1.0]
    )


def _make_writer(model):
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer._detect_mechanism_risk = UnifiedCalculixWriter._detect_mechanism_risk.__get__(writer)
    return writer


def _add_load_group(model, load):
    lg = LoadGroup(id=f"lg_{load.id}", name="LC1", is_load_case=True)
    lg.add_load(load)
    model.load_groups.append(lg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectMechanismRisk:
    """_detect_mechanism_risk() returns warnings only under the danger combination."""

    def test_pinned_bases_no_moment_connections_lateral_load_warns(self):
        """The classic portal-frame mechanism: pinned bases + hinge joints + lateral load."""
        model = StructuralModel(id="t")
        col = _member("col", (0, 0, 0), (0, 0, 3))
        model.add_member(col)
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))

        # Hinge connection between col and beam (no moment transfer)
        beam = _member("beam", (0, 0, 3), (5, 0, 3))
        model.add_member(beam)
        joint = PointConnection("j1", [0, 0, 3])
        joint.connect_member("col")
        joint.connect_member("beam")
        joint.entity_type = "hinge"
        model.connections.append(joint)

        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        warnings = writer._detect_mechanism_risk()
        assert len(warnings) == 1
        assert "mechanism" in warnings[0].lower() or "kinematic" in warnings[0].lower()

    def test_fixed_base_suppresses_warning(self):
        """A single fixed-base support (DOF 4-6) should suppress the warning."""
        model = StructuralModel(id="t")
        model.add_member(_member("col"))
        model.connections.append(_fixed_support("s1", (0, 0, 0), "col"))
        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        assert writer._detect_mechanism_risk() == []

    def test_moment_connection_suppresses_warning(self):
        """A rigid (point) connection that couples rotations suppresses the warning."""
        model = StructuralModel(id="t")
        col = _member("col", (0, 0, 0), (0, 0, 3))
        beam = _member("beam", (0, 0, 3), (5, 0, 3))
        model.add_member(col)
        model.add_member(beam)
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))

        # Rigid (point) connection — DOF 4-6 coupled → moment frame
        joint = PointConnection("j1", [0, 0, 3])
        joint.connect_member("col")
        joint.connect_member("beam")
        joint.entity_type = "point"  # rigid, no released DOFs
        model.connections.append(joint)

        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        assert writer._detect_mechanism_risk() == []

    def test_gravity_only_load_does_not_warn(self):
        """Pinned bases + no moment connections is fine under gravity-only load."""
        model = StructuralModel(id="t")
        model.add_member(_member("col"))
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))
        _add_load_group(model, _gravity_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        assert writer._detect_mechanism_risk() == []

    def test_no_loads_does_not_warn(self):
        """No loads at all → no warning (nothing to destabilise the structure)."""
        model = StructuralModel(id="t")
        model.add_member(_member("col"))
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))

        writer = _make_writer(model)
        assert writer._detect_mechanism_risk() == []

    def test_no_connections_no_warning(self):
        """Model with no connections → no supports → check terminates quietly."""
        model = StructuralModel(id="t")
        model.add_member(_member("col"))
        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        # No connections → no supports with rotational fixity detected, but also no
        # hinge connections, so step 2 finds no moment connections.  Step 3 finds a
        # lateral load → warning IS expected here (no restraint at all).
        warnings = writer._detect_mechanism_risk()
        assert len(warnings) == 1

    def test_partial_hinge_one_member_retains_rotation(self):
        """Connection releases DOF 4-6 for one member but not the other → moment-resisting."""
        model = StructuralModel(id="t")
        col = _member("col", (0, 0, 0), (0, 0, 3))
        beam = _member("beam", (0, 0, 3), (5, 0, 3))
        model.add_member(col)
        model.add_member(beam)
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))

        joint = PointConnection("j1", [0, 0, 3])
        joint.connect_member("col")
        joint.connect_member("beam")
        joint.entity_type = "point"
        # Only release rotation for beam (col retains its rotation → moment-resisting)
        joint.released_dofs_by_member = {"beam": [4, 5, 6]}
        model.connections.append(joint)

        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        assert writer._detect_mechanism_risk() == []

    def test_all_members_fully_released_is_hinge(self):
        """All members release DOF 4-6 → effectively a hinge → mechanism risk remains."""
        model = StructuralModel(id="t")
        col = _member("col", (0, 0, 0), (0, 0, 3))
        beam = _member("beam", (0, 0, 3), (5, 0, 3))
        model.add_member(col)
        model.add_member(beam)
        model.connections.append(_pinned_support("s1", (0, 0, 0), "col"))

        joint = PointConnection("j1", [0, 0, 3])
        joint.connect_member("col")
        joint.connect_member("beam")
        joint.entity_type = "point"
        joint.released_dofs_by_member = {"col": [4, 5, 6], "beam": [4, 5, 6]}
        model.connections.append(joint)

        _add_load_group(model, _lateral_load("L1", [0, 0, 3]))

        writer = _make_writer(model)
        warnings = writer._detect_mechanism_risk()
        assert len(warnings) == 1
