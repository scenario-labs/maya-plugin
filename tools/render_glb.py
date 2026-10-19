"""Renders a GLB in Maya's Viewport 2.0 without a window, through the plug-in's own importer.

Used for README pictures of 3D results: the model is landed exactly as the
Import button lands it, lit by a key, a rim and a fill light in front of a
grey backdrop, and rendered with ``ogsRender`` (Viewport 2.0, works headless).
Stills at the given angles, or a full turn; ``--gif`` also writes a looping
GIF with ffmpeg; ``--checker`` shows the UV layout instead of the materials;
``--wire`` draws every edge as a thin tube, so the topology shows (batch
Viewport 2.0 draws no wireframe).
0 CU: nothing is sent to Scenario.

Usage (mayapy, headless):
  MAYA_DISABLE_CER=1 mayapy tools/render_glb.py result.glb out/ --angles 0,180
  MAYA_DISABLE_CER=1 mayapy tools/render_glb.py result.glb out/ --turn 48 --size 480 --gif out/turn.gif
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("glb")
    parser.add_argument("out", help="folder for the JPEG frames")
    parser.add_argument("--angles", default="0", help="turntable angles in degrees, comma separated (0 is a three-quarter front view)")
    parser.add_argument("--turn", type=int, default=0, help="render a full turn in this many frames instead")
    parser.add_argument("--size", type=int, default=800)
    parser.add_argument("--gif", help="also write a looping GIF here (needs ffmpeg)")
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--checker", type=int, default=0, help="replace the materials by a checker repeated this many times across UV space")
    parser.add_argument("--wire", action="store_true", help="draw every edge over the model")
    args = parser.parse_args()
    glb, out = os.path.abspath(args.glb), os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    angles = [360.0 * i / args.turn for i in range(args.turn)] if args.turn else [float(a) for a in args.angles.split(",")]

    import maya.standalone

    maya.standalone.initialize(name="python")
    from maya import cmds

    project = tempfile.mkdtemp(prefix="scenario-render-")
    cmds.workspace(project, openWorkspace=True)
    cmds.loadPlugin(os.path.join(ROOT, "ScenarioForMaya", "plug-ins", "scenario_for_maya.py"))
    from scenario_maya.maya import landing

    stem = os.path.splitext(os.path.basename(glb))[0]
    made = landing.land_model(glb, {}, texture_folder=os.path.join(project, "sourceimages", stem), label=stem, place=(0, 0, 0))
    print(made["summary"], flush=True)
    if args.checker:
        checker = cmds.shadingNode("checker", asTexture=True, name="uv_checker")
        cmds.setAttr(checker + ".color1", 0.85, 0.85, 0.82, type="double3")
        cmds.setAttr(checker + ".color2", 0.2, 0.45, 0.75, type="double3")
        place = cmds.shadingNode("place2dTexture", asUtility=True)
        cmds.connectAttr(place + ".outUV", checker + ".uvCoord")
        cmds.setAttr(place + ".repeatUV", args.checker, args.checker, type="double2")
        shader = cmds.shadingNode("lambert", asShader=True, name="uv_checker_shader")
        cmds.connectAttr(checker + ".outColor", shader + ".color")
        cmds.select(cmds.listRelatives(made["top"], allDescendents=True, type="mesh", fullPath=True))
        cmds.hyperShade(assign=shader)

    box = cmds.exactWorldBoundingBox(made["top"])
    parts = [made["top"]]
    if args.wire:
        diagonal = sum((box[i + 3] - box[i]) ** 2 for i in range(3)) ** 0.5
        parts.append(wireframe(cmds.listRelatives(made["top"], allDescendents=True, type="mesh", fullPath=True), diagonal * 0.0012))
    # Batch mode draws no background colour, so a grey cyclorama stands behind and under the model.
    span = max(box[3] - box[0], box[4] - box[1], box[5] - box[2]) * 14
    floor = cmds.polyPlane(width=span, height=span, subdivisionsX=1, subdivisionsY=1, name="backdrop_floor")[0]
    wall = cmds.polyPlane(width=span, height=span, subdivisionsX=1, subdivisionsY=1, axis=(0, 0, 1), name="backdrop_wall")[0]
    cmds.move(0, span / 2, -span / 5, wall)
    backdrop = cmds.group(floor, wall, name="backdrop")
    cmds.setAttr(backdrop + ".rotateY", 30)
    grey = cmds.shadingNode("lambert", asShader=True, name="backdrop_grey")
    cmds.setAttr(grey + ".color", 0.3, 0.31, 0.33, type="double3")
    cmds.select(floor, wall)
    cmds.hyperShade(assign=grey)
    cmds.select(clear=True)
    for name, intensity, rotate in (("key", 1.6, (-38, 40, 0)), ("rim", 0.7, (-18, 200, 0))):
        light = cmds.directionalLight(intensity=intensity, name=name)
        cmds.setAttr(cmds.listRelatives(light, parent=True)[0] + ".rotate", *rotate, type="double3")
    cmds.ambientLight(intensity=0.5, name="fill")
    modes = cmds.attributeQuery("lightingMode", node="hardwareRenderingGlobals", listEnum=True)[0].split(":")
    cmds.setAttr("hardwareRenderingGlobals.lightingMode", modes.index("All"))
    cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", 1)
    cmds.setAttr("defaultRenderGlobals.imageFormat", 8)  # JPEG
    # Batch ogsRender writes scene-linear values; the viewport applies the view transform, so do the same.
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputTransformEnabled=True)
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputUseViewTransform=True)

    spin = cmds.group(*parts, name="spin")
    cmds.xform(spin, pivots=(0, 0, 0), worldSpace=True)
    cmds.setAttr("persp.rotate", -15, 30, 0, type="double3")
    cmds.setAttr("perspShape.focalLength", 50)
    cmds.viewFit("persp", spin, fitFactor=0.95)
    frames = []
    for index, angle in enumerate(angles):
        cmds.setAttr(spin + ".rotateY", angle)
        written = cmds.ogsRender(camera="perspShape", width=args.size, height=args.size)
        target = os.path.join(out, f"{stem}_{index:03d}.jpg")
        shutil.move(written, target)
        frames.append(target)
    print(f"{len(frames)} frame(s) in {out}", flush=True)
    if args.gif:
        pattern = os.path.join(out, f"{stem}_%03d.jpg")
        palette = f"fps={args.fps},split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=sierra2_4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps), "-i", pattern, "-filter_complex", palette, "-loop", "0", args.gif], check=True)
        print("GIF", args.gif, flush=True)
    os._exit(0)  # Maya 2027 can stall in uninitialize() after rendering


def wireframe(meshes: list, width: float) -> str:
    """One mesh of thin square tubes, one per edge of ``meshes`` (world space), in a dark material."""
    from maya import cmds
    from maya.api import OpenMaya as om

    points, counts, connects = om.MPointArray(), [], []
    for mesh in meshes:
        selection = om.MSelectionList()
        selection.add(mesh)
        edges = om.MItMeshEdge(selection.getDagPath(0))
        while not edges.isDone():
            a, b = edges.point(0, om.MSpace.kWorld), edges.point(1, om.MSpace.kWorld)
            axis = om.MVector(b - a)
            if axis.length() > 0:
                axis.normalize()
                helper = om.MVector(0, 1, 0) if abs(axis.y) < 0.9 else om.MVector(1, 0, 0)
                u = (axis ^ helper).normal() * width
                v = (axis ^ u).normal() * width
                base = len(points)
                for point in (a, b):
                    for offset in (u + v, u - v, -u - v, -u + v):
                        points.append(point + offset)
                for k in range(4):
                    counts.append(4)
                    connects += [base + k, base + (k + 1) % 4, base + 4 + (k + 1) % 4, base + 4 + k]
            edges.next()
    transform = om.MFnDagNode(om.MFnMesh().create(points, counts, connects)).fullPathName()
    transform = cmds.rename(transform, "wire")
    ink = cmds.shadingNode("lambert", asShader=True, name="wire_ink")
    cmds.setAttr(ink + ".color", 0.03, 0.04, 0.06, type="double3")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="wire_inkSG")
    cmds.connectAttr(ink + ".outColor", group + ".surfaceShader")
    cmds.sets(transform, edit=True, forceElement=group)
    return transform


if __name__ == "__main__":
    sys.exit(main())
