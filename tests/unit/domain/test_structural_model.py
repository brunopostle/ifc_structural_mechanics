"""
Tests for the StructuralModel class.
"""

import pytest

from ifc_structural_mechanics.domain.structural_model import StructuralModel


# Mock classes for testing
class MockElement:
    def __init__(self, id):
        self.id = id


class MockMember(MockElement):
    pass


class MockConnection(MockElement):
    pass


class MockLoadGroup(MockElement):
    pass


class MockLoadCombination(MockElement):
    pass


class MockResult(MockElement):
    pass


class TestStructuralModel:
    """Test cases for the StructuralModel class."""

    def test_initialization(self):
        """Test that a model can be initialized correctly."""
        # Test with all parameters
        model = StructuralModel(
            id="test_model", name="Test Model", description="Test description"
        )
        assert model.id == "test_model"
        assert model.name == "Test Model"
        assert model.description == "Test description"
        assert model.members == []
        assert model.connections == []
        assert model.load_groups == []
        assert model.load_combinations == []
        assert model.results == []

        # Test with only required parameters
        model = StructuralModel(id="test_model")
        assert model.id == "test_model"
        assert model.name is None
        assert model.description is None
        assert model.members == []
        assert model.connections == []
        assert model.load_groups == []
        assert model.load_combinations == []
        assert model.results == []

    def test_initialization_with_invalid_id(self):
        """Test that initialization fails with an empty ID."""
        with pytest.raises(ValueError):
            StructuralModel(id="")

        with pytest.raises(ValueError):
            StructuralModel(id=None)

    def test_add_member(self):
        """Test adding a member to the model."""
        model = StructuralModel(id="test_model")
        member = MockMember(id="member1")
        model.add_member(member)
        assert len(model.members) == 1
        assert model.members[0] == member

    def test_add_duplicate_member(self):
        """Test that adding a duplicate member raises an error."""
        model = StructuralModel(id="test_model")
        member = MockMember(id="member1")
        model.add_member(member)

        # Try to add a member with the same ID
        duplicate_member = MockMember(id="member1")
        with pytest.raises(ValueError):
            model.add_member(duplicate_member)

    def test_remove_member(self):
        """Test removing a member from the model."""
        model = StructuralModel(id="test_model")
        member1 = MockMember(id="member1")
        member2 = MockMember(id="member2")
        model.add_member(member1)
        model.add_member(member2)

        # Remove the first member
        result = model.remove_member("member1")
        assert result is True
        assert len(model.members) == 1
        assert model.members[0].id == "member2"

        # Try to remove a non-existent member
        result = model.remove_member("non_existent")
        assert result is False
        assert len(model.members) == 1

    def test_get_member(self):
        """Test getting a member by ID."""
        model = StructuralModel(id="test_model")
        member1 = MockMember(id="member1")
        member2 = MockMember(id="member2")
        model.add_member(member1)
        model.add_member(member2)

        # Get existing member
        result = model.get_member("member1")
        assert result == member1

        # Try to get a non-existent member
        result = model.get_member("non_existent")
        assert result is None

    def test_add_connection(self):
        """Test adding a connection to the model."""
        model = StructuralModel(id="test_model")
        connection = MockConnection(id="connection1")
        model.add_connection(connection)
        assert len(model.connections) == 1
        assert model.connections[0] == connection

    def test_add_duplicate_connection(self):
        """Test that adding a duplicate connection raises an error."""
        model = StructuralModel(id="test_model")
        connection = MockConnection(id="connection1")
        model.add_connection(connection)

        # Try to add a connection with the same ID
        duplicate_connection = MockConnection(id="connection1")
        with pytest.raises(ValueError):
            model.add_connection(duplicate_connection)

    def test_remove_connection(self):
        """Test removing a connection from the model."""
        model = StructuralModel(id="test_model")
        connection1 = MockConnection(id="connection1")
        connection2 = MockConnection(id="connection2")
        model.add_connection(connection1)
        model.add_connection(connection2)

        # Remove the first connection
        result = model.remove_connection("connection1")
        assert result is True
        assert len(model.connections) == 1
        assert model.connections[0].id == "connection2"

        # Try to remove a non-existent connection
        result = model.remove_connection("non_existent")
        assert result is False
        assert len(model.connections) == 1

    def test_get_connection(self):
        """Test getting a connection by ID."""
        model = StructuralModel(id="test_model")
        connection1 = MockConnection(id="connection1")
        connection2 = MockConnection(id="connection2")
        model.add_connection(connection1)
        model.add_connection(connection2)

        # Get existing connection
        result = model.get_connection("connection1")
        assert result == connection1

        # Try to get a non-existent connection
        result = model.get_connection("non_existent")
        assert result is None

    def test_add_load_group(self):
        """Test adding a load group to the model."""
        model = StructuralModel(id="test_model")
        load_group = MockLoadGroup(id="load_group1")
        model.add_load_group(load_group)
        assert len(model.load_groups) == 1
        assert model.load_groups[0] == load_group

    def test_add_duplicate_load_group(self):
        """Test that adding a duplicate load group raises an error."""
        model = StructuralModel(id="test_model")
        load_group = MockLoadGroup(id="load_group1")
        model.add_load_group(load_group)

        # Try to add a load group with the same ID
        duplicate_load_group = MockLoadGroup(id="load_group1")
        with pytest.raises(ValueError):
            model.add_load_group(duplicate_load_group)

    def test_remove_load_group(self):
        """Test removing a load group from the model."""
        model = StructuralModel(id="test_model")
        load_group1 = MockLoadGroup(id="load_group1")
        load_group2 = MockLoadGroup(id="load_group2")
        model.add_load_group(load_group1)
        model.add_load_group(load_group2)

        # Remove the first load group
        result = model.remove_load_group("load_group1")
        assert result is True
        assert len(model.load_groups) == 1
        assert model.load_groups[0].id == "load_group2"

        # Try to remove a non-existent load group
        result = model.remove_load_group("non_existent")
        assert result is False
        assert len(model.load_groups) == 1

    def test_get_load_group(self):
        """Test getting a load group by ID."""
        model = StructuralModel(id="test_model")
        load_group1 = MockLoadGroup(id="load_group1")
        load_group2 = MockLoadGroup(id="load_group2")
        model.add_load_group(load_group1)
        model.add_load_group(load_group2)

        # Get existing load group
        result = model.get_load_group("load_group1")
        assert result == load_group1

        # Try to get a non-existent load group
        result = model.get_load_group("non_existent")
        assert result is None

    def test_add_load_combination(self):
        """Test adding a load combination to the model."""
        model = StructuralModel(id="test_model")
        load_combination = MockLoadCombination(id="load_combination1")
        model.add_load_combination(load_combination)
        assert len(model.load_combinations) == 1
        assert model.load_combinations[0] == load_combination

    def test_add_duplicate_load_combination(self):
        """Test that adding a duplicate load combination raises an error."""
        model = StructuralModel(id="test_model")
        load_combination = MockLoadCombination(id="load_combination1")
        model.add_load_combination(load_combination)

        # Try to add a load combination with the same ID
        duplicate_load_combination = MockLoadCombination(id="load_combination1")
        with pytest.raises(ValueError):
            model.add_load_combination(duplicate_load_combination)

    def test_remove_load_combination(self):
        """Test removing a load combination from the model."""
        model = StructuralModel(id="test_model")
        load_combination1 = MockLoadCombination(id="load_combination1")
        load_combination2 = MockLoadCombination(id="load_combination2")
        model.add_load_combination(load_combination1)
        model.add_load_combination(load_combination2)

        # Remove the first load combination
        result = model.remove_load_combination("load_combination1")
        assert result is True
        assert len(model.load_combinations) == 1
        assert model.load_combinations[0].id == "load_combination2"

        # Try to remove a non-existent load combination
        result = model.remove_load_combination("non_existent")
        assert result is False
        assert len(model.load_combinations) == 1

    def test_get_load_combination(self):
        """Test getting a load combination by ID."""
        model = StructuralModel(id="test_model")
        load_combination1 = MockLoadCombination(id="load_combination1")
        load_combination2 = MockLoadCombination(id="load_combination2")
        model.add_load_combination(load_combination1)
        model.add_load_combination(load_combination2)

        # Get existing load combination
        result = model.get_load_combination("load_combination1")
        assert result == load_combination1

        # Try to get a non-existent load combination
        result = model.get_load_combination("non_existent")
        assert result is None

    def test_add_result(self):
        """Test adding a result to the model."""
        model = StructuralModel(id="test_model")
        result = MockResult(id="result1")
        model.add_result(result)
        assert len(model.results) == 1
        assert model.results[0] == result

    def test_add_duplicate_result(self):
        """Test that adding a duplicate result raises an error."""
        model = StructuralModel(id="test_model")
        result = MockResult(id="result1")
        model.add_result(result)

        # Try to add a result with the same ID
        duplicate_result = MockResult(id="result1")
        with pytest.raises(ValueError):
            model.add_result(duplicate_result)

    def test_remove_result(self):
        """Test removing a result from the model."""
        model = StructuralModel(id="test_model")
        result1 = MockResult(id="result1")
        result2 = MockResult(id="result2")
        model.add_result(result1)
        model.add_result(result2)

        # Remove the first result
        result = model.remove_result("result1")
        assert result is True
        assert len(model.results) == 1
        assert model.results[0].id == "result2"

        # Try to remove a non-existent result
        result = model.remove_result("non_existent")
        assert result is False
        assert len(model.results) == 1

    def test_get_result(self):
        """Test getting a result by ID."""
        model = StructuralModel(id="test_model")
        result1 = MockResult(id="result1")
        result2 = MockResult(id="result2")
        model.add_result(result1)
        model.add_result(result2)

        # Get existing result
        result = model.get_result("result1")
        assert result == result1

        # Try to get a non-existent result
        result = model.get_result("non_existent")
        assert result is None
