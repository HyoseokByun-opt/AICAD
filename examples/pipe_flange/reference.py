import cadquery as cq
import math

# --- PARAMETERS (mm) ---
od = 250.0              # flange outer diameter [drawing]
t = 24.0                # flange thickness [drawing]
hub_d = 140.0           # hub diameter [drawing]
hub_h = 50.0            # hub height above the flange [drawing]
bore = 90.0             # bore diameter [drawing]
pcd = 205.0             # bolt circle diameter [drawing]
bolt_d = 22.0           # bolt hole diameter [drawing]
n = 8                   # number of bolt holes [drawing]
# --- END PARAMETERS ---

prof = [(bore / 2, 0), (od / 2, 0), (od / 2, t), (hub_d / 2, t), (hub_d / 2, t + hub_h), (bore / 2, t + hub_h)]
body = cq.Workplane("XZ").polyline(prof).close().revolve(360, (0, 0, 0), (0, 1, 0))
pts = [(pcd / 2 * math.cos(2 * math.pi * (i + 0.5) / n), pcd / 2 * math.sin(2 * math.pi * (i + 0.5) / n)) for i in range(n)]
result = body.cut(cq.Workplane("XY").pushPoints(pts).circle(bolt_d / 2).extrude(t))
