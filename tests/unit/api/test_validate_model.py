"""Unit tests for the _validate_model() pre-analysis validation helper.

Imported in a standalone file because the api module has a module-level
dependency on gmsh (via the meshing package), which requires libGLU.so.1.
We mock out the affected modules in sys.modules before importing.
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out modules that import gmsh so the api module can be loaded without
# a full Gmsh installation (libGLU.so.1 is not available in the test env).
# ---------------------------------------------------------------------------


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Stub gmsh (needs libGLU.so.1 which is absent) and the sub-modules that
# import it.  Do NOT stub the meshing package or unified_calculix_writer
# because those load fine without a live gmsh binary.
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

# ---------------------------------------------------------------------------
# Now it is safe to import the real module under test
# ---------------------------------------------------------------------------

from ifc_structural_mechanics.api.structural_analysis import (  # noqa: E402
    _validate_model,
)
from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_member(id, *, material=None, section=None):
    m = MagicMock()
    m.id = id
    m.material = material
    m.section = section
    return m


def _make_group_with_loads(*load_ids):
    g = MagicMock()
    g.loads = [MagicMock(id=lid) for lid in load_ids]
    return g


def _empty_model():
    return StructuralModel(id="v_model", name="Validation Model")


_MATERIAL = Material(
    id="m1", name="Steel", elastic_modulus=210e9, poisson_ratio=0.3, density=7850
)
_SECTION = Section.create_rectangular_section(id="s1", name="R", width=0.1, height=0.1)


# ---------------------------------------------------------------------------
# Missing material
# ---------------------------------------------------------------------------


class TestValidateModelMaterial:
    def test_warns_members_missing_material(self):
        model = _empty_model()
        model.add_member(_make_member("beam_no_mat", material=None, section=_SECTION))
        model.add_member(_make_member("beam_ok", material=_MATERIAL, section=_SECTION))
        warnings = _validate_model(model, gravity=True)
        messages = [w["message"] for w in warnings]
        assert any("no material" in m for m in messages)
        assert any("beam_no_mat" in m for m in messages)

    def test_no_warning_all_members_have_material(self):
        model = _empty_model()
        model.add_member(_make_member("ok", material=_MATERIAL, section=_SECTION))
        warnings = _validate_model(model, gravity=True)
        assert not any("no material" in w["message"] for w in warnings)

    def test_truncates_long_list_at_five(self):
        model = _empty_model()
        for i in range(7):
            model.add_member(_make_member(f"b{i}", material=None, section=_SECTION))
        warnings = _validate_model(model, gravity=True)
        mat_w = [w for w in warnings if "no material" in w["message"]]
        assert mat_w
        assert "and 2 more" in mat_w[0]["message"]


# ---------------------------------------------------------------------------
# Missing section
# ---------------------------------------------------------------------------


class TestValidateModelSection:
    def test_warns_members_missing_section(self):
        model = _empty_model()
        model.add_member(_make_member("beam_no_sec", material=_MATERIAL, section=None))
        warnings = _validate_model(model, gravity=True)
        messages = [w["message"] for w in warnings]
        assert any("no section" in m for m in messages)
        assert any("beam_no_sec" in m for m in messages)

    def test_no_warning_all_members_have_section(self):
        model = _empty_model()
        model.add_member(_make_member("ok", material=_MATERIAL, section=_SECTION))
        warnings = _validate_model(model, gravity=True)
        assert not any("no section" in w["message"] for w in warnings)


# ---------------------------------------------------------------------------
# No connections
# ---------------------------------------------------------------------------


class TestValidateModelConnections:
    def test_warns_no_connections(self):
        model = _empty_model()
        warnings = _validate_model(model, gravity=True)
        messages = [w["message"] for w in warnings]
        assert any("singular" in m or "no supports" in m for m in messages)

    def test_no_warning_when_connection_exists(self):
        model = _empty_model()
        model.connections.append(MagicMock())
        warnings = _validate_model(model, gravity=True)
        assert not any("singular" in w["message"] for w in warnings)


# ---------------------------------------------------------------------------
# No loads / no gravity
# ---------------------------------------------------------------------------


class TestValidateModelLoads:
    def test_warns_no_loads_and_no_gravity(self):
        model = _empty_model()
        model.load_groups = []
        warnings = _validate_model(model, gravity=False)
        messages = [w["message"] for w in warnings]
        assert any("zero applied loads" in m or "--gravity" in m for m in messages)

    def test_no_warning_when_gravity_requested(self):
        model = _empty_model()
        model.load_groups = []
        warnings = _validate_model(model, gravity=True)
        assert not any("--gravity" in w["message"] for w in warnings)

    def test_no_warning_when_explicit_loads_present(self):
        model = _empty_model()
        model.load_groups = [_make_group_with_loads("load_1")]
        warnings = _validate_model(model, gravity=False)
        assert not any("zero applied loads" in w["message"] for w in warnings)


# ---------------------------------------------------------------------------
# Warning dict format
# ---------------------------------------------------------------------------


class TestValidateModelWarningFormat:
    def test_warning_dicts_have_required_keys(self):
        model = _empty_model()
        warnings = _validate_model(model, gravity=False)
        for w in warnings:
            assert "message" in w
            assert "severity" in w
            assert w["severity"] == "warning"
