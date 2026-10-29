import cadquery as cq

# --- PARAMETERS (mm) ---
d1 = 40.0               # first journal diameter [description]
l1 = 60.0               # first journal length [description]
d2 = 50.0               # middle section diameter [description]
l2 = 150.0              # middle section length [description]
d3 = 45.0               # third section diameter [description]
l3 = 40.0               # third section length [description]
d4 = 35.0               # end section diameter [description]
l4 = 70.0               # end section length [description]
chamfer = 1.0           # end chamfers [description]
key_w = 10.0            # keyway width [description]
key_t = 5.0             # keyway depth [description]
key_l = 50.0            # keyway length [description]
# --- END PARAMETERS ---

prof = [(0, 0), (0, d1 / 2), (l1, d1 / 2), (l1, d2 / 2), (l1 + l2, d2 / 2), (l1 + l2, d3 / 2),
        (l1 + l2 + l3, d3 / 2), (l1 + l2 + l3, d4 / 2), (l1 + l2 + l3 + l4, d4 / 2), (l1 + l2 + l3 + l4, 0)]
shaft = cq.Workplane("XY").polyline(prof).close().revolve(360, (0, 0, 0), (1, 0, 0))
shaft = shaft.faces("<X or >X").chamfer(chamfer)
key = (cq.Workplane("XY", origin=(l1 + l2 / 2, 0, d2 / 2 - key_t)).slot2D(key_l, key_w).extrude(key_t + 1))
result = shaft.cut(key)
