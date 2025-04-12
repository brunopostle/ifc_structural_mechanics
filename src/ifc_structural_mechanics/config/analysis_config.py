from typing import Dict, Any, Optional, Union
import yaml
import os
from .base_config import BaseConfig


class AnalysisConfig(BaseConfig):
    """
    Configuration management for structural analysis settings.

    Handles analysis type, solver parameters, and result output settings.
    """

    ANALYSIS_TYPES = {
        "linear_static": {
            "description": "Linear static structural analysis",
            "default_solver_params": {
                "max_iterations": 100,
                "convergence_tolerance": 1e-6,
                "divergence_tolerance": 1e3,
            },
        },
        "linear_buckling": {
            "description": "Linear buckling analysis",
            "default_solver_params": {"num_eigenvalues": 5, "solver_method": "lanczos"},
        },
    }

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration dictionary.

        Returns:
            Dict[str, Any]: Default configuration dictionary.
        """
        return {
            "analysis_type": "linear_static",
            "solver_params": self.ANALYSIS_TYPES["linear_static"][
                "default_solver_params"
            ],
            "result_output": {
                "displacement": True,
                "stress": True,
                "strain": False,
                "reaction_forces": False,
            },
        }

    def validate(self) -> None:
        """
        Validate the analysis configuration.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        # Validate analysis type with default fallback
        analysis_type = self._config.get("analysis_type", "linear_static")
        if analysis_type not in self.ANALYSIS_TYPES:
            raise ValueError(
                f"Invalid analysis type: {analysis_type}. "
                f"Supported types: {list(self.ANALYSIS_TYPES.keys())}"
            )

        # Validate solver parameters based on analysis type
        solver_params = self._config.get("solver_params", {})
        default_params = self.ANALYSIS_TYPES[analysis_type]["default_solver_params"]

        # Validate required keys and types
        for param, default_value in default_params.items():
            if param not in solver_params:
                solver_params[param] = default_value

            # Type checking and conversion
            try:
                # Try to convert to the correct type
                if not isinstance(solver_params[param], type(default_value)):
                    solver_params[param] = type(default_value)(solver_params[param])
            except (TypeError, ValueError):
                raise ValueError(
                    f"Invalid type for solver parameter {param}. "
                    f"Expected {type(default_value)}, "
                    f"got {type(solver_params[param])}"
                )

        # Update solver params
        self._config["solver_params"] = solver_params

        # Validate result output settings with defaults
        default_result_output = {
            "displacement": True,
            "stress": True,
            "strain": False,
            "reaction_forces": False,
        }
        result_output = self._config.get("result_output", default_result_output)

        # Ensure all default types are present
        for key, default_value in default_result_output.items():
            if key not in result_output:
                result_output[key] = default_value

        # Validate result output types
        valid_result_types = list(default_result_output.keys())
        for result_type, value in list(result_output.items()):
            # Remove any unexpected result types
            if result_type not in valid_result_types:
                del result_output[result_type]

            # Ensure boolean type
            if not isinstance(value, bool):
                try:
                    result_output[result_type] = bool(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"Result output for {result_type} must be a boolean"
                    )

        # Update result output in config
        self._config["result_output"] = result_output

        # Ensure analysis type and solver params are set
        self._config["analysis_type"] = analysis_type

    def get_analysis_type(self) -> str:
        """
        Get the configured analysis type.

        Returns:
            str: The current analysis type.
        """
        return self._config["analysis_type"]

    def get_solver_params(self) -> Dict[str, Union[int, float, str]]:
        """
        Get the solver parameters for the current analysis type.

        Returns:
            Dict[str, Union[int, float, str]]: Solver parameters.
        """
        return self._config["solver_params"]

    def get_result_output_settings(self) -> Dict[str, bool]:
        """
        Get the result output settings.

        Returns:
            Dict[str, bool]: Result output settings.
        """
        return self._config["result_output"]

    def set_result_output(self, result_type: str, enabled: bool):
        """
        Enable or disable a specific result output type.

        Args:
            result_type (str): Type of result to configure.
            enabled (bool): Whether to enable or disable the result type.

        Raises:
            ValueError: If the result type is invalid.
        """
        self.validate()  # Ensure current config is valid

        # Validate result type
        valid_result_types = ["displacement", "stress", "strain", "reaction_forces"]
        if result_type not in valid_result_types:
            raise ValueError(f"Invalid result output type: {result_type}")

        # Update result output setting
        self._config["result_output"][result_type] = enabled
