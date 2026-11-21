// Kroger Restock wall scanner housing
// For an M5Stack AtomS3 Lite on an Atomic QRCode2 Base.
//
// A wall bracket with a sloped cradle: the scanner lies on the cradle with
// its scan window pointing down and out from the wall (tilt, default 35°),
// the Atom's top (button + RGB LED) facing up and out. An optional snap-on
// cover has a thin press tab that works the button and lets the LED shine
// through.
//
// Parts (set with -D 'part="..."'):
//   "housing"  bracket + cradle, in print orientation (back on the bed)
//   "cover"    snap-on cover, in print orientation (top on the bed)
//   "assembly" mounted view with a dummy scanner, for checking (not printed)
//
// Print: PETG or PLA, 0.2 mm layers, 3 walls, 20 % infill, NO supports.
// The housing prints flat on its back (the cradle floor is 55° from the bed,
// so its underside needs no support). The cover prints top-down; print it in
// a light or translucent filament so the LED shows through the press tab.
//
// MEASURE YOUR UNIT. M5Stack's drawings weren't available when this was
// written. Defaults: base 48 x 24 x 17.5 mm (M5Stack's published size; it's
// unclear whether that includes the Atom, so atom_extra_h covers it).
// Check scan window side, M3 hole positions and USB-C position, then adjust
// the parameters below. Print the "housing" part once at 30 % to test fit.

/* [Part] */
part = "assembly"; // [housing, cover, assembly]
show_wall = true;  // assembly view only

/* [Scanner (measure!)] */
unit_l = 48.0;       // length, scan-window end to back end
unit_w = 24.0;       // width
unit_h = 17.5;       // height of the base
atom_extra_h = 0.0;  // extra height if the Atom sits proud of the base
fit_tol = 0.4;       // clearance per side

// The scan window is on the end face at the low (outer) end of the cradle.
scan_window_z = 3.0; // window bottom above the scanner's rear face

// Rear M3 holes, as [across, along] in mm from the rear face center line /
// the back (high) end. Defaults are placeholders: measure and adjust.
m3_holes = [[-8, 16], [8, 16]];
m3_clear_d = 3.4;
m3_head_d = 6.2;     // counterbore from below for the screw head
m3_head_h = 2.0;

// Steel washer pocket for the base's rear magnet (0 = none)
washer_d = 12.5;
washer_t = 1.2;
washer_along = 34;   // from the back end

// Atom position on top of the scanner (for the cover's press tab)
atom_along = 12;     // Atom center, from the back (high) end
atom_size = 24;

// USB-C (right-angle cable) exit in a side wall
usb_side = 1;        // 1 = +x side, -1 = -x side
usb_along = 12;      // slot center, from the back end
usb_slot_l = 14;     // slot length along the scanner
usb_slot_h = 9;      // slot height (from the top edge of the wall)

/* [Housing] */
tilt = 35;           // scan direction, degrees below horizontal (30-45)
wall = 2.4;
floor_t = 2.4;
side_wall_frac = 0.65; // side wall height as a fraction of scanner height
end_lip_h = 1.6;     // small stop at the scan end (below the window)
plate_t = 5.0;
plate_margin = 7;    // plate extends this far past the cradle each side
plate_extra_h = 22;  // plate height above/below the cradle

// Keyholes for screws/drywall anchors (flat back also takes adhesive strips)
keyhole_head_d = 8.6;
keyhole_shank_d = 4.4;
keyhole_slot = 9;
keyhole_front_skin = 1.2;
keyhole_back_skin = 1.6;   // the screw head is held behind this

/* [Cover] */
cover_t = 2.0;
cover_skirt = 6;     // skirt length over the side walls
snap_bump = 0.45;    // inward snap bump on the skirts
tab_t = 0.8;         // press-tab thickness (thin = flexible + translucent)
tab_gap = 1.0;       // U-slot width around the tab
tab_size = 15;       // tab width/length
tab_nub_h = 1.0;     // nub under the tab that presses the button

$fn = 48;

// ---------------------------------------------------------------- derived
H = unit_h + atom_extra_h;
inner_w = unit_w + 2 * fit_tol;
inner_l = unit_l + fit_tol;
outer_w = inner_w + 2 * wall;
side_wall_h = H * side_wall_frac;
plate_w = outer_w + 2 * plate_margin;
// Vertical extent of the cradle when mounted
cradle_drop = (inner_l + wall) * sin(tilt);
plate_h = cradle_drop + 2 * plate_extra_h;
// Cradle frame origin: back end of the cradle floor, on the plate face.
cradle_origin = [0, plate_t, plate_h - plate_extra_h];

// Cradle local frame: x = across, y = along (0 = back end, +y = scan end),
// z = up from the floor. Rotating about x by -tilt makes +y point down and
// out from the wall at `tilt` below horizontal, and +z point up and out.
module in_cradle_frame() {
  translate(cradle_origin) rotate([-tilt, 0, 0]) children();
}

module flatten_to_plate() {
  // Squash geometry onto the plate face (y = plate_t) for hull() wedges.
  multmatrix([[1, 0, 0, 0], [0, 0.001, 0, plate_t], [0, 0, 1, 0], [0, 0, 0, 1]])
    children();
}

// ---------------------------------------------------------------- housing
module back_plate() {
  difference() {
    translate([-plate_w / 2, 0, 0]) cube([plate_w, plate_t, plate_h]);
    for (z = [plate_extra_h * 0.25, plate_h - plate_extra_h * 0.75]) keyhole(z);
  }
}

// Keyhole from the back: the screw head enters the round hole, then the
// plate slides down so the shank rides up the slot while the head is held in
// a wider channel behind the back skin (prints as a short bridge).
module keyhole(z) {
  channel = plate_t - keyhole_back_skin - keyhole_front_skin;
  // entry hole for the head, through the back skin and channel
  translate([0, -0.01, z]) rotate([-90, 0, 0])
    cylinder(d = keyhole_head_d, h = keyhole_back_skin + channel + 0.01);
  // shank slot through the back skin, going up from the entry hole
  translate([-keyhole_shank_d / 2, -0.01, z])
    cube([keyhole_shank_d, keyhole_back_skin + 0.02, keyhole_slot]);
  translate([0, -0.01, z + keyhole_slot]) rotate([-90, 0, 0])
    cylinder(d = keyhole_shank_d, h = keyhole_back_skin + 0.02);
  // head channel behind the back skin
  translate([-keyhole_head_d / 2, keyhole_back_skin, z])
    cube([keyhole_head_d, channel, keyhole_slot]);
  translate([0, keyhole_back_skin, z + keyhole_slot]) rotate([-90, 0, 0])
    cylinder(d = keyhole_head_d, h = channel);
}

module cradle_local() {
  difference() {
    union() {
      // floor
      translate([-outer_w / 2, -wall, -floor_t]) cube([outer_w, inner_l + wall, floor_t]);
      // back end wall
      translate([-outer_w / 2, -wall, 0]) cube([outer_w, wall, side_wall_h]);
      // side walls
      for (sx = [-1, 1])
        translate([sx > 0 ? inner_w / 2 : -outer_w / 2, -wall, 0])
          cube([wall, inner_l + wall, side_wall_h]);
      // stop lip at the scan end, kept below the scan window
      translate([-outer_w / 2, inner_l, -floor_t])
        cube([outer_w, wall, floor_t + min(end_lip_h, scan_window_z - 0.5)]);
    }
    // M3 holes with counterbore from below
    for (h = m3_holes)
      translate([h[0], h[1] + fit_tol / 2, -floor_t - 0.01]) {
        cylinder(d = m3_clear_d, h = floor_t + 0.02);
        cylinder(d = m3_head_d, h = min(m3_head_h, floor_t - 0.8));
      }
    // steel washer pocket for the magnet
    if (washer_d > 0)
      translate([0, washer_along, -washer_t]) cylinder(d = washer_d, h = washer_t + 0.01);
    // USB-C exit: a slot down from the top of one side wall
    translate([
      usb_side > 0 ? inner_w / 2 - 0.01 : -outer_w / 2 - 0.01,
      usb_along - usb_slot_l / 2,
      side_wall_h - usb_slot_h
    ]) cube([wall + 0.02, usb_slot_l, usb_slot_h + 0.01]);
  }
}

// Side gussets join the cradle to the plate; open underneath so M3 screws
// can be driven up through the floor before the housing goes on the wall.
module gussets() {
  for (sx = [-1, 1]) {
    x0 = sx > 0 ? inner_w / 2 : -outer_w / 2;
    hull() {
      in_cradle_frame() translate([x0, -wall, -floor_t]) cube([wall, inner_l + wall, 0.01]);
      flatten_to_plate()
        in_cradle_frame() translate([x0, -wall, -floor_t]) cube([wall, inner_l + wall, 0.01]);
    }
  }
  // Back web under the cradle's back end
  hull() {
    in_cradle_frame() translate([-outer_w / 2, -wall, -floor_t]) cube([outer_w, wall, floor_t]);
    flatten_to_plate()
      in_cradle_frame() translate([-outer_w / 2, -wall, -floor_t]) cube([outer_w, wall, floor_t]);
  }
}

// Zip-tie bridge on the plate face under the USB side, for strain relief
module zip_tie_bridge() {
  bx = usb_side * (outer_w / 2 + plate_margin / 2);
  bz = plate_h - plate_extra_h - cradle_drop * 0.35;
  translate([bx - 2.5, plate_t, bz])
    difference() {
      cube([5, 4, 8]);
      translate([-0.01, 1.2, 2]) cube([5.02, 1.8, 4]);
    }
}

module housing_mounted() {
  // Clip anything that would poke through the flat back.
  intersection() {
    union() {
      back_plate();
      in_cradle_frame() cradle_local();
      gussets();
      zip_tie_bridge();
    }
    translate([-500, 0, -500]) cube([1000, 1000, 1000]);
  }
}

// ---------------------------------------------------------------- cover
module cover_local() {
  top_z = H + fit_tol;
  difference() {
    union() {
      // top plate, open over the scan end so the window stays clear
      translate([-outer_w / 2, -wall, top_z]) cube([outer_w, inner_l + wall - 4, cover_t]);
      // skirts hugging the side walls from outside
      for (sx = [-1, 1])
        translate([sx > 0 ? outer_w / 2 : -outer_w / 2 - wall, -wall, side_wall_h - cover_skirt])
          cube([wall, inner_l + wall - 4, top_z + cover_t - side_wall_h + cover_skirt]);
      // bridge from the skirts to the top plate
      for (sx = [-1, 1])
        translate([sx > 0 ? inner_w / 2 : -outer_w / 2 - wall, -wall, side_wall_h + 0.2])
          cube([wall * 2, inner_l + wall - 4, top_z + cover_t - side_wall_h - 0.2]);
      // snap bumps under the side-wall tops... (inward, near the skirt bottom)
      for (sx = [-1, 1])
        translate([sx > 0 ? outer_w / 2 - snap_bump : -outer_w / 2, inner_l * 0.25, side_wall_h - cover_skirt + 0.6])
          cube([snap_bump, inner_l * 0.5, 1.2]);
    }
    // keep the cover's inner bridge clear of the scanner body
    translate([-inner_w / 2, -wall - 1, side_wall_h - 0.01]) cube([inner_w, inner_l + wall + 2, top_z - side_wall_h + 0.01]);
    // USB-C exit continues through the skirt
    translate([
      usb_side > 0 ? outer_w / 2 - 0.01 : -outer_w / 2 - wall - 0.01,
      usb_along - usb_slot_l / 2,
      side_wall_h - cover_skirt - 0.01
    ]) cube([wall + 0.02, usb_slot_l, top_z + cover_t]);
    // press tab: thin down the plate and cut a U-slot around it
    translate([-tab_size / 2, atom_along - tab_size / 2, top_z + tab_t])
      cube([tab_size, tab_size, cover_t]);
    difference() {
      translate([-tab_size / 2 - tab_gap, atom_along - tab_size / 2 - tab_gap, top_z - 0.01])
        cube([tab_size + 2 * tab_gap, tab_size + tab_gap, cover_t + 0.02]);
      translate([-tab_size / 2, atom_along - tab_size / 2, top_z - 0.02])
        cube([tab_size, tab_size + tab_gap + 0.1, cover_t + 0.04]);
    }
  }
  // nub under the tab that presses the Atom's button
  translate([0, atom_along, top_z - tab_nub_h]) cylinder(d = 5, h = tab_nub_h + 0.01);
}

// ---------------------------------------------------------------- dummy
module dummy_scanner() {
  color("dimgray") translate([-unit_w / 2, fit_tol / 2, 0]) cube([unit_w, unit_l, unit_h]);
  color("white") translate([-atom_size / 2, atom_along - atom_size / 2, unit_h])
    cube([atom_size, atom_size, max(atom_extra_h, 0.01)]);
  color("red", 0.6) translate([-unit_w / 2 + 3, unit_l + fit_tol / 2, scan_window_z])
    cube([unit_w - 6, 0.5, unit_h - scan_window_z - 3]);
}

// ---------------------------------------------------------------- output
if (part == "housing") {
  // Print orientation: back plate flat on the bed.
  rotate([90, 0, 0]) housing_mounted();
} else if (part == "cover") {
  // Print orientation: top face on the bed.
  translate([0, 0, H + fit_tol + cover_t]) rotate([180, 0, 0]) cover_local();
} else {
  color("seagreen") housing_mounted();
  in_cradle_frame() {
    dummy_scanner();
    color("lightgreen", 0.8) cover_local();
  }
  if (show_wall)
    color("tan", 0.25) translate([-60, -2, -10]) cube([120, 2, plate_h + 20]); // wall
}
