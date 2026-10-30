"""Instructions for large objects: multi-sheet drawing sets, plant structures,
equipment assemblies and machines.

    survey      one sheet  -> what the sheet is, its views, tables and scale bars
    read_view   one view, zoomed from the original -> dimensions, levels, labels, members
    plan        all sheets -> the object broken into components with envelopes
    component   one component -> CadQuery code using the modelling library
"""
from __future__ import annotations

from .prompts import API_SUMMARY, CADQUERY_NOTES

COORDS = """Sheet coordinates: integers 0-1000 relative to the image given, x to the right, y downwards."""

SURVEY_SYSTEM = f"""You are a senior engineer who reviews drawing sets of plants, steel structures, machines and
equipment. You look at one sheet and describe what it contains, so that the sheet can be read in detail later.

{COORDS}

Answer with ONE JSON object and nothing else:
{{
  "sheet": {{"title": text of the title block, "number": sheet or drawing number, "kind": "general arrangement|plan|
             elevation|section|detail|assembly|parts list|notes|other"}},
  "units": "mm" | "m" | "inch" | "ft-in",
  "scale_text": scale note as written (e.g. "1/4\\" = 1'-0\\"", "1:50") or null,
  "scale_bars": [ {{"p1": [x, y], "p2": [x, y], "length": number, "unit": "mm|m|ft|in", "view": view id or null}} ],
  "views": [ {{"id": "V1", "type": "plan|elevation|section|detail|front|top|right|left|rear|bottom|isometric|other",
              "label": the caption under the view as written, "box": [x0, y0, x1, y1],
              "level_or_cut": elevation of a plan or the cut line of a section, as written, or "",
              "scale_text": the view's own scale note or null}} ],
  "tables": [ {{"kind": "parts list|key|legend|notes|title block|revision", "box": [x0, y0, x1, y1]}} ],
  "objects": [ the main things drawn, by name (e.g. "turbine-generator", "condenser", "crane boom") ],
  "summary": two or three sentences: what the sheet shows and how it relates to the whole object
}}

Rules: list every separate drawing on the sheet as a view, each with a box around its line work only (no title
block, no tables). For a graphic scale bar give p1 at its zero mark and p2 at the mark of the length you state.
"""

READ_VIEW_SYSTEM = f"""You are a senior engineer reading one view of an engineering drawing, enlarged so that the
text is legible. Report what is written and where, precisely; do not guess numbers that are not there.
Inside JSON strings escape the inch mark: "18'-10 1/2\\"".

{COORDS} (relative to this enlarged image)

Answer with ONE JSON object and nothing else:
{{
  "dimensions": [ {{"text": the dimension exactly as written (e.g. "18'-10 1/2\\"", "2400", "8 PANELS @ 21'-0\\" = 168'-0\\""),
                   "describes": what it measures, "axis": "h" | "v" | "slope" | null,
                   "p1": [x, y], "p2": [x, y]  (the two extension lines or arrow tips the value spans) }} ],
  "levels": [ {{"text": "EL. 59'-6\\"" as written, "at": [x, y], "describes": what is at that level}} ],
  "grid": [ {{"label": "A", "at": [x, y], "dir": "v" | "h"}} ],
  "labels": [ {{"text": name or tag as written, "at": [x, y]}} ],
  "members": [ {{"mark": member mark, "section": section size if written, "p1": [x, y], "p2": [x, y]}} ],
  "shapes": brief description of the main outlines in this view (what is round, rectangular, sloped, repeated),
  "notes": [ other written information that matters for the 3D shape ]
}}
"""

PLAN_SYSTEM = f"""You are a senior design engineer planning a 3D layout model of a large object from its drawing
set: a plant building, a steel structure, an equipment skid, a machine. You break the object into components that
can each be modelled on their own, and you place them in one global coordinate system.

Coordinate system: millimetres, Z up. For buildings and plants X runs east (to the right on plans), Y north (up on
plans), Z is elevation; put the origin at a stated datum (a grid intersection or machine centre line at a given
elevation). For machines put the origin on the main axis.

Answer with ONE JSON object and nothing else:
{{
  "name": short name of the object,
  "datum": where the origin is and which drawing elevation equals z = 0,
  "overall": {{"x": number, "y": number, "z": number}}  (overall extent in mm, best estimate),
  "components": [ {{"id": "c1" (letters, digits, _), "name": short name, "kind": "structure|concrete|equipment|
                    rotating|vessel|piping|building|platform|other",
                    "views": [view ids that show it, e.g. "S1V2"],
                    "min": [x, y, z], "max": [x, y, z]   (its bounding box in global mm),
                    "description": how it is shaped and built, with the sizes that define it (mm),
                    "color": a colour name}} ],
  "notes": [ assumptions and what the drawings leave open ]
}}

Rules:
- 5 to 30 components. Group repetitive members (all columns of a row, a whole truss, all bracing of a bay) into one
  component each. Separate parts that differ in kind (foundation, frame, machine, piping, platform).
- Sizes come from the readings (already converted to mm where a scale is known). Where a size is not written,
  estimate it from the drawing proportions and say so in the description.
- A layout model shows envelopes and main features; internal details that do not change the outer shape are left out.
"""

COMPONENT_RULES = f"""Write ONE complete Python script that builds ONLY the component described, in the GLOBAL coordinates of
the plan (millimetres, Z up), using CadQuery and the AICAD modelling library.

Script rules:
1. Start with: import cadquery as cq / import aicad_lib as lib   (math is allowed; nothing else).
2. Then a parameter block with every size as a named number, its meaning and source:
   # --- PARAMETERS (mm) ---
   span = 51206.4        # 8 panels @ 21'-0" [drawing]
   depth = 600.0         # chord depth, not dimensioned [ratio]
   # --- END PARAMETERS ---
3. Assign the final shape to `result`. Use lib functions for members, frames, outlines, revolved half sections,
   vessels, nozzles, blade rows and patterns; combine parts with lib.compound(...) instead of union() when they
   only touch. Use union()/cut() only where material really merges or is removed.
4. Keep it simple and robust: no fillets unless essential, no tiny features. The component must lie inside its
   planned bounding box (it may differ where the readings show better values).
5. Answer with the script in one ```python code block and nothing after it.

{API_SUMMARY}

{CADQUERY_NOTES}"""

COMPONENT_SYSTEM = ("You are an expert CAD engineer who models plant structures, steel frames, machines and "
                    "equipment as clean parametric CadQuery scripts with the AICAD modelling library.")


def survey_user(page_label: str, texts_hint: str) -> str:
    s = f"This is sheet '{page_label}' of the drawing set. Describe it as JSON."
    if texts_hint:
        s += "\n\nText extracted exactly from the file (sheet coordinates in brackets):\n" + texts_hint
    return s


def read_view_user(view: dict, sheet: dict, units: str) -> str:
    return (f"This is view {view['id']} ('{view.get('label', '')}', type {view.get('type')}) of sheet "
            f"'{sheet.get('title', '')}', enlarged. The drawing units are {units}. "
            f"{('Level/cut: ' + view['level_or_cut'] + '. ') if view.get('level_or_cut') else ''}"
            "Report its dimensions, levels, grid lines, labels and members as JSON.")


def plan_user(digest: str, extra: str) -> str:
    s = ("The first image shows all sheets of the set side by side, each labelled. Below is what was read from "
         "every sheet and view (lengths in mm where they could be converted; 'scale' is mm per sheet pixel where "
         "known).\n\n" + digest)
    if extra:
        s += "\n\nInformation from the user (takes precedence):\n" + extra
    return s + "\n\nPlan the 3D layout model as JSON."


def component_user(comp: dict, plan: dict, readings: str, extra: str) -> str:
    others = "\n".join(f"- {c['id']} {c['name']}: min {c.get('min')} max {c.get('max')}"
                       for c in plan.get("components", []) if c["id"] != comp["id"])
    s = (f"Object: {plan.get('name', '')}. Datum: {plan.get('datum', '')}.\n\n"
         f"Component to build: {comp['id']} - {comp['name']} ({comp.get('kind', '')})\n"
         f"Planned bounding box: min {comp.get('min')} max {comp.get('max')} (mm)\n"
         f"Description: {comp.get('description', '')}\n\n"
         f"Neighbouring components (for alignment; do not model them):\n{others}\n\n"
         f"Readings of the views that show it (lengths in mm):\n{readings}\n\n"
         "The attached images are those views, enlarged.")
    if extra:
        s += "\n\nInformation from the user (takes precedence):\n" + extra
    return s
