"""
Tests for the CalculiX results parser module.
"""

import pytest

from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.domain.result import (
    DisplacementResult,
    ReactionForceResult,
    StrainResult,
    StressResult,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel


class TestResultsParser:
    """Tests for the ResultsParser class."""

    @pytest.fixture
    def mock_domain_model(self):
        """Create a mock domain model for testing."""
        return StructuralModel(id="test_model")

    @pytest.fixture
    def mock_frd_file(self, tmp_path):
        """Create a mock FRD file for testing."""
        # Format based on modern CalculiX output (v2.20+)
        frd_content = """    1C
    1UNODE
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1         1 1.0000e+00 2.0000e+00 3.0000e+00 0.1000e+00 0.2000e+00 0.3000e+00
 -1         2 4.0000e+00 5.0000e+00 6.0000e+00 0.4000e+00 0.5000e+00 0.6000e+00
 -3
 -4  STRESS      6    1
 -5  SXX         1    4    1    1
 -5  SYY         1    4    2    2
 -5  SZZ         1    4    3    3
 -5  SXY         1    4    1    2
 -5  SYZ         1    4    2    3
 -5  SZX         1    4    3    1
 -1         1 10.00e+00 20.00e+00 30.00e+00 5.00e+00 6.00e+00 7.00e+00
 -1         2 11.00e+00 21.00e+00 31.00e+00 5.10e+00 6.10e+00 7.10e+00
 -3
 -4  TOSTRAIN    6    1
 -5  EXX         1    4    1    1
 -5  EYY         1    4    2    2
 -5  EZZ         1    4    3    3
 -5  EXY         1    4    1    2
 -5  EYZ         1    4    2    3
 -5  EZX         1    4    3    1
 -1         1 0.001e+00 0.002e+00 0.003e+00 0.0005e+00 0.0006e+00 0.0007e+00
 -1         2 0.0011e+00 0.0021e+00 0.0031e+00 0.00051e+00 0.00061e+00 0.00071e+00
 -3
    3C"""
        frd_file = tmp_path / "test.frd"
        frd_file.write_text(frd_content)
        return str(frd_file)

    @pytest.fixture
    def mock_dat_file(self, tmp_path):
        """Create a mock DAT file for testing."""
        dat_content = """forces (fx,fy,fz) and moments (mx,my,mz) for all nodes

        node       fx          fy          fz          mx          my          mz
         1   -10.000E+00  -20.000E+00  -30.000E+00  -1.000E+00  -2.000E+00  -3.000E+00
         2   -40.000E+00  -50.000E+00  -60.000E+00  -4.000E+00  -5.000E+00  -6.000E+00

total forces (fx,fy,fz) and moments (mx,my,mz)
       -50.000E+00  -70.000E+00  -90.000E+00  -5.000E+00  -7.000E+00  -9.000E+00"""
        dat_file = tmp_path / "test.dat"
        dat_file.write_text(dat_content)
        return str(dat_file)

    def test_init(self, mock_domain_model):
        """Test initialization."""
        parser = ResultsParser(domain_model=mock_domain_model)
        assert parser.domain_model == mock_domain_model

    def test_parse_displacements(self, mock_frd_file):
        """Test parsing displacement results."""
        parser = ResultsParser()
        results = parser.parse_displacements(mock_frd_file)

        assert len(results) == 2
        assert isinstance(results[0], DisplacementResult)
        assert results[0].reference_element == "1"
        assert results[0].get_translations() == [1.0, 2.0, 3.0]
        assert results[0].get_rotations() == [0.1, 0.2, 0.3]

        assert results[1].reference_element == "2"
        assert results[1].get_translations() == [4.0, 5.0, 6.0]
        assert results[1].get_rotations() == [0.4, 0.5, 0.6]

    def test_parse_stresses(self, mock_frd_file):
        """Test parsing stress results."""
        parser = ResultsParser()
        results = parser.parse_stresses(mock_frd_file)

        assert len(results) == 2
        assert isinstance(results[0], StressResult)
        assert results[0].reference_element == "1"
        assert results[0].get_value("sxx") == 10.0
        assert results[0].get_value("syy") == 20.0
        assert results[0].get_value("szz") == 30.0
        assert results[0].get_value("sxy") == 5.0
        assert results[0].get_value("syz") == 6.0
        assert results[0].get_value("sxz") == 7.0
        # Note: Principal stresses (s1, s2, s3) are not in the modern FRD format

    def test_parse_strains(self, mock_frd_file):
        """Test parsing strain results."""
        parser = ResultsParser()
        results = parser.parse_strains(mock_frd_file)

        assert len(results) == 2
        assert isinstance(results[0], StrainResult)
        assert results[0].reference_element == "1"
        assert results[0].get_value("exx") == 0.001
        assert results[0].get_value("eyy") == 0.002
        assert results[0].get_value("ezz") == 0.003
        assert results[0].get_value("exy") == 0.0005
        assert results[0].get_value("eyz") == 0.0006
        assert results[0].get_value("exz") == 0.0007
        # Note: Principal strains (e1, e2, e3) are not in the modern FRD format

    def test_parse_reactions(self, mock_dat_file):
        """Test parsing reaction force results."""
        parser = ResultsParser()
        results = parser.parse_reactions(mock_dat_file)

        assert len(results) == 2
        assert isinstance(results[0], ReactionForceResult)
        assert results[0].reference_element == "1"
        assert results[0].get_forces() == [-10.0, -20.0, -30.0]
        assert results[0].get_moments() == [-1.0, -2.0, -3.0]

        assert results[1].reference_element == "2"
        assert results[1].get_forces() == [-40.0, -50.0, -60.0]
        assert results[1].get_moments() == [-4.0, -5.0, -6.0]

    def test_parse_results(self, mock_frd_file, mock_dat_file):
        """Test parsing all results."""
        parser = ResultsParser()
        result_files = {"results": mock_frd_file, "data": mock_dat_file}

        parsed_results = parser.parse_results(result_files)

        assert "displacement" in parsed_results
        assert "stress" in parsed_results
        assert "strain" in parsed_results
        assert "reaction" in parsed_results

        assert len(parsed_results["displacement"]) == 2
        assert len(parsed_results["stress"]) == 2
        assert len(parsed_results["strain"]) == 2
        assert len(parsed_results["reaction"]) == 2

    def test_map_results_to_domain(
        self, mock_domain_model, mock_frd_file, mock_dat_file
    ):
        """Test mapping results to domain model."""
        parser = ResultsParser(domain_model=mock_domain_model)
        result_files = {"results": mock_frd_file, "data": mock_dat_file}

        parser.parse_results(result_files)

        # Check that results were added to the domain model
        assert len(mock_domain_model.results) > 0


class TestParseBeamSectionForces:
    """Tests for ResultsParser.parse_beam_section_forces()."""

    @pytest.fixture
    def dat_with_sf(self, tmp_path):
        """DAT file with a single beam section forces block.

        No blank line between the block banner and the column-header row —
        that matches the format the parser handles (a blank line would
        prematurely close the block).
        """
        content = """\
 STEP 1

 beam section forces and moments
  element no.  integ. pt. no.     N          T         Mf1        Mf2        Vf1        Vf2
       1           1       1.000E+03  0.000E+00  5.000E+03  2.000E+03  1.500E+03  5.000E+02
       1           2       1.100E+03  0.000E+00  4.800E+03  1.900E+03  1.400E+03  4.800E+02
       2           1       2.000E+03  1.000E+02  6.000E+03  3.000E+03  2.000E+03  6.000E+02

"""
        p = tmp_path / "analysis.dat"
        p.write_text(content)
        return str(p)

    @pytest.fixture
    def dat_multi_step(self, tmp_path):
        """DAT file with two steps, each with a beam section forces block."""
        content = """\
 STEP 1

 beam section forces and moments
  element no.  integ. pt. no.     N          T         Mf1        Mf2        Vf1        Vf2
       1           1       1.000E+03  0.000E+00  5.000E+03  0.000E+00  0.000E+00  0.000E+00

 STEP 2

 beam section forces and moments
  element no.  integ. pt. no.     N          T         Mf1        Mf2        Vf1        Vf2
       1           1       2.000E+03  0.000E+00  8.000E+03  0.000E+00  0.000E+00  0.000E+00

"""
        p = tmp_path / "analysis.dat"
        p.write_text(content)
        return str(p)

    def test_returns_list_of_dicts(self, dat_with_sf):
        parser = ResultsParser(domain_model=StructuralModel(id="m"))
        results = parser.parse_beam_section_forces(dat_with_sf)
        assert isinstance(results, list)
        assert len(results) == 3

    def test_element_and_integ_pt_parsed(self, dat_with_sf):
        parser = ResultsParser(domain_model=StructuralModel(id="m"))
        results = parser.parse_beam_section_forces(dat_with_sf)
        assert results[0]["element_id"] == 1
        assert results[0]["integ_pt"] == 1
        assert results[1]["element_id"] == 1
        assert results[1]["integ_pt"] == 2
        assert results[2]["element_id"] == 2

    def test_force_values_parsed(self, dat_with_sf):
        parser = ResultsParser(domain_model=StructuralModel(id="m"))
        results = parser.parse_beam_section_forces(dat_with_sf)
        r = results[0]
        assert abs(r["N"] - 1000.0) < 1.0
        assert abs(r["Mf1"] - 5000.0) < 1.0
        assert abs(r["Mf2"] - 2000.0) < 1.0

    def test_nonexistent_file_returns_empty(self, tmp_path):
        parser = ResultsParser(domain_model=StructuralModel(id="m"))
        results = parser.parse_beam_section_forces(str(tmp_path / "missing.dat"))
        assert results == []

    def test_multi_step_produces_separate_records(self, dat_multi_step):
        parser = ResultsParser(domain_model=StructuralModel(id="m"))
        results = parser.parse_beam_section_forces(dat_multi_step)
        assert len(results) == 2
        # Step indices should differ
        step_indices = {r.get("step_index", r.get("load_case")) for r in results}
        assert len(step_indices) == 2
