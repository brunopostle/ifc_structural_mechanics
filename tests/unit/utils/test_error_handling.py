"""
Unit tests for the error handling utilities module.

This module contains tests for the error handling utilities in the
utils.error_handling module.
"""

import unittest

# Import the module under test
from ifc_structural_mechanics.utils.error_handling import (
    AnalysisError,
    EntityType,
    ErrorSeverity,
    MeshingError,
    ModelExtractionError,
    ResultProcessingError,
    StructuralAnalysisError,
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
