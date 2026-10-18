"""
Unit tests for the error handling utilities module.

This module contains tests for the error handling utilities in the
utils.error_handling module.
"""

import unittest

# Import the module under test
from ifc_structural_mechanics.utils.error_handling import (
    AnalysisError,
    MeshingError,
    ModelExtractionError,
    ResultProcessingError,
    StructuralAnalysisError,
)


class TestStructuralAnalysisError(unittest.TestCase):
    """Test the StructuralAnalysisError class."""

    def test_init(self):
        """Test initialization of StructuralAnalysisError."""
        error = StructuralAnalysisError("Test error")
        self.assertEqual(error.message, "Test error")
        self.assertIsNone(error.code)
        self.assertEqual(error.ifc_guids, [])
        self.assertEqual(error.context, {})

        error = StructuralAnalysisError(
            "Test error",
            code="E-SUP-002",
            ifc_guids=["a", "?", "a", "b"],
            source="test_module",
        )
        self.assertEqual(error.code, "E-SUP-002")
        self.assertEqual(error.ifc_guids, ["a", "b"])
        self.assertEqual(error.context, {"source": "test_module"})

    def test_str(self):
        """Test string representation of StructuralAnalysisError."""
        error = StructuralAnalysisError("Test error")
        self.assertEqual(str(error), "error: Test error")

        error = StructuralAnalysisError("Test error", code="E-SUP-002")
        self.assertEqual(str(error), "error: [E-SUP-002] Test error")

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
            "Test error", code="E-SUP-002", ifc_guids=["a"], source="test_module"
        )
        self.assertEqual(
            error.to_dict(),
            {
                "code": "E-SUP-002",
                "message": "Test error",
                "ifc_guids": ["a"],
                "context": {"source": "test_module"},
            },
        )


class TestDerivedErrors(unittest.TestCase):
    """Test the derived error classes."""

    def test_stage_errors(self):
        """Each stage's error is a StructuralAnalysisError with its code."""
        for kind in (ModelExtractionError, MeshingError, ResultProcessingError):
            error = kind("Failed", code="E-IFC-001", ifc_guids=["g"])
            self.assertIsInstance(error, StructuralAnalysisError)
            self.assertEqual(error.message, "Failed")
            self.assertEqual(error.code, "E-IFC-001")
            self.assertEqual(error.ifc_guids, ["g"])

    def test_analysis_error(self):
        """Test AnalysisError."""
        error_details = [
            {"message": "Error 1", "severity": "critical"},
            {"message": "Error 2", "severity": "warning"},
        ]
        error = AnalysisError(
            "Analysis failed",
            code="E-SOL-001",
            error_details=error_details,
        )
        self.assertEqual(error.message, "Analysis failed")
        self.assertEqual(error.code, "E-SOL-001")
        self.assertEqual(error.error_details, error_details)
        self.assertIn("error_details", error.context)
        self.assertEqual(AnalysisError("Analysis failed").error_details, [])
