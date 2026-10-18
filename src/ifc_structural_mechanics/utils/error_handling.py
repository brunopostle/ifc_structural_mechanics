"""
Error handling utilities for the IFC structural analysis extension.

This module defines custom exception classes, error pattern matching,
error classification, and error handling utilities used throughout
the structural analysis extension.
"""

from enum import Enum, auto
from typing import Any, Dict, Iterable, List, Optional


class ErrorSeverity(Enum):
    """
    Enumeration of error severity levels.

    These levels are used to classify the severity of errors and warnings
    in the structural analysis extension.
    """

    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()

    def __str__(self) -> str:
        """Return the lowercase string representation of the severity."""
        return self.name.lower()


class EntityType(Enum):
    """
    Enumeration of entity types for error mapping.

    These entity types represent different components in the structural
    analysis domain that can be referenced in error messages.
    """

    NODE = "node"
    ELEMENT = "element"
    MATERIAL = "material"
    SECTION = "section"
    BOUNDARY = "boundary"
    LOAD = "load"
    MODEL = "model"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        """Return the string representation of the entity type."""
        return self.value


class StructuralAnalysisError(Exception):
    """
    Base exception class for all errors in the structural analysis extension.

    This is the parent class for all custom exceptions in the structural
    analysis extension, allowing for more specific error handling.
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        code: Optional[str] = None,
        ifc_guids: Iterable[str] = (),
        **kwargs,
    ):
        """
        Initialize a StructuralAnalysisError.

        Args:
            message (str): Error message.
            severity (ErrorSeverity): Severity level of the error.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            entity_id (Optional[str]): ID of the entity in the analysis software.
            domain_id (Optional[str]): ID of the entity in the domain model.
            code (Optional[str]): Its code in ``utils.messages.KINDS``, such as
                ``E-SUP-002``, which users can look up in ``docs/messages.md``.
            ifc_guids (Iterable[str]): The IFC GlobalIds of the entities it is
                about, for a viewer to highlight; a wrapper passes them on.
            **kwargs: Additional context information to include in the error.
        """
        self.code = code
        self.ifc_guids = list(dict.fromkeys(g for g in ifc_guids if g and g != "?"))
        self.message = message
        self.severity = severity
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.domain_id = domain_id
        self.context = kwargs
        super().__init__(message)

    def __str__(self) -> str:
        """
        Return a string representation of the error.

        Returns:
            str: Error message with context information.
        """
        code = f"[{self.code}] " if self.code else ""
        parts = [f"{self.severity}: {code}{self.message}"]

        # Add entity information if available
        if self.entity_type:
            entity_info = f"{self.entity_type}"
            if self.entity_id:
                entity_info += f" {self.entity_id}"
            if self.domain_id:
                entity_info += f" (domain ID: {self.domain_id})"
            parts.append(f"Entity: {entity_info}")

        # Add additional context information
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"Context: {context_str}")

        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the error to a dictionary representation.

        Returns:
            Dict[str, Any]: Dictionary containing error information.
        """
        return {
            "code": self.code,
            "message": self.message,
            "ifc_guids": self.ifc_guids,
            "severity": str(self.severity),
            "entity_type": str(self.entity_type) if self.entity_type else None,
            "entity_id": self.entity_id,
            "domain_id": self.domain_id,
            "context": self.context,
        }


class ModelExtractionError(StructuralAnalysisError):
    """
    Error raised during model extraction from IFC.

    This exception is raised when there are issues extracting
    structural model information from IFC entities.
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize a ModelExtractionError.

        Args:
            message (str): Error message.
            severity (ErrorSeverity): Severity level of the error.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            entity_id (Optional[str]): ID of the entity in the analysis software.
            domain_id (Optional[str]): ID of the entity in the domain model.
            **kwargs: Additional context information to include in the error.
        """
        super().__init__(
            message,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            domain_id=domain_id,
            **kwargs,
        )


class MeshingError(StructuralAnalysisError):
    """
    Error raised during meshing operations.

    This exception is raised when there are issues generating
    or processing finite element meshes.
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize a MeshingError.

        Args:
            message (str): Error message.
            severity (ErrorSeverity): Severity level of the error.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            entity_id (Optional[str]): ID of the entity in the analysis software.
            domain_id (Optional[str]): ID of the entity in the domain model.
            **kwargs: Additional context information to include in the error.
        """
        super().__init__(
            message,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            domain_id=domain_id,
            **kwargs,
        )


class AnalysisError(StructuralAnalysisError):
    """
    Error raised during structural analysis.

    This exception is raised when there are issues during
    the execution of the structural analysis.
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        error_details: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ):
        """
        Initialize an AnalysisError.

        Args:
            message (str): Error message.
            severity (ErrorSeverity): Severity level of the error.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            entity_id (Optional[str]): ID of the entity in the analysis software.
            domain_id (Optional[str]): ID of the entity in the domain model.
            error_details (Optional[List[Dict[str, Any]]]): Detailed information about the error.
            **kwargs: Additional context information to include in the error.
        """
        # Make sure error_details is explicitly included in the context
        context = kwargs.copy()
        if error_details is not None:
            context["error_details"] = error_details

        super().__init__(
            message,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            domain_id=domain_id,
            **context,
        )
        self.error_details = error_details or []  # Default to empty list


class ResultProcessingError(StructuralAnalysisError):
    """
    Error raised during result processing.

    This exception is raised when there are issues processing
    or converting analysis results.
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[str] = None,
        domain_id: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize a ResultProcessingError.

        Args:
            message (str): Error message.
            severity (ErrorSeverity): Severity level of the error.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            entity_id (Optional[str]): ID of the entity in the analysis software.
            domain_id (Optional[str]): ID of the entity in the domain model.
            **kwargs: Additional context information to include in the error.
        """
        super().__init__(
            message,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            domain_id=domain_id,
            **kwargs,
        )
