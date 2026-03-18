"""
Error handling utilities for the IFC structural analysis extension.

This module defines custom exception classes, error pattern matching,
error classification, and error handling utilities used throughout
the structural analysis extension.
"""

import re
from contextlib import contextmanager
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple


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
            **kwargs: Additional context information to include in the error.
        """
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
        parts = [f"{self.severity}: {self.message}"]

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
            "message": self.message,
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


# Error Pattern Matching System


class ErrorPattern:
    """
    Defines a pattern for matching errors in output text.

    This class encapsulates a regular expression pattern for matching
    error messages, along with metadata about the error type, severity,
    and entity type.
    """

    def __init__(
        self,
        pattern: str,
        entity_type: Optional[EntityType] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        description: Optional[str] = None,
    ):
        """
        Initialize an ErrorPattern.

        Args:
            pattern (str): Regular expression pattern for matching errors.
            entity_type (Optional[EntityType]): Type of entity related to the error.
            severity (ErrorSeverity): Severity level of the error.
            description (Optional[str]): Human-readable description of the pattern.
        """
        self.pattern = pattern
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.entity_type = entity_type
        self.severity = severity
        self.description = description or "No description"

    def match(self, text: str) -> Optional[re.Match]:
        """
        Match the pattern against a text string.

        Args:
            text (str): The text to match against.

        Returns:
            Optional[re.Match]: Match object if the pattern matches, None otherwise.
        """
        return self.regex.search(text)


class ErrorPatternRegistry:
    """
    Registry of error patterns for different software and analysis types.

    This class provides a central registry for error patterns used
    throughout the structural analysis extension.
    """

    # Common error patterns that apply to most structural analysis software
    COMMON_ERROR_PATTERNS = [
        # Convergence errors
        ErrorPattern(
            r"(?i).*no convergence.*",
            severity=ErrorSeverity.CRITICAL,
            description="Convergence failure",
        ),
        ErrorPattern(
            r"(?i).*divergence.*step\s+(\d+)",
            severity=ErrorSeverity.CRITICAL,
            description="Solution divergence at a specific step",
        ),
        ErrorPattern(
            r"(?i).*solver\s+failed\s+to\s+converge",
            severity=ErrorSeverity.CRITICAL,
            description="Solver convergence failure",
        ),
        # Stiffness/matrix errors
        ErrorPattern(
            r"(?i).*zero\s+pivot.*",
            severity=ErrorSeverity.CRITICAL,
            description="Zero pivot in matrix solution",
        ),
        ErrorPattern(
            r"(?i).*singular\s+matrix.*",
            severity=ErrorSeverity.CRITICAL,
            description="Singular matrix detected",
        ),
        ErrorPattern(
            r"(?i).*ill-conditioned\s+system.*",
            severity=ErrorSeverity.CRITICAL,
            description="Ill-conditioned system of equations",
        ),
        # General errors
        ErrorPattern(
            r"(?i).*error\s+in\s+step\s+(\d+)",
            severity=ErrorSeverity.CRITICAL,
            description="Error in specific analysis step",
        ),
        ErrorPattern(
            r"(?i).*fatal\s+error.*",
            severity=ErrorSeverity.CRITICAL,
            description="Fatal error",
        ),
        ErrorPattern(
            r"(?i)^error:.*",
            severity=ErrorSeverity.CRITICAL,
            description="Error message",
        ),
        ErrorPattern(
            r"(?i).*analysis\s+failed.*",
            severity=ErrorSeverity.CRITICAL,
            description="Analysis failure",
        ),
    ]

    # Common warning patterns
    COMMON_WARNING_PATTERNS = [
        # General warnings
        ErrorPattern(
            r"(?i)^warning:.*",
            severity=ErrorSeverity.WARNING,
            description="Warning message",
        ),
        ErrorPattern(
            r"(?i).*warnung:.*",
            severity=ErrorSeverity.WARNING,
            description="Warning message (German)",
        ),
        # Convergence warnings
        ErrorPattern(
            r"(?i).*slow\s+convergence.*",
            severity=ErrorSeverity.WARNING,
            description="Slow convergence",
        ),
        ErrorPattern(
            r"(?i).*convergence\s+problems.*",
            severity=ErrorSeverity.WARNING,
            description="Convergence problems",
        ),
        # Analysis warnings
        ErrorPattern(
            r"(?i).*not\s+recommended.*",
            severity=ErrorSeverity.WARNING,
            description="Not recommended usage",
        ),
        ErrorPattern(
            r"(?i).*user\s+caution.*",
            severity=ErrorSeverity.WARNING,
            description="User caution advised",
        ),
    ]

    # CalculiX-specific error patterns
    CALCULIX_ERROR_PATTERNS = [
        # Negative jacobian errors
        ErrorPattern(
            r"(?i).*negative jacobian.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.CRITICAL,
            description="Negative jacobian in element",
        ),
        ErrorPattern(
            r"(?i).*zero jacobian.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.CRITICAL,
            description="Zero jacobian in element",
        ),
        # Material errors
        ErrorPattern(
            r"(?i).*material\s+[\"']?(\w+)[\"']?\s+.*undefined",
            entity_type=EntityType.MATERIAL,
            severity=ErrorSeverity.CRITICAL,
            description="Undefined material",
        ),
        ErrorPattern(
            r"(?i).*material\s+[\"']?(\w+)[\"']?\s+.*nonexistent",
            entity_type=EntityType.MATERIAL,
            severity=ErrorSeverity.CRITICAL,
            description="Nonexistent material",
        ),
        ErrorPattern(
            r"(?i).*material\s+property.*missing",
            severity=ErrorSeverity.CRITICAL,
            description="Missing material property",
        ),
        # Node/element errors
        ErrorPattern(
            r"(?i).*node\s+(\d+).*not connected",
            entity_type=EntityType.NODE,
            severity=ErrorSeverity.CRITICAL,
            description="Node not connected",
        ),
        ErrorPattern(
            r"(?i).*node\s+(\d+).*nonexistent",
            entity_type=EntityType.NODE,
            severity=ErrorSeverity.CRITICAL,
            description="Nonexistent node",
        ),
        ErrorPattern(
            r"(?i).*element\s+(\d+).*nonexistent",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.CRITICAL,
            description="Nonexistent element",
        ),
        # Section errors
        ErrorPattern(
            r"(?i).*section\s+(\w+).*undefined",
            entity_type=EntityType.SECTION,
            severity=ErrorSeverity.CRITICAL,
            description="Undefined section",
        ),
        ErrorPattern(
            r"(?i).*section\s+(\w+).*nonexistent",
            entity_type=EntityType.SECTION,
            severity=ErrorSeverity.CRITICAL,
            description="Nonexistent section",
        ),
    ]

    # CalculiX-specific warning patterns
    CALCULIX_WARNING_PATTERNS = [
        # Element quality warnings
        ErrorPattern(
            r"(?i).*large\s+displacement.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.WARNING,
            description="Large displacement in element",
        ),
        ErrorPattern(
            r"(?i).*small\s+pivot.*",
            severity=ErrorSeverity.WARNING,
            description="Small pivot in matrix solution",
        ),
        ErrorPattern(
            r"(?i).*distorted\s+element.*(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.WARNING,
            description="Distorted element",
        ),
        ErrorPattern(
            r"(?i).*high\s+aspect\s+ratio.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.WARNING,
            description="High aspect ratio in element",
        ),
        ErrorPattern(
            r"(?i).*unreasonable\s+deformation.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.WARNING,
            description="Unreasonable deformation in element",
        ),
    ]

    def __init__(self):
        """Initialize the error pattern registry with default patterns."""
        self._patterns = {
            "common": {
                "error": self.COMMON_ERROR_PATTERNS,
                "warning": self.COMMON_WARNING_PATTERNS,
            },
            "calculix": {
                "error": self.CALCULIX_ERROR_PATTERNS,
                "warning": self.CALCULIX_WARNING_PATTERNS,
            },
        }

    def get_patterns(
        self, software: str = "common", pattern_type: Optional[str] = None
    ) -> List[ErrorPattern]:
        """
        Get error patterns for a specific software and type.

        Args:
            software (str): Software identifier (e.g., "calculix", "common").
            pattern_type (Optional[str]): Type of patterns to retrieve
                ("error", "warning", or None for both).

        Returns:
            List[ErrorPattern]: List of error patterns.
        """
        if software not in self._patterns:
            return []

        if pattern_type is None:
            # Return all patterns for the software
            all_patterns = []
            for patterns in self._patterns[software].values():
                all_patterns.extend(patterns)
            return all_patterns

        if pattern_type not in self._patterns[software]:
            return []

        return self._patterns[software][pattern_type]

    def add_pattern(
        self,
        pattern: ErrorPattern,
        software: str = "common",
        pattern_type: str = "error",
    ) -> None:
        """
        Add a new error pattern to the registry.

        Args:
            pattern (ErrorPattern): Error pattern to add.
            software (str): Software identifier to associate with the pattern.
            pattern_type (str): Type of pattern ("error" or "warning").
        """
        if software not in self._patterns:
            self._patterns[software] = {"error": [], "warning": []}

        if pattern_type not in self._patterns[software]:
            self._patterns[software][pattern_type] = []

        self._patterns[software][pattern_type].append(pattern)

    def remove_pattern(
        self,
        pattern_str: str,
        software: str = "common",
        pattern_type: Optional[str] = None,
    ) -> bool:
        """
        Remove an error pattern from the registry.

        Args:
            pattern_str (str): String representation of the pattern to remove.
            software (str): Software identifier associated with the pattern.
            pattern_type (Optional[str]): Type of pattern ("error", "warning",
                or None to search both).

        Returns:
            bool: True if the pattern was removed, False otherwise.
        """
        if software not in self._patterns:
            return False

        if pattern_type is not None:
            if pattern_type not in self._patterns[software]:
                return False

            for i, pattern in enumerate(self._patterns[software][pattern_type]):
                if pattern.pattern == pattern_str:
                    self._patterns[software][pattern_type].pop(i)
                    return True
        else:
            # Search both error and warning patterns
            for ptype in self._patterns[software]:
                for i, pattern in enumerate(self._patterns[software][ptype]):
                    if pattern.pattern == pattern_str:
                        self._patterns[software][ptype].pop(i)
                        return True

        return False


class ErrorDetector:
    """
    Detects and classifies errors in output text.

    This class uses the ErrorPatternRegistry to detect and classify
    errors in output text from structural analysis software.
    """

    def __init__(
        self,
        registry: Optional[ErrorPatternRegistry] = None,
        mapper: Optional[Any] = None,
    ):
        """
        Initialize an ErrorDetector.

        Args:
            registry (Optional[ErrorPatternRegistry]): Error pattern registry to use.
                If None, a new registry with default patterns is created.
            mapper (Optional[Any]): Entity mapper for mapping analysis IDs to domain IDs.
        """
        self.registry = registry or ErrorPatternRegistry()
        self.mapper = mapper

    def detect_errors(
        self, output_text: str, software: str = "calculix"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detect errors and warnings in output text.

        Args:
            output_text (str): Output text to analyze.
            software (str): Software identifier for pattern selection.

        Returns:
            Dict[str, List[Dict[str, Any]]]: Dictionary with 'errors' and 'warnings' lists,
                each containing dictionaries with message, severity, entity_type,
                entity_id, and domain_id details.
        """
        if not output_text:
            return {"errors": [], "warnings": []}

        errors = []
        warnings = []

        # Process each line for error patterns
        for line in output_text.splitlines():
            # Check error patterns
            for pattern in self.registry.get_patterns(software, "error"):
                match = pattern.match(line)
                if match:
                    error_info = self._create_error_info(line, pattern, match)
                    errors.append(error_info)
                    break  # Stop after finding the first matching pattern

            # Check warning patterns
            for pattern in self.registry.get_patterns(software, "warning"):
                match = pattern.match(line)
                if match:
                    warning_info = self._create_error_info(line, pattern, match)
                    warnings.append(warning_info)
                    break  # Stop after finding the first matching pattern

        # Check for overall analysis status
        if software == "calculix":
            self._check_calculix_completion_status(output_text, errors)

        return {"errors": errors, "warnings": warnings}

    def _create_error_info(
        self, line: str, pattern: ErrorPattern, match: re.Match
    ) -> Dict[str, Any]:
        """
        Create an error information dictionary from a pattern match.

        Args:
            line (str): The line of text that matched.
            pattern (ErrorPattern): The pattern that matched.
            match (re.Match): The match object.

        Returns:
            Dict[str, Any]: Dictionary with error information.
        """
        error_info = {
            "message": line.strip(),
            "severity": str(pattern.severity),
            "entity_type": str(pattern.entity_type) if pattern.entity_type else None,
            "entity_id": None,
            "domain_id": None,
        }

        # Extract entity ID if available
        if pattern.entity_type and match.groups():
            try:
                entity_id = match.group(1)
                # Convert to integer for node and element types
                if pattern.entity_type in [EntityType.NODE, EntityType.ELEMENT]:
                    entity_id = int(entity_id)

                error_info["entity_id"] = entity_id

                # Map to domain entity if mapper is available
                if self.mapper and pattern.entity_type:
                    try:
                        domain_id = self.mapper.get_domain_entity_id(
                            entity_id, str(pattern.entity_type)
                        )
                        error_info["domain_id"] = domain_id
                    except (KeyError, ValueError):
                        # Entity not found in mapper
                        pass
            except (IndexError, ValueError):
                # Failed to extract ID
                pass

        return error_info

    def _check_calculix_completion_status(
        self, output_text: str, errors: List[Dict[str, Any]]
    ) -> None:
        """
        Check CalculiX output for completion status indicators.

        Args:
            output_text (str): CalculiX output text.
            errors (List[Dict[str, Any]]): List of detected errors to update.
        """
        # Look for specific analysis status indicators
        if (
            "ANALYSIS COMPLETED" not in output_text
            and "ANALYSIS TERMINATED SUCCESSFULLY" not in output_text
        ):
            # Check if there's an indication of how the analysis ended
            if (
                "ANALYSIS INTERRUPTED" in output_text
                or "ANALYSIS ABORTED" in output_text
            ):
                errors.append(
                    {
                        "message": "Analysis was interrupted or aborted before completion",
                        "severity": str(ErrorSeverity.CRITICAL),
                        "entity_type": None,
                        "entity_id": None,
                        "domain_id": None,
                    }
                )

    def check_convergence(
        self, output_text: str, software: str = "calculix"
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the analysis converged successfully.

        Args:
            output_text (str): Output text to analyze.
            software (str): Software identifier for pattern selection.

        Returns:
            Tuple[bool, Optional[str]]: (converged, reason), where converged is True if
                the analysis converged, and reason is a message explaining the result.
        """
        if software == "calculix":
            # Check for positive completion indicators
            if (
                "ANALYSIS COMPLETED" in output_text
                or "ANALYSIS TERMINATED SUCCESSFULLY" in output_text
            ):
                return True, "Analysis completed successfully"

            # Check for explicit convergence indicators
            if "SOLUTION CONVERGED" in output_text or "STEP COMPLETED" in output_text:
                return True, "Solution converged"

            # Check for non-convergence indicators
            if "NO CONVERGENCE" in output_text or "DIVERGENCE" in output_text:
                return False, "Analysis failed to converge"

            # Check for interruption or abortion
            if (
                "ANALYSIS INTERRUPTED" in output_text
                or "ANALYSIS ABORTED" in output_text
            ):
                return False, "Analysis was interrupted or aborted"

        # Check for other error indicators
        errors = self.detect_errors(output_text, software)["errors"]
        if errors:
            error_messages = "; ".join([error["message"] for error in errors[:3]])
            return False, f"Analysis failed with errors: {error_messages}"

        # Default case - inconclusive
        return False, "Unable to determine if analysis converged"

    def generate_error_summary(
        self, parse_result: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """
        Generate a human-readable summary of errors and warnings.

        Args:
            parse_result (Dict[str, List[Dict[str, Any]]]): The result from detect_errors.

        Returns:
            str: A human-readable summary of errors and warnings.
        """
        errors = parse_result.get("errors", [])
        warnings = parse_result.get("warnings", [])

        summary = []

        if errors:
            summary.append(f"Found {len(errors)} critical issues:")
            for i, error in enumerate(errors, 1):
                entity_info = ""
                if error.get("entity_type") and error.get("entity_id"):
                    entity_info = f" in {error['entity_type']} {error['entity_id']}"
                    if error.get("domain_id"):
                        entity_info += f" (domain ID: {error['domain_id']})"

                summary.append(f"  {i}. {error['message']}{entity_info}")

        if warnings:
            summary.append(f"\nFound {len(warnings)} warnings:")
            for i, warning in enumerate(warnings, 1):
                entity_info = ""
                if warning.get("entity_type") and warning.get("entity_id"):
                    entity_info = f" in {warning['entity_type']} {warning['entity_id']}"
                    if warning.get("domain_id"):
                        entity_info += f" (domain ID: {warning['domain_id']})"

                summary.append(f"  {i}. {warning['message']}{entity_info}")

        if not errors and not warnings:
            summary.append("No errors or warnings detected in the analysis output.")

        return "\n".join(summary)

    def set_mapper(self, mapper: Any) -> None:
        """
        Set the entity mapper.

        Args:
            mapper (Any): Entity mapper for mapping analysis IDs to domain IDs.
        """
        self.mapper = mapper


@contextmanager
def error_context(context: Dict[str, Any]):
    """
    Context manager for error handling with additional context.

    This context manager captures exceptions and re-raises them
    with additional context information.

    Args:
        context (Dict[str, Any]): Context information to add to exceptions.

    Yields:
        None

    Raises:
        StructuralAnalysisError: The original exception with added context.
    """
    try:
        yield
    except StructuralAnalysisError as e:
        # Add context to existing structural analysis error
        e.context.update(context)
        raise
    except Exception as e:
        # Wrap other exceptions in StructuralAnalysisError
        raise StructuralAnalysisError(str(e), **context) from e
