"""Shared fixtures for ccxquery tests."""

import pytest


SAMPLE_INP = """\
** CalculiX Input File
** Generated for testing
**
*NODE
1, 0.000000e+00, 0.000000e+00, 0.000000e+00
2, 1.000000e+00, 0.000000e+00, 0.000000e+00
3, 2.000000e+00, 0.000000e+00, 0.000000e+00
4, 3.000000e+00, 0.000000e+00, 0.000000e+00
5, 4.000000e+00, 0.000000e+00, 0.000000e+00

*ELEMENT, TYPE=B31, ELSET=ELSET_B31
1, 1, 2
2, 2, 3
3, 3, 4
4, 4, 5

*ELSET, ELSET=MEMBER_M1
1, 2, 3, 4

*NSET, NSET=FIX_LEFT
1

*NSET, NSET=FIX_RIGHT, GENERATE
4, 5, 1

*ELSET, ELSET=ALL_ELEMENTS, GENERATE
1, 4, 1

*MATERIAL, NAME=STEEL
*ELASTIC
2.1e+11, 0.3
*DENSITY
7850.0

*BEAM SECTION, ELSET=MEMBER_M1, MATERIAL=STEEL, SECTION=RECT
0.3, 0.3
0.0, 0.0, 1.0

*BOUNDARY
FIX_LEFT, 1, 6
FIX_RIGHT, 1, 3

*STEP
*STATIC
1.0, 1.0, 1e-5, 1.0

*CLOAD
5, 2, -10000.0

*DLOAD
1, P1, 500.0

*NODE FILE
U
*EL FILE
S, E
*END STEP
"""


SAMPLE_FRD = """\
    1C
    1UUSER
    1UDATE              01.january.2025
    1UPGM               CalculiX
    2C                             5                                     1
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 1.00000E+00 0.00000E+00 0.00000E+00
 -1         3 2.00000E+00 0.00000E+00 0.00000E+00
 -1         4 3.00000E+00 0.00000E+00 0.00000E+00
 -1         5 4.00000E+00 0.00000E+00 0.00000E+00
 -3
    1PSTEP                         1           1           1
  100CL  101 1.000000000           5                     0    1           1
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1         1 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 1.50000E-04 -5.00000E-04 0.00000E+00
 -1         3 2.80000E-04-1.20000E-03 0.00000E+00
 -1         4 3.50000E-04-2.10000E-03 0.00000E+00
 -1         5 4.00000E-04-3.20000E-03 0.00000E+00
 -3
    1PSTEP                         2           1           1
  100CL  101 1.000000000           5                     0    1           1
 -4  STRESS      6    1
 -5  SXX         1    4    1    1
 -5  SYY         1    4    2    2
 -5  SZZ         1    4    3    3
 -5  SXY         1    4    1    2
 -5  SYZ         1    4    2    3
 -5  SZX         1    4    3    1
 -1         1 1.00000E+06 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 8.00000E+05 0.00000E+00 0.00000E+00 5.00000E+04 0.00000E+00 0.00000E+00
 -1         3 5.00000E+05 0.00000E+00 0.00000E+00 3.00000E+04 0.00000E+00 0.00000E+00
 -1         4 2.00000E+05 0.00000E+00 0.00000E+00 1.00000E+04 0.00000E+00 0.00000E+00
 -1         5 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -3
 9999
"""


SAMPLE_DAT = """\

                        S T E P       1


                                INCREMENT     1


 forces (fx,fy,fz) for set FIX_LEFT and target time  0.1000000E+01

          1  5.00000E+03  1.00000E+04  0.00000E+00

 total force (fx,fy,fz) for set FIX_LEFT and time  0.1000000E+01

        5.00000E+03  1.00000E+04  0.00000E+00

 forces (fx,fy,fz) for set FIX_RIGHT and target time  0.1000000E+01

          4 -2.50000E+03 -5.00000E+03  0.00000E+00
          5 -2.50000E+03 -5.00000E+03  0.00000E+00

 total force (fx,fy,fz) for set FIX_RIGHT and time  0.1000000E+01

       -5.00000E+03 -1.00000E+04  0.00000E+00

 job finished

"""


SAMPLE_DAT_NO_CONVERGENCE = """\

                        S T E P       1

 best solution and target values are not in the same proportion

 *ERROR: no convergence

"""


SAMPLE_DAT_MINIMAL = """\

                        S T E P       1

"""


@pytest.fixture
def inp_file(tmp_path):
    """Create a sample .inp file."""
    p = tmp_path / "test.inp"
    p.write_text(SAMPLE_INP)
    return str(p)


@pytest.fixture
def frd_file(tmp_path):
    """Create a sample .frd file."""
    p = tmp_path / "test.frd"
    p.write_text(SAMPLE_FRD)
    return str(p)


@pytest.fixture
def dat_file(tmp_path):
    """Create a sample .dat file."""
    p = tmp_path / "test.dat"
    p.write_text(SAMPLE_DAT)
    return str(p)


@pytest.fixture
def analysis_dir(tmp_path):
    """Create a directory with all three sibling files (.inp, .frd, .dat)."""
    (tmp_path / "analysis.inp").write_text(SAMPLE_INP)
    (tmp_path / "analysis.frd").write_text(SAMPLE_FRD)
    (tmp_path / "analysis.dat").write_text(SAMPLE_DAT)
    return tmp_path
