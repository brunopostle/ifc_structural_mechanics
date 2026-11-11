"""Results from a Windows build of CalculiX are read as those from Linux.

A Windows build's C library writes three exponent digits, so FRD numbers run
together even when positive (``3.20000E+0000.00000E+000-1.17290E-001``). The
node block was once read by 12-character columns, and crashed on the first
negative coordinate ("could not convert string to float: '2-1.17290E-0'");
the tokeniser read ``E+0001.5`` as an exponent of 0001. Reported by Robert
with CalculiX 2.23 from calculix/CalculiX-Windows on his Gerber beam
(tests/test_data/gerber_two_span_beam.ifc), 2026-11-11.
"""

import json
import os

from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from ifc_structural_mechanics.analysis.results_parser import (
    ResultsParser,
    _parse_frd_data_line,
)
from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from tests.helpers import as_written_on_windows

GERBER = os.path.join("tests", "test_data", "gerber_two_span_beam.ifc")


def test_robert_s_line():
    node, values = _parse_frd_data_line(
        " -1        273.20000E+0000.00000E+000-1.17290E-001\n"
    )
    assert node == "27"
    assert values == [3.2, 0.0, -0.11729]


def test_positive_numbers_that_run_together():
    """``E+0001.5`` is an exponent of 000 and the next number, not E+0001."""
    _, values = _parse_frd_data_line(
        " -1         13.20000E+0001.50000E+001-2.00000E-0021.00000E+000\n"
    )
    assert values == [3.2, 15.0, -0.02, 1.0]


def _analyse(tmp_path, name, monkeypatch=None):
    if monkeypatch is not None:
        collect = CalculixRunner._collect_result_files

        def collect_as_on_windows(self):
            files = collect(self)
            as_written_on_windows(files["results"])
            return files

        monkeypatch.setattr(
            CalculixRunner, "_collect_result_files", collect_as_on_windows
        )
    output = str(tmp_path / name)
    result = analyze_ifc(ifc_path=GERBER, output_dir=output)
    assert result["status"] == "success", result.get("errors")
    with open(os.path.join(output, "results.json")) as fh:
        data = json.load(fh)
    data.pop("run")
    return data, os.path.join(output, "analysis.frd")


def test_a_windows_frd_gives_the_same_results(tmp_path, monkeypatch):
    linux, linux_frd = _analyse(tmp_path, "linux")
    windows, windows_frd = _analyse(tmp_path, "windows", monkeypatch)
    with open(windows_frd) as fh:
        assert "E+000" in fh.read()
    assert json.dumps(windows, sort_keys=True) == json.dumps(linux, sort_keys=True)
    parser = ResultsParser()
    assert parser.parse_node_coordinates(windows_frd) == parser.parse_node_coordinates(
        linux_frd
    )
