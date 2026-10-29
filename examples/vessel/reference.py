import cadquery as cq
import math

# --- PARAMETERS (mm) ---
shell_d = 800.0         # shell outside diameter [description]
shell_h = 1500.0        # straight shell height [description]
head_h = 200.0          # 2:1 ellipsoidal head height = D/4 [description]
leg_s = 100.0           # square leg size [description]
leg_l = 400.0           # leg length below the bottom head [description]
top_nz_d = 114.3        # top nozzle OD, 100A [description]
top_nz_h = 150.0        # top nozzle height above the head [description]
side_nz_d = 60.5        # side nozzle OD, 50A [description]
side_nz_z = 300.0       # side nozzle height above the bottom tangent line [description]
side_nz_r = 600.0       # side nozzle projection from the vessel axis [description]
# --- END PARAMETERS ---

z0 = leg_l + head_h                                  # bottom tangent line
r = shell_d / 2
shell = cq.Workplane("XY", origin=(0, 0, z0)).circle(r).extrude(shell_h)
head = cq.Solid.makeSphere(1.0, angleDegrees1=0, angleDegrees2=90)
top = cq.Workplane().add(head.scale(1.0)).val().transformGeometry(cq.Matrix([[r, 0, 0, 0], [0, r, 0, 0], [0, 0, head_h, z0 + shell_h]]))
bot = cq.Workplane().add(head).val().transformGeometry(cq.Matrix([[r, 0, 0, 0], [0, r, 0, 0], [0, 0, -head_h, z0]]))
body = shell.union(cq.Workplane().add(top)).union(cq.Workplane().add(bot))
legs = cq.Workplane("XY").polarArray(r - leg_s / 2, 45, 360, 4).rect(leg_s, leg_s).extrude(z0 + 50)
nz_top = cq.Workplane("XY", origin=(0, 0, z0 + shell_h + head_h - 20)).circle(top_nz_d / 2).extrude(top_nz_h + 20)
nz_side = cq.Workplane("YZ", origin=(0, 0, z0 + side_nz_z)).circle(side_nz_d / 2).extrude(side_nz_r)
result = body.union(legs).union(nz_top).union(nz_side)
