import cadquery as cq
import aicad_lib as lib

# --- PARAMETERS (mm) ---
a = 4000.0              # leg spacing, square [description]
h = 9000.0              # height to the top of the legs [description]
leg = "PIPE273x9.3"     # legs [description]
brace = "PIPE168.3x7.1" # horizontal braces at each level [description]
diag = "PIPE114.3x6"    # X-braces in every face and bay [description]
deck_t = 12.0           # deck plate thickness [description]
deck_w = 4400.0         # deck plate size, square [description]
tank_d = 2000.0         # tank diameter [description]
tank_h = 2500.0         # tank straight height [description]
tank_t = 10.0           # tank wall thickness [description]
# --- END PARAMETERS ---

levels = [0.0, 3000.0, 6000.0, h]
corners = [(0.0, 0.0), (a, 0.0), (a, a), (0.0, a)]
nodes = {f"{i}_{k}": (x, y, z) for k, z in enumerate(levels) for i, (x, y) in enumerate(corners)}
members = []
for i in range(4):
    for k in range(3):
        members.append((f"{i}_{k}", f"{i}_{k + 1}", leg))
for k in range(1, 4):
    for i in range(4):
        members.append((f"{i}_{k}", f"{(i + 1) % 4}_{k}", brace))
for k in range(3):
    for i in range(4):
        j = (i + 1) % 4
        members.append((f"{i}_{k}", f"{j}_{k + 1}", diag))
        members.append((f"{j}_{k}", f"{i}_{k + 1}", diag))
tower = lib.frame(nodes, members)
c = a / 2
# the deck plate is centred on the top of the legs (its mid-plane at z = h)
deck = lib.plate([(c - deck_w / 2, c - deck_w / 2), (c + deck_w / 2, c - deck_w / 2),
                  (c + deck_w / 2, c + deck_w / 2), (c - deck_w / 2, c + deck_w / 2)], deck_t, z=h - deck_t / 2)
tank = lib.vessel((c, c, h + deck_t / 2 + tank_d / 4), tank_d, tank_h, t=tank_t)

assembly = cq.Assembly(name="tubular_tower")
assembly.add(tower.val(), name="tower", color=cq.Color("steelblue"))
assembly.add(deck.val(), name="deck", color=cq.Color("gray"))
assembly.add(tank.val(), name="tank", color=cq.Color("lightgray"))
