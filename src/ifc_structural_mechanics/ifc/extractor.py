"""
Main extractor coordinator for IFC structural analysis models.

This module contains the Extractor class which coordinates the extraction of
structural analysis models from IFC files, using specialized extractors for
different parts of the model.
"""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Union

import ifcopenshell
import ifcopenshell.util.unit

from ..domain.structural_model import StructuralModel
from ..utils.error_handling import ModelExtractionError
from ..utils.messages import warning
from ..utils.units import unit_to_si
from .connections_extractor import ConnectionsExtractor
from .entity_identifier import (
    is_structural_connection,
    is_structural_curve_member,
    is_structural_member,
    is_structural_surface_member,
)
from .loads_extractor import LoadsExtractor
from .members_extractor import MembersExtractor


class Extractor:
    """
    Coordinator for extracting a complete structural model from an IFC file.

    This class orchestrates the extraction process using specialized extractors
    for different parts of the structural model (members, connections, loads, etc.).
    """

    def __init__(self, ifc_file: Union[str, ifcopenshell.file]):
        """
        Initialize an Extractor.

        Args:
            ifc_file: Path to an IFC file or an ifcopenshell.file object

        Raises:
            ValueError: If ifc_file is invalid
            FileNotFoundError: If the IFC file does not exist
        """
        self.logger = logging.getLogger(__name__)
        # What the analysis will not do exactly as the file says. They end
        # up in ``model.analysis_warnings`` and from there in the results
        # Warnings for the results (``utils.messages.warning``)
        self.warnings: List[Dict[str, Any]] = []

        # Handle different input types
        if isinstance(ifc_file, str):
            try:
                self.ifc = ifcopenshell.open(ifc_file)
                self.logger.info(f"Opened IFC file: {ifc_file}")
            except Exception as e:
                self.logger.error(f"Failed to open IFC file: {e}")
                raise FileNotFoundError(f"Could not open IFC file: {ifc_file}")
        elif hasattr(ifc_file, "by_type") and callable(ifc_file.by_type):
            # This is likely an ifcopenshell.file object or a valid mock
            self.ifc = ifc_file
            self.logger.info("Using provided ifcopenshell.file object")
        else:
            self.logger.error("Invalid IFC file parameter provided")
            raise ModelExtractionError(
                "ifc_file must be a file path or an ifcopenshell.file object",
                code="E-GEN-001",
            )

        # Get unit scale factors for different unit types
        self.unit_scales = self._get_unit_scales()

        # Initialize specialized extractors with unit scales
        self.members_extractor = MembersExtractor(self.ifc, self.unit_scales)
        self.connections_extractor = ConnectionsExtractor(self.ifc, self.unit_scales)
        self.loads_extractor = LoadsExtractor(self.ifc, self.unit_scales)

    def _get_unit_scales(self) -> Dict[str, float]:
        """
        Calculate unit scale factors for different unit types.

        Returns:
            Dict[str, float]: Dictionary of unit scale factors
        """
        unit_scales = {}

        for unit_type in (
            "LENGTHUNIT",
            "FORCEUNIT",
            "PRESSUREUNIT",
            "MASSUNIT",
            "PLANEANGLEUNIT",
            "THERMODYNAMICTEMPERATUREUNIT",
            "AREAUNIT",
        ):
            try:
                # An area has a unit of its own: Bonsai's default project has
                # lengths in millimetres and areas in square metres. A file
                # that declares none has no scale here, see MembersExtractor.
                if (
                    unit_type == "AREAUNIT"
                    and not ifcopenshell.util.unit.get_project_unit(self.ifc, unit_type)
                ):
                    continue
                scale = ifcopenshell.util.unit.calculate_unit_scale(self.ifc, unit_type)
            except ModelExtractionError:
                raise
            except Exception as error:
                raise ModelExtractionError(
                    f"The {unit_type} of the IFC file cannot be worked out, so "
                    f"its values cannot be converted: {error}",
                    code="E-IFC-004",
                ) from error
            unit_scales[unit_type] = scale
            self.logger.info(f"Unit scale for {unit_type}: {scale}")

        # Fix ifcopenshell bug: calculate_unit_scale for MASSUNIT with
        # GRAM-based units (e.g. MEGA GRAM) returns prefix*1.0 instead
        # of prefix*0.001 because GRAM != KILOGRAM (the SI base).
        # Detect GRAM-based mass units and apply the missing 0.001 factor.
        if unit_scales["MASSUNIT"] != 1.0:
            for assignment in self.ifc.by_type("IfcUnitAssignment"):
                if any(
                    getattr(unit, "UnitType", None) == "MASSUNIT"
                    and getattr(unit, "Name", None) == "GRAM"
                    for unit in assignment.Units
                ):
                    unit_scales["MASSUNIT"] *= 0.001
                    self.logger.info(
                        f"Corrected MASSUNIT scale for GRAM base: "
                        f"{unit_scales['MASSUNIT']}"
                    )
                    break

        # Derived units as the file declares them, which need not be made of its
        # length and mass units. MembersExtractor says what none declared means.
        for unit_type in ("MASSDENSITYUNIT", "MOMENTOFINERTIAUNIT"):
            try:
                unit = ifcopenshell.util.unit.get_project_unit(self.ifc, unit_type)
                if unit:
                    unit_scales[unit_type] = unit_to_si(unit)
            except Exception as error:
                raise ModelExtractionError(
                    f"The {unit_type} of the IFC file cannot be worked out, so "
                    f"its values cannot be converted: {error}",
                    code="E-IFC-004",
                ) from error

        # Warn when the model is not in SI base units so engineers know
        # their values will be scaled. Most structural tools use metres, but
        # some Bonsai/Revit workflows default to millimetres.
        _si_labels = {
            "LENGTHUNIT": "m",
            "FORCEUNIT": "N",
            "PRESSUREUNIT": "Pa",
            "MASSUNIT": "kg",
        }
        for unit_type, si_label in _si_labels.items():
            scale = unit_scales.get(unit_type, 1.0)
            if abs(scale - 1.0) > 1e-9:
                self.logger.warning(
                    f"Non-SI {unit_type} detected (scale = {scale}). "
                    f"Values from IFC are multiplied by {scale} to convert to {si_label}. "
                    f"If your model was created in mm, ensure all geometry and property "
                    f"values are consistent."
                )

        return unit_scales

    def extract_model(
        self, model_id: Optional[str] = None, name: Optional[str] = None
    ) -> StructuralModel:
        """
        Extract a complete structural model from the IFC file.

        Args:
            model_id: Optional ID for the model (will be generated if not provided)
            name: Optional name for the model (will be extracted from IFC if not provided)

        Returns:
            A complete StructuralModel containing all extracted information
        """
        self.logger.info("Extracting complete structural model")

        # Find structural analysis model in IFC
        analysis_models = list(self.ifc.by_type("IfcStructuralAnalysisModel"))

        if analysis_models:
            analysis_model = analysis_models[0]
            if len(analysis_models) > 1:
                self.warnings.append(
                    warning(
                        "W-IFC-001",
                        f"The file has {len(analysis_models)} structural analysis "
                        f"models; only the first, "
                        f"'{analysis_model.Name or analysis_model.GlobalId}', is "
                        "analysed.",
                        ifc_guids=[m.GlobalId for m in analysis_models[1:]],
                    )
                )
            model = StructuralModel(
                model_id or analysis_model.GlobalId,
                name or analysis_model.Name or "Structural Analysis Model",
            )
            self._extract_items_from_analysis_model(analysis_model, model)
        else:
            self.logger.info(
                "No IfcStructuralAnalysisModel found, extracting structural elements directly"
            )
            model = StructuralModel(
                model_id or self._generate_model_id(),
                name or self._extract_model_name() or "Structural Analysis Model",
            )
            self._extract_items_directly(model)

        self._extract_loads_for_model(model)
        self._pass_on_warnings(model)
        return model

    def _pass_on_warnings(self, model: StructuralModel) -> None:
        """Put the extractors' warnings where the results pick them up."""
        messages = list(self.warnings)
        for extractor in (
            self.members_extractor,
            self.connections_extractor,
            self.loads_extractor,
        ):
            messages.extend(getattr(extractor, "warnings", None) or [])
        if not hasattr(model, "analysis_warnings"):
            model.analysis_warnings = []
        seen = {recorded["message"] for recorded in model.analysis_warnings}
        for found in messages:
            if found["message"] in seen:
                continue
            seen.add(found["message"])
            self.logger.warning(f"[{found['code']}] {found['message']}")
            model.analysis_warnings.append(found)

    def _add_member(self, entity, model) -> None:
        """Add the member an IFC entity describes; an error if it cannot be."""
        if is_structural_curve_member(entity):
            model.add_member(self.members_extractor._create_curve_member(entity))
        elif is_structural_surface_member(entity):
            model.add_member(self.members_extractor._create_surface_member(entity))

    def _extract_items_from_analysis_model(self, analysis_model, model):
        """
        Extract structural items from an analysis model by traversing its groups.

        Args:
            analysis_model: The IfcStructuralAnalysisModel entity
            model: The domain model to populate

        Raises:
            ModelExtractionError: If a member or connection of the model
                cannot be analysed. Loads are read with their load groups.
        """
        for group in analysis_model.IsGroupedBy:
            for item in getattr(group, "RelatedObjects", None) or []:
                if is_structural_member(item):
                    self._add_member(item, model)
                elif is_structural_connection(item):
                    model.add_connection(
                        self.connections_extractor._create_domain_connection(item)
                    )

        self.logger.info(f"Added {len(model.members)} structural members to the model")
        self.logger.info(
            f"Added {len(model.connections)} structural connections to the model"
        )

    def _extract_items_directly(self, model):
        """
        Extract structural items directly from the IFC file when no analysis model is present.

        Args:
            model: The domain model to populate

        Raises:
            ModelExtractionError: If a member or connection cannot be analysed.
        """
        for entity_type in ("IfcStructuralCurveMember", "IfcStructuralSurfaceMember"):
            for entity in self.ifc.by_type(entity_type):
                self._add_member(entity, model)
        self.logger.info(f"Added {len(model.members)} structural members to the model")

        for entity_type in (
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ):
            for entity in self.ifc.by_type(entity_type):
                model.add_connection(
                    self.connections_extractor._create_domain_connection(entity)
                )
        self.logger.info(
            f"Added {len(model.connections)} structural connections to the model"
        )

    def _extract_loads_for_model(self, model):
        """
        Extract loads, load groups, and load combinations for the model.

        Args:
            model: The domain model to populate with loads and load groups

        Raises:
            ModelExtractionError: If a load of a group cannot be analysed.
        """
        load_groups = self.loads_extractor.extract_load_groups()
        for group in load_groups:
            # The weight of the members is a load too (SelfWeightCoefficients)
            if group.has_actions:
                model.add_load_group(group)

        grouped = {
            load.action_id or load.id for group in load_groups for load in group.actions
        }
        loose = [
            action
            for action in self.ifc.by_type("IfcStructuralAction")
            if action.GlobalId not in grouped
        ]
        if loose:
            self.warnings.append(
                warning(
                    "W-LOD-002",
                    f"{len(loose)} load(s) of the file belong to no load group or "
                    "load case and are not applied (the first is "
                    f"{loose[0].GlobalId}).",
                    ifc_guids=[action.GlobalId for action in loose],
                )
            )

        for combo in self.loads_extractor.extract_load_combinations():
            model.add_load_combination(combo)
            # A combination may name a group that has no loads of its own
            for group_id in combo.load_groups:
                if model.get_load_group(group_id) is None:
                    for group in load_groups:
                        if group.id == group_id:
                            model.add_load_group(group)
                            break

        self.logger.info(f"Added {len(model.load_groups)} load groups to the model")
        self.logger.info(
            f"Added {len(model.load_combinations)} load combinations to the model"
        )

    def _generate_model_id(self) -> str:
        """
        Generate a unique ID for the model.

        Returns:
            A unique ID string
        """
        return str(uuid.uuid4())

    def _extract_model_name(self) -> Optional[str]:
        """
        Extract a name for the model from the IFC file.

        Returns:
            A name string or None if extraction fails
        """
        # Try to get name from project
        projects = list(self.ifc.by_type("IfcProject"))
        if projects and hasattr(projects[0], "Name") and projects[0].Name:
            return projects[0].Name

        # Try to get name from the filename
        if hasattr(self.ifc, "wrapped_data") and hasattr(
            self.ifc.wrapped_data, "filename"
        ):
            filename = self.ifc.wrapped_data.filename
            return os.path.splitext(os.path.basename(filename))[0]

        return None
