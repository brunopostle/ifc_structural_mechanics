"""
Base entity class for IFC structural analysis domain models.

This module provides a base class that defines common functionality for all
domain entities in the structural analysis model, including validation,
property access, and serialization.
"""

import uuid
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar, Union

T = TypeVar("T", bound="DomainEntity")


class DomainEntity:
    """
    Base class for all domain entities in the structural analysis model.

    This class provides common functionality for all domain entities, including:
    - Unique identifier management
    - Entity type specification
    - Property validation
    - Metadata management
    - Serialization to dictionary format

    All domain entities should inherit from this class to ensure consistent
    behavior and reduce code duplication across the domain model.
    """

    def __init__(
        self,
        id: Optional[str] = None,
        entity_type: Optional[str] = None,
        allow_validation_bypass: bool = False,
    ) -> None:
        """
        Initialize a domain entity with a unique identifier and type.

        Args:
            id: Unique identifier for the entity. If None, a UUID will be generated.
            entity_type: Type of the entity (e.g., "member", "connection", "load").
                If None, the class name will be used.
            allow_validation_bypass: If True, allows bypassing validation for testing
                or incremental construction.

        Raises:
            ValueError: If validation fails and allow_validation_bypass is False.
        """
        # Set ID (generate UUID if not provided)
        self.id = id if id is not None else str(uuid.uuid4())

        # Set entity type (use class name if not provided)
        self.entity_type = (
            entity_type if entity_type is not None else self.__class__.__name__.lower()
        )

        # Initialize metadata dictionary for additional properties
        self.metadata: Dict[str, Any] = {}

        # Initialize validation bypass flag
        self._allow_validation_bypass = allow_validation_bypass

        # Perform validation unless bypassed
        if not allow_validation_bypass:
            self.validate()

    def validate(self) -> bool:
        """
        Validate the entity properties.

        This method should be overridden by subclasses to implement specific
        validation logic. The base implementation validates the ID.

        Returns:
            True if the entity is valid.

        Raises:
            ValueError: If validation fails.
        """
        self._validate_id()
        return True

    def _validate_id(self) -> None:
        """
        Validate the entity ID.

        Raises:
            ValueError: If the ID is not a valid string.
        """
        if self.id is None:
            raise ValueError("Entity ID cannot be None")
        if not isinstance(self.id, str):
            raise ValueError(f"Entity ID must be a string, got {type(self.id)}")
        if self.id == "":
            raise ValueError("Entity ID cannot be empty")

    def _validate_property(
        self,
        name: str,
        value: Any,
        allow_none: bool = False,
        validator: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """
        Validate a property value.

        Args:
            name: Name of the property for error messages.
            value: Value to validate.
            allow_none: If True, allows None value.
            validator: Optional function that validates the value and returns True
                if valid, or raises ValueError if invalid.

        Raises:
            ValueError: If validation fails.
        """
        # Check if None is allowed
        if value is None and not allow_none:
            raise ValueError(f"{name} cannot be None")

        # Skip further validation if None and allowed
        if value is None:
            return

        # Apply custom validator if provided
        if validator is not None:
            validator(value)

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata to the entity.

        Args:
            key: Key for the metadata.
            value: Value to store.
        """
        self.metadata[key] = value

    def get_metadata(self, key: str) -> Any:
        """
        Get metadata from the entity.

        Args:
            key: Key for the metadata.

        Returns:
            The metadata value.

        Raises:
            KeyError: If the key is not found.
        """
        if key not in self.metadata:
            raise KeyError(f"Metadata key '{key}' not found")
        return self.metadata[key]

    def has_metadata(self, key: str) -> bool:
        """
        Check if metadata key exists.

        Args:
            key: Key to check.

        Returns:
            True if the key exists, False otherwise.
        """
        return key in self.metadata

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the entity to a dictionary representation.

        Returns:
            Dictionary representation of the entity.
        """
        result = {"id": self.id, "entity_type": self.entity_type}

        # Include metadata if not empty
        if self.metadata:
            result["metadata"] = self.metadata.copy()

        return result

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """
        Create an entity from a dictionary representation.

        Args:
            data: Dictionary representation of the entity.

        Returns:
            A new instance of the entity.

        Raises:
            ValueError: If the dictionary is missing required fields.
        """
        if "id" not in data:
            raise ValueError("Dictionary must contain 'id' field")

        # Create instance with ID from dictionary and bypass validation initially
        instance = cls(id=data["id"], allow_validation_bypass=True)

        # Add metadata if present
        if "metadata" in data and isinstance(data["metadata"], dict):
            for key, value in data["metadata"].items():
                instance.add_metadata(key, value)

        # Now validate the fully configured instance
        instance.validate()

        return instance


class DomainEntityCollection(Generic[T]):
    """
    Collection of domain entities of the same type.

    This class provides a container for managing multiple domain entities
    of the same type, with methods for adding, removing, and querying entities.

    This class can be used as a base for implementation of collection classes
    like LoadGroup, LoadCombination, etc.
    """

    def __init__(self, entity_type: Optional[str] = None):
        """
        Initialize a domain entity collection.

        Args:
            entity_type: Optional type name for the entities in the collection.
        """
        self.entity_type = entity_type
        self.entities: List[T] = []

    def add(self, entity: T) -> None:
        """
        Add an entity to the collection.

        Args:
            entity: Entity to add.

        Raises:
            ValueError: If the entity is None or already exists in the collection.
        """
        if entity is None:
            raise ValueError("Cannot add None entity to collection")

        if entity in self.entities:
            raise ValueError(
                f"Entity with ID '{entity.id}' already exists in collection"
            )

        self.entities.append(entity)

    def remove(self, entity: Union[T, str]) -> bool:
        """
        Remove an entity from the collection.

        Args:
            entity: Entity or entity ID to remove.

        Returns:
            True if the entity was removed, False if not found.
        """
        entity_id = entity if isinstance(entity, str) else entity.id

        for i, e in enumerate(self.entities):
            if e.id == entity_id:
                self.entities.pop(i)
                return True

        return False

    def get_by_id(self, entity_id: str) -> Optional[T]:
        """
        Get an entity by its ID.

        Args:
            entity_id: ID of the entity to get.

        Returns:
            The entity if found, None otherwise.
        """
        for entity in self.entities:
            if entity.id == entity_id:
                return entity

        return None

    def clear(self) -> None:
        """Remove all entities from the collection."""
        self.entities.clear()

    def __len__(self) -> int:
        """
        Get the number of entities in the collection.

        Returns:
            Number of entities.
        """
        return len(self.entities)

    def as_dict_list(self) -> List[Dict[str, Any]]:
        """
        Convert all entities in the collection to a list of dictionaries.

        Returns:
            List of dictionary representations of the entities.
        """
        return [entity.as_dict() for entity in self.entities]
