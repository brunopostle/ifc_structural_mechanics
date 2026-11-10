"""The IFC files we write for tests are valid IFC, EXPRESS rules included.

The example models are other tools' and stay as they are (``portal_01``
breaks IfcDerivedUnit WR1, ``W-IFC-006``); ours should not need the library
to tolerate anything.
"""

import glob
import os

import ifcopenshell
import ifcopenshell.validate
import pytest

TEST_DATA = os.path.join(os.path.dirname(__file__), "..", "test_data")
FILES = sorted(glob.glob(os.path.join(TEST_DATA, "**", "*.ifc"), recursive=True))


def test_there_are_files():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_valid(path):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(path), logger, express_rules=True)
    assert [str(s["message"]).splitlines()[0] for s in logger.statements] == []
