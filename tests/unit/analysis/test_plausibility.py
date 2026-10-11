"""Warnings for results too large to be believed."""

from ifc_structural_mechanics.analysis.plausibility import plausibility_warnings
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel


def _model():
    """A 20 m x 10 m slab on a 5 m column: the model is 22.9 m across."""
    material = Material(
        id="m", name="m", density=2500.0, elastic_modulus=30e9, poisson_ratio=0.2
    )
    model = StructuralModel(id="model")
    model.add_member(
        SurfaceMember(
            id="slab",
            geometry={"boundaries": [[(0, 0, 5), (20, 0, 5), (20, 10, 5), (0, 10, 5)]]},
            material=material,
            thickness=Thickness(id="t", name="t", value=0.2),
        )
    )
    model.add_member(
        CurveMember(
            id="column",
            geometry=[[0, 0, 0], [0, 0, 5]],
            material=material,
            section=Section.create_rectangular_section("s", "s", width=0.4, height=0.4),
        )
    )
    return model


def _results(cases):
    """``cases`` maps a load case to ``{member: (largest, relative)}`` in metres."""
    members = {}
    for case, values in cases.items():
        for member_id, (largest, relative) in values.items():
            members.setdefault(member_id, {"id": member_id, "by_load_case": {}})[
                "by_load_case"
            ][case] = {
                "max_displacement_m": largest,
                "max_relative_displacement_m": relative,
            }
    return {
        "load_cases": list(cases),
        "members": list(members.values()),
        "global_displacements": {
            "by_load_case": {
                case: {"max_displacement_m": max(v[0] for v in values.values())}
                for case, values in cases.items()
            }
        },
    }


def _messages(cases):
    return [w["message"] for w in plausibility_warnings(_results(cases), _model())]


def test_ordinary_results_raise_nothing():
    """Span / 500 on the slab, a few millimetres of sway on the column."""
    assert _messages({"Dead": {"slab": (0.045, 0.040), "column": (0.006, 0.005)}}) == []


def test_member_distorting_by_more_than_a_hundredth_of_its_size():
    """The slab is 22.4 m corner to corner; 0.46 m is 1/49 of that."""
    messages = _messages({"Live": {"slab": (0.46, 0.46), "column": (0.001, 0.001)}})

    assert len(messages) == 1
    assert "Load case Live: member slab distorts by 460 mm over its 22.4 m (1/49)" in (
        messages[0]
    )
    assert "other member" not in messages[0]


def test_member_carried_along_by_others_is_not_blamed():
    """It moves a long way but keeps its shape."""
    assert _messages({"Wind": {"slab": (0.6, 0.02), "column": (0.6, 0.03)}}) == []


def test_worst_member_is_named_and_the_rest_counted():
    messages = _messages({"Live": {"slab": (0.5, 0.5), "column": (0.5, 0.4)}})

    assert len(messages) == 1
    assert "member column distorts by 400 mm over its 5 m (1/12)" in messages[0]
    assert "1 other member(s) exceed the same limit." in messages[0]


def test_displacement_beyond_a_twentieth_of_the_model_is_a_mechanism():
    messages = _messages({"Dead": {"slab": (1500.0, 0.0), "column": (2.0, 0.0)}})

    assert len(messages) == 1
    assert "Load case Dead: the largest displacement is 1.5 km, at member slab" in (
        messages[0]
    )
    assert "in a model 22.9 m across" in messages[0]
    assert "probably a mechanism" in messages[0]


def test_each_load_case_is_judged_alone():
    messages = _messages(
        {
            "Dead": {"slab": (0.01, 0.01), "column": (0.001, 0.001)},
            "Live": {"slab": (0.9, 0.9), "column": (0.001, 0.001)},
        }
    )

    assert len(messages) == 1
    assert messages[0].startswith("Load case Live")


def test_warning_points_at_the_member():
    warnings = plausibility_warnings(
        _results({"Live": {"slab": (0.9, 0.9), "column": (0.0, 0.0)}}), _model()
    )

    assert warnings[0]["domain_id"] == "slab"
    assert warnings[0]["severity"] == "warning"


def test_results_without_members_or_cases_raise_nothing():
    assert plausibility_warnings({}, _model()) == []
    assert plausibility_warnings(_results({"Dead": {"slab": (9.0, 9.0)}}), None) == []


def test_distortion_beyond_the_size_of_the_member_is_not_written_as_a_fraction():
    messages = _messages({"Live": {"slab": (0.5, 0.0), "column": (9.0, 9.0)}})
    (message,) = [m for m in messages if "distorts by" in m]

    assert "column distorts by 9 m over its 5 m (more than half of it)" in message
