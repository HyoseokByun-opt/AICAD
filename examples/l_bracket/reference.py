import cadquery as cq

# --- PARAMETERS (mm) ---
leg_x = 100.0           # horizontal leg length [drawing]
leg_z = 80.0            # vertical leg height [drawing]
width = 60.0            # bracket width [drawing]
t = 10.0                # wall thickness (not dimensioned on the drawing) [ratio]
hole_d = 11.0           # hole diameter [drawing]
hole_x = 65.0           # hole position on the base from the back face [drawing]
hole_z = 50.0           # hole height on the upright [drawing]
hole_s = 30.0           # hole spacing across the width [drawing]
# --- END PARAMETERS ---

prof = [(0, 0), (leg_x, 0), (leg_x, t), (t, t), (t, leg_z), (0, leg_z)]
body = cq.Workplane("XZ").polyline(prof).close().extrude(-width / 2, both=True)
body = body.edges("|Y").edges(cq.selectors.NearestToPointSelector((t, 0, t))).fillet(8)
base_holes = cq.Workplane("XY").pushPoints([(hole_x, -hole_s / 2), (hole_x, hole_s / 2)]).circle(hole_d / 2).extrude(t)
up_holes = cq.Workplane("YZ").pushPoints([(-hole_s / 2, hole_z), (hole_s / 2, hole_z)]).circle(hole_d / 2).extrude(t)
result = body.cut(base_holes).cut(up_holes)
