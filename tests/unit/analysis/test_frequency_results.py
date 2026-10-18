"""Reading and reporting the modes of a modal analysis (lon)."""

import pytest

from ifc_structural_mechanics.analysis.plausibility import plausibility_warnings
from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.domain.result import DisplacementResult
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter
from ifc_structural_mechanics.utils.error_handling import ResultProcessingError

# What CalculiX 2.21 and 2.23 print for a *FREQUENCY step (cantilever_01,
# two modes kept; the same in both versions)
DAT = """
                        S T E P       1


     E I G E N V A L U E   O U T P U T

 MODE NO    EIGENVALUE                       FREQUENCY
                                     REAL PART            IMAGINARY PART
                           (RAD/TIME)      (CYCLES/TIME     (RAD/TIME)

      1   0.1357128E+05   0.1164958E+03   0.1854089E+02   0.0000000E+00
      2   0.5353897E+05   0.2313849E+03   0.3682605E+02   0.0000000E+00

     P A R T I C I P A T I O N   F A C T O R S

MODE NO.   X-COMPONENT     Y-COMPONENT     Z-COMPONENT     X-ROTATION      Y-ROTATION      Z-ROTATION

      1   0.3361027E-16  -0.1071859E+01   0.6308402E-12   0.4669551E-13  -0.1373131E-11  -0.2336635E+01
      2   0.9622077E-14   0.5951130E-12   0.1070753E+01  -0.4471250E-14  -0.2340622E+01   0.1347994E-11

     E F F E C T I V E   M O D A L   M A S S

MODE NO.   X-COMPONENT     Y-COMPONENT     Z-COMPONENT     X-ROTATION      Y-ROTATION      Z-ROTATION

      1   0.1129650E-32   0.1148882E+01   0.3979594E-24   0.2180471E-26   0.1885490E-23   0.5459861E+01
      2   0.9258437E-28   0.3541595E-24   0.1146512E+01   0.1999207E-28   0.5478509E+01   0.1817089E-23
TOTAL     0.9258550E-28   0.1148882E+01   0.1146512E+01   0.2199463E-26   0.5478509E+01   0.5459861E+01

     T O T A L   E F F E C T I V E   M A S S

           X-COMPONENT     Y-COMPONENT     Z-COMPONENT     X-ROTATION      Y-ROTATION      Z-ROTATION

          0.1839259E+01   0.1843111E+01   0.1852741E+01   0.3081481E-01   0.5640575E+01   0.5622144E+01


     F R A C T I O N   O F   T O T A L S

           X-COMPONENT     Y-COMPONENT     Z-COMPONENT     X-ROTATION      Y-ROTATION      Z-ROTATION

          0.5033800E-28   0.6233379E+00   0.6188191E+00   0.7137723E-25   0.9712671E+00   0.9711389E+00
"""

# A mechanism: CalculiX gives a negative eigenvalue an imaginary frequency
MECHANISM_DAT = """
     E I G E N V A L U E   O U T P U T

 MODE NO    EIGENVALUE                       FREQUENCY
                                     REAL PART            IMAGINARY PART
                           (RAD/TIME)      (CYCLES/TIME     (RAD/TIME)

      1  -0.5273819E-06   0.0000000E+00   0.0000000E+00   0.7262106E-03
      2   0.2962458E-06   0.5442846E-03   0.8662559E-04   0.0000000E+00
      3   0.1357128E+05   0.1164958E+03   0.1854089E+02   0.0000000E+00
"""


@pytest.fixture
def modal(tmp_path):
    path = tmp_path / "freq.dat"
    path.write_text(DAT)
    return ResultsParser().parse_frequencies(str(path))


def test_frequencies_are_read(modal):
    first, second = modal["modes"]
    assert first["mode"] == 1
    assert first["eigenvalue"] == pytest.approx(13571.28)
    assert first["angular_frequency"] == pytest.approx(116.4958)
    assert first["frequency"] == pytest.approx(18.54089)
    assert second["frequency"] == pytest.approx(36.82605)


def test_participation_and_effective_mass_are_read(modal):
    first = modal["modes"][0]
    assert first["participation"][1] == pytest.approx(-1.071859)
    assert first["effective_mass"][1] == pytest.approx(1.148882)
    assert first["effective_mass"][5] == pytest.approx(5.459861)
    assert modal["total_effective_mass"][2] == pytest.approx(1.852741)


def test_a_static_result_file_has_no_modes(tmp_path):
    path = tmp_path / "static.dat"
    path.write_text(" displacements (vx,vy,vz) for set NALL and time  1.\n")
    assert ResultsParser().parse_frequencies(str(path)) == {}


def test_shapes_are_named_after_their_modes(modal):
    parsed = {"displacement": []}
    for step in (1, 2):
        shape = DisplacementResult(reference_element=7)
        shape.set_translations([0.0, float(step), 0.0])
        shape.add_metadata("load_case", f"step_{step}")
        parsed["displacement"].append(shape)
    ResultsParser._take_mode_shapes(parsed, modal["modes"])
    assert parsed["displacement"] == []
    assert [r.metadata["load_case"] for r in parsed["mode_shapes"]] == [
        "Mode 1",
        "Mode 2",
    ]


def _exported(modal):
    return ResultsExporter(
        domain_model=StructuralModel(id="test"),
        parsed_results={"displacement": [], "modal": modal},
        analysis_type="modal",
    )._build()


def test_modes_in_results_json(modal):
    data = _exported(modal)
    assert data["analysis_type"] == "modal"
    assert data["load_cases"] == []
    assert data["units"]["frequency"] == "Hz" and data["units"]["mass"] == "kg"
    first = data["modal"]["modes"][0]
    assert first["frequency_Hz"] == pytest.approx(18.54089)
    assert first["period_s"] == pytest.approx(1 / 18.54089)
    assert first["mechanism"] is False
    assert first["effective_mass_kg"]["y"] == pytest.approx(1.148882)
    assert first["effective_mass_moment_kgm2"]["rz"] == pytest.approx(5.459861)
    assert first["participation_factors"]["rz"] == pytest.approx(-2.336635)
    fraction = data["modal"]["mass_fraction"]
    assert fraction["y"] == pytest.approx(1.148882 / 1.843111)
    assert fraction["z"] == pytest.approx(1.146512 / 1.852741)


def test_no_modes_is_an_error():
    with pytest.raises(ResultProcessingError, match="no modes") as raised:
        _exported({})
    assert raised.value.code == "E-RES-007"


def test_mechanisms_are_marked_and_reported(tmp_path):
    path = tmp_path / "free.dat"
    path.write_text(MECHANISM_DAT)
    modal = ResultsParser().parse_frequencies(str(path))
    data = _exported(modal)
    marks = [m["mechanism"] for m in data["modal"]["modes"]]
    assert marks == [True, True, False]
    assert data["modal"]["modes"][0]["period_s"] is None
    (warned,) = [
        w
        for w in plausibility_warnings(data, StructuralModel(id="test"))
        if w["code"] == "W-CHK-003"
    ]
    assert "2 of the 3 modes" in warned["message"]


def test_a_sound_model_has_no_mechanism_warning(modal):
    data = _exported(modal)
    warnings = plausibility_warnings(data, StructuralModel(id="test"))
    assert not [w for w in warnings if w["code"] == "W-CHK-003"]
