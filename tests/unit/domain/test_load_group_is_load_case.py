"""Tests for LoadGroup.is_load_case flag."""

from ifc_structural_mechanics.domain.load import LoadGroup, PointLoad
import numpy as np


class TestLoadGroupIsLoadCase:
    """Tests for the is_load_case attribute on LoadGroup."""

    def test_default_is_false(self):
        """LoadGroup defaults to is_load_case=False (sub-group behaviour)."""
        group = LoadGroup(id="g1", name="Sub-Group")
        assert group.is_load_case is False

    def test_explicit_true(self):
        """Setting is_load_case=True marks the group as a load case."""
        case = LoadGroup(id="lc1", name="Dead Load", is_load_case=True)
        assert case.is_load_case is True

    def test_explicit_false(self):
        """Explicitly passing is_load_case=False keeps default behaviour."""
        group = LoadGroup(id="g2", is_load_case=False)
        assert group.is_load_case is False

    def test_is_load_case_does_not_affect_loads(self):
        """is_load_case flag does not affect load storage."""
        load = PointLoad(
            id="p1",
            magnitude=1000.0,
            direction=[0, 0, -1],
            position=[1.0, 0.0, 0.0],
        )
        case = LoadGroup(id="lc2", name="Live Load", is_load_case=True)
        case.add_load(load)
        assert len(case.loads) == 1
        assert case.loads[0] is load

    def test_filter_load_cases_from_mixed_list(self):
        """Filtering by is_load_case correctly separates cases from sub-groups."""
        sub = LoadGroup(id="sg1", name="Wind sub-group")
        case1 = LoadGroup(id="lc1", name="Dead", is_load_case=True)
        case2 = LoadGroup(id="lc2", name="Live", is_load_case=True)

        all_groups = [sub, case1, case2]
        load_cases = [g for g in all_groups if g.is_load_case]
        sub_groups = [g for g in all_groups if not g.is_load_case]

        assert len(load_cases) == 2
        assert len(sub_groups) == 1
        assert sub_groups[0] is sub
