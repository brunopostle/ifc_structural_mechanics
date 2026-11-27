"""The sets of loads a buckling analysis finds the factors of (bqj)."""

import pytest

from ifc_structural_mechanics.analysis.buckling_loads import (
    buckling_load_sets,
    governing_set,
)
from ifc_structural_mechanics.domain.load import LoadCombination, LoadGroup, PointLoad
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.utils.error_handling import AnalysisError


def _case(model, group_id, name, loaded=True):
    group = LoadGroup(id=group_id, name=name, is_load_case=True)
    if loaded:
        group.add_load(
            PointLoad(
                id=f"p_{group_id}",
                magnitude=1.0,
                direction=[0, 0, -1],
                position=[0, 0, 0],
            )
        )
    model.load_groups.append(group)
    return group


def _model(combinations=True):
    model = StructuralModel(id="m")
    _case(model, "D", "Dead")
    _case(model, "S", "Snow")
    _case(model, "W", "Wind")
    _case(model, "E", "Empty", loaded=False)
    if combinations:
        model.load_combinations = [
            LoadCombination("C1", "ULS snow", load_groups={"D": 1.35, "S": 1.5}),
            LoadCombination("C2", "ULS wind", load_groups={"D": 1.0, "W": 1.5}),
        ]
    return model


def test_a_set_per_combination():
    sets, warnings = buckling_load_sets(_model())
    assert [(s.name, s.kind, s.ifc_guid) for s in sets] == [
        ("ULS snow", "load_combination", "C1"),
        ("ULS wind", "load_combination", "C2"),
    ]
    assert sets[0].factors == {"D": 1.35, "S": 1.5}
    assert sets[0].case_factors == {"Dead": 1.35, "Snow": 1.5}
    assert warnings == []


def test_a_set_per_load_case_without_combinations():
    sets, _ = buckling_load_sets(_model(combinations=False))
    # A case with nothing in it has nothing to buckle under
    assert [(s.name, s.kind, s.factors) for s in sets] == [
        ("Dead", "load_case", {"D": 1.0}),
        ("Snow", "load_case", {"S": 1.0}),
        ("Wind", "load_case", {"W": 1.0}),
    ]


def test_every_load_without_load_cases():
    (only,), _ = buckling_load_sets(StructuralModel(id="m"))
    assert (only.name, only.kind, only.ifc_guid) == (
        "Reference loads",
        "all_loads",
        None,
    )


def test_gravity_is_a_set_of_its_own():
    sets, _ = buckling_load_sets(_model(), gravity=True)
    assert [s.name for s in sets] == ["ULS snow", "ULS wind", "Gravity"]
    assert (sets[-1].gravity, sets[-1].factors, sets[-1].ifc_guid) == (1.0, {}, None)
    assert sets[0].gravity == 0.0


def test_a_combination_of_empty_cases_is_warned_about():
    model = _model()
    model.load_combinations.append(
        LoadCombination("C3", "Nothing", load_groups={"E": 1.0})
    )
    sets, (warned,) = buckling_load_sets(model)
    assert [s.name for s in sets] == ["ULS snow", "ULS wind"]
    assert warned["code"] == "W-LOD-012"
    assert warned["ifc_guids"] == ["C3"]


def test_chosen_by_name_in_the_order_given():
    sets, _ = buckling_load_sets(
        _model(), combinations=["ULS wind"], load_cases=["Snow", "Dead"]
    )
    assert [(s.name, s.kind) for s in sets] == [
        ("ULS wind", "load_combination"),
        ("Snow", "load_case"),
        ("Dead", "load_case"),
    ]


def test_only_load_cases_chosen():
    sets, _ = buckling_load_sets(_model(), load_cases=["Wind"])
    assert [s.name for s in sets] == ["Wind"]


@pytest.mark.parametrize(
    "selection, named",
    [
        ({"combinations": ["ULS 9"]}, "combination 'ULS 9'"),
        ({"load_cases": ["Live"]}, "load case 'Live'"),
        ({"load_cases": ["Empty"]}, "load case 'Empty'"),
        ({"load_cases": ["Gravity"]}, "load case 'Gravity'"),
    ],
)
def test_a_name_the_file_does_not_have(selection, named):
    with pytest.raises(AnalysisError) as raised:
        buckling_load_sets(_model(), **selection)
    assert raised.value.code == "E-LOD-009"
    assert named in str(raised.value)
    assert "ULS snow, ULS wind" in str(raised.value)


def test_a_name_given_twice_is_one_set():
    sets, _ = buckling_load_sets(_model(), combinations=["ULS snow", "ULS snow"])
    assert [s.name for s in sets] == ["ULS snow"]


def test_a_case_and_a_combination_of_one_name_are_told_apart():
    model = _model()
    model.load_combinations.append(
        LoadCombination("C4", "Snow", load_groups={"S": 1.5})
    )
    sets, _ = buckling_load_sets(model, combinations=["Snow"], load_cases=["Snow"])
    assert [s.name for s in sets] == ["Snow", "Snow (load case)"]


def test_two_combinations_of_one_name_go_by_their_globalid():
    model = _model()
    model.load_combinations.append(
        LoadCombination("C5", "ULS snow", load_groups={"S": 2.0})
    )
    sets, _ = buckling_load_sets(model)
    assert [s.name for s in sets] == ["ULS snow", "ULS wind", "ULS snow (C5)"]
    with pytest.raises(AnalysisError):
        buckling_load_sets(model, combinations=["ULS snow"])
    (chosen,), _ = buckling_load_sets(model, combinations=["ULS snow (C5)"])
    assert chosen.ifc_guid == "C5"


@pytest.mark.parametrize(
    "factors, governing",
    [
        ([[(1, 4.0)], [(1, 2.5)]], 1),
        ([[(1, 4.0)], [(1, -1.0), (2, 6.0)]], 0),
        ([[(1, -4.0)], [(1, 3.0)]], 1),
        ([[(1, -4.0)], [(1, -3.0)]], None),
    ],
)
def test_the_governing_set_buckles_first(factors, governing):
    assert governing_set(factors) == governing
