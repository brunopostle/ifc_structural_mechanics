"""
Tests for the structural connection domain model classes.
"""

from ifc_structural_mechanics.domain.structural_connection import (
    StructuralConnection,
    PointConnection,
    RigidConnection,
    HingeConnection,
)


class TestStructuralConnection:
    """Tests for the base StructuralConnection class."""

    def test_initialization(self):
        """Test initialization of a structural connection."""
        connection = StructuralConnection("conn-1", "test-type")
        assert connection.id == "conn-1"
        assert (
            connection.entity_type == "test-type"
        )  # Changed from connection_type to entity_type
        assert connection.connected_members == []

    def test_connect_disconnect_member(self):
        """Test connecting and disconnecting members."""
        connection = StructuralConnection("conn-1", "test-type")

        # Connect a member
        connection.connect_member("member-1")
        assert "member-1" in connection.connected_members
        assert connection.is_connected_to("member-1")

        # Connect another member
        connection.connect_member("member-2")
        assert "member-2" in connection.connected_members
        assert connection.is_connected_to("member-2")

        # Connecting the same member again should not duplicate
        connection.connect_member("member-1")
        assert connection.connected_members.count("member-1") == 1

        # Disconnect a member
        connection.disconnect_member("member-1")
        assert "member-1" not in connection.connected_members
        assert not connection.is_connected_to("member-1")

        # Disconnecting a non-connected member should not raise an error
        connection.disconnect_member("non-existent")

    def test_validation(self):
        """Test validation of structural connections."""
        connection = StructuralConnection("conn-1", "test-type")

        # Connection with no members should be invalid
        assert not connection.validate()

        # Connection with one member should be invalid
        connection.connect_member("member-1")
        assert not connection.validate()

        # Connection with two or more members should be valid
        connection.connect_member("member-2")
        assert connection.validate()


class TestPointConnection:
    """Tests for the PointConnection class."""

    def test_initialization(self):
        """Test initialization of a point connection."""
        connection = PointConnection("conn-1", [1.0, 2.0, 3.0])
        assert connection.id == "conn-1"
        assert (
            connection.entity_type == "point"
        )  # Changed from connection_type to entity_type
        assert connection.position == [1.0, 2.0, 3.0]
        assert connection.connected_members == []

    def test_validation(self):
        """Test validation of point connections."""
        connection = PointConnection("conn-1", [1.0, 2.0, 3.0])

        # Connection with no members should be invalid
        assert not connection.validate()

        # Connection with one member should be invalid
        connection.connect_member("member-1")
        assert not connection.validate()

        # Connection with two or more members should be valid
        connection.connect_member("member-2")
        assert connection.validate()

        # Test with invalid position
        invalid_connection = PointConnection("conn-2", [1.0, 2.0])
        invalid_connection.connect_member("member-1")
        invalid_connection.connect_member("member-2")
        assert not invalid_connection.validate()  # Fixed: removed the extra parentheses

        # Test with invalid position type
        invalid_connection = PointConnection("conn-3", [1.0, "invalid", 3.0])
        invalid_connection.connect_member("member-1")
        invalid_connection.connect_member("member-2")
        assert not invalid_connection.validate()  # Fixed: removed the extra parentheses


class TestRigidConnection:
    """Tests for the RigidConnection class."""

    def test_initialization(self):
        """Test initialization of a rigid connection."""
        # Test with position
        connection = RigidConnection("conn-1", [1.0, 2.0, 3.0])
        assert connection.id == "conn-1"
        assert (
            connection.entity_type == "rigid"
        )  # Changed from connection_type to entity_type
        assert connection.position == [1.0, 2.0, 3.0]
        assert connection.connected_members == []

        # Test without position
        connection = RigidConnection("conn-2")
        assert connection.id == "conn-2"
        assert (
            connection.entity_type == "rigid"
        )  # Changed from connection_type to entity_type
        assert connection.position is None
        assert connection.connected_members == []

    def test_validation(self):
        """Test validation of rigid connections."""
        # Test with position
        connection = RigidConnection("conn-1", [1.0, 2.0, 3.0])

        # Connection with no members should be invalid
        assert not connection.validate()

        # Connection with two members should be valid
        connection.connect_member("member-1")
        connection.connect_member("member-2")
        assert connection.validate()

        # Test without position
        connection = RigidConnection("conn-2")
        connection.connect_member("member-1")
        connection.connect_member("member-2")
        assert connection.validate()

        # Test with invalid position
        invalid_connection = RigidConnection("conn-3", [1.0, "invalid", 3.0])
        invalid_connection.connect_member("member-1")
        invalid_connection.connect_member("member-2")
        assert not invalid_connection.validate()  # Fixed: removed the extra parentheses


class TestHingeConnection:
    """Tests for the HingeConnection class."""

    def test_initialization(self):
        """Test initialization of a hinge connection."""
        # Test with rotation axis
        connection = HingeConnection("conn-1", [1.0, 2.0, 3.0], [0.0, 0.0, 1.0])
        assert connection.id == "conn-1"
        assert (
            connection.entity_type == "hinge"
        )  # Changed from connection_type to entity_type
        assert connection.position == [1.0, 2.0, 3.0]
        assert connection.rotation_axis == [0.0, 0.0, 1.0]
        assert connection.connected_members == []

        # Test without rotation axis
        connection = HingeConnection("conn-2", [1.0, 2.0, 3.0])
        assert connection.id == "conn-2"
        assert (
            connection.entity_type == "hinge"
        )  # Changed from connection_type to entity_type
        assert connection.position == [1.0, 2.0, 3.0]
        assert connection.rotation_axis is None
        assert connection.connected_members == []

    def test_validation(self):
        """Test validation of hinge connections."""
        # Test with rotation axis
        connection = HingeConnection("conn-1", [1.0, 2.0, 3.0], [0.0, 0.0, 1.0])

        # Connection with no members should be invalid
        assert not connection.validate()

        # Connection with two members should be valid
        connection.connect_member("member-1")
        connection.connect_member("member-2")
        assert connection.validate()

        # Test without rotation axis
        connection = HingeConnection("conn-2", [1.0, 2.0, 3.0])
        connection.connect_member("member-1")
        connection.connect_member("member-2")
        assert connection.validate()

        # Test with invalid position
        invalid_connection = HingeConnection("conn-3", [1.0, "invalid", 3.0])
        invalid_connection.connect_member("member-1")
        invalid_connection.connect_member("member-2")
        assert not invalid_connection.validate()  # Fixed: removed the extra parentheses

        # Test with invalid rotation axis
        invalid_connection = HingeConnection(
            "conn-4", [1.0, 2.0, 3.0], [0.0, "invalid", 1.0]
        )
        invalid_connection.connect_member("member-1")
        invalid_connection.connect_member("member-2")
        assert (
            not invalid_connection.validate()
        )  # Fixed: added parentheses and fixed validation check
