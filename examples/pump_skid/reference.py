import cadquery as cq

# --- PARAMETERS (mm) ---
frame_l = 1400.0        # base frame length [drawing]
frame_w = 700.0         # base frame width [drawing]
frame_h = 120.0         # base frame height [drawing]
flange_t = 12.0         # channel flange / top plate thickness [assumed]
motor_d = 300.0         # motor body diameter [drawing]
motor_l = 520.0         # motor body length [drawing]
motor_x = -310.0        # motor centre along X [drawing]
ped_h = 70.0            # motor pedestal height [drawing]
pump_l = 380.0          # pump casing length [drawing]
pump_w = 300.0          # pump casing width [drawing]
pump_h = 340.0          # pump casing height [drawing]
pump_x = 390.0          # pump centre along X [drawing]
anchor_d = 24.0         # anchor bolt holes [drawing]
# --- END PARAMETERS ---

axis_z = frame_h + ped_h + motor_d / 2
frame = (cq.Workplane("XY").box(frame_l, frame_w, frame_h, centered=(True, True, False))
         .faces(">Z").workplane().rect(frame_l - 2 * flange_t, frame_w - 2 * flange_t).cutBlind(-(frame_h - flange_t))
         .faces("<Z").workplane().rect(frame_l - 100, frame_w - 100, forConstruction=True).vertices().hole(anchor_d))
ped = cq.Workplane("XY", origin=(motor_x, 0, frame_h)).rect(motor_l * 0.8, motor_d * 0.8).extrude(ped_h)
motor = cq.Workplane("YZ", origin=(motor_x - motor_l / 2, 0, axis_z)).circle(motor_d / 2).extrude(motor_l)
pump = cq.Workplane("XY", origin=(pump_x, 0, frame_h)).rect(pump_l, pump_w).extrude(pump_h)
shaft = cq.Workplane("YZ", origin=(motor_x + motor_l / 2, 0, axis_z)).circle(30).extrude(pump_x - pump_l / 2 - motor_x - motor_l / 2)

assembly = cq.Assembly(name="pump_skid")
assembly.add(frame, name="base_frame", color=cq.Color("gray50"))
assembly.add(ped, name="motor_pedestal", color=cq.Color("gray50"))
assembly.add(motor, name="motor", color=cq.Color("steelblue"))
assembly.add(pump, name="pump", color=cq.Color("orange"))
assembly.add(shaft, name="coupling", color=cq.Color("lightgray"))
