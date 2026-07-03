Title: gen3delem.f: *USER ELEMENT (TYPE=U1) crashes with "first thickness ... is zero" when mixed with any other 1D/2D element

Body:

`gen3delem.f`'s node-count filter excludes `C3D`/`D`/`G`/`E`/`MASS` prefixes but not `U` (user elements):

```fortran
if((lakon(i)(1:2).ne.'C3').and.(lakon(i)(1:1).ne.'D').and.
 &     (lakon(i)(1:1).ne.'G').and.(lakon(i)(1:1).ne.'E').and.
 &     (lakon(i)(1:4).ne.'MASS')) then
```

For a `TYPE=U1` element, none of the following `if/elseif` branches match its `lakon` string, so `numnod` is never assigned that iteration — it keeps whatever value the *previous* element left it at. The loop then checks `thicke(1,indexe+j)` for `j=1..numnod`, but `*BEAM SECTION,SECTION=GENERAL` (the only section card valid for U1) never populates `thicke` (see `beamgeneralsections.f`, skipped via `if(section.ne.'GENE')`). That value is always `0.d0`, so the check always fails: `*ERROR in gen3delem: first thickness in node N of element M is zero`.

Effect: any model with a U1 element *and* any other 1D/2D element (B31, S3, ...) crashes — regardless of element ID order. A model with only U1 elements works fine.

**Repro:** one B31 + one U1 element (both with valid sections/material) in the same `.inp` → crashes. Delete the B31 → succeeds.

**Fix:** exclude `U`-prefixed lakon entries the same way the others are excluded:

```diff
--- a/src/gen3delem.f
+++ b/src/gen3delem.f
@@ -119,7 +119,8 @@
           if(ipkon(i).lt.0) cycle
           if((lakon(i)(1:2).ne.'C3').and.(lakon(i)(1:1).ne.'D').and.
      &         (lakon(i)(1:1).ne.'G').and.(lakon(i)(1:1).ne.'E').and.
-     &         (lakon(i)(1:4).ne.'MASS')) then
+     &         (lakon(i)(1:4).ne.'MASS').and.
+     &         (lakon(i)(1:1).ne.'U')) then
```

Verified by rebuilding CalculiX 2.23 with this change: fixes the minimal repro and a real ~730-element mixed B31+S3+U1 model that previously failed identically. Confirmed still present in current `master` (commit `6d460bc`).
