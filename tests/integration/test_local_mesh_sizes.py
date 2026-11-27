"""A finer mesh at a member or connection named by its GlobalId (3if).

GitHub issue #1: one --mesh-size for the whole model meshes everything as
finely as the one place that needs it. MeshingConfig.set_local_element_size()
gives a member or connection a size of its own, which grows to the size of the
members around it through Gmsh Threshold fields.
"""

import gmsh
import numpy as np
import pytest

from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_connection import RigidConnection
from ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.gmsh_geometry import (
    GmshGeometryConverter,
    _point_distance,
    _segment_distance,
)
from ifc_structural_mechanics.utils.error_handling import MeshingError
from tests.helpers import fixed_support

MATERIAL = Material(
    id="m", name="Concrete", elastic_modulus=30e9, poisson_ratio=0.2, density=2500
)
SECTION = Section.create_rectangular_section(id="s", name="R", width=0.3, height=0.3)
COARSE = 1.0
FINE = 0.1


@pytest.fixture(autouse=True)
def gmsh_session():
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _model() -> StructuralModel:
    """An 8 by 4 slab with a column under its middle and a beam along y = -2."""
    model = StructuralModel(id="model", name="Local sizes")
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry=[
                [0.0, 0.0, 0.0],
                [8.0, 0.0, 0.0],
                [8.0, 4.0, 0.0],
                [0.0, 4.0, 0.0],
            ],
            material=MATERIAL,
            thickness=0.2,
            ifc_guid="SLAB",
        )
    )
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[[0.0, -2.0, 0.0], [8.0, -2.0, 0.0]],
            material=MATERIAL,
            section=SECTION,
            ifc_guid="BEAM",
        )
    )
    column_head = RigidConnection("column_head", [4.0, 2.0, 0.0], ifc_guid="HEAD")
    column_head.set_stiffness_properties(
        {key: 1e20 for key in ("dx", "dy", "dz", "drx", "dry", "drz")}
    )
    column_head.connect_member("slab")
    model.add_connection(column_head)
    edge = RigidConnection("edge", [0.0, 2.0, 0.0], ifc_guid="EDGE")
    edge.edge = [[0.0, 0.0, 0.0], [0.0, 4.0, 0.0]]
    edge.connect_member("slab")
    model.add_connection(edge)
    model.add_connection(fixed_support([0.0, -2.0, 0.0], "beam", "beam_end"))
    return model


def _mesh(local_sizes=None, model=None):
    model = model or _model()
    config = MeshingConfig()
    config.set_default_mesh_size(COARSE)
    for guid, size in (local_sizes or {}).items():
        config.set_local_element_size(guid, size)
    GmshGeometryConverter(meshing_config=config).convert_model(model)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", config.get_min_element_size())
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", config.get_max_element_size())
    gmsh.model.mesh.generate(2)
    return model


def _edges(dim):
    """Lengths and midpoints of the edges of the mesh's elements of ``dim``."""
    tags, coords, _ = gmsh.model.mesh.getNodes()
    xyz = dict(zip(tags, coords.reshape(-1, 3)))
    lengths, middles = [], []
    for kind, _, nodes in zip(*gmsh.model.mesh.getElements(dim)):
        corners = 2 if dim == 1 else 3
        nodes = nodes.reshape(-1, gmsh.model.mesh.getElementProperties(kind)[3])
        for element in nodes[:, :corners]:
            for i in range(corners if dim == 2 else 1):
                a, b = xyz[element[i]], xyz[element[(i + 1) % corners]]
                lengths.append(np.linalg.norm(a - b))
                middles.append((a + b) / 2)
    return np.array(lengths), np.array(middles)


def _size_near(dim, distance_from, within):
    lengths, middles = _edges(dim)
    near = np.array([distance_from(m) for m in middles]) < within
    assert near.any()
    return float(np.median(lengths[near]))


def _size_far(dim, distance_from, beyond):
    lengths, middles = _edges(dim)
    far = np.array([distance_from(m) for m in middles]) > beyond
    assert far.any()
    return float(np.median(lengths[far]))


def _from_point(point):
    return lambda m: np.linalg.norm(m - np.array(point))


def _from_x0_edge(m):
    return abs(m[0]) if 0.0 <= m[1] <= 4.0 else np.inf


def test_no_local_size_leaves_no_field():
    _mesh()
    assert len(gmsh.model.mesh.field.list()) == 0


def test_finer_at_a_point_connection_and_graded_away():
    _mesh({"HEAD": FINE})
    head = _from_point([4.0, 2.0, 0.0])
    assert _size_near(2, head, 0.3) == pytest.approx(FINE, rel=0.5)
    # Graded: twice as far, not much more than twice as coarse at a quarter
    # per metre, and the far corners of the slab are as coarse as before
    assert _size_near(2, head, 1.0) < 0.5 * COARSE
    assert _size_far(2, head, 3.9) > 0.6 * COARSE


def test_finer_along_a_line_connection():
    _mesh({"EDGE": FINE})
    assert _size_near(2, _from_x0_edge, 0.1) == pytest.approx(FINE, rel=0.5)
    assert _size_far(2, _from_x0_edge, 5.0) > 0.6 * COARSE


def test_finer_over_a_curve_member():
    _mesh({"BEAM": FINE})
    on_beam = _size_near(1, lambda m: abs(m[1] + 2.0), 1e-6)
    assert on_beam == pytest.approx(FINE, rel=0.2)


def test_finer_over_a_surface_member():
    _mesh({"SLAB": FINE})
    assert _size_far(2, lambda m: 0.0, -1.0) == pytest.approx(FINE, rel=0.5)
    # The beam, 2 m from the slab, is graded to it
    lengths, middles = _edges(1)
    on_beam = np.abs(middles[:, 1] + 2.0) < 1e-6
    assert np.median(lengths[on_beam]) > 2 * FINE


def test_a_point_on_a_shell_is_warned_about():
    model = _mesh({"HEAD": FINE, "EDGE": FINE})
    warned = [w for w in model.analysis_warnings if w["code"] == "W-MSH-003"]
    assert len(warned) == 1
    assert warned[0]["ifc_guids"] == ["HEAD"]


def test_a_beam_is_not_warned_about():
    model = _mesh({"BEAM": FINE})
    assert not [
        w for w in getattr(model, "analysis_warnings", []) if w["code"] == "W-MSH-003"
    ]


def test_an_unknown_globalid_is_refused():
    with pytest.raises(MeshingError) as raised:
        _mesh({"NOT_THERE": FINE})
    assert raised.value.code == "E-MSH-006"
    assert raised.value.ifc_guids == ["NOT_THERE"]


def test_a_size_no_finer_than_around_is_refused():
    with pytest.raises(MeshingError) as raised:
        _mesh({"HEAD": COARSE})
    assert raised.value.code == "E-MSH-007"


@pytest.mark.parametrize(
    "point, expected",
    [([1.0, 2.0, 3.0], 0.0), ([2.0, 2.0, 3.0], 1.0), ([1.0, -1.0, -1.0], 5.0)],
)
def test_point_distance_expression(point, expected):
    """The MathEval expressions, evaluated as Gmsh would."""
    expression = _point_distance([1.0, 2.0, 3.0])
    assert _evaluate(expression, point) == pytest.approx(expected)


@pytest.mark.parametrize(
    "point, expected",
    [
        ([1.0, 1.0, 0.0], 1.0),  # beside the middle
        ([-3.0, 0.0, 0.0], 3.0),  # beyond the start
        ([5.0, 4.0, 0.0], 5.0),  # beyond the end
        ([0.5, 0.0, -2.0], 2.0),
    ],
)
def test_segment_distance_expression(point, expected):
    expression = _segment_distance([0.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    assert _evaluate(expression, point) == pytest.approx(expected)


def _evaluate(expression, point):
    x, y, z = point
    return eval(
        expression.replace("^", "**"),
        {"sqrt": np.sqrt, "max": max, "min": min, "x": x, "y": y, "z": z},
    )
