# Axel

*English · [Русский](README.ru.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)*

Object manipulator for the FreeCAD 3D view, modelled on the Gumball from Rhinoceros. Python package `freecad.axel`.

![Anatomy of the manipulator](docs/02-widget-anatomy.en.svg)

## Usage

### Handles

![Move, rotate, move in a plane, scale, extrude](docs/media/overview.gif)

Select an object and the manipulator appears at the centre of its bounding box. **Arrows** move along an axis, the **square** moves in a plane, **arcs** rotate; a dashed guide and a label next to the cursor show the current distance or angle. The small **cube** on an arrow scales along that axis; the **dot** extrudes — here a closed Draft line with a face becomes a `Part::Extrusion` solid. Cubes and dots appear on objects whose workbench has declared an adapter with those capabilities (Draft lines and vertices, the `examples/cylinder.py` sample). **Shift** refines: uniform scale on a cube, scale in a plane on the square, extrude to both sides on a dot. Each drag is one undo step.

### Draft lines: vertices and extrusion

![Vertex markers, moving a vertex, extruding the end vertex, back to the object](docs/media/draft.gif)

A selected Draft line shows **markers** on its vertices. Click a marker and the manipulator jumps to that vertex: the arrows now move only that point. On the end vertex of an open line the extrude dot pulls out a **new segment** — drag it again to continue the line. A click on the line itself returns the manipulator to the whole object; the scale cube then transforms all points precisely, leaving `Placement` untouched.

### Manipulator menu

![Right-click on the origin: alignment, operations, handle visibility, step](docs/media/menu.gif)

**Right-click the origin** for the menu: relocate or reset the frame (a **double-click** on any handle also starts relocating the origin), choose the **alignment**, arm an **operation**, set the **drag strength**, hide or show groups of **handles**. The **Step** toggle snaps moves, rotations and scales to the configured increments — the label reads "10,00 mm · step"; **Ctrl** during a drag inverts the toggle temporarily.

### Alignment

![World, object and view alignment](docs/media/alignment.gif)

The frame can follow the **world** axes, the **object's** own axes (`Placement`, or a hint from the adapter — for a Draft line, X runs along its first segment), the **working plane** of Draft, or the **view** (X and Y in the screen plane). Same handles, different directions; the mode is remembered in the settings and can also be cycled with the *Axel: next alignment* command.

### Double letters: copy, split, extrude

![C,C — copies; D,D — split into segments; E,E — extrude the end vertex](docs/media/double-keys.gif)

Press a letter twice **before** dragging to arm an operation for the next drag; the hint appears next to the cursor. `C, C` — the drag makes a **copy** and selects it, so a series is just `C, C` again. `D, D` on a Draft line turns the drag into a **slider** for the number of segments (markers preview the new vertices; a digit sets the exact number). `E, E` with an end vertex selected **extrudes** a new segment from it. Workbench adapters can declare their own letters.

### Numeric input

![Click a handle and type; digits during a drag](docs/media/numeric.gif)

**Click** an arrow, arc or scale cube instead of dragging it, and an input field appears: `25` ⏎ moves 25 mm, `45` ⏎ rotates 45°, `1.5` ⏎ scales 1.5×. **During a drag** just start typing: the digit opens the field along the current direction, and the field understands units and expressions — `3 cm` gives exactly 30 mm.

Workbench authors: [docs/Adapter Author Guide.md](docs/Adapter%20Author%20Guide.md); the API is `freecad.axel.api` (`API_VERSION = 1`).

## Requirements

- FreeCAD ≥ 1.1 (Python 3.11, pivy and PySide as shipped with FreeCAD). No external dependencies.

## Installation

**Addon Manager** (Tools → Addon Manager, content type "Other"). Until Axel is listed in the FreeCAD catalog, add the repository by hand: in the Addon Manager preferences ("Custom repositories") enter `https://github.com/Onyx125/Axel` with branch `main`, then find "Axel" in the list and press Install. Axel is not a workbench, so the Addon Manager **will not remind you to restart**: restart FreeCAD manually after installing or updating.

**Manually:** copy the repository folder (or unpack a release archive) into `Mod/Axel` of your FreeCAD user folder — on Windows `%APPDATA%\FreeCAD\v1-1\Mod\Axel` — so that `package.xml` and `freecad/axel/` are inside it. Restart FreeCAD.

After start-up the manipulator appears on the selected object; the "Axel" button in the status bar or the command in the View menu turns it on and off.

## Licence

LGPL-2.1-or-later, the same as FreeCAD.
