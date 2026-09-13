"""Стандартный адаптер ``assembly`` (7.7): компоненты сборки Assembly.

Компонент — прямой потомок ``Assembly::AssemblyObject`` (или гибкой подсборки
``Assembly::AssemblyLink`` с ``Rigid = False``): ``App::Part``, ``PartDesign::Body``, ``App::Link``,
жёсткая подсборка. Свободный компонент ведёт себя как ``placement``; компонент, участвующий
хотя бы в одном незаглушённом сопряжении или заземлённый, берётся с ``disabled_reason``.
"""

from __future__ import annotations

import FreeCAD as App

from ..core.i18n import tr
from ..core.intent import Intent
from ..core.target import TargetItem, is_assembly_boundary
from .base import AdapterState, Capabilities
from .placement import HANDLES, PlacementAdapter, has_placement_property

ASSEMBLY_TYPE = "Assembly::AssemblyObject"
ASSEMBLY_LINK_TYPE = "Assembly::AssemblyLink"


def component_assembly(item: TargetItem) -> App.DocumentObject | None:
    """Сборка, компонентом которой является объект элемента (через гибкую подсборку — она сама)."""
    parent = item.parent()
    if parent is None or not is_assembly_boundary(parent):
        return None
    if parent.TypeId == ASSEMBLY_LINK_TYPE:
        # у AssemblyLink getLinkedObject() возвращает саму ссылку — берём свойство
        linked = getattr(parent, "LinkedObject", None)
        return linked if linked is not None and linked.TypeId == ASSEMBLY_TYPE else None
    return parent


def joint_group(assembly: App.DocumentObject) -> App.DocumentObject | None:
    """Группа сопряжений сборки без создания новой (``UtilsAssembly.getJointGroup`` создаёт)."""
    for obj in assembly.Group:
        if obj.TypeId == "Assembly::JointGroup":
            return obj
    return None


def _refers_to(joint: App.DocumentObject, prop: str, candidates: set[str]) -> bool:
    ref = getattr(joint, prop, None)
    if not ref:
        return False
    obj = ref[0] if isinstance(ref, tuple) else ref
    return obj is not None and obj.Name in candidates


def joints_of(
    assembly: App.DocumentObject, component: App.DocumentObject
) -> list[App.DocumentObject]:
    """Незаглушённые сопряжения сборки, в которых участвует компонент (7.7).

    Ссылки в 1.1 привязаны к компоненту; для компонента-ссылки внутри гибкой подсборки
    (``PS001 → PS``) считаются ссылки и на саму ссылку, и на связанный объект.
    """
    group = joint_group(assembly)
    if group is None:
        return []
    names = {component.Name}
    linked = getattr(component, "LinkedObject", None)
    if linked is not None and linked is not component:
        names.add(linked.Name)
    found = []
    for joint in group.Group:
        if getattr(joint, "Suppressed", False):
            continue
        if (
            _refers_to(joint, "Reference1", names)
            or _refers_to(joint, "Reference2", names)
            or _refers_to(joint, "ObjectToGround", names)
        ):
            found.append(joint)
    return found


class AssemblyAdapter(PlacementAdapter):
    """Компонент сборки: как ``placement``, но с проверкой сопряжений."""

    id = "axel.assembly"
    priority = 15

    def supports(self, item: TargetItem) -> bool:
        """Прямой потомок сборки (или гибкой подсборки) со свойством ``Placement``."""
        obj = item.object()
        if obj is None or not has_placement_property(obj):
            return False
        return component_assembly(item) is not None

    def capabilities(self, item: TargetItem) -> Capabilities:
        """Серый манипулятор, если компонент участвует в сопряжении или заземлён."""
        base = super().capabilities(item)
        if base.disabled_reason:
            return base
        assembly = component_assembly(item)
        joints = joints_of(assembly, item.object()) if assembly is not None else []
        if joints:
            label = joints[0].Label
            reason = tr(
                'Part is constrained by joint "{}". Move it with Assembly tools or delete the joint'
            ).format(label)
            return Capabilities(handles=HANDLES, can_copy=True, disabled_reason=reason)
        return Capabilities(handles=HANDLES, can_copy=True)

    def begin(self, items: list[TargetItem], intent: Intent) -> AdapterState:
        """Снимок как у ``placement``."""
        return super().begin(items, intent)
