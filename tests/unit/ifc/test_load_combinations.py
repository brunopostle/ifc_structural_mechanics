"""Load combinations are read with the factor the file gives each load case.

A combination is an ``IfcStructuralLoadGroup`` of type ``LOAD_COMBINATION``;
the relations that fill it carry the factors. One that cannot be formed is
left out and reported, never read as something else.
"""

import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

# An entity is only valid while its file is alive
_FILES = []


def _open(name):
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    _FILES.append(model)
    return model


def _extract(model):
    """Return ``{combination name: {case name: factor}}`` and the warnings."""
    domain_model = Extractor(model).extract_model()
    names = {
        case.GlobalId: case.Name for case in model.by_type("IfcStructuralLoadCase")
    }
    combinations = {
        combination.name: {
            names[group_id]: factor
            for group_id, factor in combination.load_groups.items()
        }
        for combination in domain_model.load_combinations
    }
    return combinations, [w["message"] for w in domain_model.analysis_warnings]


def _group(model, name):
    (group,) = [g for g in model.by_type("IfcStructuralLoadGroup") if g.Name == name]
    return group


def _assign(model, objects, group, factor=None):
    arguments = [ifcopenshell.guid.new(), None, None, None, objects, None, group]
    if factor is None:
        return model.create_entity("IfcRelAssignsToGroup", *arguments)
    return model.create_entity("IfcRelAssignsToGroupByFactor", *arguments, factor)


class TestExampleFiles:
    def test_beam_01(self):
        combinations, warnings = _extract(_open("beam_01"))
        assert combinations == {
            "DCon1": {"Dead": 1.5},
            "DCon2": {"Dead": 1.5, "Live": 1.5},
        }
        assert not [w for w in warnings if "no results" in w]

    def test_building_02(self):
        combinations, _ = _extract(_open("building_02"))
        assert len(combinations) == 17
        assert combinations["1.4D+1.6L"] == {
            "Dead": 1.4,
            "Extra_dead": 1.4,
            "Live": 1.6,
        }
        assert combinations["1.2(D+L-W)"] == {
            "Dead": 1.2,
            "Live": 1.2,
            "Extra_dead": 1.2,
            "WIND": -1.2,
        }
        # Filled by a relation without a factor
        assert combinations["FOUNDATIONS"] == {"Dead": 1.0, "Extra_dead": 1.0}


class TestSelfWeightOfALoadCase:
    """``SelfWeightCoefficients`` makes the members' weight part of the case."""

    def test_coefficients_are_kept_on_the_load_case(self):
        model = Extractor(_open("beam_01")).extract_model()
        by_name = {group.name: group for group in model.load_groups}
        assert by_name["Dead"].self_weight_coefficients == [0.0, 0.0, -1.0]
        assert by_name["Dead"].includes_self_weight

    def test_case_with_nothing_but_self_weight_is_a_load_case_of_the_model(self):
        """It has no loads, and it loads the structure all the same."""
        ifc = _open("beam_01")
        for action in list(ifc.by_type("IfcStructuralAction")):
            ifc.remove(action)
        model = Extractor(ifc).extract_model()
        (dead,) = [group for group in model.load_groups if group.name == "Dead"]
        assert dead.loads == []
        assert dead.has_actions

    def test_all_zero_coefficients_are_no_self_weight(self):
        model = Extractor(_open("beam_01")).extract_model()
        assert [g.name for g in model.load_groups if g.includes_self_weight] == ["Dead"]

    def test_nothing_is_said_about_it(self):
        """It is applied, so there is nothing to warn about."""
        _, warnings = _extract(_open("beam_01"))
        assert not [w for w in warnings if "weight" in w]


class TestFactors:
    def test_relation_without_a_factor_counts_once(self):
        model = _open("beam_01")
        combination = _group(model, "DCon1")
        for relation in model.by_type("IfcRelAssignsToGroupByFactor"):
            if relation.RelatingGroup == combination:
                model.remove(relation)
        _assign(model, [_group_case(model, "Dead")], combination)
        combinations, _ = _extract(model)
        assert combinations["DCon1"] == {"Dead": 1.0}

    def test_coefficient_of_the_combination_multiplies(self):
        model = _open("beam_01")
        _group(model, "DCon2").Coefficient = 2.0
        combinations, _ = _extract(model)
        assert combinations["DCon2"] == {"Dead": 3.0, "Live": 3.0}
        assert combinations["DCon1"] == {"Dead": 1.5}

    def test_case_assigned_twice_is_added(self):
        model = _open("beam_01")
        _assign(model, [_group_case(model, "Dead")], _group(model, "DCon1"), 0.25)
        combinations, _ = _extract(model)
        assert combinations["DCon1"] == {"Dead": 1.75}

    def test_negative_factor(self):
        model = _open("beam_01")
        _assign(model, [_group_case(model, "Live")], _group(model, "DCon1"), -1.0)
        combinations, _ = _extract(model)
        assert combinations["DCon1"] == {"Dead": 1.5, "Live": -1.0}


class TestWhatCannotBeFormed:
    def test_combination_of_nothing_is_left_out_and_reported(self):
        model = _open("beam_01")
        combination = _group(model, "DCon1")
        for relation in model.by_type("IfcRelAssignsToGroupByFactor"):
            if relation.RelatingGroup == combination:
                model.remove(relation)
        combinations, warnings = _extract(model)
        assert list(combinations) == ["DCon2"]
        (warning,) = [w for w in warnings if "name no load case" in w]
        assert "1 load combination(s) name no load case" in warning
        assert "DCon1" in warning

    def test_combination_of_a_load_group_is_left_out_and_reported(self):
        """Only load cases are solved, so only they can be added up."""
        model = _open("beam_01")
        plain_group = [
            g
            for g in model.by_type("IfcStructuralLoadGroup")
            if g.PredefinedType == "LOAD_GROUP" and g.Name == "Dead"
        ][0]
        _assign(model, [plain_group], _group(model, "DCon1"), 1.2)
        combinations, warnings = _extract(model)
        assert list(combinations) == ["DCon2"]
        (warning,) = [w for w in warnings if "not a load case" in w]
        assert "1 load combination(s) include something that is not a load" in warning
        assert "DCon1" in warning
        assert plain_group.GlobalId in warning

    def test_combination_of_a_combination_is_left_out_and_reported(self):
        model = _open("beam_01")
        _assign(model, [_group(model, "DCon1")], _group(model, "DCon2"), 1.0)
        combinations, warnings = _extract(model)
        assert list(combinations) == ["DCon1"]
        assert any("DCon2" in w and "not a load case" in w for w in warnings)


def _group_case(model, name):
    (case,) = [c for c in model.by_type("IfcStructuralLoadCase") if c.Name == name]
    return case
