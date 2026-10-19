"""The plug-in's recording import command (spec 6.4 and 7.3): any import is one undo step.

API edits made from Python never enter Maya's undo queue, and importers
either flush it or undo badly. So every import runs inside ``scenarioImport``:
the command runs the build with undo recording paused, remembers the nodes it
created, deletes them on undo (top DAG nodes through one ``MDagModifier``,
then each remaining DG node such as materials through its own modifier) and
restores the very same nodes on redo by reversing those modifiers. Redo
never imports again: a redo that rebuilt the nodes crashed Maya in tests.

Callers do not invoke the command by hand: ``run(build)`` stages a Python
callable, calls the command and returns what the callable returned. Call it
inside an open undo chunk to group it with the namespace and selection.
"""

from __future__ import annotations

from maya import cmds
from maya.api import OpenMaya as om

NAME = "scenarioImport"

_staged: dict = {}


def run(build):
    """Runs ``build()`` as one undoable step and returns its result (re-raising its error)."""
    if not hasattr(cmds, NAME):
        raise RuntimeError("The Scenario for Maya plug-in is not loaded.")
    _staged.clear()
    _staged["build"] = build
    try:
        getattr(cmds, NAME)()
    except RuntimeError:
        if "error" in _staged:
            raise _staged["error"] from None
        raise
    finally:
        _staged.pop("build", None)
    if "error" in _staged:
        raise _staged.pop("error")
    return _staged.pop("result", None)


class ImportCommand(om.MPxCommand):
    def __init__(self) -> None:
        super().__init__()
        self.handles: list = []
        self.dag_mod = None
        self.dg_mods: list = []

    @staticmethod
    def creator():
        return ImportCommand()

    def isUndoable(self) -> bool:
        return bool(self.handles)

    def doIt(self, _args) -> None:
        build = _staged.get("build")
        if build is None:
            raise RuntimeError(f"{NAME} is called by Scenario for Maya only.")
        before = set(cmds.ls(uuid=True))
        recording = cmds.undoInfo(query=True, state=True)
        if recording:
            cmds.undoInfo(stateWithoutFlush=False)
        try:
            _staged["result"] = build()
        except Exception as error:  # noqa: BLE001
            _staged["error"] = error
        finally:
            if recording:
                cmds.undoInfo(stateWithoutFlush=True)
            self._remember(before)
        if "error" in _staged:
            self._delete()  # a half-built import never stays in the scene
            self.handles = []
            raise RuntimeError(f"Scenario import failed: {_staged['error']}")

    def _remember(self, before: set) -> None:
        new = [uuid for uuid in cmds.ls(uuid=True) if uuid not in before]
        names = cmds.ls(new, long=True) or []
        selection = om.MSelectionList()
        for name in names:
            try:
                selection.add(name)
            except RuntimeError:
                continue
        self.handles = [om.MObjectHandle(selection.getDependNode(index)) for index in range(selection.length())]

    def _alive(self) -> list:
        return [handle.object() for handle in self.handles if handle.isValid() and handle.isAlive()]

    def _delete(self) -> None:
        objects = self._alive()
        paths = {om.MFnDagNode(o).fullPathName() for o in objects if o.hasFn(om.MFn.kDagNode)}
        tops = []
        for o in objects:
            if not o.hasFn(om.MFn.kDagNode):
                continue
            node = om.MFnDagNode(o)
            parent = node.parent(0) if node.parentCount() else None
            parent_path = om.MFnDagNode(parent).fullPathName() if parent is not None and parent.hasFn(om.MFn.kDagNode) else ""
            if parent_path not in paths:
                tops.append(o)
        # Decide first, queue after: once a parent is queued, its children report empty paths.
        self.dag_mod = om.MDagModifier()
        for o in tops:
            self.dag_mod.deleteNode(o)
        self.dag_mod.doIt()
        self.dg_mods = []
        skipped = []
        for handle in self.handles:
            if not (handle.isValid() and handle.isAlive()):
                continue  # gone with an earlier deletion (a materialInfo with its shading group)
            o = handle.object()
            if o.hasFn(om.MFn.kDagNode):
                continue
            modifier = om.MDGModifier()
            try:
                modifier.deleteNode(o)
                modifier.doIt()
                self.dg_mods.append(modifier)
            except RuntimeError:
                skipped.append(om.MFnDependencyNode(o).name())
        if skipped:
            om.MGlobal.displayWarning(f"Scenario undo could not delete: {', '.join(skipped)}")

    def undoIt(self) -> None:
        if self.dag_mod is None:
            self._delete()
            return
        self.dag_mod.doIt()
        for modifier in self.dg_mods:
            modifier.doIt()

    def redoIt(self) -> None:
        if self.dag_mod is None:
            return
        for modifier in reversed(self.dg_mods):
            modifier.undoIt()
        self.dag_mod.undoIt()


def register(plugin) -> None:
    plugin.registerCommand(NAME, ImportCommand.creator)


def deregister(plugin) -> None:
    try:
        plugin.deregisterCommand(NAME)
    except RuntimeError:
        pass
