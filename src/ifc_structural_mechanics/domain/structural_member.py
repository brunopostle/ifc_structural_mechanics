"""
Structural member domain models for the IFC structural analysis extension.

This module defines the structural member domain models that represent 
structural elements in the intermediate representation between IFC and 
analysis formats.
"""

from typing import Any, Dict, List, Optional

from ifc_structural_mechanics.domain.base_entity import DomainEntity


class StructuralMember(DomainEntity):
    """
    Base class for structural members in the domain model.

    This class serves as the base for all structural members, providing common
    properties and methods for handling boundary conditions and loads.

    Attributes:
        id (str): Unique identifier for the member.
        entity_type (str): Type of the entity, automatically set to the class name.
        geometry (Any): Geometry representation of the member.
        material (Any): Material properties of the member.
        boundary_conditions (List): List of boundary conditions applied to the member.
        loads (List): List of loads applied to the member.
    """

    def __init__(
        self,
        id: str,
        member_type: str,
        geometry: Any,
        material: Any,
        allow_none_props: bool = False,
        ifc_guid: Optional[str] = None,
    ) -> None:
        """
        Initialize a structural member.

        Args:
            id (str): Unique identifier for the member.
            member_type (str): Type of the structural member ("curve" or "surface").
            geometry (Any): Geometry representation of the member.
            material (Any): Material properties of the member.
            allow_none_props (bool): If True, allows None values for material and other properties
                                    (used for testing or incremental construction).
            ifc_guid (Optional[str]): IFC GlobalId for traceability to source model.

        Raises:
            ValueError: If any of the required parameters are invalid.
        """
        # Initialize instance variables before calling parent constructor
        self.geometry = geometry
        self.material = material
        self.boundary_conditions: List[Any] = []
        self.loads: List[Any] = []

        # NEW: Traceability fields for error propagation
        self.ifc_guid: Optional[str] = ifc_guid
        self.mesh_entity_ids: List[str] = []
        self.analysis_element_ids: List[int] = []

        # Initialize base entity with ID and type
        super().__init__(
            id=id, entity_type=member_type, allow_validation_bypass=allow_none_props
        )

        # Validate member properties if not bypassing validation
        if not allow_none_props:
            self.validate()

    def validate(self) -> bool:
        """
        Validate the member properties.

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If any property is invalid.
        """
        # First validate base entity properties
        super().validate()

        # Validate member type
        if self.entity_type not in ["curve", "surface"]:
            raise ValueError(
                f"Member type '{self.entity_type}' is not supported. "
                "Type must be either 'curve' or 'surface'"
            )

        # Validate geometry and material
        if self.geometry is None:
            raise ValueError("Geometry cannot be None")

        if self.material is None and not self._allow_validation_bypass:
            raise ValueError("Material cannot be None")

        return True

    def add_boundary_condition(self, boundary_condition: Any) -> None:
        """
        Add a boundary condition to the member.

        Args:
            boundary_condition (Any): The boundary condition to add.

        Raises:
            ValueError: If the boundary condition is None.
        """
        if boundary_condition is None:
            raise ValueError("Boundary condition cannot be None")

        self.boundary_conditions.append(boundary_condition)

    def remove_boundary_condition(self, boundary_condition: Any) -> None:
        """
        Remove a boundary condition from the member.

        Args:
            boundary_condition (Any): The boundary condition to remove.

        Raises:
            ValueError: If the boundary condition is not found.
        """
        if boundary_condition not in self.boundary_conditions:
            raise ValueError("Boundary condition not found")

        self.boundary_conditions.remove(boundary_condition)

    def add_load(self, load: Any) -> None:
        """
        Add a load to the member.

        Args:
            load (Any): The load to add.

        Raises:
            ValueError: If the load is None.
        """
        if load is None:
            raise ValueError("Load cannot be None")

        self.loads.append(load)

    def remove_load(self, load: Any) -> None:
        """
        Remove a load from the member.

        Args:
            load (Any): The load to remove.

        Raises:
            ValueError: If the load is not found.
        """
        if load not in self.loads:
            raise ValueError("Load not found")

        self.loads.remove(load)

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the member to a dictionary representation.

        Returns:
            Dict[str, Any]: Dictionary representation of the member.
        """
        result = super().as_dict()

        # Add member-specific properties
        result.update(
            {
                "geometry": self.geometry,
                "material": self.material,
                "boundary_conditions": self.boundary_conditions,
                "loads": self.loads,
            }
        )

        return result


class CurveMember(StructuralMember):
    """
    Representation of a structural curve member (beam, column, etc.).

    This class extends the base StructuralMember to represent curve elements
    like beams and columns, adding section properties.

    Attributes:
        section (Any): Section properties for the curve member.
        local_axis (Optional[tuple]): Local coordinate system axis for the member (x, y, z).
                                      Used for beam orientation in FEA.
    """

    def __init__(
        self,
        id: str,
        geometry: Any,
        material: Any,
        section: Any,
        allow_none_props: bool = False,
        ifc_guid: Optional[str] = None,
        local_axis: Optional[tuple] = None,
    ) -> None:
        """
        Initialize a curve member.

        Args:
            id (str): Unique identifier for the member.
            geometry (Any): Geometry representation of the member.
            material (Any): Material properties of the member.
            section (Any): Section properties of the curve member.
            allow_none_props (bool): If True, allows None values for material and section
                                    (used for testing or incremental construction).
            ifc_guid (Optional[str]): IFC GlobalId for traceability to source model.
            local_axis (Optional[tuple]): Local axis orientation vector (x, y, z) for the member.

        Raises:
            ValueError: If any of the required parameters are invalid.
        """
        # Set section property first
        self.section = section
        self.local_axis = local_axis

        # Initialize parent with common properties
        super().__init__(id, "curve", geometry, material, allow_none_props, ifc_guid)

        # Validate section if not bypassing validation
        if not allow_none_props:
            self._validate_section(section)

    def validate(self) -> bool:
        """
        Validate curve member properties.

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If any property is invalid.
        """
        super().validate()
        self._validate_section(self.section, self._allow_validation_bypass)
        return True

    def _validate_section(self, section: Any, allow_none_props: bool = False) -> None:
        """
        Validate section properties.

        Args:
            section (Any): Section properties to validate.
            allow_none_props (bool): If True, allows None value for section.

        Raises:
            ValueError: If the section is invalid.
        """
        if section is None and not allow_none_props:
            raise ValueError("Section cannot be None for a curve member")

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the curve member to a dictionary representation.

        Returns:
            Dict[str, Any]: Dictionary representation of the curve member.
        """
        result = super().as_dict()
        result["section"] = self.section
        return result


class SurfaceMember(StructuralMember):
    """
    Representation of a structural surface member (wall, slab, etc.).

    This class extends the base StructuralMember to represent surface elements
    like walls and slabs, adding thickness properties.

    Attributes:
        thickness (Any): Thickness property for the surface member.
    """

    def __init__(
        self,
        id: str,
        geometry: Any,
        material: Any,
        thickness: Any,
        allow_none_props: bool = False,
        ifc_guid: Optional[str] = None,
    ) -> None:
        """
        Initialize a surface member.

        Args:
            id (str): Unique identifier for the member.
            geometry (Any): Geometry representation of the member.
            material (Any): Material properties of the member.
            thickness (Any): Thickness property of the surface member.
            allow_none_props (bool): If True, allows None values for material and thickness
                                    (used for testing or incremental construction).
            ifc_guid (Optional[str]): IFC GlobalId for traceability to source model.

        Raises:
            ValueError: If any of the required parameters are invalid.
        """
        # Set thickness property first
        self.thickness = thickness

        # Initialize parent with common properties
        super().__init__(id, "surface", geometry, material, allow_none_props, ifc_guid)

        # Validate thickness if not bypassing validation
        if not allow_none_props:
            self._validate_thickness(thickness)

    def validate(self) -> bool:
        """
        Validate surface member properties.

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If any property is invalid.
        """
        super().validate()
        self._validate_thickness(self.thickness, self._allow_validation_bypass)
        return True

    def _validate_thickness(
        self, thickness: Any, allow_none_props: bool = False
    ) -> None:
        """
        Validate thickness property.

        Args:
            thickness (Any): Thickness property to validate.
            allow_none_props (bool): If True, allows None value for thickness.

        Raises:
            ValueError: If the thickness is invalid.
        """
        if thickness is None and not allow_none_props:
            raise ValueError("Thickness cannot be None for a surface member")

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert the surface member to a dictionary representation.

        Returns:
            Dict[str, Any]: Dictionary representation of the surface member.
        """
        result = super().as_dict()
        result["thickness"] = self.thickness
        return result
