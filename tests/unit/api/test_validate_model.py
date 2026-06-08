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


# ---------------------------------------------------------------------------
# Section approximation warnings
# ---------------------------------------------------------------------------


def _section_with_approx(*msgs):
    """Return a Section whose approximations list contains the given messages."""
    sec = Section.create_rectangular_section(
        id="sx", name="approx", width=0.1, height=0.1
    )
    sec.approximations = list(msgs)
    return sec


class TestValidateModelSectionApproximations:
    def test_asymmetric_i_warning_reaches_result(self):
        model = _empty_model()
        member = _make_member(
            "beam_asym",
            material=_MATERIAL,
            section=_section_with_approx(
                "Asymmetric I-section (IfcAsymmetricIShapeProfileDef) approximated as "
                "symmetric: top and bottom flanges averaged"
            ),
        )
        member.ifc_guid = "3AbCdEfGhI"
        model.add_member(member)
        model.connections.append(MagicMock())
        model.load_groups = [_make_group_with_loads("L1")]
        warnings = _validate_model(model, gravity=True)
        approx_warns = [w for w in warnings if "beam_asym" in w["message"]]
        assert approx_warns, "expected a warning naming the member"
        assert any("3AbCdEfGhI" in w["message"] for w in approx_warns)
        assert any("asymmetric" in w["message"].lower() for w in approx_warns)
        assert approx_warns[0]["domain_id"] == "beam_asym"
        assert approx_warns[0]["ifc_guid"] == "3AbCdEfGhI"

    def test_l_section_warning_reaches_result(self):
        model = _empty_model()
        member = _make_member(
            "col_l",
            material=_MATERIAL,
            section=_section_with_approx(
                "L-section (angle) analysed with zero product of inertia"
            ),
        )
        member.ifc_guid = "LGuid123"
        model.add_member(member)
        model.connections.append(MagicMock())
        model.load_groups = [_make_group_with_loads("L1")]
        warnings = _validate_model(model, gravity=True)
        approx_warns = [w for w in warnings if "col_l" in w["message"]]
        assert approx_warns
        assert any("product of inertia" in w["message"].lower() for w in approx_warns)

    def test_unsupported_profile_warning_reaches_result(self):
        model = _empty_model()
        member = _make_member(
            "beam_unk",
            material=_MATERIAL,
            section=_section_with_approx(
                "Unsupported profile type 'IfcZShapeProfileDef' replaced with default section"
            ),
        )
        member.ifc_guid = None
        model.add_member(member)
        model.connections.append(MagicMock())
        model.load_groups = [_make_group_with_loads("L1")]
        warnings = _validate_model(model, gravity=True)
        approx_warns = [w for w in warnings if "beam_unk" in w["message"]]
        assert approx_warns

    def test_no_approximation_warning_for_clean_section(self):
        model = _empty_model()
        member = _make_member("ok_beam", material=_MATERIAL, section=_SECTION)
        member.ifc_guid = "CleanGuid"
        model.add_member(member)
        model.connections.append(MagicMock())
        model.load_groups = [_make_group_with_loads("L1")]
        warnings = _validate_model(model, gravity=True)
        approx_warns = [w for w in warnings if "ok_beam" in w["message"]]
        assert not approx_warns, "clean section must produce no approximation warning"
