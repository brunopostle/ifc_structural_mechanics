"""The JSON Schema of results.json (94g.13.1).

Every results.json a test writes is validated against it (the
``results_match_their_schema`` fixture in ``tests/conftest.py``); these check
the schema itself and the example in the documentation.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from ifc_structural_mechanics.export import ResultsExporter, results_schema
from tests.helpers import check_results_schema

EXAMPLE = Path(__file__).parents[3] / "docs" / "examples" / "beam_01_results.json"


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text())


def test_schema_is_a_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(results_schema())


def test_schema_is_of_the_version_written():
    schema = results_schema()
    assert schema["properties"]["schema_version"]["const"] == (
        ResultsExporter.SCHEMA_VERSION
    )
    assert schema["$id"].endswith("/" + ResultsExporter.SCHEMA_VERSION)


def test_example_in_the_documentation_matches(example):
    check_results_schema(example)


def test_key_it_does_not_describe_is_an_error(example):
    """So a key added to the results without the schema fails the tests."""
    for path in ((), ("members", 0), ("supports", 0), ("global_reactions", "total")):
        changed = copy.deepcopy(example)
        target = changed
        for key in path:
            target = target[key]
        target["something_new"] = 1.0
        with pytest.raises(AssertionError, match="something_new"):
            check_results_schema(changed)


def test_names_of_load_cases_are_free(example):
    """A load case or combination may be called anything."""
    changed = copy.deepcopy(example)
    member = changed["members"][0]
    member["by_load_case"]["Any name at all"] = member["by_load_case"].pop("Dead")
    check_results_schema(changed)


def test_value_of_the_wrong_kind_is_an_error(example):
    changed = copy.deepcopy(example)
    changed["supports"][0]["moments"] = "guessed"
    with pytest.raises(AssertionError, match="moments"):
        check_results_schema(changed)
