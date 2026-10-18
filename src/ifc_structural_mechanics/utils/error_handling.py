"""
Error handling utilities for the IFC structural analysis extension.

This module defines the custom exception classes used throughout the
structural analysis extension, one per stage of the pipeline.
"""

from typing import Any, Dict, Iterable, List, Optional


class StructuralAnalysisError(Exception):
    """
    Base exception class for all errors in the structural analysis extension.

    This is the parent class for all custom exceptions in the structural
    analysis extension, allowing for more specific error handling.
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        ifc_guids: Iterable[str] = (),
        **kwargs,
    ):
        """
        Initialize a StructuralAnalysisError.

        Args:
            message (str): Error message.
            code (Optional[str]): Its code in ``utils.messages.KINDS``, such as
                ``E-SUP-002``, which users can look up in ``docs/messages.md``.
            ifc_guids (Iterable[str]): The IFC GlobalIds of the entities it is
                about, for a viewer to highlight; a wrapper passes them on.
            **kwargs: Additional context information to include in the error.
        """
        self.code = code
        self.ifc_guids = list(dict.fromkeys(g for g in ifc_guids if g and g != "?"))
        self.message = message
        self.context = kwargs
        super().__init__(message)

    def __str__(self) -> str:
        """
        Return a string representation of the error.

        Returns:
            str: Error message with context information.
        """
        code = f"[{self.code}] " if self.code else ""
        parts = [f"error: {code}{self.message}"]
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
            "context": self.context,
        }


class ModelExtractionError(StructuralAnalysisError):
    """
    Error raised during model extraction from IFC.

    This exception is raised when there are issues extracting
    structural model information from IFC entities.
    """


class MeshingError(StructuralAnalysisError):
    """
    Error raised during meshing operations.

    This exception is raised when there are issues generating
    or processing finite element meshes.
    """


class AnalysisError(StructuralAnalysisError):
    """
    Error raised during structural analysis.

    This exception is raised when there are issues during
    the execution of the structural analysis.
    """

    def __init__(
        self,
        message: str,
        error_details: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ):
        """
        Initialize an AnalysisError.

        Args:
            message (str): Error message.
            error_details (Optional[List[Dict[str, Any]]]): Detailed information about the error.
            **kwargs: ``code``, ``ifc_guids`` and context, as for
                ``StructuralAnalysisError``.
        """
        if error_details is not None:
            kwargs["error_details"] = error_details
        super().__init__(message, **kwargs)
        self.error_details = error_details or []


class ResultProcessingError(StructuralAnalysisError):
    """
    Error raised during result processing.

    This exception is raised when there are issues processing
    or converting analysis results.
    """
