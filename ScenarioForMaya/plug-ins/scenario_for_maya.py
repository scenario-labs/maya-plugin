"""Scenario for Maya: the Maya plug-in entry point.

Thin by design. It makes sure the ``scenario_maya`` package beside this file
is the one imported (also when Maya loads this file from outside the module),
then hands over to ``scenario_maya.maya.lifecycle``. Maya does not set
``__file__`` for Python plug-ins, so the folder comes from the code object's
file name, and the version must be known before ``MFnPlugin`` is created
(a second ``MFnPlugin`` with a version does not replace "Unknown").
"""

import os
import sys

from maya.api import OpenMaya as om

VENDOR = "Scenario"


def maya_useNewAPI():
    """Tells Maya this plug-in uses the Python API 2.0."""


def _use_sibling_package():
    plug_ins = os.path.dirname(os.path.realpath(_use_sibling_package.__code__.co_filename))
    scripts = os.path.join(os.path.dirname(plug_ins), "scripts")
    loaded = sys.modules.get("scenario_maya")
    if loaded is not None and not os.path.realpath(getattr(loaded, "__file__", "") or "").startswith(os.path.realpath(scripts) + os.sep):
        for name in [n for n in sys.modules if n == "scenario_maya" or n.startswith("scenario_maya.")]:
            del sys.modules[name]
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def initializePlugin(mobject):
    _use_sibling_package()
    import scenario_maya
    from scenario_maya.maya import lifecycle

    om.MFnPlugin(mobject, VENDOR, scenario_maya.__version__, "Any")
    try:
        lifecycle.load()
    except Exception:
        lifecycle.unload()
        raise


def uninitializePlugin(mobject):
    om.MFnPlugin(mobject)
    from scenario_maya.maya import lifecycle

    try:
        lifecycle.unload()
    finally:
        lifecycle.purge_modules()
