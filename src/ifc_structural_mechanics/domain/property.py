"""
Property classes for structural domain model.

This module provides classes for material, section, and thickness properties
used in structural analysis models.
"""

import math
from typing import Dict, Optional, Tuple, Union


class Material:
    """Material property class for structural analysis.

    Represents the material properties used in structural analysis,
    including basic mechanical properties and optional thermal properties.

    Attributes:
        id (str): Unique identifier for the material
        name (str): Name of the material
        density (float): Density of the material in kg/m³
        elastic_modulus (float): Young's modulus in N/m²
        poisson_ratio (float): Poisson's ratio (dimensionless)
        thermal_expansion_coefficient (Optional[float]): Coefficient of thermal expansion in 1/K
        yield_strength (Optional[float]): Yield strength in N/m²
        ultimate_strength (Optional[float]): Ultimate strength in N/m²
    """

    def __init__(
        self,
        id: str,
        name: str,
        density: float,
        elastic_modulus: float,
        poisson_ratio: float,
        thermal_expansion_coefficient: Optional[float] = None,
        yield_strength: Optional[float] = None,
        ultimate_strength: Optional[float] = None,
    ):
        """Initialize a Material with its properties.

        Args:
            id (str): Unique identifier for the material
            name (str): Name of the material
            density (float): Density of the material in kg/m³
            elastic_modulus (float): Young's modulus in N/m²
            poisson_ratio (float): Poisson's ratio (dimensionless)
            thermal_expansion_coefficient (Optional[float], optional): Coefficient of thermal
                expansion in 1/K. Defaults to None.
            yield_strength (Optional[float], optional): Yield strength in N/m². Defaults to None.
            ultimate_strength (Optional[float], optional): Ultimate strength in N/m².
                Defaults to None.

        Raises:
            ValueError: If required properties have invalid values
        """
        self.id = id
        self.name = name
        self.density = density
        self.elastic_modulus = elastic_modulus
        self.poisson_ratio = poisson_ratio
        self.thermal_expansion_coefficient = thermal_expansion_coefficient
        self.yield_strength = yield_strength
        self.ultimate_strength = ultimate_strength

        self._validate()

    def _validate(self) -> None:
        """Validate material properties.

        Raises:
            ValueError: If material properties have invalid values
        """
        if not self.id:
            raise ValueError("Material ID cannot be empty")

        if not self.name:
            raise ValueError("Material name cannot be empty")

        if self.density <= 0:
            raise ValueError(f"Density must be positive, got {self.density}")

        if self.elastic_modulus <= 0:
            raise ValueError(
                f"Elastic modulus must be positive, got {self.elastic_modulus}"
            )

        if not -1.0 < self.poisson_ratio < 0.5:
            raise ValueError(
                f"Poisson's ratio must be between -1.0 and 0.5, got {self.poisson_ratio}"
            )

        if (
            self.thermal_expansion_coefficient is not None
            and self.thermal_expansion_coefficient < 0
        ):
            raise ValueError(
                f"Thermal expansion coefficient cannot be negative, "
                f"got {self.thermal_expansion_coefficient}"
            )

        if self.yield_strength is not None and self.yield_strength <= 0:
            raise ValueError(
                f"Yield strength must be positive, got {self.yield_strength}"
            )

        if self.ultimate_strength is not None and self.ultimate_strength <= 0:
            raise ValueError(
                f"Ultimate strength must be positive, got {self.ultimate_strength}"
            )

    def get_shear_modulus(self) -> float:
        """Calculate shear modulus from elastic modulus and Poisson's ratio.

        Returns:
            float: Shear modulus in N/m²
        """
        return self.elastic_modulus / (2 * (1 + self.poisson_ratio))

    def get_bulk_modulus(self) -> float:
        """Calculate bulk modulus from elastic modulus and Poisson's ratio.

        Returns:
            float: Bulk modulus in N/m²
        """
        return self.elastic_modulus / (3 * (1 - 2 * self.poisson_ratio))

    def get_lame_parameters(self) -> Tuple[float, float]:
        """Calculate Lamé parameters from elastic modulus and Poisson's ratio.

        Returns:
            Tuple[float, float]: Lamé parameters (lambda, mu) in N/m²
        """
        mu = self.get_shear_modulus()
        lambda_param = (self.elastic_modulus * self.poisson_ratio) / (
            (1 + self.poisson_ratio) * (1 - 2 * self.poisson_ratio)
        )
        return lambda_param, mu

    def as_dict(self) -> Dict[str, Union[str, float, None]]:
        """Return material properties as a dictionary.

        Returns:
            Dict[str, Union[str, float, None]]: Dictionary of material properties
        """
        return {
            "id": self.id,
            "name": self.name,
            "density": self.density,
            "elastic_modulus": self.elastic_modulus,
            "poisson_ratio": self.poisson_ratio,
            "thermal_expansion_coefficient": self.thermal_expansion_coefficient,
            "yield_strength": self.yield_strength,
            "ultimate_strength": self.ultimate_strength,
        }


class Section:
    """Cross-section property class for structural curve members.

    Represents the cross-section properties of structural curve members
    such as beams and columns.

    Attributes:
        id (str): Unique identifier for the section
        name (str): Name of the section
        section_type (str): Type of section (e.g., "rectangular", "I", "circular")
        area (float): Cross-sectional area in m²
        dimensions (Dict[str, float]): Dictionary of dimensions specific to the section type
    """

    def __init__(
        self,
        id: str,
        name: str,
        section_type: str,
        area: float,
        dimensions: Dict[str, float],
        allow_incomplete_dims: bool = False,
    ):
        """Initialize a Section with its properties.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            section_type (str): Type of section (e.g., "rectangular", "I", "circular")
            area (float): Cross-sectional area in m²
            dimensions (Dict[str, float]): Dictionary of dimensions specific to the section type
            allow_incomplete_dims (bool): If True, allows incomplete dimensions (for testing)

        Raises:
            ValueError: If required properties have invalid values
        """
        self.id = id
        self.name = name
        self.section_type = section_type.lower()
        self.area = area
        self.dimensions = dimensions
        self.allow_incomplete_dims = allow_incomplete_dims

        self._validate()
        self._calculate_properties()

    def _validate(self) -> None:
        """Validate section properties.

        Raises:
            ValueError: If section properties have invalid values
        """
        if not self.id:
            raise ValueError("Section ID cannot be empty")

        if not self.name:
            raise ValueError("Section name cannot be empty")

        if not self.section_type:
            raise ValueError("Section type cannot be empty")

        if self.area <= 0:
            raise ValueError(f"Area must be positive, got {self.area}")

        if not self.dimensions:
            raise ValueError("Dimensions dictionary cannot be empty")

        # Skip detailed dimension validation for testing
        if self.allow_incomplete_dims:
            return

        # Validate dimensions based on section_type
        if self.section_type == "rectangular":
            required_dims = ["width", "height"]
        elif self.section_type == "circular":
            required_dims = ["radius"]
        elif self.section_type == "i":
            required_dims = ["width", "height", "web_thickness", "flange_thickness"]
        elif self.section_type == "t":
            required_dims = ["width", "height", "web_thickness", "flange_thickness"]
        elif self.section_type == "l":
            required_dims = ["width", "height", "thickness"]
        elif self.section_type == "c":
            required_dims = ["width", "height", "web_thickness", "flange_thickness"]
        elif self.section_type == "hollow_rectangular":
            required_dims = ["outer_width", "outer_height", "thickness"]
        elif self.section_type == "hollow_circular":
            required_dims = ["outer_radius", "thickness"]
        else:
            required_dims = []

        for dim in required_dims:
            if dim not in self.dimensions:
                raise ValueError(
                    f"Required dimension '{dim}' missing for {self.section_type} section"
                )
            if self.dimensions[dim] <= 0:
                raise ValueError(
                    f"Dimension '{dim}' must be positive, got {self.dimensions[dim]}"
                )

    def _calculate_properties(self) -> None:
        """Calculate section properties based on section type and dimensions."""
        # Skip property calculation for incomplete test sections
        if self.allow_incomplete_dims:
            # Initialize basic properties with null values for testing
            self.moment_of_inertia_y = None
            self.moment_of_inertia_z = None
            self.torsional_constant = None
            self.warping_constant = None
            self.shear_area_y = None
            self.shear_area_z = None
            return

        # Normal calculation for complete sections
        if self.section_type == "rectangular":
            self._calculate_rectangular_properties()
        elif self.section_type == "circular":
            self._calculate_circular_properties()
        elif self.section_type == "i":
            self._calculate_i_properties()
        elif self.section_type == "t":
            self._calculate_t_properties()
        elif self.section_type == "l":
            self._calculate_l_properties()
        elif self.section_type == "c":
            self._calculate_c_properties()
        elif self.section_type == "hollow_rectangular":
            self._calculate_hollow_rectangular_properties()
        elif self.section_type == "hollow_circular":
            self._calculate_hollow_circular_properties()
        else:
            # For custom sections, only store the provided area
            self.moment_of_inertia_y = None
            self.moment_of_inertia_z = None
            self.torsional_constant = None
            self.warping_constant = None
            self.shear_area_y = None
            self.shear_area_z = None

    def _calculate_rectangular_properties(self) -> None:
        """Calculate properties for rectangular section."""
        b = self.dimensions["width"]
        h = self.dimensions["height"]

        # Calculate moments of inertia
        self.moment_of_inertia_y = (b * h**3) / 12  # About y-axis (strong axis)
        self.moment_of_inertia_z = (h * b**3) / 12  # About z-axis (weak axis)

        # Calculate torsional constant
        if b >= h:
            self.torsional_constant = (h * b**3) * (
                16 / 3 - 3.36 * (b / h) * (1 - (b**4) / (12 * h**4))
            )
        else:
            self.torsional_constant = (b * h**3) * (
                16 / 3 - 3.36 * (h / b) * (1 - (h**4) / (12 * b**4))
            )

        # Warping constant (not commonly used for rectangular sections)
        self.warping_constant = None

        # Shear areas
        self.shear_area_y = 5 / 6 * self.area  # Approximation for rectangular
        self.shear_area_z = 5 / 6 * self.area  # Approximation for rectangular

    def _calculate_circular_properties(self) -> None:
        """Calculate properties for circular section."""
        r = self.dimensions["radius"]

        # Calculate moments of inertia (same in both directions for circular)
        self.moment_of_inertia_y = (math.pi * r**4) / 4
        self.moment_of_inertia_z = self.moment_of_inertia_y

        # Calculate torsional constant (equals polar moment of inertia for circular)
        self.torsional_constant = (math.pi * r**4) / 2

        # Warping constant (zero for circular sections)
        self.warping_constant = 0

        # Shear areas
        self.shear_area_y = 0.9 * self.area  # Approximation for circular
        self.shear_area_z = 0.9 * self.area  # Approximation for circular

    def _calculate_i_properties(self) -> None:
        """Calculate properties for I-section."""
        b = self.dimensions["width"]
        h = self.dimensions["height"]
        tw = self.dimensions["web_thickness"]
        tf = self.dimensions["flange_thickness"]

        # Calculate moments of inertia
        # Strong axis (y-axis) - vertical web
        self.moment_of_inertia_y = (b * h**3) / 12 - (b - tw) * (h - 2 * tf) ** 3 / 12

        # Weak axis (z-axis) - horizontal flanges
        self.moment_of_inertia_z = (2 * tf * b**3) / 12 + tw * (h - 2 * tf) ** 3 / 12

        # Approximate torsional constant
        self.torsional_constant = (1 / 3) * (b * tf**3 * 2 + (h - 2 * tf) * tw**3)

        # Warping constant - complex calculation, simplified approximation
        self.warping_constant = (tf * b**3 * (h - tf) ** 2) / 24

        # Shear areas - approximate
        self.shear_area_y = h * tw  # Web area for y-direction
        self.shear_area_z = 2 * b * tf  # Flange area for z-direction

    def _calculate_t_properties(self) -> None:
        """Calculate properties for T-section."""
        b = self.dimensions["width"]
        h = self.dimensions["height"]
        tw = self.dimensions["web_thickness"]
        tf = self.dimensions["flange_thickness"]

        # Calculate centroid position from bottom
        Af = b * tf  # Area of flange
        Aw = tw * (h - tf)  # Area of web
        y_centroid = (Af * (h - tf / 2) + Aw * (h - tf) / 2) / (Af + Aw)

        # Calculate moments of inertia about centroidal axes
        # Strong axis (y-axis) - vertical web
        Iy_flange = (b * tf**3) / 12 + Af * (h - tf / 2 - y_centroid) ** 2
        Iy_web = (tw * (h - tf) ** 3) / 12 + Aw * ((h - tf) / 2 - y_centroid) ** 2
        self.moment_of_inertia_y = Iy_flange + Iy_web

        # Weak axis (z-axis) - horizontal flange
        Iz_flange = (tf * b**3) / 12
        Iz_web = (tw**3 * (h - tf)) / 12
        self.moment_of_inertia_z = Iz_flange + Iz_web

        # Approximate torsional constant
        self.torsional_constant = (1 / 3) * (b * tf**3 + (h - tf) * tw**3)

        # Warping constant - simplified approximation
        self.warping_constant = (b**3 * tf * (h - tf) ** 2) / 12

        # Shear areas - approximate
        self.shear_area_y = tw * (h - tf)  # Web area for y-direction
        self.shear_area_z = b * tf  # Flange area for z-direction

    def _calculate_l_properties(self) -> None:
        """Calculate properties for L-section (angle)."""
        w = self.dimensions["width"]
        h = self.dimensions["height"]
        t = self.dimensions["thickness"]

        # Calculate centroid position from corner
        Ax = t * h  # Area in x-direction
        Az = t * w  # Area in z-direction
        A = Ax + Az - t**2  # Total area (subtracting overlap)

        cx = (Az * w / 2) / A  # Centroid x-coordinate
        cy = (Ax * h / 2) / A  # Centroid y-coordinate

        # Calculate moments of inertia about centroidal axes
        # These are simplified approximations
        Ixx = (t * h**3) / 3 - t * cy**2
        Izz = (t * w**3) / 3 - t * cx**2
        Ixz = t * cx * cy

        # Calculate principal moments of inertia
        avg = (Ixx + Izz) / 2
        diff = (Ixx - Izz) / 2
        rad = math.sqrt(diff**2 + Ixz**2)

        self.moment_of_inertia_y = avg + rad  # Major principal moment
        self.moment_of_inertia_z = avg - rad  # Minor principal moment

        # Approximate torsional constant
        self.torsional_constant = (1 / 3) * t**3 * (w + h - t)

        # Warping constant - simplified approximation
        self.warping_constant = (t * (w**2 * h**2) * (w + h)) / 36

        # Shear areas - approximate
        self.shear_area_y = 2 / 3 * t * h  # Approximation
        self.shear_area_z = 2 / 3 * t * w  # Approximation

    def _calculate_c_properties(self) -> None:
        """Calculate properties for C-section (channel)."""
        b = self.dimensions["width"]
        h = self.dimensions["height"]
        tw = self.dimensions["web_thickness"]
        tf = self.dimensions["flange_thickness"]

        # Calculate centroid position from web
        Aw = tw * h  # Area of web
        Af = 2 * tf * b  # Area of flanges
        A = Aw + Af

        # For symmetric C-section, centroid is offset from web
        cx = (Af * b / 2) / A

        # Calculate moments of inertia
        # Strong axis (y-axis) - vertical web
        self.moment_of_inertia_y = (tw * h**3) / 12 + 2 * (
            (tf * b**3) / 12 + tf * b * (h / 2) ** 2
        )

        # Weak axis (z-axis) - horizontal flanges
        self.moment_of_inertia_z = (h * tw**3) / 12 + 2 * (
            b * tf**3 / 12 + b * tf * cx**2
        )

        # Approximate torsional constant
        self.torsional_constant = (1 / 3) * (h * tw**3 + 2 * b * tf**3)

        # Warping constant - simplified approximation
        self.warping_constant = (h**2 * b**2 * tf) / 6

        # Shear areas - approximate
        self.shear_area_y = h * tw  # Web area for y-direction
        self.shear_area_z = 2 * b * tf  # Flange area for z-direction

    def _calculate_hollow_rectangular_properties(self) -> None:
        """Calculate properties for hollow rectangular section."""
        bo = self.dimensions["outer_width"]
        ho = self.dimensions["outer_height"]
        t = self.dimensions["thickness"]

        # Calculate inner dimensions
        bi = bo - 2 * t
        hi = ho - 2 * t

        # Check if dimensions are valid
        if bi <= 0 or hi <= 0:
            raise ValueError(
                "Thickness too large for hollow rectangular section dimensions"
            )

        # Calculate moments of inertia
        self.moment_of_inertia_y = (bo * ho**3) / 12 - (bi * hi**3) / 12
        self.moment_of_inertia_z = (ho * bo**3) / 12 - (hi * bi**3) / 12

        # Approximate torsional constant
        self.torsional_constant = 2 * t * (bo - t) * (ho - t) ** 2 / (bo + ho - 2 * t)

        # Warping constant - simplified approximation
        self.warping_constant = None  # Complex calculation

        # Shear areas - approximate
        self.shear_area_y = 2 * (ho * t)  # Approximation
        self.shear_area_z = 2 * (bo * t)  # Approximation

    def _calculate_hollow_circular_properties(self) -> None:
        """Calculate properties for hollow circular section."""
        ro = self.dimensions["outer_radius"]
        t = self.dimensions["thickness"]

        # Calculate inner radius
        ri = ro - t

        # Check if dimensions are valid
        if ri <= 0:
            raise ValueError(
                "Thickness too large for hollow circular section dimensions"
            )

        # Calculate moments of inertia (same in both directions for circular)
        self.moment_of_inertia_y = (math.pi / 4) * (ro**4 - ri**4)
        self.moment_of_inertia_z = self.moment_of_inertia_y

        # Calculate torsional constant
        self.torsional_constant = (math.pi / 2) * (ro**4 - ri**4)

        # Warping constant (zero for circular sections)
        self.warping_constant = 0

        # Shear areas - approximate
        self.shear_area_y = 0.9 * self.area  # Approximation for hollow circular
        self.shear_area_z = 0.9 * self.area  # Approximation for hollow circular

    def get_radius_of_gyration(self) -> Tuple[float, float]:
        """Calculate radii of gyration about principal axes.

        Returns:
            Tuple[float, float]: Radii of gyration (ry, rz) in m
        """
        if not hasattr(self, "moment_of_inertia_y") or not hasattr(
            self, "moment_of_inertia_z"
        ):
            return None, None

        if self.moment_of_inertia_y is None or self.moment_of_inertia_z is None:
            return None, None

        ry = math.sqrt(self.moment_of_inertia_y / self.area)
        rz = math.sqrt(self.moment_of_inertia_z / self.area)
        return ry, rz

    def get_section_modulus(self) -> Tuple[float, float]:
        """Calculate section moduli about principal axes.

        Returns:
            Tuple[float, float]: Section moduli (Wy, Wz) in m³
        """
        if not hasattr(self, "moment_of_inertia_y") or not hasattr(
            self, "moment_of_inertia_z"
        ):
            return None, None

        if self.moment_of_inertia_y is None or self.moment_of_inertia_z is None:
            return None, None

        # For simple sections, approximate using standard formulas
        if self.section_type == "rectangular":
            h = self.dimensions["height"]
            b = self.dimensions["width"]
            wy = self.moment_of_inertia_y / (h / 2)
            wz = self.moment_of_inertia_z / (b / 2)
        elif self.section_type == "circular":
            r = self.dimensions["radius"]
            wy = wz = self.moment_of_inertia_y / r
        else:
            # For complex sections, this is a simplification
            # A more accurate calculation would consider the distance to extreme fibers
            wy = None
            wz = None

        return wy, wz

    @classmethod
    def create_rectangular_section(
        cls, id: str, name: str, width: float, height: float
    ) -> "Section":
        """Create a rectangular section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            width (float): Width of the section in m
            height (float): Height of the section in m

        Returns:
            Section: A Section object with rectangular properties
        """
        area = width * height
        dimensions = {"width": width, "height": height}
        return cls(id, name, "rectangular", area, dimensions)

    @classmethod
    def create_circular_section(cls, id: str, name: str, radius: float) -> "Section":
        """Create a circular section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            radius (float): Radius of the section in m

        Returns:
            Section: A Section object with circular properties
        """
        area = math.pi * radius**2
        dimensions = {"radius": radius}
        return cls(id, name, "circular", area, dimensions)

    @classmethod
    def create_i_section(
        cls,
        id: str,
        name: str,
        width: float,
        height: float,
        web_thickness: float,
        flange_thickness: float,
    ) -> "Section":
        """Create an I-section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            width (float): Width of the section in m
            height (float): Height of the section in m
            web_thickness (float): Thickness of the web in m
            flange_thickness (float): Thickness of the flanges in m

        Returns:
            Section: A Section object with I-section properties
        """
        # Calculate area: 2 flanges + 1 web
        flange_area = width * flange_thickness * 2
        web_area = web_thickness * (height - 2 * flange_thickness)
        area = flange_area + web_area

        dimensions = {
            "width": width,
            "height": height,
            "web_thickness": web_thickness,
            "flange_thickness": flange_thickness,
        }

        return cls(id, name, "i", area, dimensions)

    @classmethod
    def create_t_section(
        cls,
        id: str,
        name: str,
        width: float,
        height: float,
        web_thickness: float,
        flange_thickness: float,
    ) -> "Section":
        """Create a T-section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            width (float): Width of the section in m
            height (float): Height of the section in m
            web_thickness (float): Thickness of the web in m
            flange_thickness (float): Thickness of the flange in m

        Returns:
            Section: A Section object with T-section properties
        """
        # Calculate area: 1 flange + 1 web
        flange_area = width * flange_thickness
        web_area = web_thickness * (height - flange_thickness)
        area = flange_area + web_area

        dimensions = {
            "width": width,
            "height": height,
            "web_thickness": web_thickness,
            "flange_thickness": flange_thickness,
        }

        return cls(id, name, "t", area, dimensions)

    @classmethod
    def create_hollow_rectangular_section(
        cls,
        id: str,
        name: str,
        outer_width: float,
        outer_height: float,
        thickness: float,
    ) -> "Section":
        """Create a hollow rectangular section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            outer_width (float): Outer width of the section in m
            outer_height (float): Outer height of the section in m
            thickness (float): Wall thickness in m

        Returns:
            Section: A Section object with hollow rectangular properties
        """
        # Calculate inner dimensions
        inner_width = outer_width - 2 * thickness
        inner_height = outer_height - 2 * thickness

        if inner_width <= 0 or inner_height <= 0:
            raise ValueError("Thickness too large for given dimensions")

        # Calculate area
        area = outer_width * outer_height - inner_width * inner_height

        dimensions = {
            "outer_width": outer_width,
            "outer_height": outer_height,
            "thickness": thickness,
        }

        return cls(id, name, "hollow_rectangular", area, dimensions)

    @classmethod
    def create_hollow_circular_section(
        cls, id: str, name: str, outer_radius: float, thickness: float
    ) -> "Section":
        """Create a hollow circular section.

        Args:
            id (str): Unique identifier for the section
            name (str): Name of the section
            outer_radius (float): Outer radius of the section in m
            thickness (float): Wall thickness in m

        Returns:
            Section: A Section object with hollow circular properties
        """
        # Calculate inner radius
        inner_radius = outer_radius - thickness

        if inner_radius <= 0:
            raise ValueError("Thickness too large for given radius")

        # Calculate area
        area = math.pi * (outer_radius**2 - inner_radius**2)

        dimensions = {
            "outer_radius": outer_radius,
            "thickness": thickness,
        }

        return cls(id, name, "hollow_circular", area, dimensions)

    def as_dict(self) -> Dict[str, Union[str, float, Dict[str, float], None]]:
        """Return section properties as a dictionary.

        Returns:
            Dict[str, Union[str, float, Dict[str, float], None]]: Dictionary of section properties
        """
        result = {
            "id": self.id,
            "name": self.name,
            "section_type": self.section_type,
            "area": self.area,
            "dimensions": self.dimensions,
        }

        # Add calculated properties if they exist
        if hasattr(self, "moment_of_inertia_y"):
            result["moment_of_inertia_y"] = self.moment_of_inertia_y

        if hasattr(self, "moment_of_inertia_z"):
            result["moment_of_inertia_z"] = self.moment_of_inertia_z

        if hasattr(self, "torsional_constant"):
            result["torsional_constant"] = self.torsional_constant

        if hasattr(self, "warping_constant") and self.warping_constant is not None:
            result["warping_constant"] = self.warping_constant

        if hasattr(self, "shear_area_y") and self.shear_area_y is not None:
            result["shear_area_y"] = self.shear_area_y

        if hasattr(self, "shear_area_z") and self.shear_area_z is not None:
            result["shear_area_z"] = self.shear_area_z

        return result


class Thickness:
    """Thickness property class for structural surface members.

    Represents the thickness properties of structural surface members
    such as walls, slabs, and shells.

    Attributes:
        id (str): Unique identifier for the thickness property
        name (str): Name of the thickness property
        value (float): Nominal thickness value in m
        is_variable (bool): Whether the thickness is variable across the surface
        min_value (Optional[float]): Minimum thickness value for variable thickness
        max_value (Optional[float]): Maximum thickness value for variable thickness
    """

    def __init__(
        self,
        id: str,
        name: str,
        value: float,
        is_variable: bool = False,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ):
        """Initialize a Thickness with its properties.

        Args:
            id (str): Unique identifier for the thickness property
            name (str): Name of the thickness property
            value (float): Nominal thickness value in m
            is_variable (bool, optional): Whether the thickness is variable across the surface.
                Defaults to False.
            min_value (Optional[float], optional): Minimum thickness value for variable thickness.
                Defaults to None.
            max_value (Optional[float], optional): Maximum thickness value for variable thickness.
                Defaults to None.

        Raises:
            ValueError: If required properties have invalid values
        """
        self.id = id
        self.name = name
        self.value = value
        self.is_variable = is_variable
        self.min_value = min_value
        self.max_value = max_value

        self._validate()

    def _validate(self) -> None:
        """Validate thickness properties.

        Raises:
            ValueError: If thickness properties have invalid values
        """
        if not self.id:
            raise ValueError("Thickness ID cannot be empty")

        if not self.name:
            raise ValueError("Thickness name cannot be empty")

        if self.value <= 0:
            raise ValueError(f"Thickness value must be positive, got {self.value}")

        if self.is_variable:
            if self.min_value is None or self.max_value is None:
                raise ValueError(
                    "Min and max values must be provided for variable thickness"
                )
            if self.min_value <= 0:
                raise ValueError(
                    f"Minimum thickness value must be positive, got {self.min_value}"
                )
            if self.max_value <= 0:
                raise ValueError(
                    f"Maximum thickness value must be positive, got {self.max_value}"
                )
            if self.min_value > self.max_value:
                raise ValueError(
                    f"Minimum thickness ({self.min_value}) cannot be greater than "
                    f"maximum thickness ({self.max_value})"
                )
            if not self.min_value <= self.value <= self.max_value:
                raise ValueError(
                    f"Nominal thickness ({self.value}) must be between "
                    f"minimum ({self.min_value}) and maximum ({self.max_value})"
                )

    def get_average_value(self) -> float:
        """Get the average thickness value.

        Returns:
            float: Average thickness value in m. For constant thickness, returns the nominal value.
                For variable thickness, returns the average of min and max values.
        """
        if not self.is_variable:
            return self.value
        return (self.min_value + self.max_value) / 2

    def as_dict(self) -> Dict[str, Union[str, float, bool, None]]:
        """Return thickness properties as a dictionary.

        Returns:
            Dict[str, Union[str, float, bool, None]]: Dictionary of thickness properties
        """
        return {
            "id": self.id,
            "name": self.name,
            "value": self.value,
            "is_variable": self.is_variable,
            "min_value": self.min_value,
            "max_value": self.max_value,
        }
