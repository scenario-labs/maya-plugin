"""``scenarioSetUVs``: writes one UV set of a mesh as one undo step (spec 6.4, 7.3).

``MFnMesh.setUVs`` and ``assignUVs`` called from a script never enter Maya's
undo queue, so Replace UVs writes through this command: it keeps the set's
previous UVs and assignments, writes the new ones, and swaps them back on undo
and forward again on redo. Verified headless in Maya 2027.2 inside an undo
chunk with ``polyUVSet -copy`` and ``delete -constructionHistory``: two undo
and redo cycles, then a save and reopen, gave back the exact UVs.

The shape must have no construction history: history re-evaluates the mesh
and overwrites a direct write. ``maya/apply.py`` deletes it first, after the
review says so. Callers use ``run``, which stages the arrays for the command.
"""

from __future__ import annotations

from maya import cmds
from maya.api import OpenMaya as om

NAME = "scenarioSetUVs"

_staged: dict = {}


def run(shape: str, uv_set: str, us: list, vs: list, counts: list, ids: list) -> None:
    """Writes ``uv_set`` of ``shape``: UV values, then the UV id of each face corner (``counts`` per face, 0 for none)."""
    if not hasattr(cmds, NAME):
        raise RuntimeError("The Scenario for Maya plug-in is not loaded.")
    _staged.clear()
    _staged.update(shape=shape, uv_set=uv_set, data=(list(us), list(vs), list(counts), list(ids)))
    try:
        getattr(cmds, NAME)()
    finally:
        _staged.clear()


def _mesh(shape: str) -> om.MFnMesh:
    selection = om.MSelectionList()
    selection.add(shape)
    return om.MFnMesh(selection.getDagPath(0))


def _write(shape: str, uv_set: str, data: tuple) -> None:
    us, vs, counts, ids = data
    fn = _mesh(shape)
    fn.clearUVs(uv_set)
    if us:
        fn.setUVs(us, vs, uv_set)
        fn.assignUVs(counts, ids, uv_set)


class SetUVsCommand(om.MPxCommand):
    def __init__(self) -> None:
        super().__init__()
        self.shape = ""
        self.uv_set = ""
        self.old: tuple = ()
        self.new: tuple = ()

    @staticmethod
    def creator():
        return SetUVsCommand()

    def isUndoable(self) -> bool:
        return bool(self.new)

    def doIt(self, _args) -> None:
        if "data" not in _staged:
            raise RuntimeError(f"{NAME} is called by Scenario for Maya only.")
        self.shape, self.uv_set = _staged["shape"], _staged["uv_set"]
        # Keep the shape by handle: undo and redo find it even after a rename.
        self.shape = _mesh(self.shape).fullPathName()
        fn = _mesh(self.shape)
        if fn.numUVs(self.uv_set):
            us, vs = fn.getUVs(self.uv_set)
            counts, ids = fn.getAssignedUVs(self.uv_set)
            self.old = (list(us), list(vs), list(counts), list(ids))
        else:
            self.old = ([], [], [], [])
        self.new = _staged["data"]
        _write(self.shape, self.uv_set, self.new)

    def undoIt(self) -> None:
        _write(self.shape, self.uv_set, self.old)

    def redoIt(self) -> None:
        _write(self.shape, self.uv_set, self.new)


def register(plugin) -> None:
    plugin.registerCommand(NAME, SetUVsCommand.creator)


def deregister(plugin) -> None:
    try:
        plugin.deregisterCommand(NAME)
    except RuntimeError:
        pass
