"""Tests for partial end-release extraction in ConnectionsExtractor.

Replaces the old _has_rotational_releases() tests with the new
_extract_end_releases() API which returns per-member released DOF lists.
"""

from unittest.mock import MagicMock

import pytest

from ifc_structural_mechanics.domain.structural_connection import StructuralConnection
from ifc_structural_mechanics.ifc.connections_extractor import ConnectionsExtractor


def _extractor():
    """Minimal ConnectionsExtractor stub."""
    mock_ifc = MagicMock()
    mock_ifc.by_type.return_value = []
    extractor = ConnectionsExtractor.__new__(ConnectionsExtractor)
    extractor.ifc = mock_ifc
    extractor.logger = MagicMock()
    extractor.length_scale = 1.0
    extractor.force_scale = 1.0
    return extractor


def _stiffness(value):
    """Wrap a value as IfcOpenShell does for stiffness attributes."""
    attr = MagicMock()
    attr.wrappedValue = value
    return attr


def _make_rel(member_id, rot_x=None, rot_y=None, rot_z=None):
    """Build a mock IfcRelConnectsStructuralMember with AppliedCondition."""
    member = MagicMock()
    member.GlobalId = member_id

    condition = MagicMock()
    condition.RotationalStiffnessX = _stiffness(rot_x) if rot_x is not None else None
    condition.RotationalStiffnessY = _stiffness(rot_y) if rot_y is not None else None
    condition.RotationalStiffnessZ = _stiffness(rot_z) if rot_z is not None else None

    rel = MagicMock()
    rel.RelatingStructuralMember = member
    rel.AppliedCondition = condition
    return rel


def _make_connection(*rels):
    """Build a mock IfcStructuralPointConnection containing the given rels."""
    conn = MagicMock()
    conn.ConnectsStructuralMembers = list(rels)
    return conn


# ---------------------------------------------------------------------------
# _extract_end_releases — basic behaviour
# ---------------------------------------------------------------------------


class TestExtractEndReleases:
    def test_no_connects_attr_returns_empty(self):
        ext = _extractor()
        conn = MagicMock(spec=[])  # no attributes
        assert ext._extract_end_releases(conn) == {}

    def test_no_condition_returns_empty(self):
        ext = _extractor()
        rel = _make_rel("m1")
        rel.AppliedCondition = None
        conn = _make_connection(rel)
        assert ext._extract_end_releases(conn) == {}

    def test_all_fixed_returns_empty(self):
        """True stiffness → not released → empty dict."""
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_x=True, rot_y=True, rot_z=True))
        assert ext._extract_end_releases(conn) == {}

    def test_nonzero_spring_not_released(self):
        """Positive spring stiffness → not released."""
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_x=1e6, rot_y=1e6, rot_z=1e6))
        assert ext._extract_end_releases(conn) == {}

    # --- single axis releases ---

    def test_rot_x_false_releases_dof4(self):
        """RotationalStiffnessX=False → DOF 4 released."""
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_x=False))
        result = ext._extract_end_releases(conn)
        assert "m1" in result
        assert 4 in result["m1"]
        assert 5 not in result["m1"]
        assert 6 not in result["m1"]

    def test_rot_y_zero_releases_dof5(self):
        """RotationalStiffnessY=0.0 → DOF 5 released."""
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_y=0.0))
        result = ext._extract_end_releases(conn)
        assert 5 in result["m1"]

    def test_rot_z_false_releases_dof6(self):
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_z=False))
        result = ext._extract_end_releases(conn)
        assert 6 in result["m1"]

    def test_full_pin_releases_all_three(self):
        """All three rotational DOFs free → [4, 5, 6]."""
        ext = _extractor()
        conn = _make_connection(_make_rel("m1", rot_x=False, rot_y=False, rot_z=False))
        result = ext._extract_end_releases(conn)
        assert sorted(result["m1"]) == [4, 5, 6]

    # --- multiple members ---

    def test_partial_release_only_for_one_member(self):
        """One member has a release, the other is rigid."""
        ext = _extractor()
        rel_released = _make_rel("m_beam", rot_x=False)
        rel_rigid = _make_rel("m_column", rot_x=True, rot_y=True, rot_z=True)
        conn = _make_connection(rel_released, rel_rigid)
        result = ext._extract_end_releases(conn)
        assert "m_beam" in result
        assert 4 in result["m_beam"]
        assert "m_column" not in result

    def test_two_members_different_releases(self):
        """Each member has a different axis released."""
        ext = _extractor()
        rel_a = _make_rel("m_a", rot_x=False)    # releases DOF 4
        rel_b = _make_rel("m_b", rot_z=0.0)      # releases DOF 6
        conn = _make_connection(rel_a, rel_b)
        result = ext._extract_end_releases(conn)
        assert result["m_a"] == [4]
        assert result["m_b"] == [6]

    def test_missing_member_on_rel_is_skipped(self):
        """RelatingStructuralMember = None → relationship skipped."""
        ext = _extractor()
        rel = _make_rel("m1", rot_x=False)
        rel.RelatingStructuralMember = None
        conn = _make_connection(rel)
        assert ext._extract_end_releases(conn) == {}


# ---------------------------------------------------------------------------
# StructuralConnection.released_dofs_by_member and has_end_releases property
# ---------------------------------------------------------------------------


class TestConnectionDomainModel:
    def _make_conn(self):
        return StructuralConnection.__new__(StructuralConnection)

    def test_empty_by_default(self):
        c = StructuralConnection("c1", "point")
        assert c.released_dofs_by_member == {}

    def test_has_end_releases_false_when_empty(self):
        c = StructuralConnection("c1", "point")
        assert c.has_end_releases is False

    def test_has_end_releases_true_when_populated(self):
        c = StructuralConnection("c1", "point")
        c.released_dofs_by_member = {"m1": [4]}
        assert c.has_end_releases is True

    def test_partial_releases_stored_correctly(self):
        c = StructuralConnection("c1", "point")
        c.released_dofs_by_member = {"m_beam": [4, 5], "m_col": [6]}
        assert sorted(c.released_dofs_by_member["m_beam"]) == [4, 5]
        assert c.released_dofs_by_member["m_col"] == [6]
