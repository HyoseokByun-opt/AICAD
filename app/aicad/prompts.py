"""Instructions for the AI at each step.

    read     drawing image  -> specification (JSON): views, dimensions,
             features, and sheet points for sizes that are not written
    code     specification / description -> CadQuery script
    repair   failed script + error -> corrected script
    refine   drawing views next to the model's views -> corrected script
    edit     script + instruction -> changed script

The coordinate convention is the same everywhere and matches the
projections the program draws: X to the right in the front view, Y away
from the viewer (depth), Z up.
"""
from __future__ import annotations

AXES = """Coordinate system (use it everywhere):
- X: left to right in the FRONT view (width / length).
- Y: depth, from the front of the object towards the back (left to right in the RIGHT view).
- Z: up (height; vertical in the front and right views).
- Units: millimetres. The object stands on the XY plane (lowest point at z = 0) and is centred on X and Y,
  unless the drawing defines a datum, in which case that datum is the origin."""

# ---------------------------------------------------------------- reading
READ_SYSTEM = f"""You are a senior mechanical design engineer. You read engineering drawings of parts and
equipment (orthographic views, sections, details, outline drawings, catalogue sheets, hand sketches)
and prepare them for 3D CAD modelling.

{AXES}

Sheet coordinates: integers from 0 to 1000 relative to the image, x to the right and y downwards
(0,0 = top-left corner, 1000,1000 = bottom-right corner).

Answer with ONE JSON object and nothing else, with these keys:
{{
  "part_name": short name of the object (letters, digits, '-', '_'),
  "kind": "part" or "assembly" (several separate components, e.g. equipment on a base frame),
  "summary": one or two sentences: what the object is and how it is built in 3D,
  "units": "mm", "m", "inch" or "ft-in" (as written on the drawing; mm if not stated),
  "scale_bars": [ {{"p1": [x, y] at the zero mark, "p2": [x, y] at the mark of `length`, "length": number,
                   "unit": "mm|m|ft|in"}} ]  (graphic scale bars; [] if none),
  "projection": "third-angle", "first-angle" or "unknown",
  "drawing_scale": scale from the title block such as "1:2", or null,
  "views": [ {{"id": "V1", "type": "front|top|bottom|left|right|rear|section|detail|isometric|other",
              "box": [x0, y0, x1, y1], "label": text label under the view or ""}} ],
  "overall": {{"x": size or null, "y": size or null, "z": size or null}}  (a number in the drawing unit, or the
             text as written such as "168'-0\\""),
  "dimensions": [ {{"id": "D1", "name": snake_case name, "value": number, "type": "length|diameter|radius|angle|count|thread",
                   "axis": "x|y|z" or null, "view": view id, "text": the text exactly as written,
                   "describes": what the dimension measures}} ],
  "features": [ {{"id": "F1", "op": "base|boss|rib|cut|pocket|hole|slot|pattern|fillet|chamfer|revolve|shell|sweep|component|other",
                 "description": precise description with positions and sizes (refer to dimension ids),
                 "uses": ["D1", "D3"]}} ],
  "estimates": [ {{"id": "E1", "name": snake_case name, "describes": the size that is needed but not written,
                  "view": view id, "p1": [x, y], "p2": [x, y], "axis": "x|y|z" or null}} ],
  "notes": [ material, finish, thread specifications, general notes ],
  "questions": [ ambiguities a designer would ask about ]
}}

Rules:
1. "type" of a view is the side of the object the view shows, taking the projection method into account
   (in first-angle projection the top view is drawn BELOW the front view; in third-angle ABOVE it).
2. "box" encloses only the object's outline in that view: no dimension lines, leaders, text, title block or border.
3. Copy every dimension written on the drawing into "dimensions", with its number exactly as written
   (diameter values for Ø, radius values for R, the count for "4x" or "4-"). Never invent a number.
4. "overall" holds the overall extent of the object along X, Y and Z only where it is written (directly or
   as an obvious sum of chained dimensions); otherwise null.
5. For every size needed to model the object that is NOT written (thicknesses, positions, diameters of
   unlabelled features, heights in a view without dimensions), add an "estimates" entry with two sheet
   points p1 and p2 that span that size in one orthographic view. The program measures it on the sheet and
   scales it by the written dimensions. Place the points precisely on the lines that bound the size.
6. "features" is the ordered list of modelling operations a CAD designer would use, from the base solid to
   holes and edge breaks. For equipment outline drawings model the outer envelope and the main features
   (body, legs or skirt, base frame, nozzles and flanges, motor, anchor holes); internal details are not
   needed unless drawn.
7. If text extracted from the drawing file is supplied, its numbers are exact: use them.
8. Feet-and-inch drawings: always copy the text exactly (18'-10 1/2"); the program converts it. Inside JSON
   strings escape the inch mark: "18'-10 1/2\\"". A drawing without
   dimensions often has a graphic scale bar: report it in "scale_bars" - it gives every size by measurement.
"""


def read_user(texts_hint: str, extra: str) -> str:
    s = ("Read this drawing and return the JSON specification.")
    if texts_hint:
        s += "\n\nText extracted exactly from the drawing file (sheet coordinates of each item in brackets):\n" + texts_hint
    if extra:
        s += "\n\nAdditional information from the user (takes precedence over the drawing where they differ):\n" + extra
    return s


# ---------------------------------------------------------------- code
CADQUERY_NOTES = """CadQuery facts (version 2.x) - follow them exactly:
- Workplane("XY"): local x = X, local y = Y, extrude towards +Z.
- Workplane("XZ"): local x = X, local y = Z, extrude towards -Y (use .extrude(-d) or both=True to go +Y).
- Workplane("YZ"): local x = Y, local y = Z, extrude towards +X.
- Put a workplane anywhere: cq.Workplane("XY", origin=(x, y, z)) or .workplane(offset=h) or
  .transformed(offset=(x, y, z), rotate=(rx, ry, rz)).
- box(L, W, H, centered=(True, True, False)) puts the bottom face on z = 0.
- cylinder(height, radius, direct=(0, 0, 1), centered=(True, True, False)).
- Profiles: .rect(w, h), .circle(r), .polygon(n, d), .slot2D(length, diameter, angle),
  .polyline([(x, y), ...]).close(), .moveTo(x, y).lineTo(x, y).threePointArc((x, y), (x, y)).close().
- .extrude(d), .extrude(d, both=True), .cutBlind(-d), .cutThruAll(), .revolve(360, (0, 0, 0), (0, 1, 0))
  (on Workplane("XZ") this revolves about the global Z axis; draw the half profile at x >= 0).
- Holes on a face: .faces(">Z").workplane(centerOption="CenterOfBoundBox").pushPoints([(x, y), ...]).hole(d)
  .cboreHole(d, cbore_d, cbore_depth), .cskHole(d, csk_d, 90). hole(d, depth) for blind holes.
  After faces(">Z").workplane() the origin is the face centre (CenterOfBoundBox); local axes follow the face.
- Arrays: .rarray(xSpacing, ySpacing, nx, ny), .polarArray(radius, startAngle, angle, count).
- Every operation returns a NEW object; nothing changes in place. Always assign: body = body.cut(tool).
- Booleans take solids: a.union(b), a.cut(b), a.intersect(b) (extrude a profile before using it as a tool).
  Translate/rotate solids: .translate((x, y, z)),
  .rotate((0, 0, 0), (0, 0, 1), angle_deg).
- Selectors: faces(">Z"), faces("<Y"), edges("|Z"), edges(">Z"), edges("not |Z"), faces("%CYLINDER").
- .fillet(r) and .chamfer(d) on selected edges; apply them LAST and keep r smaller than the thinnest wall
  the edge touches. .shell(-t) on a selected face for hollow bodies.
- Sweep: path = cq.Workplane("XZ").polyline([...]); cq.Workplane("XY").circle(r).sweep(path).
- Assembly: assembly = cq.Assembly(name="name"); assembly.add(solid, name="body", color=cq.Color("gray"),
  loc=cq.Location((x, y, z))). Colours: "gray", "gray50", "lightgray", "steelblue", "orange", "red",
  "green", "blue", "black", "yellow" or cq.Color(r, g, b) with 0..1 values."""

API_SUMMARY = """lib functions (mm, Z up, global coordinates; each returns a Workplane):
  units:     lib.ft(feet, inches) -> mm ; lib.inch(x) ; lib.ftin("18'-10 1/2\\"") -> mm
  solids:    lib.box(x0,y0,z0, x1,y1,z1) ; lib.box_c(cx,cy,cz, lx,ly,lz) ; lib.cyl(p0, p1, d) ;
             lib.tube(p0, p1, od, t) ; lib.cone(p0, p1, d0, d1) ; lib.sphere(c, d)
  outlines:  lib.prism([(x,y),...], z0, z1)  plan outline between elevations (slabs, pedestals, foundations)
             lib.extrude_on("XZ", [(x,z),...], y0, y1)  elevation/section outline extruded across (also "YZ" with (y,z))
             lib.revolve([(r,h),...], origin=(x,y,z), axis="z")  half section revolved (casings, rotors, vessels, shafts)
             lib.plate([(x,y),...], t, z)
  steel:     lib.member("HEB300" | "H300x300x10x15" | "IPE400" | "W14x30" | "C200x80x7.5x11" | "UPN200" |
                        "L100x100x10" | "L4x4x1/2" | "PIPE168.3x7.1" | "SHS100x100x6" | "RHS200x100x6" |
                        "FB100x10" | "ROD50", p0, p1, roll=0, align="center"|"top"|"bottom")
             lib.frame(nodes={"A": (x,y,z), ...}, members=[("A","B","HEB300"), ("B","C","L75x75x8", 0), ...])
             lib.grating(x0,y0,x1,y1, z_top, t=30) ; lib.handrail([p0,p1,...], h=1100) ;
             lib.ladder((x,y,z), top_z) ; lib.stair(p_bottom, p_top, width=900)
  piping:    lib.pipe([p0,p1,p2,...], od, t=None) ; lib.flange(center, direction, od, t, bore, pcd, n_bolts, bolt_d) ;
             lib.nozzle(base, direction, od, length, flange_od=None, flange_t=None)
  vessels:   lib.vessel(base, d, h, head="2:1"|"hemi"|"cone"|"flat", axis="z") ; lib.dish(center, d, h, direction)
  machines:  lib.blade_row(origin, n, r_hub, r_tip, height, stagger=30, twist=0, axis="z")  (height = axial width) ;
             lib.bolt_holes(center, direction, pcd, n, d, length)  (cut tools) ;
             lib.polar(shape, n, origin, axis) ; lib.linear(shape, n, (dx,dy,dz)) ;
             lib.spiral_case(origin, inlet_d, r_stay, axis="z")  (turbine/pump volute) ;
             lib.transition(p0, ("circle", d), p1, ("rect", w, h))  (draft tubes, ducts, hoppers, reducers)
  grouping:  lib.compound(a, b, [c, d], ...)  several solids as one part without slow unions"""


CODE_RULES = f"""{AXES}

Write ONE complete Python script for CadQuery that builds the object.

Script rules:
1. First line: import cadquery as cq  (import math and import aicad_lib as lib are allowed; nothing else;
   no files, no show()). The library helps with steel members, frames, revolved half sections, vessels,
   nozzles, flanges, bolt circles and blade rows - see the list below.
2. Then the parameter block, every dimension a named number with a comment and its source in brackets:
   # --- PARAMETERS (mm) ---
   length = 200.0      # overall length [drawing]
   rib_t = 8.0         # rib thickness [ratio]
   # --- END PARAMETERS ---
   Sources: [drawing] written on the drawing, [ratio] measured from the drawing proportions,
   [description] stated by the user, [assumed] a sensible default (standard size or proportion).
   Counts are integers (n_holes = 4). Derived values are computed below the block, not typed in.
3. Build in this order: base solid -> added bodies (union) -> cuts, pockets, holes -> fillets/chamfers.
   Use only the parameters (no unexplained numbers) so that a changed parameter rebuilds correctly.
4. The final solid goes into a variable named `result`. For several separate components build each one
   as a solid and put them into `assembly = cq.Assembly(...)` with names and colours (then do not set result).
5. Prefer simple robust operations. Never fillet all edges at once. Do not model threads as helices:
   a tapped hole is a plain hole of the nominal diameter (say so in the comment).
6. Answer with the script in one ```python code block and nothing after it.

{CADQUERY_NOTES}

{API_SUMMARY}"""

CODE_SYSTEM = """You are an expert CAD engineer who writes clean, parametric CadQuery (Python) models.
You know engineering drawing conventions, standard parts (flanges, bolts, bearings, profiles, pipe sizes)
and how equipment is built. Your models are dimensionally exact where the drawing is explicit and
proportionally faithful where it is not."""

EXAMPLE_FLANGE = '''import cadquery as cq
import math

# --- PARAMETERS (mm) ---
flange_d = 200.0        # flange outer diameter [drawing]
flange_t = 18.0         # flange thickness [drawing]
hub_d = 110.0           # hub outer diameter [drawing]
hub_h = 40.0            # hub height above the flange [ratio]
bore_d = 60.0           # through bore [drawing]
pcd = 160.0             # bolt circle diameter [drawing]
bolt_d = 18.0           # bolt hole diameter [drawing]
n_bolts = 8             # number of bolt holes [drawing]
# --- END PARAMETERS ---

# half profile in the XZ plane, revolved about Z
profile = [(bore_d / 2, 0), (flange_d / 2, 0), (flange_d / 2, flange_t), (hub_d / 2, flange_t),
           (hub_d / 2, flange_t + hub_h), (bore_d / 2, flange_t + hub_h)]
body = cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))

pts = [(pcd / 2 * math.cos(2 * math.pi * i / n_bolts), pcd / 2 * math.sin(2 * math.pi * i / n_bolts))
       for i in range(n_bolts)]
holes = cq.Workplane("XY").pushPoints(pts).circle(bolt_d / 2).extrude(flange_t)
result = body.cut(holes)
'''

EXAMPLE_ASSEMBLY = '''import cadquery as cq

# --- PARAMETERS (mm) ---
frame_l = 1200.0        # base frame length [drawing]
frame_w = 600.0         # base frame width [drawing]
frame_h = 100.0         # channel height [ratio]
tank_d = 500.0          # vessel diameter [drawing]
tank_h = 900.0          # vessel shell height [drawing]
nozzle_d = 89.1         # nozzle pipe OD, 80A [assumed]
nozzle_l = 150.0        # nozzle projection from the shell [ratio]
anchor_d = 22.0         # anchor bolt holes [drawing]
# --- END PARAMETERS ---

frame = (cq.Workplane("XY").box(frame_l, frame_w, frame_h, centered=(True, True, False))
         .faces(">Z").workplane().rect(frame_l - 2 * 10, frame_w - 2 * 10).cutBlind(-(frame_h - 10))
         .faces("<Z").workplane().rect(frame_l - 80, frame_w - 80, forConstruction=True).vertices()
         .hole(anchor_d))
tank = cq.Workplane("XY", origin=(0, 0, frame_h)).circle(tank_d / 2).extrude(tank_h)
nozzle = (cq.Workplane("YZ", origin=(tank_d / 2 - 20, 0, frame_h + tank_h * 0.75))
          .circle(nozzle_d / 2).extrude(nozzle_l + 20))

assembly = cq.Assembly(name="vessel_skid")
assembly.add(frame, name="base_frame", color=cq.Color("gray50"))
assembly.add(tank, name="vessel", color=cq.Color("lightgray"))
assembly.add(nozzle, name="nozzle_N1", color=cq.Color("steelblue"))
'''


def code_user_from_spec(resolved_table: str, spec_json: str, extra: str, with_image: bool, checks=()) -> str:
    s = (("The drawing is attached. " if with_image else "") +
         "Build the 3D model from this specification.\n\n"
         "Values to use (name | value | unit | source | meaning). Use them as parameters with the same source tags; "
         "sizes marked 'ratio' were measured on the sheet:\n" + resolved_table +
         "\n\nSpecification read from the drawing:\n" + spec_json)
    if checks:
        s += ("\n\nThe program measured the views on the sheet and found these inconsistencies. Look at the drawing "
              "again where they apply and use the value the drawing really shows (a measured size that two views "
              "agree on usually means a dimension was misread):\n- " + "\n- ".join(checks))
    if extra:
        s += "\n\nAdditional instructions from the user (take precedence):\n" + extra
    s += ("\n\nIf a size needed for the model is not in the table, estimate it from the drawing proportions "
          "relative to known sizes and mark it [ratio], or use a standard value and mark it [assumed].")
    return s


def code_user_from_text(text: str) -> str:
    return ("Build the 3D model described below. Where a size is not given, choose a sensible engineering value "
            "(standard sizes, typical proportions) and mark it [assumed]; sizes stated by the user are "
            "[description].\n\nDescription:\n" + text)


def code_messages(user_text: str) -> list:
    return [
        {"role": "system", "content": CODE_SYSTEM + "\n\n" + CODE_RULES},
        {"role": "user", "content": "Example of the expected style (a flange):"},
        {"role": "assistant", "content": "```python\n" + EXAMPLE_FLANGE + "```"},
        {"role": "user", "content": "Example of an equipment assembly:"},
        {"role": "assistant", "content": "```python\n" + EXAMPLE_ASSEMBLY + "```"},
        {"role": "user", "content": user_text},
    ]


# ---------------------------------------------------------------- repair
def repair_user(code: str, err: dict) -> str:
    line = err.get("line")
    hints = []
    if err.get("ok"):
        # it built, but operations were thrown away
        s = "The script below runs, but some operations have no effect on the model:\n"
        s += "\n".join("- " + m for m in err.get("lint", [])) + "\n"
    else:
        s = "The script below failed when it was run.\n\n"
        s += f"Error: {err.get('error')}\n"
        if line:
            s += f"At line {line}: {err.get('line_text', '')}\n"
        for m in err.get("lint", []):
            hints.append(m[0].upper() + m[1:] + ".")
    e = (err.get("error") or "") + (err.get("line_text") or "")
    if "fillet" in e or "chamfer" in e or "BRep_API: command not done" in e or "StdFail_NotDone" in e:
        hints.append("A fillet or chamfer (or a boolean) failed: reduce the radius below the adjacent wall "
                     "thickness, select fewer edges, or remove the cosmetic fillet.")
    if "pending" in e.lower() or "No pending wires" in e:
        hints.append("extrude/cut needs a closed profile first (rect, circle, polyline(...).close()).")
    if "no objects" in e.lower() or "Cannot find a solid" in e or "IndexError" in e:
        hints.append("A selector returned nothing or the stack has no solid: check faces/edges selectors "
                     "and use explicit workplanes with origin=(x, y, z).")
    if "not allowed" in e:
        hints.append("Only cadquery and math may be imported; no file access.")
    if "produced no shape" in e or "no solid" in e:
        hints.append("Assign the final solid to `result` (or the assembly to `assembly`).")
    if "Null TopoDS_Shape" in e or "null shape" in e.lower():
        hints.append("A boolean or feature received an empty shape: cut()/union() need solids, not 2D profiles "
                     "(extrude the profile first, e.g. tool = cq.Workplane('XY').rect(a, b).extrude(h)); "
                     "cutThruAll(), hole() and fillet() must be chained on the solid itself "
                     "(body = body.faces('>Z').workplane().circle(r).cutThruAll()).")
    if "timed out" in e or "did not finish" in e:
        hints.append("The script is too slow: avoid huge patterns and loops of booleans (union/cut inside a loop); "
                     "collect many separate pieces with lib.compound(...) instead of fusing them, model repeated "
                     "members once per row, and leave out small details such as bolts and rivets.")
    if hints:
        s += "Hints: " + " ".join(hints) + "\n"
    s += ("\nCorrect the script. Keep the parameter block, the parameter names and the design intent. "
          "Answer with the complete corrected script in one ```python code block.\n\n```python\n" + code + "\n```")
    return s


# ---------------------------------------------------------------- refine
def refine_user(code: str, report: str) -> str:
    return ("The first image is the original drawing. The second image shows, for each view, the drawing view "
            "(left) next to the same view of the model built by the current script (right; hidden edges dashed).\n\n"
            "Measured comparison:\n" + report +
            "\n\nCompare the two columns view by view: overall proportions, the position and size of every feature, "
            "missing or extra features, mirrored or rotated geometry. First list the differences briefly, then "
            "give the complete corrected script in one ```python code block. Keep the parameter block and the "
            "values from the drawing; correct values marked [ratio] or [assumed] if the comparison shows they are "
            "wrong.\n\nCurrent script:\n```python\n" + code + "\n```")


# ---------------------------------------------------------------- edit
def edit_user(code: str, instruction: str) -> str:
    return ("Change the model as requested. Keep everything else unchanged. Add new parameters for new sizes "
            "(source [description]; [assumed] if you had to choose the value). Answer with the complete "
            "script in one ```python code block.\n\nRequest:\n" + instruction +
            "\n\nCurrent script:\n```python\n" + code + "\n```")


def extract_code(text: str) -> str:
    import re
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    t = (text or "").strip()
    i = t.find("import cadquery")
    return (t[i:] if i >= 0 else t) + "\n"
