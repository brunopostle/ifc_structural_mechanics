"""
Result classes for the IFC structural analysis extension.

This module provides classes for representing different types of analysis results
in the domain model. These results are associated with structural elements and 
contain values from analyses.
"""

from typing import Dict, List, Any


class Result:
    """Base class for analysis results."""

    def __init__(self, result_type: str, reference_element: str):
        """
        Initialize a result.

        Args:
            result_type: Type of the result (e.g., "displacement", "stress")
            reference_element: ID of the element this result is associated with
        """
        self.result_type = result_type
        self.reference_element = reference_element
        self.values: Dict[str, Any] = {}  # Key-value pairs for result data
        self.metadata: Dict[str, Any] = {}  # Additional metadata about the result

    def add_value(self, key: str, value: Any) -> None:
        """
        Add a result value.

        Args:
            key: Key for the result value
            value: The result value to add
        """
        self.values[key] = value

    def get_value(self, key: str) -> Any:
        """
        Get a result value.

        Args:
            key: Key for the result value

        Returns:
            The result value associated with the key

        Raises:
            KeyError: If the key is not found
        """
        if key not in self.values:
            raise KeyError(f"Result value '{key}' not found")
        return self.values[key]

    def has_value(self, key: str) -> bool:
        """
        Check if a result value exists.

        Args:
            key: Key for the result value

        Returns:
            True if the value exists, False otherwise
        """
        return key in self.values

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata about the result.

        Args:
            key: Key for the metadata
            value: The metadata value to add
        """
        self.metadata[key] = value

    def get_metadata(self, key: str) -> Any:
        """
        Get metadata about the result.

        Args:
            key: Key for the metadata

        Returns:
            The metadata value associated with the key

        Raises:
            KeyError: If the key is not found
        """
        if key not in self.metadata:
            raise KeyError(f"Metadata '{key}' not found")
        return self.metadata[key]

    def validate(self) -> bool:
        """
        Validate the result.

        Returns:
            True if the result is valid, False otherwise
        """
        # Base validation: check if we have a reference element and values
        return bool(self.reference_element and self.values)


class DisplacementResult(Result):
    """
    Result class for nodal displacements.

    Displacement results typically contain translation and rotation values
    at nodes or points on structural elements.
    """

    def __init__(self, reference_element: str, load_case: str = ""):
        """
        Initialize a displacement result.

        Args:
            reference_element: ID of the element this result is associated with
            load_case: Optional name of the load case for this result
        """
        super().__init__("displacement", reference_element)
        if load_case:
            self.add_metadata("load_case", load_case)

    def set_translations(self, translations: List[float]) -> None:
        """
        Set the translation values.

        Args:
            translations: List of translation values [tx, ty, tz]
        """
        if len(translations) != 3:
            raise ValueError("Translations must be a list of 3 values [tx, ty, tz]")
        self.add_value("tx", translations[0])
        self.add_value("ty", translations[1])
        self.add_value("tz", translations[2])

    def set_rotations(self, rotations: List[float]) -> None:
        """
        Set the rotation values.

        Args:
            rotations: List of rotation values [rx, ry, rz]
        """
        if len(rotations) != 3:
            raise ValueError("Rotations must be a list of 3 values [rx, ry, rz]")
        self.add_value("rx", rotations[0])
        self.add_value("ry", rotations[1])
        self.add_value("rz", rotations[2])

    def get_translations(self) -> List[float]:
        """
        Get the translation values.

        Returns:
            List of translation values [tx, ty, tz]
        """
        return [
            self.get_value("tx") if self.has_value("tx") else 0.0,
            self.get_value("ty") if self.has_value("ty") else 0.0,
            self.get_value("tz") if self.has_value("tz") else 0.0,
        ]

    def get_rotations(self) -> List[float]:
        """
        Get the rotation values.

        Returns:
            List of rotation values [rx, ry, rz]
        """
        return [
            self.get_value("rx") if self.has_value("rx") else 0.0,
            self.get_value("ry") if self.has_value("ry") else 0.0,
            self.get_value("rz") if self.has_value("rz") else 0.0,
        ]

    def get_magnitude(self) -> float:
        """
        Calculate the magnitude of the displacement.

        Returns:
            Magnitude of the displacement vector
        """
        translations = self.get_translations()
        import math

        return math.sqrt(sum(t * t for t in translations))

    def validate(self) -> bool:
        """
        Validate the displacement result.

        Returns:
            True if the result is valid, False otherwise
        """
        base_valid = super().validate()
        return base_valid and (
            self.has_value("tx")
            or self.has_value("ty")
            or self.has_value("tz")
            or self.has_value("rx")
            or self.has_value("ry")
            or self.has_value("rz")
        )


class StressResult(Result):
    """
    Result class for element stresses.

    Stress results typically contain normal and shear stress components
    at points within structural elements.
    """

    def __init__(self, reference_element: str, load_case: str = ""):
        """
        Initialize a stress result.

        Args:
            reference_element: ID of the element this result is associated with
            load_case: Optional name of the load case for this result
        """
        super().__init__("stress", reference_element)
        if load_case:
            self.add_metadata("load_case", load_case)

    def set_normal_stresses(self, stresses: Dict[str, float]) -> None:
        """
        Set the normal stress values.

        Args:
            stresses: Dictionary of normal stress components, e.g., {"xx": 10.0, "yy": 5.0, "zz": 2.0}
        """
        for key, value in stresses.items():
            self.add_value(f"s{key}", value)

    def set_shear_stresses(self, stresses: Dict[str, float]) -> None:
        """
        Set the shear stress values.

        Args:
            stresses: Dictionary of shear stress components, e.g., {"xy": 3.0, "yz": 1.5, "xz": 0.5}
        """
        for key, value in stresses.items():
            self.add_value(f"s{key}", value)

    def set_principal_stresses(self, stresses: List[float]) -> None:
        """
        Set the principal stress values.

        Args:
            stresses: List of principal stresses [s1, s2, s3]
        """
        if len(stresses) != 3:
            raise ValueError(
                "Principal stresses must be a list of 3 values [s1, s2, s3]"
            )
        self.add_value("s1", stresses[0])
        self.add_value("s2", stresses[1])
        self.add_value("s3", stresses[2])

    def get_von_mises_stress(self) -> float:
        """
        Calculate the von Mises equivalent stress.

        Returns:
            Von Mises equivalent stress value

        Raises:
            ValueError: If the necessary stress components are not available
        """
        if self.has_value("s1") and self.has_value("s2") and self.has_value("s3"):
            # Calculate from principal stresses
            s1 = self.get_value("s1")
            s2 = self.get_value("s2")
            s3 = self.get_value("s3")
            import math

            return math.sqrt(0.5 * ((s1 - s2) ** 2 + (s2 - s3) ** 2 + (s3 - s1) ** 2))
        elif (
            self.has_value("sxx")
            and self.has_value("syy")
            and self.has_value("szz")
            and self.has_value("sxy")
            and self.has_value("syz")
            and self.has_value("sxz")
        ):
            # Calculate from stress components
            sxx = self.get_value("sxx")
            syy = self.get_value("syy")
            szz = self.get_value("szz")
            sxy = self.get_value("sxy")
            syz = self.get_value("syz")
            sxz = self.get_value("sxz")
            import math

            return math.sqrt(
                0.5
                * (
                    (sxx - syy) ** 2
                    + (syy - szz) ** 2
                    + (szz - sxx) ** 2
                    + 6 * (sxy ** 2 + syz ** 2 + sxz ** 2)
                )
            )
        else:
            raise ValueError(
                "Insufficient stress components to calculate von Mises stress"
            )

    def validate(self) -> bool:
        """
        Validate the stress result.

        Returns:
            True if the result is valid, False otherwise
        """
        base_valid = super().validate()
        # Check if we have at least one stress component
        has_stress_component = any(
            key.startswith("s") and key != "stress" for key in self.values.keys()
        )
        return base_valid and has_stress_component


class StrainResult(Result):
    """
    Result class for element strains.

    Strain results typically contain normal and shear strain components
    at points within structural elements.
    """

    def __init__(self, reference_element: str, load_case: str = ""):
        """
        Initialize a strain result.

        Args:
            reference_element: ID of the element this result is associated with
            load_case: Optional name of the load case for this result
        """
        super().__init__("strain", reference_element)
        if load_case:
            self.add_metadata("load_case", load_case)

    def set_normal_strains(self, strains: Dict[str, float]) -> None:
        """
        Set the normal strain values.

        Args:
            strains: Dictionary of normal strain components, e.g., {"xx": 0.001, "yy": 0.0005}
        """
        for key, value in strains.items():
            self.add_value(f"e{key}", value)

    def set_shear_strains(self, strains: Dict[str, float]) -> None:
        """
        Set the shear strain values.

        Args:
            strains: Dictionary of shear strain components, e.g., {"xy": 0.0003, "yz": 0.0001}
        """
        for key, value in strains.items():
            self.add_value(f"e{key}", value)

    def set_principal_strains(self, strains: List[float]) -> None:
        """
        Set the principal strain values.

        Args:
            strains: List of principal strains [e1, e2, e3]
        """
        if len(strains) != 3:
            raise ValueError(
                "Principal strains must be a list of 3 values [e1, e2, e3]"
            )
        self.add_value("e1", strains[0])
        self.add_value("e2", strains[1])
        self.add_value("e3", strains[2])

    def get_equivalent_strain(self) -> float:
        """
        Calculate the equivalent strain.

        Returns:
            Equivalent strain value

        Raises:
            ValueError: If the necessary strain components are not available
        """
        if self.has_value("e1") and self.has_value("e2") and self.has_value("e3"):
            # Calculate from principal strains
            e1 = self.get_value("e1")
            e2 = self.get_value("e2")
            e3 = self.get_value("e3")
            import math

            return math.sqrt(2 / 3 * ((e1 - e2) ** 2 + (e2 - e3) ** 2 + (e3 - e1) ** 2))
        elif (
            self.has_value("exx")
            and self.has_value("eyy")
            and self.has_value("ezz")
            and self.has_value("exy")
            and self.has_value("eyz")
            and self.has_value("exz")
        ):
            # Calculate from strain components
            exx = self.get_value("exx")
            eyy = self.get_value("eyy")
            ezz = self.get_value("ezz")
            exy = self.get_value("exy")
            eyz = self.get_value("eyz")
            exz = self.get_value("exz")
            import math

            return math.sqrt(
                2
                / 3
                * (
                    (exx - eyy) ** 2
                    + (eyy - ezz) ** 2
                    + (ezz - exx) ** 2
                    + 6 * (exy ** 2 + eyz ** 2 + exz ** 2)
                )
            )
        else:
            raise ValueError(
                "Insufficient strain components to calculate equivalent strain"
            )

    def validate(self) -> bool:
        """
        Validate the strain result.

        Returns:
            True if the result is valid, False otherwise
        """
        base_valid = super().validate()
        # Check if we have at least one strain component
        has_strain_component = any(
            key.startswith("e") and key != "strain" for key in self.values.keys()
        )
        return base_valid and has_strain_component


class ReactionForceResult(Result):
    """
    Result class for support reactions.

    Reaction force results typically contain force and moment components
    at support or boundary condition locations.
    """

    def __init__(self, reference_element: str, load_case: str = ""):
        """
        Initialize a reaction force result.

        Args:
            reference_element: ID of the element this result is associated with
            load_case: Optional name of the load case for this result
        """
        super().__init__("reaction", reference_element)
        if load_case:
            self.add_metadata("load_case", load_case)

    def set_forces(self, forces: List[float]) -> None:
        """
        Set the reaction force values.

        Args:
            forces: List of force values [fx, fy, fz]
        """
        if len(forces) != 3:
            raise ValueError("Forces must be a list of 3 values [fx, fy, fz]")
        self.add_value("fx", forces[0])
        self.add_value("fy", forces[1])
        self.add_value("fz", forces[2])

    def set_moments(self, moments: List[float]) -> None:
        """
        Set the reaction moment values.

        Args:
            moments: List of moment values [mx, my, mz]
        """
        if len(moments) != 3:
            raise ValueError("Moments must be a list of 3 values [mx, my, mz]")
        self.add_value("mx", moments[0])
        self.add_value("my", moments[1])
        self.add_value("mz", moments[2])

    def get_forces(self) -> List[float]:
        """
        Get the reaction force values.

        Returns:
            List of force values [fx, fy, fz]
        """
        return [
            self.get_value("fx") if self.has_value("fx") else 0.0,
            self.get_value("fy") if self.has_value("fy") else 0.0,
            self.get_value("fz") if self.has_value("fz") else 0.0,
        ]

    def get_moments(self) -> List[float]:
        """
        Get the reaction moment values.

        Returns:
            List of moment values [mx, my, mz]
        """
        return [
            self.get_value("mx") if self.has_value("mx") else 0.0,
            self.get_value("my") if self.has_value("my") else 0.0,
            self.get_value("mz") if self.has_value("mz") else 0.0,
        ]

    def get_force_magnitude(self) -> float:
        """
        Calculate the magnitude of the reaction force.

        Returns:
            Magnitude of the force vector
        """
        forces = self.get_forces()
        import math

        return math.sqrt(sum(f * f for f in forces))

    def get_moment_magnitude(self) -> float:
        """
        Calculate the magnitude of the reaction moment.

        Returns:
            Magnitude of the moment vector
        """
        moments = self.get_moments()
        import math

        return math.sqrt(sum(m * m for m in moments))

    def validate(self) -> bool:
        """
        Validate the reaction force result.

        Returns:
            True if the result is valid, False otherwise
        """
        base_valid = super().validate()
        return base_valid and (
            self.has_value("fx")
            or self.has_value("fy")
            or self.has_value("fz")
            or self.has_value("mx")
            or self.has_value("my")
            or self.has_value("mz")
        )
