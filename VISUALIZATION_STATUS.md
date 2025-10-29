# Visualization Status

## Current Session Summary (2025-10-29)

### Completed ✓

1. **Fixed node ID mapping for stress visualization**
   - Problem: CalculiX FRD results use different node IDs than Gmsh mesh
   - Solution: Implemented coordinate-based mapping between INP and FRD nodes
   - Result: Stress visualization now works correctly
     - Undistorted mesh ✓
     - Physically reasonable stress distribution (higher at bottom corners/supports) ✓
     - Credible stress range: 0 to 600 kPa ✓

2. **Updated `ResultVisualizer.load_mesh_from_frd()`**
   - Reads both FRD (for node coordinates) and INP (for element connectivity)
   - Creates coordinate-based mapping with 0.15m tolerance (handles CalculiX mesh refinement)
   - Stores mapping in `self._inp_node_to_frd_node` for use in result mapping

3. **Updated `apply_displacement_field()` and `add_stress_field()`**
   - Now use INP-to-FRD node mapping when available
   - Fallback to direct ID mapping if not using FRD loader

4. **Test suite passing**: 453 tests pass

### Current Issue ⚠️

**Displacement visualization shows near-zero values (1e-10 to 1e-15 meters)**

- Visualization works (mesh undistorted, pattern looks contiguous/non-random)
- BUT displacement magnitude is far too small (femtometers instead of ~10mm)
- Raw FRD file contains values like `1.82482E-15` which is essentially numerical noise

**Possible causes:**
1. No loads applied to the model (or loads are missing)
2. Model is over-constrained (too many boundary conditions)
3. Unit conversion issue
4. Wrong load case selected (building_01 might not have loads)

### Next Steps

1. **Investigate why displacements are so small:**
   - Check if building_01.ifc has any loads defined
   - Check INP file for load definitions (*CLOAD, *DLOAD sections)
   - Verify boundary conditions aren't over-constraining the model
   - Try building_02.ifc which is known to have multiple load cases

2. **Multiple load cases support:**
   - User mentioned building_02 has multiple load cases
   - Need to parse multiple PSTEP sections from FRD
   - Add UI to select which load case to visualize

3. **Add deformed mesh visualization:**
   - Once displacement values are correct, show displaced geometry at 10x or 100x scale
   - User mentioned "usually you look at a displacement model at 1x or 10x displacement"

## Files Modified

- `src/ifc_structural_mechanics/visualization/result_visualizer.py`
  - Added `load_mesh_from_frd()` method
  - Updated `apply_displacement_field()` with coordinate mapping
  - Updated `add_stress_field()` with coordinate mapping

- `visualize_from_frd.py` (new)
  - Test script for FRD-based visualization
  - Currently shows displacement (can switch to stress by uncommenting)

## Key Learnings

1. CalculiX renumbers and refines nodes - FRD has ~8900 nodes vs INP's 596 nodes
2. Coordinate-based mapping works well with 0.15m tolerance
3. FRD file format uses fixed-width columns, not space-separated
4. Stress visualization is working correctly and verified by user

## Commands to Resume

```bash
# View stress (working):
# Edit visualize_from_frd.py to set field='Von Mises Stress' and call viz.add_stress_field()
python visualize_from_frd.py

# View displacement (shows near-zero values):
python visualize_from_frd.py

# Check loads in INP file:
grep -A 10 "^\*CLOAD\|^\*DLOAD" results_building_01/analysis.inp

# Try building_02 which has multiple load cases:
# First need to run analysis on building_02.ifc
```

## Commit Status

Last commit: `2dd7321` - "Fix visualization node ID mapping using coordinate-based approach"
