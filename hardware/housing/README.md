# Wall housing for the AtomS3 Lite + Atomic QRCode2 Base

Parametric OpenSCAD source: `kroger_scanner_housing.scad`. Exported STLs:
`kroger_scanner_housing.stl` and `kroger_scanner_cover.stl` (default
parameters). Both are single, watertight solids already in print orientation.

## What it is

- **Back plate** with two keyholes (screws or drywall anchors) and a flat back
  that also takes adhesive strips (e.g. Command strips).
- **Sloped cradle:** the scanner lies on it with the scan window pointing down
  and out from the wall, 35° below horizontal by default (`tilt`, 30–45).
  The Atom's top (its button, with the RGB LED shining through it) faces up and out.
- **Scan end open,** so the scan window and its illumination are clear. A
  small lip at the bottom stops the scanner sliding out.
- **Retention:** M3 screws up through the cradle floor into the base's rear
  M3 holes (the gussets leave the underside open for a screwdriver), plus a
  pocket for a steel washer that the base's rear magnet grips.
- **USB-C:** slot in one side wall for a right-angle USB-C cable, and a
  zip-tie bridge on the plate for strain relief.
- **Optional snap-on cover** with a thin press tab over the Atom: it works
  the button and lets the LED glow through (print it in a light or
  translucent filament).

## Before printing: measure your unit

M5Stack's dimension drawings weren't available while this was designed. The
defaults use M5Stack's published size for the base, 48 × 24 × 17.5 mm. It's
not clear whether that includes the Atom, so check these with calipers and
adjust the parameters at the top of the `.scad` file:

| Parameter | Default | What to check |
| --- | --- | --- |
| `unit_l`, `unit_w`, `unit_h` | 48, 24, 17.5 | Assembled scanner size |
| `atom_extra_h` | 0 | Extra height if the Atom sits above the base |
| `scan_window_z` | 3 | Window bottom above the rear face (lip must stay below it) |
| `m3_holes` | `[[-8,16],[8,16]]` | Rear M3 hole positions (placeholders) |
| `washer_along` | 34 | Where the rear magnet is |
| `atom_along` | 12 | Atom center from the back end (cover press tab) |
| `usb_side`, `usb_along` | +x, 12 | Where the USB-C port ends up |
| `fit_tol` | 0.4 | Clearance per side; raise for a looser fit |

Tip: print the housing once at 30 % scale (or just the cradle) to check the
fit cheaply.

## Exporting

OpenSCAD 2021.01 or newer:

```bash
openscad -o kroger_scanner_housing.stl -D 'part="housing"' kroger_scanner_housing.scad
openscad -o kroger_scanner_cover.stl   -D 'part="cover"'   kroger_scanner_housing.scad
openscad -D 'part="assembly"' kroger_scanner_housing.scad   # preview with a dummy scanner
```

Or open the file in OpenSCAD and use the Customizer panel.

## Printing

| Setting | Value |
| --- | --- |
| Material | PETG (preferred near a warm kitchen) or PLA |
| Layer height | 0.2 mm |
| Walls / infill | 3 walls, 20 % infill |
| Supports | **None** |
| Housing orientation | Flat on its back (as exported). The cradle floor is 55° from the bed, so its underside prints without support. Keyhole channels are short bridges. |
| Cover orientation | Top face down (as exported). The press tab is 0.8 mm thick. |

## Assembly

1. Plug the AtomS3 Lite onto the QRCode2 base.
2. Optional: glue a steel washer (12 mm, 1.2 mm thick by default) into the
   pocket in the cradle floor.
3. Set the scanner in the cradle, scan window toward the open (low) end. If
   you use screws, drive two M3 screws up through the floor into the base.
4. Route the right-angle USB-C cable through the side slot and zip-tie it to
   the bridge on the plate.
5. Snap the cover on (optional).
6. Hang it: two screws or anchors in the wall, heads standing about 3 mm
   proud, spaced to match the keyholes. Push the plate onto them and slide it
   down. Or use adhesive strips on the flat back.

Mount it at a comfortable height for holding a package under the window.
The scan engine reads from a few centimetres away.
