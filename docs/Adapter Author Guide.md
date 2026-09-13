# Adapter Author Guide

*English · [Русский](Руководство%20автора%20адаптера.md)*

How to teach the Axel manipulator to work with the objects of your workbench: move and
rotate them your own way, scale and extrude them, declare edit points and double-letter
operations. The public API is the `freecad.axel.api` module, version `API_VERSION = 1`
(section 16 of the specification). Everything else in the package is internal and may change.

A ready-made example is `freecad/axel/examples/cylinder.py`: an adapter for `Part::Cylinder`
that turns scaling into `Radius` and `Height`, extrusion into growing the height or the radius,
declares the `A, A` slider operation for the sector angle and constrains the intent. Its tests
are in `freecad/axel/tests/test_scale_extrude.py`. The reference for operations on lines is
`freecad/axel/adapters/draft.py` (`E, E` — vertex extrusion, `D, D` — splitting).

## 1. How it works

1. The user selects objects. Axel builds a **target** (`Target`) out of `TargetItem` elements:
   the document, the selection path, the object to move according to rule 7.3 and its global
   matrix.
2. For every item the registry picks an **adapter**: the first one in descending `priority`
   whose `supports(item)` is true. Workbench adapters register with `priority ≥ 100` and
   override the standard ones (`placement`, `attachment`, `assembly`, `draft`).
3. The adapter reports its **capabilities**: which handles to show, on which axes, whether
   copying is allowed, why the object is unavailable.
4. Dragging a handle is a **session**: one application-level transaction, undone by a single
   Ctrl+Z. Axel computes the **intent** (`Intent`) in terms of the manipulator frame — offset,
   angle, factors, extrusion distance, slider value — and calls
   `begin → constrain → preview (many times) → commit` or `cancel`.
5. The adapter translates the intent into property changes. The core knows nothing about
   object types.

Rules worth keeping:

- **The intent is always measured from the start of the session.** `preview` receives the full
  offset / angle / factor relative to the snapshot taken in `begin`, not an increment. Apply
  it to the stored original values, not to the current ones.
- **An error must not bring FreeCAD down.** An exception in an adapter method cancels the
  session with a rollback and is reported; still, better not to raise from `preview`.
- **The session rolls the document back.** `cancel` releases only what does not belong to the
  document (temporary scene nodes, caches).

## 2. A minimal adapter

```python
from freecad.axel import api

class PipeAdapter(api.Adapter):
    id = "mywb.pipe"
    priority = 100

    def supports(self, item):
        obj = item.object()
        return getattr(obj, "Proxy", None) is not None and getattr(obj.Proxy, "Type", "") == "Pipe"

    def capabilities(self, item):
        return api.Capabilities(
            handles=frozenset({api.HandleKind.MOVE_AXIS, api.HandleKind.ROTATE}),
            axes=frozenset({0}),        # only along the frame's X and around it
        )

    def begin(self, items, intent):
        state = api.AdapterState(list(items))
        state.data["placements"] = {it.obj_name: it.object().Placement.copy() for it in items}
        return state

    def preview(self, state, intent):
        delta = intent.matrix()      # global matrix D: G' = D·G
        for item in state.items:
            obj = item.object()
            original = state.data["placements"][obj.Name]
            # for an object inside a container: L' = P⁻¹·D·P·L, see adapters/placement.py
            obj.Placement = App.Placement(delta * original.toMatrix())

    def commit(self, state, intent):
        self.preview(state, intent)
        return [item.obj_name for item in state.items]   # what to recompute

api.register_adapter(PipeAdapter())
```

Register from the workbench's `InitGui.py` or when the workbench is activated. The workbench
must work without Axel: wrap the import in `try/except ImportError` and check
`api.API_VERSION`.

`Adapter` is an ordinary class; inheriting is optional but convenient: the default methods do
nothing. It is often simpler to inherit the standard `PlacementAdapter`
(`freecad.axel.adapters.placement`) and override only what differs — that is how `draft` and
the `cylinder` example are built.

## 3. The protocol, method by method

| Method | When it is called | What to return |
|---|---|---|
| `supports(item)` | On every rebuild of the target | `True` if the object is yours |
| `capabilities(item)` | After the adapter is chosen | `Capabilities`: handles, axes, `can_copy`, `disabled_reason` |
| `frame_hint(item)` | When the frame is built | `FrameHint(origin, rotation)` or `None` |
| `edit_points(item)` | With a single selected object, after every commit | A list of `EditPoint` with stable `id`s |
| `operations(item)` | On a rebuild of the target | A list of `OperationSpec` |
| `begin(items, intent)` | Mouse press on a handle | An opaque state (`AdapterState`) with a snapshot |
| `constrain(state, intent)` | Before every `preview` and `commit` | The intent, possibly altered |
| `preview(state, intent)` | Every mouse move | — |
| `commit(state, intent)` | Mouse release or Enter | Names of the changed objects |
| `cancel(state)` | Esc, object deletion, an error | — |
| `duplicate(state)` | `C, C` before dragging | A new state for the copies |
| `operation_name(intent)` | Opening the session | A name for the undo history |

### Capabilities

- `handles` — handle kinds: `MOVE_AXIS`, `MOVE_PLANE`, `MOVE_FREE`, `ROTATE`, `SCALE_AXIS`,
  `EXTRUDE`. Scale and extrude handles appear **only** if the adapter declared them: objects
  without an adapter have none (decision 5 of the specification). `MENU` stays in the
  enumeration for compatibility but has no handle: the menu opens by right-clicking the origin.
- `axes` — on which frame axes to show arrows, arcs, cubes and dots.
- `disabled_reason` — the manipulator is drawn grey, the reason goes to the hint and the status
  bar. Use it instead of `supports() → False`: the user should understand why not.
- With several objects the capabilities intersect: the common set of handles is shown.

### Frame

`FrameHint.origin` sets the manipulator origin instead of the bounding-box centre (for
example, the axis of a pipe), `FrameHint.rotation` — the orientation in the "By object" mode
(for example, X along the pipe). With several hinted items the origin is the centre of their
bounding boxes.

## 4. What the intent carries

`Intent.operation` and the fields it fills:

| Operation | Fields | How to apply |
|---|---|---|
| `TRANSLATE` | `translation` (global) | `intent.matrix()` — the matrix `D` |
| `ROTATE` | `axis`, `angle` (radians), `center` | `intent.matrix()` |
| `SCALE` | `factors` per **frame** axis, `center`, `axis` | `intent.matrix()` gives `T(c)·R·S(f)·R⁻¹·T(−c)`; a parametric object usually needs the factors themselves — map the frame axes onto the object axes as in `examples/cylinder.py` |
| `EXTRUDE` | `distance` (mm, signed), `axis`, `both_sides` | The adapter builds the geometry; there is no matrix |
| `PARAMETER` | `value`, `op_id` | Operation slider; there is no matrix |

Common fields: `frame` — the frame at the start of the session, `handle` — which handle,
`copy` — a copy is in progress, `op_id` — the armed operation, `point_id` — an edit point is
being moved, `step` — snapping was active, `source` — mouse or numeric input.

What the core has already done: drag strength, snapping (Ctrl), the ban on negative scale
(`AllowMirror`), the screen-space rotation mode, clamping the slider to `minimum…maximum`.
The adapter receives the final value.

`constrain` is the place for your own constraints: snap a length to the grid step, forbid
values below a minimum, pull towards connection points. Return
`dataclasses.replace(intent, …)`.

## 5. Scale and extrude

Scale handles (cubes on the axes) and extrude handles (dots on the arrows) are shown when
`capabilities` include `SCALE_AXIS` and `EXTRUDE`. Modifiers:

- scale: dragging — along one axis, Shift — uniformly along all three, Shift on Move 2D —
  along the two axes of the plane; clicking a cube — numeric input of the factor;
- extrude: dragging a dot — `distance` along the axis, Shift — `both_sides`.

The meaning of the operations is up to the adapter: for a pipe, scaling along the axis changes
the length of a segment, extruding prolongs it. `examples/cylinder.py` shows how to account
for scaling being relative to the manipulator origin rather than the object origin: the base is
shifted so that the point `intent.center` stays in place.

## 6. Edit points

`edit_points(item)` returns points with stable `id`s, a global position and, if needed, an
orientation and their own set of handles. With a single selected object markers appear on it;
clicking a marker puts the manipulator at the point. The session then runs as usual, but the
intent has `point_id` filled in: the adapter moves that point rather than the object
(`adapters/draft.py`, the `Points` vertices).

After a commit the adapter is queried again and the chosen point is kept by `id`. If the
operation created a new point that should become selected (as `E, E` does), put its `id` into
`state.select_point`.

## 7. Double-letter operations

```python
def operations(self, item):
    return [
        api.OperationSpec(
            id="length", scope=api.OperationScope.OBJECT, key="L", title="Set length",
            handles=frozenset({api.HandleKind.MOVE_AXIS}),
            param=api.ParamSpec(kind=float, default=float(item.object().Length),
                                minimum=10.0, maximum=5000.0, title="Length", step=50.0),
        ),
    ]
```

- The FreeCAD command and the `L, L` shortcut are created **automatically** as soon as the
  operation first appears on a target; the shortcut can be reassigned in Tools → Customize,
  the entry is in the manipulator menu. The letters C, E, D are reserved for copy, extrude and
  split — an adapter that implements extrusion or splitting declares an operation with
  `id="extrude"` / `"split"` and gets the standard `Axel_OpExtrude` / `Axel_OpSplit`
  commands. A new operation with a taken letter is not registered; the error is reported.
- `scope` — over the object or over the selected point. A point operation may limit which
  points it is available on: `points=frozenset({"v0", "v5"})`.
- `handles` — on which handles the operation acts; dragging the others stays ordinary.
- The user presses the double letter, then drags a handle. The intent carries `op_id`;
  `begin` receives it when the session opens and may prepare the snapshot differently (as
  `draft` inserts a copy of the vertex for `extrude`).
- An operation with `param` is a **slider**: a `PARAMETER` intent whose value grows as the
  cursor moves along the handle's screen direction, every `SliderStepPx` pixels — `±1` for
  `int` or `±step` for `float` (default `(maximum − minimum) / 100`). Digits during the slider
  set an exact value, releasing applies, Esc cancels. Do not change the document during the
  slider: fill `state.markers` in `preview` — Axel shows markers of the future result and the
  caption `"title: value"`; change the document in `commit`.

## 8. Copying

`C, C` before dragging calls `duplicate(state)` right after `begin`: create the copies
(`doc.copyObject`), return a new state for them and put the originals back where they were.
All of this happens inside one transaction — Ctrl+Z removes the copies. After the commit Axel
selects the copies (names from `commit`). Forbid copying with `can_copy=False`.

## 9. Events and suppression

```python
api.events.drag_started.connect(lambda target, intent: ...)
api.events.drag_committed.connect(lambda target, intent, changed_names: ...)
api.events.drag_cancelled.connect(lambda target: ...)
api.events.target_changed.connect(lambda target_or_none: ...)
api.events.operation_armed.connect(lambda op_id_or_none: ...)

api.add_suppression_rule("mywb.tool_active", lambda: MyTool.is_running())
api.remove_suppression_rule("mywb.tool_active")
api.current_target(), api.is_enabled(), api.refresh()
```

Handlers run on the main thread; an exception is logged and does not disturb Axel. A
suppression rule hides the manipulator while its predicate is true (for example, while the
workbench's own interactive tool is running) — it is checked on every rebuild of the target,
and adding or removing a rule rebuilds the target.

## 10. Common mistakes

- **Increments instead of the full intent.** `preview` is called repeatedly with the full value
  measured from the start of the session; adding it to the object's current state is wrong.
- **Recompute in `preview`.** Do not call `recompute` yourself: the recompute policy during a
  drag is the user's choice (`RecomputeDuringDrag`); after `commit` Axel recomputes the
  objects whose names you returned.
- **Your own transactions.** Do not open `doc.openTransaction` — the session already holds an
  application-level transaction; a nested one breaks single-step undo.
- **Copies inside a container.** `doc.copyObject` creates the copy outside containers; add it
  to the original's container yourself (see `PlacementAdapter.duplicate`).
- **Bounding boxes on every call.** `Shape.BoundBox` in FreeCAD 1.1 leaks by a weak reference
  per call; do not compute bounding boxes in `preview` — cache them in `begin`.
- **The operation letter.** C, E, D are taken; a single letter that matches another command's
  key is not a conflict (the double fires immediately, the single one after a timeout), but an
  exact `L, L` match with a foreign command leaves the operation without a shortcut — Axel
  reports it.
- **Registering before Axel starts.** `api.register_adapter` may be called at any time: if
  Axel is not enabled yet, the adapter simply waits in the registry.
