# Changelog

*English · [Русский](CHANGELOG.ru.md)*

Section numbers in parentheses refer to the Axel specification.

## [Unreleased]

- Numeric input started by a digit during a drag (9.3): the field showed the digit reformatted («3» → «3,00») with the caret after the first character, so typing a unit afterwards produced «3 cm,00» and was rejected. The text is now set after the field is shown; «3», then « cm», then Enter gives 30 mm.

## [0.1.2] — 2026-09-17

- Wider hit areas without changing the look (8.3): each arrow, arc, scale cube and extrude dot carries an invisible pickable shadow — a tube of ≈5.6 px around the shaft and the arc that also reaches beyond the arrow tip (outward only) and beyond both ends of the arc, and a sphere of ≈5.6 px around the cube and the dot. Arrows and arcs now pick from about 6 px away instead of 2–6 and a little past their ends, the cube and the dot from 5–6 px instead of 4–5.
- **Esc** with the manipulator shown acts like a click on empty space: the selection is cleared and the manipulator goes away (9.1). A drag, the numeric field and origin relocation are still cancelled first. While Axel is suppressed (sketch edit, a Draft command) Esc is left to FreeCAD.
- Keys are now taken from the viewer widget that owns the keyboard focus, not from its viewport: a real Esc during a drag (and digits typed during a drag) did not reach Axel before — only synthetic events in the probes did.
- A 3D view whose widget is already gone (a view being closed) no longer raises `RuntimeError … already deleted` on every refresh; such a view is skipped and a failed binding leaves no stray nodes in the scene graph (5.1.6).
- The preferences group now has an icon (`preferences-axel`); FreeCAD no longer reports "Cannot find icon: preferences-axel" when the theme changes.
- Magnetic cursor (8.5): while the cursor is over a handle it is gently pulled to the centre of the scale cube or extrude dot, or to the nearest point of an arrow's axis or of an arc, so that a click lands on the handle; the plane square is large enough and is left alone. Setting *Pull the cursor onto the handle under it* (`SnapCursor`, on by default).

## [0.1.1] — 2026-09-13

- Two `try/except/continue` spots flagged by Bandit (B112, low severity) in `input/operations.py` and `runtime.py` are replaced with small helper functions (`_shortcut_of`, `_graphics_view_of`); no behaviour change. The Addon Index scans addons with Bandit, the report is now clean.
- README (English and Russian) opens with the manipulator anatomy diagram; the diagram is generated from the handle constants and is bilingual.

## [0.1.0] — 2026-09-13

First release for the Addon Manager (content type "other", `package.xml` per Appendix B). Axel is not a workbench: restart FreeCAD manually after installing.

### Fine-tuning from user feedback (2026-09-13)
- The origin dot is no longer draggable: clicking it selects the point marker beneath it, otherwise the click is swallowed; right-click opens the menu, double-click relocates the origin (7.10, 9.1).
- The armed-operation label stays hidden for the whole drag and does not come back while the frame moves (8.4).
- The hovered and the active handle are drawn on top of the others; equal gaps between cone, dot and cube (8.1, 8.2).
- Extruding Draft objects: the handle on an axis creates a `Part::Extrusion`; the dot at an end vertex continues the line with a new segment (7.8).
- Scaling Draft objects (Wire, BSpline, BezCurve, Circle, Polygon, Ellipse, Rectangle); the shape updates while dragging; the scale cube's edge equals the cone diameter (7.8, 8.1, 11.2).
- "By object" alignment for Draft lines: X along the line, Z is the normal of its plane (7.8, 12.2).
- Move 2D caption in the form "ΔX … ΔY … L …" (8.4).
- The manipulator moves together with the object while dragging (11.2).
- Handle hints go to the status bar instead of a tooltip; the "Step" button was removed from the status bar, the command and menu entry remain (8.5, 15.2).
- Hover highlight is black instead of yellow (`ConfigVersion` 6); action cursors removed; the dragger's yellow active arrow removed (8.2, 8.3, 8.5).
- Rotation arcs with radius 0.75·S, symmetric about 225°; gap to the origin 0.20·S (8.1).
- Arrow cones 30 % longer towards the origin (0.208·S).
- Manipulator 20 % smaller: `SizePx` 80 px instead of 100 (the old default is dropped at start-up, `ConfigVersion` 5).
- Move 2D square: rounded corners, outline and a 3×3 grid in the axis colour (50 % transparent), fill more transparent (75 %).
- Semi-transparent manipulator: a "Transparency" setting (`TransparencyPercent`, default 30 %) for all handles; the white origin dot is 20 % more transparent than the other handles, its outline is a 1.25 px ring with at least 60 % transparency.
- Arrow shafts start at the same distance from the origin as the near end of the arc (was 0.12·S, now ≈0.163·S).
- Handles are drawn in flat colour without shading (the `BASE_COLOR` light model now sits inside each handle's geometry); the origin dot has a dark outline as intended in 8.1.
- Thinner arrow shafts and arcs: `ShaftWidthPx` 1.5 px instead of 2.5 (the old default is dropped at start-up, `ConfigVersion` 4).
- 6 px dots in the axis colour at the ends of the rotation arcs.
- Rotation arcs 20 % shorter, equally at both ends: 190.6°–259.4° instead of 182°–268°.
- The origin dot 30 % smaller: `OriginPx` 6 px instead of 9. A saved old default is dropped once at start-up (`ConfigVersion` 3).
- Fixed: after switching orthographic ↔ perspective the degenerate handles stopped updating — FreeCAD creates a new camera node and the Axel sensor stayed on the old one; it is now re-attached.
- In-plane move handles: a square of 0.25 of the manipulator size centred on the bounding box of two arrows (centre at 0.5 on both axes); only the plane handle facing the screen most is shown (the frame's XY on a tie).
- Rotation arcs as in Rhino 8: a full quarter with radius 1.05 of the manipulator size between the negative frame axes, independent of the camera.
- Menu icon removed: the manipulator menu opens by right-clicking the origin, from the status bar button or by a command. The `MenuCirclePx`, `MenuOffset` and `ShowMenu` settings are gone; `HandleKind.MENU` stays in API 1.0 for compatibility but is ignored.
- The selection a workbench command makes right after creating an object (Draft Line etc.) is cleared — the manipulator does not appear until the user selects the object. The `DeselectNewObjects` setting on the Axel page, on by default (13.2).
- Fixed: the manipulator turned monochrome light grey after the first "OK" in the preferences dialog — the colour buttons in the form had no defaults and wrote grey into all five keys. The form now has defaults (also used by "Reset"), corrupted entries are cleaned at start-up.

### Stage 4 — operations through adapters and API 1.0 (completed 2026-09-12)
- Scale along an axis, uniform (Shift) and in two axes (Shift + Move 2D); extrusion, including both sides; numeric input of the factor and the distance. Handles appear only on objects with a scale adapter.
- Operation slider: `D, D` splits a Draft line into segments, the count grows along the arrow, digits set an exact value, markers of the future vertices and a caption at the cursor.
- `E, E` on the end vertex of a Draft Line/Wire: a new vertex and segment, the line stays a single polyline, repeating continues it.
- Workbench adapter operations get a FreeCAD command and a shortcut automatically; the armed-operation label at the manipulator origin; adapter frame hints (`frame_hint`).
- Public API 1.0: `api.events`, suppression rules, `current_target`, `refresh`; `API_VERSION = 1`. Adapter author guide and the `Part::Cylinder` example adapter.
- Stage 4 acceptance passed automatically: 23 checks (4 items) in a live FreeCAD 1.1.3.

### Stage 3 — precision, copying, performance (completed 2026-09-12)
- Copying with the `C, C` operation; the double-letter operation mechanism with shortcut conflict checking.
- Edit points: Draft line vertices move individually, the manipulator jumps to the point.
- View alignment; snapping as a toggle with temporary inversion by Ctrl.
- A full preferences page in the FreeCAD dialog, changes apply without restart.
- Recompute policies during dragging and a simplified wireframe preview for large selections.
- Russian and English interface; the performance requirements of 17.1 are met.
- Stage 3 acceptance passed automatically: 17 checks (7 items) in a live FreeCAD 1.1.3.

### Stage 2 — move and rotate in full (completed 2026-09-12)
- Move 2D handles, free move by the origin, rotation arcs in all three alignment modes.
- Numeric input by click and during a drag; screen-space rotation mode for an edge-on ring.
- Relocating the origin as the rotation centre (it travels with the object), world/plane/object alignment and its cycle.
- The `attachment` and `assembly` adapters, `App::Link` and nested containers; the "unavailable" state with the reason in the hint.
- Guides and cursor captions (HUD), cursors by handle type, the manipulator menu; display in all 3D views of the document.
- Stage 2 acceptance passed automatically: 33 checks (10 items) in a live FreeCAD 1.1.3.

### Stage 1 — minimal working manipulator (completed 2026-09-12)
- Move arrows along the axes, plane handles, rotation arcs, the origin; constant screen size; drawn on top of the geometry.
- The `placement` adapter for top-level objects and objects inside containers/Links; one transaction per drag; Esc.
- The `Axel_Toggle` command in the View menu, a status bar button; settings read from `Mod/Axel`.
- Stage 1 acceptance passed automatically: 16 checks in a live FreeCAD 1.1.3.

### Stage 0 (completed 2026-09-12)
- Skeleton of the `freecad.axel` package, `package.xml`, ruff and pytest configuration.
- Seven technical probes in FreeCAD 1.1.3 (`tools/probes/`), the Stage 0 report.
- 25 FreeCAD API contract tests without the GUI (`test_c4_freecad_api.py`).
- Specification 0.3: all ⚑ marks replaced with verified calls; decision 18 — splitting into segments with `D, D`.
