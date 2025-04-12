"""
Unit tests for the error handling utilities module.

This module contains tests for the error handling utilities in the
utils.error_handling module.
"""

import re
import unittest
from unittest.mock import MagicMock, patch

# Import the module under test
from ifc_structural_mechanics.utils.error_handling import (
    ErrorSeverity,
    EntityType,
    StructuralAnalysisError,
    ModelExtractionError,
    MeshingError,
    AnalysisError,
    ResultProcessingError,
    ErrorPattern,
    ErrorPatternRegistry,
    ErrorDetector,
    EntityErrorMapper,
    error_context,
    format_error_message,
    ErrorCollector,
    traceable_errors,
)


class TestErrorSeverity(unittest.TestCase):
    """Test the ErrorSeverity enumeration."""

    def test_string_representation(self):
        """Test the string representation of error severities."""
        self.assertEqual(str(ErrorSeverity.INFO), "info")
        self.assertEqual(str(ErrorSeverity.WARNING), "warning")
        self.assertEqual(str(ErrorSeverity.ERROR), "error")
        self.assertEqual(str(ErrorSeverity.CRITICAL), "critical")


class TestEntityType(unittest.TestCase):
    """Test the EntityType enumeration."""

    def test_string_representation(self):
        """Test the string representation of entity types."""
        self.assertEqual(str(EntityType.NODE), "node")
        self.assertEqual(str(EntityType.ELEMENT), "element")
        self.assertEqual(str(EntityType.MATERIAL), "material")
        self.assertEqual(str(EntityType.SECTION), "section")
        self.assertEqual(str(EntityType.BOUNDARY), "boundary")
        self.assertEqual(str(EntityType.LOAD), "load")
        self.assertEqual(str(EntityType.MODEL), "model")
        self.assertEqual(str(EntityType.UNKNOWN), "unknown")


class TestStructuralAnalysisError(unittest.TestCase):
    """Test the StructuralAnalysisError class."""

    def test_init(self):
        """Test initialization of StructuralAnalysisError."""
        # Basic initialization
        error = StructuralAnalysisError("Test error")
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.severity, ErrorSeverity.ERROR)
        self.assertIsNone(error.entity_type)
        self.assertIsNone(error.entity_id)
        self.assertIsNone(error.domain_id)
        self.assertEqual(error.context, {})

        # Initialization with all parameters
        error = StructuralAnalysisError(
            "Test error",
            severity=ErrorSeverity.CRITICAL,
            entity_type=EntityType.NODE,
            entity_id="123",
            domain_id="N123",
            source="test_module",
        )
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(error.entity_type, EntityType.NODE)
        self.assertEqual(error.entity_id, "123")
        self.assertEqual(error.domain_id, "N123")
        self.assertEqual(error.context, {"source": "test_module"})

    def test_str(self):
        """Test string representation of StructuralAnalysisError."""
        # Basic error
        error = StructuralAnalysisError("Test error")
        self.assertEqual(str(error), "error: Test error")

        # Error with entity information
        error = StructuralAnalysisError(
            "Test error",
            entity_type=EntityType.NODE,
            entity_id="123",
            domain_id="N123",
        )
        self.assertEqual(
            str(error), "error: Test error | Entity: node 123 (domain ID: N123)"
        )

        # Error with context
        error = StructuralAnalysisError(
            "Test error",
            source="test_module",
            line=42,
        )
        self.assertEqual(
            str(error), "error: Test error | Context: source=test_module, line=42"
        )

    def test_to_dict(self):
        """Test conversion of StructuralAnalysisError to dictionary."""
        error = StructuralAnalysisError(
            "Test error",
            severity=ErrorSeverity.CRITICAL,
            entity_type=EntityType.NODE,
            entity_id="123",
            domain_id="N123",
            source="test_module",
        )
        error_dict = error.to_dict()

        self.assertEqual(error_dict["message"], "Test error")
        self.assertEqual(error_dict["severity"], "critical")
        self.assertEqual(error_dict["entity_type"], "node")
        self.assertEqual(error_dict["entity_id"], "123")
        self.assertEqual(error_dict["domain_id"], "N123")
        self.assertEqual(error_dict["context"], {"source": "test_module"})


class TestDerivedErrors(unittest.TestCase):
    """Test the derived error classes."""

    def test_model_extraction_error(self):
        """Test ModelExtractionError."""
        error = ModelExtractionError(
            "Failed to extract model",
            severity=ErrorSeverity.CRITICAL,
            entity_type=EntityType.MODEL,
        )
        self.assertEqual(error.message, "Failed to extract model")
        self.assertEqual(error.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(error.entity_type, EntityType.MODEL)

    def test_meshing_error(self):
        """Test MeshingError."""
        error = MeshingError(
            "Failed to generate mesh",
            severity=ErrorSeverity.CRITICAL,
            entity_type=EntityType.ELEMENT,
            entity_id="E123",
        )
        self.assertEqual(error.message, "Failed to generate mesh")
        self.assertEqual(error.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(error.entity_type, EntityType.ELEMENT)
        self.assertEqual(error.entity_id, "E123")

    def test_analysis_error(self):
        """Test AnalysisError."""
        error_details = [
            {"message": "Error 1", "severity": "critical"},
            {"message": "Error 2", "severity": "warning"},
        ]
        error = AnalysisError(
            "Analysis failed",
            severity=ErrorSeverity.CRITICAL,
            error_details=error_details,
        )
        self.assertEqual(error.message, "Analysis failed")
        self.assertEqual(error.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(error.error_details, error_details)
        self.assertIn("error_details", error.context)

    def test_result_processing_error(self):
        """Test ResultProcessingError."""
        error = ResultProcessingError(
            "Failed to process results",
            severity=ErrorSeverity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="123",
        )
        self.assertEqual(error.message, "Failed to process results")
        self.assertEqual(error.severity, ErrorSeverity.ERROR)
        self.assertEqual(error.entity_type, EntityType.NODE)
        self.assertEqual(error.entity_id, "123")


class TestErrorPattern(unittest.TestCase):
    """Test the ErrorPattern class."""

    def test_init(self):
        """Test initialization of ErrorPattern."""
        pattern = ErrorPattern(
            r"(?i).*negative jacobian.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
            severity=ErrorSeverity.CRITICAL,
            description="Negative jacobian in element",
        )
        self.assertEqual(pattern.pattern, r"(?i).*negative jacobian.*element\s+(\d+)")
        self.assertIsInstance(pattern.regex, re.Pattern)
        self.assertEqual(pattern.entity_type, EntityType.ELEMENT)
        self.assertEqual(pattern.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(pattern.description, "Negative jacobian in element")

    def test_match(self):
        """Test matching of ErrorPattern."""
        # Pattern with capture group
        pattern = ErrorPattern(
            r"(?i).*negative jacobian.*element\s+(\d+)",
            entity_type=EntityType.ELEMENT,
        )

        # Successful match
        match = pattern.match("Error: negative jacobian detected in element 123")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "123")

        # No match
        match = pattern.match("No errors detected")
        self.assertIsNone(match)

        # Pattern without capture group
        pattern = ErrorPattern(r"(?i).*singular\s+matrix.*")

        # Successful match
        match = pattern.match("Warning: singular matrix detected")
        self.assertIsNotNone(match)

        # No match
        match = pattern.match("No errors detected")
        self.assertIsNone(match)


class TestErrorPatternRegistry(unittest.TestCase):
    """Test the ErrorPatternRegistry class."""

    def test_init(self):
        """Test initialization of ErrorPatternRegistry."""
        registry = ErrorPatternRegistry()

        # Check default patterns
        self.assertGreater(len(registry._patterns["common"]["error"]), 0)
        self.assertGreater(len(registry._patterns["common"]["warning"]), 0)
        self.assertGreater(len(registry._patterns["calculix"]["error"]), 0)
        self.assertGreater(len(registry._patterns["calculix"]["warning"]), 0)

    def test_get_patterns(self):
        """Test getting patterns from the registry."""
        registry = ErrorPatternRegistry()

        # Get all patterns for a software
        all_calculix_patterns = registry.get_patterns("calculix")
        self.assertGreater(len(all_calculix_patterns), 0)

        # Get specific pattern type
        calculix_errors = registry.get_patterns("calculix", "error")
        self.assertGreater(len(calculix_errors), 0)
        self.assertTrue(all(isinstance(p, ErrorPattern) for p in calculix_errors))

        # Get patterns for non-existent software
        nonexistent_patterns = registry.get_patterns("nonexistent")
        self.assertEqual(len(nonexistent_patterns), 0)

        # Get patterns for non-existent pattern type
        nonexistent_type = registry.get_patterns("calculix", "nonexistent")
        self.assertEqual(len(nonexistent_type), 0)

    def test_add_pattern(self):
        """Test adding a pattern to the registry."""
        registry = ErrorPatternRegistry()

        # Add a new pattern to existing software and type
        new_pattern = ErrorPattern(
            r"(?i).*test error.*",
            severity=ErrorSeverity.ERROR,
            description="Test error pattern",
        )

        initial_count = len(registry.get_patterns("calculix", "error"))
        registry.add_pattern(new_pattern, "calculix", "error")
        new_count = len(registry.get_patterns("calculix", "error"))

        self.assertEqual(new_count, initial_count + 1)

        # Add a pattern to a new software
        registry.add_pattern(new_pattern, "new_software", "error")
        self.assertEqual(len(registry.get_patterns("new_software", "error")), 1)

        # Add a pattern to a new pattern type
        registry.add_pattern(new_pattern, "calculix", "new_type")
        self.assertEqual(len(registry.get_patterns("calculix", "new_type")), 1)

    def test_remove_pattern(self):
        """Test removing a pattern from the registry."""
        registry = ErrorPatternRegistry()

        # Add a new pattern
        test_pattern = ErrorPattern(
            r"(?i).*test pattern.*",
            description="Test pattern for removal",
        )
        registry.add_pattern(test_pattern, "calculix", "error")

        # Remove the pattern
        removed = registry.remove_pattern(r"(?i).*test pattern.*", "calculix", "error")
        self.assertTrue(removed)

        # Try to remove a non-existent pattern
        removed = registry.remove_pattern(
            r"(?i).*nonexistent pattern.*", "calculix", "error"
        )
        self.assertFalse(removed)

        # Try to remove from a non-existent software
        removed = registry.remove_pattern(
            r"(?i).*test pattern.*", "nonexistent", "error"
        )
        self.assertFalse(removed)

        # Try to remove from a non-existent pattern type
        removed = registry.remove_pattern(
            r"(?i).*test pattern.*", "calculix", "nonexistent"
        )
        self.assertFalse(removed)

        # Add pattern to both error and warning types and remove without specifying type
        registry.add_pattern(test_pattern, "calculix", "error")
        registry.add_pattern(test_pattern, "calculix", "warning")

        removed = registry.remove_pattern(r"(?i).*test pattern.*", "calculix")
        self.assertTrue(removed)


class TestErrorDetector(unittest.TestCase):
    """Test the ErrorDetector class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_mapper = MagicMock()
        self.mock_mapper.get_domain_entity_id = MagicMock(return_value="D123")

        self.detector = ErrorDetector(mapper=self.mock_mapper)

    def test_detect_errors(self):
        """Test detecting errors in output text."""
        # Create test output with errors and warnings
        output_text = """
        Start of analysis
        ERROR: negative jacobian detected in element 123
        Warning: high aspect ratio in element 456
        Analysis completed with errors
        """

        # Detect errors and warnings
        result = self.detector.detect_errors(output_text, "calculix")

        # Check errors
        self.assertGreater(len(result["errors"]), 0)
        error = result["errors"][0]
        self.assertIn("negative jacobian", error["message"])
        self.assertEqual(error["severity"], "critical")
        self.assertEqual(error["entity_type"], "element")
        self.assertEqual(error["entity_id"], 123)

        # Check warnings
        self.assertGreater(len(result["warnings"]), 0)
        warning = result["warnings"][0]
        self.assertIn("high aspect ratio", warning["message"])
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["entity_type"], "element")
        self.assertEqual(warning["entity_id"], 456)

        # Test with empty output
        result = self.detector.detect_errors("")
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(len(result["warnings"]), 0)

    def test_check_convergence(self):
        """Test checking convergence status."""
        # Successful completion
        output_text = "ANALYSIS COMPLETED SUCCESSFULLY"
        converged, reason = self.detector.check_convergence(output_text, "calculix")
        self.assertTrue(converged)
        self.assertIn("completed successfully", reason)

        # Convergence indicator
        output_text = "SOLUTION CONVERGED"
        converged, reason = self.detector.check_convergence(output_text, "calculix")
        self.assertTrue(converged)
        self.assertIn("converged", reason)

        # Non-convergence
        output_text = "NO CONVERGENCE AFTER 100 ITERATIONS"
        converged, reason = self.detector.check_convergence(output_text, "calculix")
        self.assertFalse(converged)
        self.assertIn("failed to converge", reason)

        #
