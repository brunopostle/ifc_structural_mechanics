# Structural Analysis Functionality for IFC: Implementation Proposal

## 1. Executive Summary

This proposal outlines a plan to provide IFC structural analysis capabilities by leveraging existing IFC structural models and integrating with the open-source CalculiX finite element solver. The implementation will provide a headless workflow for processing structural models, analyzing them using CalculiX, and reporting analysis success or failure with appropriate error handling.

## 2. Background and Objectives

Bonsai BIM currently offers basic tools to edit and create `IfcStructuralAnalysisModel` objects and their associated entities. This proposal aims to extend this functionality to provide a structural analysis workflow that can be operated independently of the Bonsai UI.

**Primary Objectives:**
- Process structural analysis models from IFC files
- Transform IFC structural elements into CalculiX input format
- Execute CalculiX analysis as a subprocess
- Report analysis success or failure with appropriate error handling
- Provide access to raw result files for further processing

**Secondary Objectives:**
- Ensure adequate performance for reasonably sized models
- Implement validation mechanisms to verify analysis input
- Establish a foundation for future expansion of analysis types
- Create a clear API for future integration

## 3. Technical Approach

### 3.1 Architectural Overview

The revised architecture focuses on a clear data flow between components with well-defined interfaces:

1. **Input Processing**: 
   - IFC file → Structural domain model representation
   - Domain model includes structural elements, connections, loads, and properties

2. **Analysis Preparation**:
   - Domain model → Gmsh geometry → Finite element mesh → CalculiX input (.inp file)
   - Clear mapping rules from domain entities to FEA entities

3. **Analysis Execution**:
   - CalculiX input → CalculiX solver → Raw results files
   
4. **Results Processing**:
   - Parse CalculiX output for errors and warnings
   - Report success/failure status with detailed information

This staged approach allows for clear interfaces between components and easier testing of each stage.

### 3.2 Domain Model and Mapping Schema

A critical addition is the explicit domain model that serves as an intermediate representation between IFC and analysis formats:

```python
# Example domain model class for a structural member
class StructuralMember:
    """Domain model for structural members extracted from IFC."""
    def __init__(self, id, type, geometry, material, section=None):
        self.id = id  # Unique identifier
        self.type = type  # "curve" or "surface"
        self.geometry = geometry  # Geometry representation
        self.material = material  # Material properties
        self.section = section  # Section properties (for curve members)
        self.boundary_conditions = []  # Applied boundary conditions
        self.loads = []  # Applied loads
```

Explicit mapping schema definitions will control the transformation between:
- IFC entities → Domain model objects
- Domain model objects → Gmsh geometry
- Domain model objects → CalculiX elements

These mapping schemas will be configured separately from the implementation code to improve maintainability.

### 3.3 Data Translation Framework

#### IFC to Domain Model Translator

A structured set of extractors will convert IFC entities to domain model objects:

1. Extract geometry from IFC structural elements
2. Extract material and section properties
3. Extract boundary conditions
4. Extract loads and load cases

These extractors will operate on specific IFC entity types and produce domain model objects.

#### Domain Model to CalculiX Translator

A separate set of processors will convert domain model objects to CalculiX input:

1. Generate node definitions from geometry
2. Create element definitions based on member types
3. Apply material and section properties
4. Define boundary conditions
5. Configure load cases and combinations

Next, implement the mapping modules in src/ifc_structural_mechanics/mapping/ with:
1. domain_to_gmsh.py: Maps domain model entities to Gmsh geometry
   - Maintains bidirectional mapping for tracing errors back to domain model
   - Preserves entity identity through the meshing process

2. domain_to_calculix.py: Maps domain model entities to CalculiX elements
   - Links CalculiX elements and nodes to original domain entities
   - Enables tracing analysis errors back to source elements

### 3.4 Meshing Strategy

The meshing process will be clearly defined:

1. **Domain Model to Gmsh Geometry**:
   - Convert domain model geometry to Gmsh geometry format
   - Apply meshing parameters based on element types and properties

2. **Mesh Generation**:
   - Execute Gmsh with appropriate parameters
   - Manage the subprocess with clear error handling

3. **Mesh Conversion**:
   - Convert Gmsh output to CalculiX mesh format
   - Map domain properties to mesh elements

Each step will have well-defined inputs, outputs, and error handling.

### 3.5 Analysis Execution

Analysis execution will be separated into:

1. **Input Preparation**:
   - Generate complete CalculiX input file from mesh and analysis parameters
   - Configure solver settings based on analysis type

2. **Solver Execution**:
   - Run CalculiX as a subprocess
   - Implement robust error detection and recovery
   - Capture and parse solver output for errors and warnings

### 3.6 Error Handling and Reporting

The system will provide comprehensive error handling:

1. **Error Detection**:
   - Detect errors at each stage of the pipeline
   - Identify common issues in CalculiX output

2. **User-Friendly Reporting**:
   - Provide clear, contextual error messages
   - Distinguish between warnings and critical errors

3. **Cleanup**:
   - Ensure proper cleanup of temporary files
   - Graceful termination in error situations

### 3.7 Configuration Management

A dedicated configuration system will manage:

1. **Analysis Settings**:
   - Analysis type (linear static, etc.)
   - Solver parameters

2. **Meshing Parameters**:
   - Element types and sizes
   - Mesh quality settings

3. **Process Management**:
   - Subprocess timeouts and retries
   - Error handling policies

## 4. Implementation Plan

### 4.1 Repository Structure

The repository structure reflects the architecture:

```
ifc_structural_mechanics/
├── LICENSE                   # Open source license
├── README.md                 # Project documentation
├── pyproject.toml            # Project configuration and dependencies
├── setup.py                  # Package installation
├── .github/                  # GitHub configuration
│   └── workflows/            # CI/CD workflows
│       ├── test.yml          # Automated testing
│       └── lint.yml          # Code quality checks
├── docs/                     # Documentation
│   ├── index.md              # Getting started guide
│   ├── developer_guide.md    # Development guidelines
│   ├── mapping_schemas.md    # Entity mapping documentation
│   ├── api_reference.md      # API reference
│   └── examples/             # Example models and usage
├── src/                      # Source code
│   └── ifc_structural_mechanics/    # Main package
│       ├── __init__.py       # Package initialization
│       ├── domain/           # Domain model definitions
│       │   ├── __init__.py
│       │   ├── structural_model.py     # Core model container
│       │   ├── structural_member.py    # Member models
│       │   ├── structural_connection.py # Connection models
│       │   ├── load.py                 # Load models
│       │   ├── property.py             # Property models
│       │   └── result.py               # Result models
│       ├── ifc/             # IFC processing modules
│       │   ├── __init__.py
│       │   ├── extractor.py            # Core extraction coordinator
│       │   ├── entity_identifier.py    # Entity type identification
│       │   ├── members_extractor.py    # Extract structural members
│       │   ├── connections_extractor.py # Extract connections
│       │   ├── loads_extractor.py      # Extract load groups
│       │   ├── properties_extractor.py # Extract materials and sections
│       │   ├── geometry/              # IFC-specific geometry utilities
│       │   │   ├── __init__.py
│       │   │   ├── curve_geometry.py   # Curve extraction
│       │   │   ├── surface_geometry.py # Surface extraction
│       │   │   └── topology.py         # Topology extraction
│       │   └── results_writer.py       # Write results back to IFC
│       ├── meshing/         # Meshing modules
│       │   ├── __init__.py
│       │   ├── gmsh_geometry.py        # Domain to Gmsh geometry converter
│       │   ├── gmsh_runner.py          # Gmsh subprocess controller
│       │   └── mesh_converter.py       # Mesh format converter
│       ├── analysis/        # Analysis modules
│       │   ├── __init__.py
│       │   ├── calculix_input.py       # Generate CalculiX input files
│       │   ├── calculix_runner.py      # CalculiX subprocess controller
│       │   └── results_parser.py       # Parse results files
│       ├── visualization/   # Visualization modules
│       │   ├── __init__.py
│       │   └── paraview_exporter.py    # Export to ParaView
│       ├── mapping/         # Mapping schemas and utilities
│       │   ├── __init__.py
│       │   ├── ifc_to_domain.py        # IFC to domain model mappings
│       │   ├── domain_to_gmsh.py       # Domain model to Gmsh mappings
│       │   └── domain_to_calculix.py   # Domain model to CalculiX mappings
│       ├── config/          # Configuration handling
│       │   ├── __init__.py
│       │   ├── analysis_config.py      # Analysis configuration
│       │   ├── meshing_config.py       # Meshing configuration
│       │   └── system_config.py        # System configuration
│       ├── cli/             # Command-line interface
│       │   ├── __init__.py
│       │   └── commands.py             # CLI commands
│       ├── api/             # Public API for integration
│       │   ├── __init__.py
│       │   └── structural_analysis.py  # Main API
│       └── utils/           # Utility functions
│           ├── __init__.py
│           ├── subprocess_utils.py     # Subprocess management
│           ├── error_handling.py       # Error management
│           └── file_utils.py           # File operations
├── tests/                   # Test directory
│   ├── conftest.py          # Test configuration
│   ├── test_data/           # Test data files
│   │   ├── simple_beam.ifc  # Simple beam model for testing
│   │   └── frame.ifc        # Frame structure for testing
│   ├── unit/                # Unit tests
│   │   ├── domain/          # Domain model tests
│   │   │   ├── test_structural_model.py
│   │   │   ├── test_structural_member.py
│   │   │   ├── test_structural_connection.py
│   │   │   ├── test_load.py
│   │   │   ├── test_property.py
│   │   │   └── test_result.py
│   │   ├── ifc/             # IFC tests
│   │   │   ├── test_extractor.py
│   │   │   ├── test_entity_identifier.py
│   │   │   ├── test_members_extractor.py
│   │   │   ├── test_connections_extractor.py
│   │   │   ├── test_loads_extractor.py
│   │   │   ├── test_properties_extractor.py
│   │   │   ├── geometry/
│   │   │   │   ├── test_curve_geometry.py
│   │   │   │   ├── test_surface_geometry.py
│   │   │   │   └── test_topology.py
│   │   │   └── test_results_writer.py
│   │   ├── meshing/         # Meshing tests
│   │   │   ├── test_gmsh_geometry.py
│   │   │   ├── test_gmsh_runner.py
│   │   │   └── test_mesh_converter.py
│   │   ├── analysis/        # Analysis tests
│   │   │   ├── test_calculix_input.py
│   │   │   ├── test_calculix_runner.py
│   │   │   └── test_results_parser.py
│   │   ├── mapping/         # Mapping tests
│   │   │   ├── test_ifc_to_domain.py
│   │   │   ├── test_domain_to_gmsh.py
│   │   │   └── test_domain_to_calculix.py
│   │   ├── config/          # Configuration tests
│   │   │   ├── test_analysis_config.py
│   │   │   ├── test_meshing_config.py
│   │   │   └── test_system_config.py
│   │   └── utils/           # Utility tests
│   │       ├── test_subprocess_utils.py
│   │       ├── test_error_handling.py
│   │       └── test_file_utils.py
│   └── integration/         # Integration tests
│       ├── test_extraction_pipeline.py  # IFC to domain model
│       ├── test_meshing_workflow.py     # Domain model to mesh
│       ├── test_analysis_workflow.py    # Mesh to analysis results
│       └── test_end_to_end.py           # Complete workflow
├── examples/                # Example scripts
│   ├── simple_beam_analysis.py  # Analyze a simple beam
│   ├── frame_analysis.py        # Analyze a frame structure
│   └── surface_analysis.py      # Analyze a surface structure
└── scripts/                 # Utility scripts
    ├── install_dependencies.sh  # Install external dependencies
    └── check_environment.py     # Check for required tools
```

### 4.2 Development Phases

The implementation will proceed in phases, with each phase building upon the previous one and delivering a working system with increasing capabilities.

#### Phase 1: Core Domain Model & Basic IFC Extraction

This phase establishes the foundation of the system by implementing the domain model and basic IFC extraction.

**Tasks:**
1. Implement domain model classes
2. Create IFC entity identification utilities
3. Implement geometry extraction utilities
4. Create basic extractors for members, properties, and loads
5. Develop a main extractor coordinator

**Deliverables:**
- Working domain model with clear interfaces
- Basic IFC extraction for simple structural elements
- Unit tests for all implemented components

#### Phase 2: Meshing and Analysis Pipeline

This phase implements the meshing and analysis pipeline.

**Tasks:**
1. Implement domain model to Gmsh geometry conversion
2. Create Gmsh process runner with error handling
3. Develop mesh converter for CalculiX format
4. Implement CalculiX input file generator
5. Create CalculiX process runner with error handling
6. Develop output parser for detecting errors and warnings

**Deliverables:**
- Complete meshing pipeline with error handling
- Working analysis execution with proper process management
- Error detection and reporting system

#### Phase 3: API, CLI, and Documentation

This phase creates the user-facing components and documentation.

**Tasks:**
1. Implement a clean, simple API for the core workflow
2. Create a command-line interface using Click
3. Develop comprehensive documentation and examples
4. Implement integration tests for the complete workflow

**Deliverables:**
- Public API for integrating the functionality
- Command-line tool for direct usage
- Documentation and examples
- Comprehensive test suite

### 4.3 Dependencies and Requirements

**Core Dependencies:**
- CalculiX (CCX executable)
- Gmsh with Python API
- IfcOpenShell for IFC processing
- NumPy/SciPy for numerical operations

**Development Dependencies:**
- pytest for testing
- Black for code formatting
- Sphinx for documentation generation

**Installation Requirements:**
- Define clear installation procedures for external dependencies
- Create configuration discovery for Gmsh and CalculiX executables
- Provide fallback options when dependencies are missing

## 5. Challenges and Risk Mitigation

### 5.1 Technical Challenges

**Complex Geometry Handling**:
- **Risk**: IFC geometric representations may not translate cleanly to Gmsh
- **Mitigation**: Implement geometry simplification where needed
- **Tests**: Create test cases with complex IFC geometries

**Subprocess Management**:
- **Risk**: Subprocess failures could be difficult to diagnose
- **Mitigation**: Implement robust logging and error capturing
- **Tests**: Create failure scenario tests for each subprocess

**Error Detection**:
- **Risk**: CalculiX errors may be difficult to parse and interpret
- **Mitigation**: Develop comprehensive error pattern matching
- **Tests**: Create tests with known error conditions

### 5.2 Initial Limitations

1. Support limited to linear static analysis
2. Basic element types only (beams, shells)
3. Simple loading conditions
4. External validation required for complex models
5. Command-line interface only (no GUI)

### 5.3 Error Handling Strategy

The OutputParser should be able to identify issues and associate them with the original IFC entities. This requires maintaining the mapping information throughout the analysis pipeline so that error messages can include references to the original IFC entities. For example, an error related to a negative jacobian in element 42 should be traced back to the specific IFC structural member that was mapped to that element.

## 6. Future Extensions

Potential future enhancements include:
1. Support for dynamic analysis
2. Non-linear material behavior
3. Additional solver backends
4. Result visualization integration
5. Parallel processing for improved performance

## 7. Conclusion

This revised proposal focuses on creating a clean, robust workflow for structural analysis of IFC models. By emphasizing a clear domain model, robust error handling, and a simple API, the implementation will provide a solid foundation for structural analysis capabilities with CalculiX.

The modular architecture with explicit interfaces will make the implementation more maintainable and testable, while providing a solid foundation for future extensions.

## Appendix A: Example API Usage

```python
from ifc_structural_mechanics.api import analyze_ifc

# Run analysis on an IFC file
result = analyze_ifc(
    ifc_path="path/to/model.ifc",
    output_dir="path/to/output",
    analysis_type="linear_static",
    mesh_size=0.1,
    verbose=True
)

# Check result
if result["status"] == "success":
    print("Analysis completed successfully")
    print(f"Output files: {result['output_files']}")
    
    # Raw output files can be processed with external tools
    frd_file = result["output_files"].get("Results database")
    if frd_file:
        print(f"Results database available at {frd_file}")
        # Use external tools for visualization or further processing
else:
    print("Analysis failed")
    for error in result["errors"]:
        print(f"Error: {error}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}")
```

## Appendix B: Example CLI Usage

```bash
# Basic usage
ifc-analysis path/to/model.ifc path/to/output

# With options
ifc-analysis path/to/model.ifc path/to/output --analysis-type=linear_static --mesh-size=0.1 --verbose
```
