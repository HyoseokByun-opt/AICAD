import cadquery as cq

# --- PARAMETERS (mm) ---
length = 240.0          # overall length [drawing]
width = 160.0           # overall width [drawing]
thickness = 16.0        # plate thickness [drawing]
corner_r = 10.0         # corner radius [drawing]
hole_d = 18.0           # mounting hole diameter [drawing]
hole_px = 180.0         # hole spacing along X [drawing]
hole_py = 100.0         # hole spacing along Y [drawing]
bore_d = 60.0           # central bore [drawing]
# --- END PARAMETERS ---

result = (cq.Workplane("XY").box(length, width, thickness, centered=(True, True, False))
          .edges("|Z").fillet(corner_r)
          .faces(">Z").workplane().rarray(hole_px, hole_py, 2, 2).hole(hole_d)
          .faces(">Z").workplane().hole(bore_d))
