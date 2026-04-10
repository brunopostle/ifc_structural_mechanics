"""Tests for _has_rotational_releases() in ConnectionsExtractor."""

from unittest.mock import MagicMock

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


def _make_connection_with_condition(rot_x=None, rot_y=None, rot_z=None):
    """Build a mock IfcStructuralPointConnection with AppliedCondition."""
    ifc_conn = MagicMock()

    def _make_stiffness(value):
        """Wrap a value the way IfcOpenShell does."""
        attr = MagicMock()
        attr.wrappedValue = value
        return attr

    condition = MagicMock()
    condition.RotationalStiffnessX = (
        _make_stiffness(rot_x) if rot_x is not None else None
    )
    condition.RotationalStiffnessY = (
        _make_stiffness(rot_y) if rot_y is not None else None
    )
    condition.RotationalStiffnessZ = (
        _make_stiffness(rot_z) if rot_z is not None else None
    )

    rel = MagicMock()
    rel.AppliedCondition = condition
    ifc_conn.ConnectsStructuralMembers = [rel]
    return ifc_conn


class TestHasRotationalReleases:
    """_has_rotational_releases() correctly identifies released DOFs."""

    def test_false_value_is_released(self):
        """wrappedValue=False (explicitly free) → released."""
        extractor = _extractor()
        conn = _make_connection_with_condition(rot_x=False)
        assert extractor._has_rotational_releases(conn) is True

    def test_zero_stiffness_is_released(self):
        """wrappedValue=0.0 (zero spring) → released."""
        extractor = _extractor()
        conn = _make_connection_with_condition(rot_y=0.0)
        assert extractor._has_rotational_releases(conn) is True

    def test_true_value_is_not_released(self):
        """wrappedValue=True (fixed) → not released."""
        extractor = _extractor()
        conn = _make_connection_with_condition(rot_x=True, rot_y=True, rot_z=True)
        assert extractor._has_rotational_releases(conn) is False

    def test_nonzero_spring_is_not_released(self):
        """wrappedValue=1e6 (spring stiffness > 0) → not released."""
        extractor = _extractor()
        conn = _make_connection_with_condition(rot_x=1e6, rot_y=1e6, rot_z=1e6)
        assert extractor._has_rotational_releases(conn) is False

    def test_no_condition_returns_false(self):
        """No AppliedCondition → not released."""
        extractor = _extractor()
        ifc_conn = MagicMock()
        rel = MagicMock()
        rel.AppliedCondition = None
        ifc_conn.ConnectsStructuralMembers = [rel]
        assert extractor._has_rotational_releases(ifc_conn) is False

    def test_no_connects_returns_false(self):
        """Connection without ConnectsStructuralMembers → not released."""
        extractor = _extractor()
        ifc_conn = MagicMock(spec=[])  # no attributes at all
        assert extractor._has_rotational_releases(ifc_conn) is False

    def test_z_rotation_released(self):
        """Only Z rotation released → still returns True."""
        extractor = _extractor()
        conn = _make_connection_with_condition(rot_x=True, rot_y=True, rot_z=False)
        assert extractor._has_rotational_releases(conn) is True
