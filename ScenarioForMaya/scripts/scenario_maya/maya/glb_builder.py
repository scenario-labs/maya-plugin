"""GLB results as native Maya nodes (spec 6.2, 6.5 and 6.7).

``build`` runs on the main thread inside ``import_command.run``, so the whole
import is one undo step; the file is parsed beforehand by ``core.gltf``,
which also writes the embedded textures. Glossary of the conversions:

- Units: glTF metres become the scene's linear unit (x100 in centimetres).
  Values given through ``cmds`` use the scene unit; mesh points, matrices and
  distance keys given through the API are in centimetres whatever the scene
  unit (a metre scene once got models 100 times too small).
- Up axis: glTF is Y-up; in a Z-up scene the root group turns 90 degrees on X.
- Meshes: one Maya mesh per glTF mesh node, its triangle primitives merged
  with a shading group per primitive. Vertices that glTF splits along UV or
  normal seams are welded back by position, so the mesh is one piece; UVs and
  normals stay per face-vertex. Normals come from the file (locked, as an FBX
  import leaves them).
- Joints: a joint's rest rotation goes to ``jointOrient`` and ``rotate`` stays
  zero, as FBX rigs arrive, so GLB and FBX rigs land the same way. Rotation
  keys are converted (Maya joint matrix = rotate x jointOrient, verified).
  ``segmentScaleCompensate`` is off: glTF has no such thing.
- Skins: the mesh sits under the root with ``inheritsTransform`` off, the
  skinCluster's bind pre-matrices are the file's inverse bind matrices.
- Morph targets: a blendShape at the front of the chain.
- Animation: the first clip is keyed from the scene's start frame; the
  playback range is not changed. Other clips are listed, not imported.
"""

from __future__ import annotations

import math

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from ..core import naming
from . import landing

RAW = "Raw"
SHADER_ATTRS = {
    "openPBRSurface": {"base": "baseColor", "metal": "baseMetalness", "rough": "specularRoughness", "emission": "emissionColor", "opacity": "geometryOpacity"},
    "standardSurface": {"base": "baseColor", "metal": "metalness", "rough": "specularRoughness", "emission": "emissionColor", "opacity": "opacity"},
    "lambert": {"base": "color"},
}
# [assumed] openPBR's emission is in nits and defaults to 0; 1000 reads as a lit
# surface in Viewport 2.0 and Arnold. To check against Scenario's emissive results.
EMISSION_NITS = 1000.0


def build(doc, images: list, base: str) -> dict:
    """Builds the document's default scene under ``<base>_grp``; returns what was made."""
    return _Builder(doc, images, base).run()


def build_materials(doc, images: list, base: str, name: str = "") -> dict:
    """Only the document's materials (Replace textures, spec 6.4): ``{shaders, shading_groups, notes}``.

    ``name`` replaces the file's material names (the first gets it as is, the others a number)."""
    if name:
        for index, material in enumerate(doc.json.get("materials") or []):
            material["name"] = name if index == 0 else f"{name}_{index + 1}"
    builder = _Builder(doc, images, base)
    builder._materials()
    return {"shaders": builder.shaders, "shading_groups": builder.shading_groups, "textured": sorted(builder.textured), "notes": builder.notes}


def _row_quaternion(values) -> om.MQuaternion:
    x, y, z, w = values
    return om.MQuaternion(x, y, z, w)


def _degrees(rotation: om.MEulerRotation) -> tuple:
    return math.degrees(rotation.x), math.degrees(rotation.y), math.degrees(rotation.z)


def _short(path: str) -> str:
    """A node's own name: no DAG path, no namespace."""
    return path.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _long(name: str) -> str:
    return (cmds.ls(name, long=True) or [name])[0]


def _depend_node(name: str):
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDependNode(0)


class _Builder:
    def __init__(self, doc, images: list, base: str) -> None:
        self.doc = doc
        self.data = doc.json
        self.images = images
        self.base = base
        # cmds takes distances in the scene's unit; the API (mesh points, matrices, anim curves) in centimetres.
        self.unit = om.MDistance(1.0, om.MDistance.kMeters).asUnits(om.MDistance.uiUnit())
        self.internal = om.MDistance(1.0, om.MDistance.kMeters).asUnits(om.MDistance.internalUnit())
        self.fps = om.MTime(1.0, om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
        self.notes: list = []
        self.nodes: dict = {}
        self.rest: dict = {}
        self.joint_nodes = {joint for skin in self.data.get("skins") or [] for joint in skin.get("joints") or []}
        self.skinned = {index for index, node in enumerate(self.data.get("nodes") or []) if "skin" in node and "mesh" in node}
        self.shading_groups: list = []
        self.shaders: list = []
        self.textured: set = set()
        self.meshes: dict = {}
        self.blend_shapes: dict = {}
        self.skin_clusters: list = []
        self.collapsed = 0
        self.root = ""
        self._offset = 0

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    # -- the whole build ---------------------------------------------------

    def run(self) -> dict:
        self.root = _long(cmds.group(empty=True, name=f"{self.base}_grp"))
        if cmds.upAxis(query=True, axis=True) == "z":
            cmds.setAttr(self.root + ".rotateX", 90)
        self._materials()
        scenes = self.data.get("scenes") or []
        if scenes:
            roots = scenes[self.data.get("scene", 0)].get("nodes") or []
        else:
            children = {child for node in self.data.get("nodes") or [] for child in node.get("children") or []}
            roots = [index for index in range(len(self.data.get("nodes") or [])) if index not in children]
        for index in roots:
            self._node(index, self.root)
        for index in sorted(self.nodes):
            if "mesh" in self.data["nodes"][index]:
                self._mesh(index)
        for index in sorted(self.meshes):
            self._morphs(index)
        for index in sorted(self.meshes):
            if index in self.skinned:
                self._skin(index)
        clip = self._animation()
        if self.collapsed:
            self.note(f"{self.collapsed} collapsed triangle(s) left out")
        return {
            "top": self.root,
            "meshes": [mesh["shape"] for mesh in self.meshes.values()],
            "shaders": self.shaders,
            "shading_groups": self.shading_groups,
            "joints": [self.nodes[index] for index in sorted(self.joint_nodes) if index in self.nodes],
            "skin_clusters": self.skin_clusters,
            "blend_shapes": list(self.blend_shapes.values()),
            "clip": clip,
            "other_clips": [anim.get("name") or f"clip_{index + 1}" for index, anim in enumerate(self.data.get("animations") or [])][1:],
            "collapsed_triangles": self.collapsed,
            "notes": self.notes,
        }

    # -- materials -----------------------------------------------------------

    def _texture(self, info: dict, name: str, space: str):
        textures = self.data.get("textures") or []
        index = info.get("index")
        if index is None or index >= len(textures):
            return None
        source = textures[index].get("source")
        path = self.images[source] if source is not None and source < len(self.images) else ""
        if not path:
            self.note("a texture is missing from the file")
            return None
        if info.get("texCoord", 0) != 0:
            self.note("textures on a second UV set use the first one")
        if "KHR_texture_transform" in (info.get("extensions") or {}):
            self.note("texture offsets and tiling from the file are not applied")
        texture, _place = landing.file_texture(path, name, space)
        return texture

    def _materials(self) -> None:
        kind = landing.surface_type()
        attrs = SHADER_ATTRS.get(kind, SHADER_ATTRS["lambert"])
        for index, material in enumerate(self.data.get("materials") or []):
            name = naming.node_name(material.get("name") or f"material_{index + 1}")
            shader = cmds.shadingNode(kind, asShader=True, name=f"{name}_mtl")
            group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{name}_SG")
            cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
            pbr = material.get("pbrMetallicRoughness") or {}
            factor = list(pbr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0])
            cmds.setAttr(f"{shader}.{attrs['base']}", *factor[:3], type="double3")
            if "metal" in attrs:
                cmds.setAttr(f"{shader}.{attrs['metal']}", float(pbr.get("metallicFactor", 1.0)))
                cmds.setAttr(f"{shader}.{attrs['rough']}", float(pbr.get("roughnessFactor", 1.0)))
            if pbr.get("baseColorTexture"):
                texture = self._texture(pbr["baseColorTexture"], f"{name}_base_color", landing.SRGB)
                if texture:
                    cmds.setAttr(texture + ".colorGain", *factor[:3], type="double3")
                    cmds.connectAttr(texture + ".outColor", f"{shader}.{attrs['base']}", force=True)
                    self.textured.add(index)
                    if material.get("alphaMode", "OPAQUE") != "OPAQUE" and "opacity" in attrs:
                        cmds.setAttr(texture + ".alphaGain", factor[3])
                        self._opacity(shader, kind, texture + ".outAlpha")
                        if material.get("alphaMode") == "MASK":
                            self.note("alpha cut-outs show as transparency")
            elif material.get("alphaMode", "OPAQUE") != "OPAQUE" and factor[3] < 1.0 and kind == "openPBRSurface":
                cmds.setAttr(shader + ".geometryOpacity", factor[3])
            if pbr.get("metallicRoughnessTexture") and "metal" in attrs:
                texture = self._texture(pbr["metallicRoughnessTexture"], f"{name}_metal_rough", RAW)
                if texture:
                    # glTF packs roughness in green and metalness in blue; colorGain carries the factors.
                    cmds.setAttr(texture + ".colorGain", 1.0, float(pbr.get("roughnessFactor", 1.0)), float(pbr.get("metallicFactor", 1.0)), type="double3")
                    cmds.connectAttr(texture + ".outColorG", f"{shader}.{attrs['rough']}", force=True)
                    cmds.connectAttr(texture + ".outColorB", f"{shader}.{attrs['metal']}", force=True)
            if material.get("normalTexture"):
                texture = self._texture(material["normalTexture"], f"{name}_normal", RAW)
                if texture:
                    bump = cmds.shadingNode("bump2d", asUtility=True, name=f"{name}_normal_bump")
                    cmds.setAttr(bump + ".bumpInterp", 1)  # tangent-space normals (glTF: OpenGL convention, as Maya)
                    cmds.setAttr(bump + ".bumpDepth", float(material["normalTexture"].get("scale", 1.0)))
                    cmds.connectAttr(texture + ".outAlpha", bump + ".bumpValue")
                    cmds.connectAttr(bump + ".outNormal", shader + ".normalCamera")
            emissive = list(material.get("emissiveFactor") or [0.0, 0.0, 0.0])
            strength = float(((material.get("extensions") or {}).get("KHR_materials_emissive_strength") or {}).get("emissiveStrength", 1.0))
            if (any(emissive) or material.get("emissiveTexture")) and "emission" in attrs:
                cmds.setAttr(f"{shader}.{attrs['emission']}", *emissive, type="double3")
                if material.get("emissiveTexture"):
                    texture = self._texture(material["emissiveTexture"], f"{name}_emissive", landing.SRGB)
                    if texture:
                        cmds.setAttr(texture + ".colorGain", *emissive, type="double3")
                        cmds.connectAttr(texture + ".outColor", f"{shader}.{attrs['emission']}", force=True)
                if kind == "openPBRSurface":
                    cmds.setAttr(shader + ".emissionLuminance", EMISSION_NITS * strength)
                else:
                    cmds.setAttr(shader + ".emission", strength)
            if material.get("occlusionTexture"):
                self.note("ambient occlusion maps are saved, not connected")
            self.shaders.append(shader)
            self.shading_groups.append(group)

    def _opacity(self, shader: str, kind: str, plug: str) -> None:
        if kind == "openPBRSurface":
            cmds.connectAttr(plug, shader + ".geometryOpacity", force=True)
        else:
            for channel in "RGB":
                cmds.connectAttr(plug, f"{shader}.opacity{channel}", force=True)

    # -- hierarchy -------------------------------------------------------------

    def _trs(self, node: dict) -> tuple:
        if "matrix" in node:
            # glTF matrices are column-major with column vectors; read in order they are Maya's row-vector matrix.
            matrix = om.MTransformationMatrix(om.MMatrix([float(value) for value in node["matrix"]]))
            translation = matrix.translation(om.MSpace.kTransform)
            return (translation.x, translation.y, translation.z), matrix.rotation(asQuaternion=True), tuple(matrix.scale(om.MSpace.kTransform))
        rotation = _row_quaternion(node.get("rotation") or (0.0, 0.0, 0.0, 1.0))
        return tuple(node.get("translation") or (0.0, 0.0, 0.0)), rotation, tuple(node.get("scale") or (1.0, 1.0, 1.0))

    def _node(self, index: int, parent: str) -> None:
        node = self.data["nodes"][index]
        name = naming.node_name(node.get("name") or f"node_{index + 1}")
        joint = index in self.joint_nodes
        if index in self.skinned:
            # glTF ignores a skinned mesh node's transform: its vertices follow the joints only.
            path = _long(cmds.createNode("transform", name=name, parent=self.root))
            cmds.setAttr(path + ".inheritsTransform", 0)
        else:
            path = _long(cmds.createNode("joint" if joint else "transform", name=name, parent=parent))
            translation, rotation, scale = self._trs(node)
            cmds.setAttr(path + ".translate", *(value * self.unit for value in translation))
            cmds.setAttr(path + ".scale", *scale)
            if joint:
                self.rest[index] = rotation
                cmds.setAttr(path + ".jointOrient", *_degrees(rotation.asEulerRotation()))
                cmds.setAttr(path + ".segmentScaleCompensate", 0)
            else:
                cmds.setAttr(path + ".rotate", *_degrees(rotation.asEulerRotation()))
        self.nodes[index] = path
        for child in node.get("children") or []:
            self._node(child, path)

    # -- meshes ------------------------------------------------------------------

    def _geometry(self, primitives: list, weld: bool) -> dict:
        unit = self.internal
        welded: dict = {}
        points: list = []
        first: list = []
        counts: list = []
        connects: list = []
        corners: list = []
        ranges: list = []
        uv_u: list = []
        uv_v: list = []
        normals: list = []
        colors: list = []
        has_uv = any("TEXCOORD_0" in primitive["attributes"] for primitive in primitives)
        has_normals = all("NORMAL" in primitive["attributes"] for primitive in primitives)
        has_colors = any("COLOR_0" in primitive["attributes"] for primitive in primitives)
        collapsed = 0
        for primitive in primitives:
            attributes = primitive["attributes"]
            position = self.doc.accessor(attributes["POSITION"])
            values = position.values
            offset = self._offset
            remap = []
            for vertex in range(position.count):
                key = (values[3 * vertex], values[3 * vertex + 1], values[3 * vertex + 2])
                target = welded.get(key) if weld else None
                if target is None:
                    target = len(points)
                    points.append((key[0] * unit, key[1] * unit, key[2] * unit))
                    first.append(offset + vertex)
                    if weld:
                        welded[key] = target
                remap.append(target)
            if has_uv:
                if "TEXCOORD_0" in attributes:
                    uv = self.doc.accessor(attributes["TEXCOORD_0"]).values
                    uv_u.extend(uv[0::2])
                    uv_v.extend(1.0 - value for value in uv[1::2])  # glTF V runs down the image
                else:
                    uv_u.extend([0.0] * position.count)
                    uv_v.extend([0.0] * position.count)
            if has_normals:
                normal = self.doc.accessor(attributes["NORMAL"]).values
                normals.extend(zip(normal[0::3], normal[1::3], normal[2::3], strict=True))
            if has_colors:
                if "COLOR_0" in attributes:
                    color = self.doc.accessor(attributes["COLOR_0"])
                    width = color.components
                    for vertex in range(color.count):
                        row = color.values[vertex * width : (vertex + 1) * width]
                        colors.append((row[0], row[1], row[2], row[3] if width == 4 else 1.0))
                else:
                    colors.extend([(1.0, 1.0, 1.0, 1.0)] * position.count)
            indices = self.doc.accessor(primitive["indices"]).values if "indices" in primitive else range(position.count)
            start = len(counts)
            for corner in range(0, len(indices) - 2, 3):
                a, b, c = indices[corner], indices[corner + 1], indices[corner + 2]
                wa, wb, wc = remap[a], remap[b], remap[c]
                if wa == wb or wb == wc or wa == wc:
                    collapsed += 1
                    continue
                counts.append(3)
                connects.extend((wa, wb, wc))
                corners.extend((offset + a, offset + b, offset + c))
            ranges.append((primitive.get("material"), start, len(counts) - 1))
            self._offset += position.count
        return {
            "points": points,
            "first": first,
            "counts": counts,
            "connects": connects,
            "corners": corners,
            "ranges": ranges,
            "uv": (uv_u, uv_v) if has_uv else None,
            "normals": normals if has_normals else None,
            "colors": colors if has_colors else None,
            "collapsed": collapsed,
        }

    def _create(self, transform: str, primitives: list, weld: bool):
        self._offset = 0
        geometry = self._geometry(primitives, weld)
        if not geometry["counts"]:
            raise ValueError("no triangles")
        fn = om.MFnMesh()
        shape_object = fn.create(om.MFloatPointArray(geometry["points"]), geometry["counts"], geometry["connects"], parent=_depend_node(transform))
        return fn, shape_object, geometry

    def _mesh(self, index: int) -> None:
        node = self.data["nodes"][index]
        mesh = (self.data.get("meshes") or [])[node["mesh"]]
        primitives = [p for p in mesh.get("primitives") or [] if p.get("mode", 4) == 4 and "POSITION" in (p.get("attributes") or {})]
        if len(primitives) < len(mesh.get("primitives") or []):
            self.note("points, lines and strips are not imported")
        if not primitives:
            return
        if any("JOINTS_1" in p["attributes"] for p in primitives):
            self.note("joint influences past the fourth are not imported")
        if any("TEXCOORD_1" in p["attributes"] for p in primitives):
            self.note("a second UV set is not imported")
        transform = self.nodes[index]
        try:
            fn, shape_object, geometry = self._create(transform, primitives, weld=True)
        except (RuntimeError, ValueError):
            # Welding can make a shape Maya refuses (two faces on the same corners); keep the split vertices.
            try:
                fn, shape_object, geometry = self._create(transform, primitives, weld=False)
            except (RuntimeError, ValueError) as error:
                self.note(f"mesh {mesh.get('name') or index} could not be built: {error}")
                return
            self.note("some vertices could not be welded and stay split")
        self.collapsed += geometry["collapsed"]
        faces = [face for face in range(len(geometry["counts"])) for _ in range(3)]
        if geometry["uv"]:
            fn.setUVs(geometry["uv"][0], geometry["uv"][1])
            fn.assignUVs(geometry["counts"], geometry["corners"])
        if geometry["normals"]:
            fn.setFaceVertexNormals(om.MVectorArray([geometry["normals"][corner] for corner in geometry["corners"]]), faces, geometry["connects"])
        shape = om.MFnDagNode(shape_object).fullPathName()
        shape = cmds.rename(shape, _short(transform) + "Shape")
        shape = _long(shape)
        if geometry["colors"]:
            fn.createColorSet("colorSet1")
            fn.setCurrentColorSetName("colorSet1")
            fn.setFaceVertexColors(om.MColorArray([geometry["colors"][corner] for corner in geometry["corners"]]), faces, geometry["connects"])
            if not any(material in self.textured for material, _start, _end in geometry["ranges"]):
                cmds.setAttr(shape + ".displayColors", 1)  # untextured results carry their colours here
        ranges = [(material, start, end) for material, start, end in geometry["ranges"] if end >= start]
        for material, start, end in ranges:
            group = self.shading_groups[material] if material is not None and material < len(self.shading_groups) else "initialShadingGroup"
            members = shape if len(ranges) == 1 else f"{shape}.f[{start}:{end}]"
            cmds.sets(members, edit=True, forceElement=group)
        self.meshes[index] = {"shape": shape, "transform": transform, "primitives": primitives, "first": geometry["first"], "points": geometry["points"]}

    def _per_vertex(self, primitives: list, attribute: str, width: int, fill: float = 0.0) -> list:
        """An attribute concatenated over the primitives, in the order ``first`` indexes."""
        out: list = []
        for primitive in primitives:
            count = self.doc.accessor(primitive["attributes"]["POSITION"]).count
            index = primitive["attributes"].get(attribute)
            if index is None:
                out.extend([fill] * (count * width))
            else:
                out.extend(self.doc.accessor(index).values)
        return out

    def _morphs(self, index: int) -> None:
        mesh_record = self.meshes[index]
        primitives = mesh_record["primitives"]
        targets = max((len(p.get("targets") or []) for p in primitives), default=0)
        if not targets:
            return
        mesh = self.data["meshes"][self.data["nodes"][index]["mesh"]]
        names = (mesh.get("extras") or {}).get("targetNames") or [f"target_{k + 1}" for k in range(targets)]
        transform = mesh_record["transform"]
        duplicates = []
        for k in range(targets):
            deltas: list = []
            for primitive in primitives:
                count = self.doc.accessor(primitive["attributes"]["POSITION"]).count
                own = primitive.get("targets") or []
                target = own[k] if k < len(own) else {}
                if "POSITION" in target:
                    deltas.extend(self.doc.accessor(target["POSITION"]).values)
                else:
                    deltas.extend([0.0] * (count * 3))
            duplicate = cmds.duplicate(transform, name=naming.node_name(names[k] if k < len(names) else f"target_{k + 1}"), returnRootsOnly=True)[0]
            shape = cmds.listRelatives(duplicate, shapes=True, fullPath=True)[0]
            points = om.MPointArray(
                [
                    (x + deltas[3 * o] * self.internal, y + deltas[3 * o + 1] * self.internal, z + deltas[3 * o + 2] * self.internal)
                    for (x, y, z), o in zip(mesh_record["points"], mesh_record["first"], strict=True)
                ]
            )
            om.MFnMesh(_depend_node(shape)).setPoints(points, om.MSpace.kObject)
            duplicates.append(duplicate)
        blend = cmds.blendShape(duplicates + [transform], name=f"{_short(transform)}_blendShape", frontOfChain=True)[0]
        cmds.delete(duplicates)
        weights = self.data["nodes"][index].get("weights") or mesh.get("weights") or []
        for k, weight in enumerate(weights[:targets]):
            cmds.setAttr(f"{blend}.w[{k}]", float(weight))
        self.blend_shapes[index] = blend

    # -- skins ---------------------------------------------------------------------

    def _skin(self, index: int) -> None:
        node = self.data["nodes"][index]
        skin = self.data["skins"][node["skin"]]
        joint_indices = skin.get("joints") or []
        joints = [self.nodes[joint] for joint in joint_indices if joint in self.nodes]
        if len(joints) != len(joint_indices):
            self.note("a skin names joints outside the scene; it was not bound")
            return
        record = self.meshes[index]
        transform = record["transform"]
        cluster = cmds.skinCluster(joints, transform, toSelectedBones=True, maximumInfluences=4, normalizeWeights=1, obeyMaxInfluences=False, name=f"{_short(transform)}_skinCluster")[0]
        fn = oma.MFnSkinCluster(_depend_node(cluster))
        influences = fn.influenceObjects()
        physical = {influences[i].fullPathName(): i for i in range(len(influences))}
        inverse_binds = self.doc.accessor(skin["inverseBindMatrices"]) if "inverseBindMatrices" in skin else None
        to_physical = []
        for k, joint in enumerate(joints):
            path = om.MSelectionList()
            path.add(joint)
            dag = path.getDagPath(0)
            logical = fn.indexForInfluenceObject(dag)
            matrix = list(inverse_binds.row(k)) if inverse_binds else list(om.MMatrix())
            matrix[12] *= self.internal
            matrix[13] *= self.internal
            matrix[14] *= self.internal
            cmds.setAttr(f"{cluster}.bindPreMatrix[{logical}]", matrix, type="matrix")
            to_physical.append(physical[dag.fullPathName()])
        joint_ids = self._per_vertex(record["primitives"], "JOINTS_0", 4)
        weights = self._per_vertex(record["primitives"], "WEIGHTS_0", 4)
        count = len(record["first"])
        width = len(influences)
        flat = [0.0] * (count * width)
        for vertex, original in enumerate(record["first"]):
            for c in range(4):
                weight = weights[4 * original + c]
                if weight > 0.0:
                    flat[vertex * width + to_physical[int(joint_ids[4 * original + c])]] += weight
        shape_path = om.MSelectionList()
        shape_path.add(record["shape"])
        component = om.MFnSingleIndexedComponent()
        vertices = component.create(om.MFn.kMeshVertComponent)
        component.addElements(list(range(count)))
        fn.setWeights(shape_path.getDagPath(0), vertices, om.MIntArray(list(range(width))), om.MDoubleArray(flat), False)
        cmds.setAttr(cluster + ".geomMatrix", list(om.MMatrix()), type="matrix")
        self.skin_clusters.append(cluster)

    # -- animation -------------------------------------------------------------------

    def _animation(self):
        animations = self.data.get("animations") or []
        if not animations:
            return None
        animation = animations[0]
        start = cmds.playbackOptions(query=True, minTime=True)
        end_seconds = 0.0
        for channel in animation.get("channels") or []:
            target = channel.get("target") or {}
            index = target.get("node")
            if index not in self.nodes:
                continue
            sampler = (animation.get("samplers") or [])[channel["sampler"]]
            times = list(self.doc.accessor(sampler["input"]).values)
            if not times:
                continue
            end_seconds = max(end_seconds, times[-1])
            output = self.doc.accessor(sampler["output"])
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation == "CUBICSPLINE":
                self.note("cubic spline curves are keyed as linear")
            tangent = oma.MFnAnimCurve.kTangentStep if interpolation == "STEP" else oma.MFnAnimCurve.kTangentLinear
            frames = om.MTimeArray([om.MTime(start + seconds * self.fps, om.MTime.uiUnit()) for seconds in times])
            path = target.get("path")
            if path == "weights":
                self._weight_keys(index, output, len(times), interpolation, frames, tangent)
                continue
            rows = [output.row(3 * i + 1) if interpolation == "CUBICSPLINE" else output.row(i) for i in range(len(times))]
            node = self.nodes[index]
            if path == "translation":
                series = [("translate" + axis, oma.MFnAnimCurve.kAnimCurveTL, [row[k] * self.internal for row in rows]) for k, axis in enumerate("XYZ")]
            elif path == "scale":
                series = [("scale" + axis, oma.MFnAnimCurve.kAnimCurveTU, [row[k] for row in rows]) for k, axis in enumerate("XYZ")]
            elif path == "rotation":
                rest = self.rest.get(index)
                eulers = []
                previous = None
                for row in rows:
                    quaternion = _row_quaternion(row)
                    if rest is not None:
                        quaternion = quaternion * rest.inverse()  # joint matrix = rotate x jointOrient
                    euler = quaternion.asEulerRotation()
                    if previous is not None:
                        euler.setToClosestSolution(previous)
                    previous = euler
                    eulers.append(euler)
                series = [("rotate" + axis, oma.MFnAnimCurve.kAnimCurveTA, [getattr(e, axis.lower()) for e in eulers]) for axis in "XYZ"]
            else:
                continue
            for attribute, curve_type, values in series:
                selection = om.MSelectionList()
                selection.add(f"{node}.{attribute}")
                curve = oma.MFnAnimCurve()
                curve.create(selection.getPlug(0), curve_type)
                curve.addKeys(frames, om.MDoubleArray(values), tangent, tangent)
        frames_long = round(end_seconds * self.fps)
        return {"name": animation.get("name") or "clip_1", "start": start, "end": start + frames_long, "seconds": end_seconds}

    def _weight_keys(self, index: int, output, keys: int, interpolation: str, frames, tangent) -> None:
        blend = self.blend_shapes.get(index)
        if not blend:
            return
        per_key = len(output.values) // keys
        targets = per_key // 3 if interpolation == "CUBICSPLINE" else per_key
        for k in range(targets):
            values = []
            for i in range(keys):
                base = i * per_key + (targets if interpolation == "CUBICSPLINE" else 0)
                values.append(output.values[base + k])
            selection = om.MSelectionList()
            selection.add(f"{blend}.w[{k}]")
            curve = oma.MFnAnimCurve()
            curve.create(selection.getPlug(0), oma.MFnAnimCurve.kAnimCurveTU)
            curve.addKeys(frames, om.MDoubleArray(values), tangent, tangent)


def inspect(made: dict, unit: float | None = None) -> dict:
    """The import checks shown on the result card and returned to agents (spec 6.7)."""
    unit = unit or om.MDistance(1.0, om.MDistance.kMeters).asUnits(om.MDistance.uiUnit())
    faces = vertices = non_manifold = 0
    uv_sets: dict = {}
    for shape in made.get("meshes") or []:
        faces += cmds.polyEvaluate(shape, face=True)
        vertices += cmds.polyEvaluate(shape, vertex=True)
        non_manifold += len(cmds.polyInfo(shape, nonManifoldEdges=True) or [])
        uv_sets[_short(shape)] = cmds.polyUVSet(shape, query=True, allUVSets=True) or []
    # The visible meshes only: a skinned mesh's hidden bind-pose shape sits in the file's raw space.
    box = cmds.exactWorldBoundingBox(made["meshes"]) if made.get("meshes") else [0.0] * 6
    size = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
    textures = [node for node in cmds.listHistory(made.get("shading_groups") or [], pruneDagObjects=True) or [] if cmds.nodeType(node) == "file"] if made.get("shading_groups") else []
    missing = [node for node in textures if not cmds.file(cmds.getAttr(node + ".fileTextureName"), query=True, exists=True)]
    influences = 0
    for cluster in made.get("skin_clusters") or []:
        influences = max(influences, len(cmds.skinCluster(cluster, query=True, influence=True) or []))
    targets = sum(cmds.blendShape(blend, query=True, weightCount=True) or 0 for blend in made.get("blend_shapes") or [])
    return {
        "faces": faces,
        "vertices": vertices,
        "size_scene_units": [round(value, 4) for value in size],
        "size_metres": [round(value / unit, 4) for value in size],
        "uv_sets": uv_sets,
        "non_manifold_edges": non_manifold,
        "collapsed_triangles": made.get("collapsed_triangles", 0),
        "materials": len(made.get("shaders") or []),
        "textures": len(textures),
        "missing_textures": missing,
        "joints": len(made.get("joints") or []),
        "influences": influences,
        "blend_shape_targets": targets,
        "clip": made.get("clip"),
        "other_clips": made.get("other_clips") or [],
        "notes": made.get("notes") or [],
    }
