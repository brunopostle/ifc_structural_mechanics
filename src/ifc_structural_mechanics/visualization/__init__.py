"""
Pictures of analysis results.

``output_files.AnalysisOutput`` reads an output directory of ``analyze_ifc()``
(no PyVista needed); ``plot.render()`` and ``plot.plot()`` draw it with PyVista
(``pip install 'ifc_structural_mechanics[viz]'``). ``ifc-analysis plot`` is the
command for it.
"""

from .output_files import AnalysisOutput

__all__ = ["AnalysisOutput"]
