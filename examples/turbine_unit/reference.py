import cadquery as cq
import math
import aicad_lib as lib

# Turbine and generator unit (Wilson Dam, 1925) - layout model of the half section.
# Sizes measured on the sheet with its graphic scale (3/8" = 1'-0"); the drawing
# carries no dimensions. Origin on the shaft axis at the generator floor, z up.
# Datum: generator floor = z 0.


def z(ft_below_floor):
    return -lib.ft(ft_below_floor)


# ================================================================== generator
def build_generator():
    # --- PARAMETERS generator (mm) ---
    stator_r = 4572.0       # stator frame outside radius, 15 ft [ratio]
    bore_r = 2835.0         # stator bore radius, 9.3 ft [ratio]
    stator_h = 1737.0       # stator frame height, 5.7 ft [ratio]
    bracket_r = 3536.0      # upper bracket arm radius, 11.6 ft [ratio]
    bracket_h = 2263.0      # upper bracket height, 7.4 ft [ratio]
    rotor_r = 2800.0        # rotor rim radius, 9.2 ft [ratio]
    # --- END PARAMETERS ---
    stator = lib.revolve([(bore_r, 0), (stator_r, 0), (stator_r, stator_h), (bore_r, stator_h)])
    rotor = lib.revolve([(600, 150), (rotor_r, 150), (rotor_r, stator_h - 150), (600, stator_h - 150)])
    # upper bracket: a conical spider from the frame up to the bearing housing
    bracket = lib.revolve([(1200, stator_h), (bracket_r, stator_h), (bracket_r, stator_h + 500),
                           (1600, stator_h + bracket_h), (700, stator_h + bracket_h), (700, stator_h + bracket_h - 400),
                           (1200, stator_h + 400)])
    # inspection windows: round openings in the bracket
    holes = lib.polar(lib.cyl((0, 0, stator_h + 1100), (bracket_r + 100, 0, stator_h + 1100), 600), 8)
    return lib.compound(stator, rotor, bracket.cut(holes))


def build_exciter():
    # --- PARAMETERS exciter (mm) ---
    exc_r = 1372.0          # main exciter radius, 4.5 ft [ratio]
    exc_z0 = 4000.0         # exciter base above the floor [ratio]
    exc_h = 2440.0          # main and pilot exciter height, 8 ft [ratio]
    # --- END PARAMETERS ---
    main = lib.revolve([(0, 0), (exc_r, 0), (exc_r, exc_h * 0.55), (exc_r * 0.75, exc_h * 0.7),
                        (exc_r * 0.6, exc_h), (0, exc_h)], origin=(0, 0, exc_z0))
    lamp = lib.sphere((0, 0, exc_z0 + exc_h + 350), 600)
    return lib.compound(main, lamp)


def build_shaft():
    # --- PARAMETERS shaft (mm) ---
    shaft_d = 610.0         # main shaft diameter, 2 ft [ratio]
    top_z = 4000.0          # top of the shaft at the exciter [ratio]
    bottom_z = -13700.0     # shaft end at the runner, 45 ft below the floor [ratio]
    coupling_d = 1100.0     # shaft coupling flange diameter [ratio]
    coupling_z = -1830.0    # coupling below the floor, 6 ft [ratio]
    # --- END PARAMETERS ---
    shaft = lib.cyl((0, 0, bottom_z), (0, 0, top_z), shaft_d)
    coupling = lib.cyl((0, 0, coupling_z - 150), (0, 0, coupling_z + 150), coupling_d)
    return lib.compound(shaft, coupling)


# ================================================================== turbine
def build_runner():
    # --- PARAMETERS runner (mm) ---
    hub_r = 760.0           # runner crown at the hub [ratio]
    tip_r = 1981.0          # runner band radius, 6.5 ft [ratio]
    runner_z = -13300.0     # runner blades centre below the floor [ratio]
    blade_h = 1500.0        # axial height of the blade row [ratio]
    n_blades = 15           # runner vanes [assumed]
    # --- END PARAMETERS ---
    crown = lib.revolve([(0, 0), (tip_r, 0), (tip_r, 300), (hub_r, 700), (0, 700)],
                        origin=(0, 0, runner_z + blade_h / 2))
    blades = lib.blade_row((0, 0, runner_z - blade_h / 2), n_blades, hub_r, tip_r, blade_h, stagger=55, twist=25)
    band = lib.revolve([(tip_r - 60, 0), (tip_r + 60, 0), (tip_r + 260, blade_h), (tip_r + 140, blade_h)],
                       origin=(0, 0, runner_z - blade_h / 2))
    return lib.compound(crown, blades, band)


def build_distributor():
    # --- PARAMETERS distributor (mm) ---
    gate_r_in = 2300.0      # wicket gate circle inner radius [ratio]
    gate_r_out = 2750.0     # wicket gate circle outer radius [ratio]
    stay_r_in = 2900.0      # stay ring inner radius [ratio]
    stay_r_out = 3350.0     # stay ring outer radius [ratio]
    vane_h = 1500.0         # distributor height [ratio]
    vane_z = -13300.0       # distributor centre below the floor [ratio]
    n_gates = 20            # wicket gates (text: "a collar of 20 wicket gates") [drawing]
    n_stay = 12             # stay vanes [assumed]
    # --- END PARAMETERS ---
    z0 = vane_z - vane_h / 2
    gates = lib.blade_row((0, 0, z0), n_gates, gate_r_in, gate_r_out, vane_h, stagger=0, thickness=0.18)
    stays = lib.blade_row((0, 0, z0), n_stay, stay_r_in, stay_r_out, vane_h, stagger=0, thickness=0.25)
    rings = lib.compound(
        lib.revolve([(gate_r_in, vane_h), (stay_r_out, vane_h), (stay_r_out, vane_h + 250), (gate_r_in, vane_h + 250)], origin=(0, 0, z0)),
        lib.revolve([(gate_r_in, -250), (stay_r_out, -250), (stay_r_out, 0), (gate_r_in, 0)], origin=(0, 0, z0)))
    return lib.compound(gates, stays, rings)


def build_spiral_case():
    # --- PARAMETERS spiral_case (mm) ---
    inlet_d = 4176.0        # spiral distributor inlet height, 13.7 ft [ratio]
    r_stay = 3350.0         # stay ring outer radius [ratio]
    case_z = -13300.0       # centre plane below the floor [ratio]
    # --- END PARAMETERS ---
    return lib.spiral_case((0, 0, case_z), inlet_d, r_stay, start_angle=180, inlet_length=3000)


def build_draft_tube():
    # --- PARAMETERS draft_tube (mm) ---
    throat_d = 4200.0       # draft tube throat below the runner [ratio]
    exit_w = 9150.0         # spreading draft tube width at the bottom, 30 ft [ratio]
    exit_h = 5500.0         # depth of the spreading part [ratio]
    top_z = -14100.0        # top of the draft tube [ratio]
    depth = 7000.0          # draft tube depth shown, 23 ft [ratio]
    cone_d = 2100.0         # Moody draft cone base diameter [ratio]
    # --- END PARAMETERS ---
    tube = lib.transition((0, 0, top_z), ("circle", throat_d), (0, 0, top_z - depth), ("rect", exit_w, exit_h))
    liner = tube.cut(lib.transition((0, 0, top_z + 1), ("circle", throat_d - 300), (0, 0, top_z - depth - 1),
                                    ("rect", exit_w - 300, exit_h - 300)))
    cone = lib.cone((0, 0, top_z - depth), (0, 0, top_z - 1500), cone_d, 200)
    return lib.compound(liner, cone)


# ================================================================== building
def build_floor_equipment():
    # --- PARAMETERS floor_equipment (mm) ---
    tank_x = 5000.0         # oil pressure tank position from the axis, 16.4 ft [ratio]
    tank_d = 1220.0         # oil pressure tank diameter, 4 ft [ratio]
    tank_h = 3350.0         # oil pressure tank height, 11 ft [ratio]
    gov_x = 6550.0          # governor position from the axis, 21.5 ft [ratio]
    gov_h = 1830.0          # governor height, 6 ft [ratio]
    # --- END PARAMETERS ---
    tank = lib.vessel((tank_x, 0, 300), tank_d, tank_h - 600, head="2:1")
    governor = lib.compound(lib.box_c(gov_x, 0, gov_h / 2, 700, 700, gov_h), lib.cyl((gov_x, 0, gov_h), (gov_x, 0, gov_h + 500), 350))
    rail = lib.handrail([(7000, -3000, 0), (12000, -3000, 0), (12000, 3000, 0)], h=1070)
    stair = lib.stair((12500, 0, -5800), (17600, 0, 0), width=1200)
    return lib.compound(tank, governor, rail, stair)


def build_concrete():
    # --- PARAMETERS concrete (mm) ---
    left = 8230.0           # concrete to the left of the axis, 27 ft [ratio]
    right = 12500.0         # concrete to the right of the axis, 41 ft [ratio]
    width = 18000.0         # block width across the unit [assumed]
    bottom_z = -21300.0     # foundation level shown, 70 ft below the floor [ratio]
    pit_r = 3000.0          # turbine pit radius, 9.8 ft [ratio]
    pit_bottom = -12400.0   # pit floor (head cover) below the floor [ratio]
    # --- END PARAMETERS ---
    block = lib.box(-left, -width / 2, bottom_z, right, width / 2, 0)
    pit = lib.cyl((0, 0, pit_bottom), (0, 0, 10), 2 * pit_r)
    spiral_void = lib.cyl((0, 0, -15600), (0, 0, -11000), 2 * 7600)
    draft_void = lib.transition((0, 0, -14000), ("circle", 4300), (0, 0, -21400), ("rect", 9300, 5650))
    # cut away the front-right quarter, as the drawing shows the unit in half section
    quarter = lib.box(0, -width, bottom_z - 10, right + 10, 0, 10)
    return block.cut(pit).cut(spiral_void).cut(draft_void).cut(quarter)


COMPONENTS = [
    ("generator", "Generator (stator, rotor, upper bracket)", build_generator, "steelblue"),
    ("exciter", "Main and pilot exciter", build_exciter, "darkblue"),
    ("shaft", "Main shaft and coupling", build_shaft, "gray50"),
    ("runner", "Francis runner", build_runner, "orange"),
    ("distributor", "Wicket gates and stay vanes", build_distributor, "gold"),
    ("spiral_case", "Spiral distributor (casing)", build_spiral_case, "teal"),
    ("draft_tube", "Draft tube and Moody cone", build_draft_tube, "darkgreen"),
    ("floor_equipment", "Oil tank, governor, stair, rail", build_floor_equipment, "red"),
    ("concrete", "Powerhouse concrete (quarter cut away)", build_concrete, "lightgray"),
]
assembly = lib.assemble("wilson_turbine_generator_unit", COMPONENTS)
