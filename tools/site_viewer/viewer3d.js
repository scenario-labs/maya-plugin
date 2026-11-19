// The 3D viewer of the maya.scenario.com page (site/index.html).
//
// Bundled with three.js into site/assets/vendor/viewer3d.min.js by `npm run build`
// in this folder (README in AGENTS.md, Commands). The page loads the bundle when a
// viewer comes near the view, then calls ScenarioViewer3D.mount(box) for each
// <div class="v3d" data-src="model.glb"> as it comes near.
//
// A viewer: the model turning with OrbitControls (drag, wheel or pinch; on touch
// screens a vertical swipe still scrolls the page), its first clip playing (or
// waiting for Play under reduced motion), one button per clip when the file has
// several, and five views that all follow the skinned, animated meshes:
// Textured, Solid (one clay material), Wireframe (edges over the clay),
// Normals and Rig (the joints through a dimmed mesh).
//
// Box attributes:
//   data-src     the GLB, required
//   data-orbit   "azimuth polar distance": degrees from the front, degrees from
//                the top, and a factor of the distance that fits the model
//                (default "30 75 1")
//   data-clip    the clip to start with (default: the file's first)
//   aria-label   what the model is, for screen readers

import {
  AnimationMixer,
  Box3,
  BufferGeometry,
  Color,
  DirectionalLight,
  Float32BufferAttribute,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshNormalMaterial,
  MeshStandardMaterial,
  NeutralToneMapping,
  PCFShadowMap,
  Group,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  Scene,
  ShadowMaterial,
  SkinnedMesh,
  SphereGeometry,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

const VIEWS = [
  ["textured", "Textured"],
  ["solid", "Solid"],
  ["wire", "Wireframe"],
  ["normals", "Normals"],
  ["rig", "Rig"],
];
const CLAY = 0xb8b0a8;
const BONE = 0xf0a07f; // the page's terracotta, lightened to read on the dark ground
const calm = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

function button(label, pressed) {
  const b = el("button", null, label);
  b.type = "button";
  if (pressed !== undefined) b.setAttribute("aria-pressed", pressed ? "true" : "false");
  return b;
}

// One copy of a mesh that shares its geometry and, for a skinned mesh, its
// skeleton, so it follows every key of the clip.
function twin(mesh, material) {
  let t;
  if (mesh.isSkinnedMesh) {
    t = new SkinnedMesh(mesh.geometry, material);
    t.bindMode = mesh.bindMode;
    t.bind(mesh.skeleton, mesh.bindMatrix);
  } else {
    t = new Mesh(mesh.geometry, material);
  }
  if (mesh.morphTargetInfluences) {
    t.morphTargetInfluences = mesh.morphTargetInfluences;
    t.morphTargetDictionary = mesh.morphTargetDictionary;
  }
  t.position.copy(mesh.position);
  t.quaternion.copy(mesh.quaternion);
  t.scale.copy(mesh.scale);
  t.frustumCulled = false;
  t.visible = false;
  return t;
}

export function mount(box) {
  if (box._v3d) return box._v3d;
  const state = { box };
  box._v3d = state;
  const wait = box.querySelector(".v3d-wait") || box.appendChild(el("span", "v3d-wait", "Loading the 3D view"));
  wait.setAttribute("role", "status");
  const fail = (why) => {
    box.setAttribute("data-state", "failed");
    wait.textContent = why || "The 3D view could not load.";
  };

  let renderer;
  try {
    renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch (e) {
    fail("This browser cannot show 3D here.");
    return state;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NeutralToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFShadowMap;
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = "v3d-canvas";
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", (box.getAttribute("aria-label") || "A 3D model") + ". Drag to turn, scroll or pinch to zoom.");
  box.insertBefore(canvas, box.firstChild);

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.9;
  pmrem.dispose();
  const sun = new DirectionalLight(0xffffff, 1.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.02;
  sun.shadow.radius = 6;
  scene.add(sun, sun.target);

  const camera = new PerspectiveCamera(30, 1, 0.01, 1000);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.enablePan = false;
  canvas.style.touchAction = "pan-y"; // a vertical swipe scrolls the page; a sideways drag turns
  let interacting = false;
  controls.addEventListener("start", () => { interacting = true; wake(); });
  controls.addEventListener("end", () => { interacting = false; });
  controls.addEventListener("change", () => wake());

  // The bar: Play and the clips at the bottom, the views at the top.
  const views = el("div", "v3d-views");
  views.setAttribute("role", "group");
  views.setAttribute("aria-label", "View");
  const bar = el("div", "v3d-bar");
  const play = button("Pause", false);
  play.setAttribute("data-3d-play", "");
  const viewButtons = VIEWS.map(([key, label]) => {
    const b = button(label, key === "textured");
    b.setAttribute("data-3d-view", key);
    views.appendChild(b);
    return b;
  });

  const mixer = { m: null, actions: [], current: null, paused: false };
  const parts = []; // { mesh, original, solid, wire }
  let rig = null, joints = null, jointList = [];
  let view = "textured";
  let visible = false, running = false, last = 0;

  function frame(now) {
    running = false;
    if (!state.ready) return;
    const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
    last = now;
    const animating = mixer.m && !mixer.paused && mixer.current;
    if (animating) mixer.m.update(dt);
    controls.update();
    if (view === "rig") placeJoints();
    renderer.render(scene, camera);
    if (visible && (animating || interacting || controls._needsMore)) schedule();
    else last = 0;
  }
  function schedule() {
    if (!running) { running = true; requestAnimationFrame(frame); }
  }
  function wake() { if (visible) schedule(); }
  // Damping keeps turning a little after the drag: render those frames too.
  controls.addEventListener("change", () => { controls._needsMore = true; clearTimeout(controls._t); controls._t = setTimeout(() => { controls._needsMore = false; }, 400); });

  function resize() {
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (state.ready && state.refit) state.refit();
    wake();
  }
  if (window.ResizeObserver) new ResizeObserver(resize).observe(box);
  else window.addEventListener("resize", resize);
  resize();

  if (window.IntersectionObserver) {
    new IntersectionObserver((es) => {
      visible = es.some((e) => e.isIntersecting);
      if (visible) { last = 0; schedule(); }
    }).observe(box);
  } else visible = true;

  function setPlayLabel() {
    const on = mixer.current && !mixer.paused;
    play.textContent = on ? "Pause" : "Play";
    play.setAttribute("aria-pressed", on ? "true" : "false");
  }
  function startClip(i, fromStart) {
    if (!mixer.m || !mixer.actions[i]) return;
    mixer.actions.forEach((a, j) => { if (j !== i) a.stop(); });
    const a = mixer.actions[i];
    if (fromStart || mixer.current !== a) { a.reset(); a.play(); }
    mixer.current = a;
    clipButtons.forEach((b, j) => b.setAttribute("aria-pressed", j === i ? "true" : "false"));
  }
  const clipButtons = [];
  play.addEventListener("click", () => {
    if (!mixer.current) return;
    mixer.paused = !mixer.paused;
    setPlayLabel();
    wake();
  });

  function setView(key) {
    view = key;
    viewButtons.forEach((b) => b.setAttribute("aria-pressed", b.getAttribute("data-3d-view") === key ? "true" : "false"));
    box.setAttribute("data-view", key);
    for (const p of parts) {
      p.wire.visible = key === "wire";
      if (key === "textured") p.mesh.material = p.original;
      else if (key === "normals") p.mesh.material = p.normals;
      else if (key === "rig") p.mesh.material = p.ghost;
      else p.mesh.material = p.solid;
      p.mesh.castShadow = key !== "rig";
    }
    if (rig) rig.visible = joints.visible = key === "rig";
    if (key === "rig") placeJoints();
    wake();
  }
  viewButtons.forEach((b) => b.addEventListener("click", () => setView(b.getAttribute("data-3d-view"))));

  // The joints as dots, drawn over the mesh, with lines to their parents.
  const _p = new Vector3();
  function placeJoints() {
    if (!joints) return;
    const pos = rig.geometry.getAttribute("position");
    let k = 0;
    jointList.forEach((j, i) => {
      j.bone.getWorldPosition(_p);
      j.dot.position.copy(_p);
      if (j.parent) {
        pos.setXYZ(k++, _p.x, _p.y, _p.z);
        j.parent.getWorldPosition(_p);
        pos.setXYZ(k++, _p.x, _p.y, _p.z);
      }
    });
    pos.needsUpdate = true;
    rig.geometry.computeBoundingSphere();
  }

  const src = box.getAttribute("data-src");
  new GLTFLoader().load(
    src,
    (gltf) => {
      try { build(gltf); } catch (e) { fail(); if (window.console) console.error(e); }
    },
    (ev) => {
      if (ev.total) wait.textContent = "Loading the 3D view, " + Math.round((100 * ev.loaded) / ev.total) + " %";
    },
    () => fail()
  );

  function build(gltf) {
    const root = gltf.scene;
    scene.add(root);
    const solid = new MeshStandardMaterial({ color: CLAY, roughness: 0.62, metalness: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    const wireMat = new MeshBasicMaterial({ color: 0x23252a, wireframe: true, transparent: true, opacity: 0.32 });
    const normals = new MeshNormalMaterial();
    const ghost = new MeshStandardMaterial({ color: CLAY, roughness: 0.7, metalness: 0, transparent: true, opacity: 0.38, depthWrite: false });
    const meshes = [];
    root.traverse((o) => { if (o.isMesh) meshes.push(o); });
    for (const mesh of meshes) {
      mesh.castShadow = true;
      mesh.frustumCulled = false; // skinned meshes move out of their rest bounds
      const side = Array.isArray(mesh.material) ? mesh.material[0].side : mesh.material.side;
      const s = side === solid.side ? solid : Object.assign(solid.clone(), { side });
      const wire = twin(mesh, wireMat);
      mesh.parent.add(wire);
      parts.push({ mesh, original: mesh.material, solid: s, wire, normals, ghost });
    }

    // Clips.
    if (gltf.animations.length) {
      mixer.m = new AnimationMixer(root);
      mixer.actions = gltf.animations.map((c) => mixer.m.clipAction(c));
    }

    // Frame each clip as a whole: its bounds, sampled, so a raised arm stays in the box.
    // A clip that walks away (the nutcracker's March) gets its own, wider framing.
    const rest = new Box3();
    const sample = new Box3();
    root.updateMatrixWorld(true);
    rest.setFromObject(root, true);
    const clipBounds = gltf.animations.map((clip, i) => {
      const u = rest.clone();
      const a = mixer.actions[i];
      a.reset().play();
      const steps = 16;
      for (let s = 0; s <= steps; s++) {
        mixer.m.setTime((clip.duration * s) / steps);
        root.updateMatrixWorld(true);
        u.union(sample.setFromObject(root, true));
      }
      a.stop();
      return u;
    });
    if (mixer.m) mixer.m.setTime(0);
    const bounds = rest.clone();
    clipBounds.forEach((u) => bounds.union(u));
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    const r = Math.max(size.length() / 2, 1e-3);

    // Ground: a shadow catcher under the lowest point of the clip.
    const ground = new Mesh(new PlaneGeometry(r * 8, r * 8), new ShadowMaterial({ opacity: 0.32 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(center.x, bounds.min.y, center.z);
    ground.receiveShadow = true;
    scene.add(ground);
    sun.position.set(center.x + r * 0.6, bounds.max.y + r * 3, center.z + r * 1.2);
    sun.target.position.copy(center);
    const sc = sun.shadow.camera;
    sc.left = sc.bottom = -r * 1.6;
    sc.right = sc.top = r * 1.6;
    sc.near = 0.01;
    sc.far = r * 10;
    sc.updateProjectionMatrix();

    // Rig view: dots on the joints and lines to their parents.
    const bones = [];
    root.traverse((o) => { if (o.isBone) bones.push(o); });
    if (bones.length) {
      const dotGeo = new SphereGeometry(r * 0.024, 12, 8);
      const dotMat = new MeshBasicMaterial({ color: BONE, depthTest: false, transparent: true });
      joints = new Group(); // the dots live in world space
      joints.visible = false;
      scene.add(joints);
      jointList = bones.map((bone) => {
        const dot = new Mesh(dotGeo, dotMat);
        dot.renderOrder = 11;
        joints.add(dot);
        return { bone, dot, parent: bone.parent && bone.parent.isBone ? bone.parent : null };
      });
      const n = jointList.filter((j) => j.parent).length;
      const g = new BufferGeometry();
      g.setAttribute("position", new Float32BufferAttribute(new Float32Array(n * 6), 3));
      rig = new LineSegments(g, new LineBasicMaterial({ color: BONE, depthTest: false, transparent: true, opacity: 0.9 }));
      rig.renderOrder = 10;
      rig.frustumCulled = false;
      rig.visible = false;
      scene.add(rig);
    } else {
      viewButtons[4].remove();
    }

    // Camera: the box of the clip in view, from the angles of data-orbit.
    const o = (box.getAttribute("data-orbit") || "30 75 1").trim().split(/\s+/).map(Number);
    const az = ((o[0] || 0) * Math.PI) / 180, pol = ((isNaN(o[1]) ? 75 : o[1]) * Math.PI) / 180, k = o[2] || 1;
    function frameTo(u, keepAngles) {
      const sz = u.getSize(new Vector3()), c = u.getCenter(new Vector3());
      const t = Math.tan(((camera.fov / 2) * Math.PI) / 180);
      const across = Math.max(sz.x, sz.z, 0.8 * Math.hypot(sz.x, sz.z)); // about the widest it gets as it turns
      const aspect = camera.aspect || 1.6;
      const d = Math.max(sz.y / 2 / t, across / 2 / (t * aspect)) * 1.06 * k + across / 3;
      let dir;
      if (keepAngles) dir = camera.position.clone().sub(controls.target).normalize();
      else dir = new Vector3(Math.sin(pol) * Math.sin(az), Math.cos(pol), Math.sin(pol) * Math.cos(az));
      controls.target.copy(c);
      camera.position.copy(c).addScaledVector(dir, d);
      camera.near = d / 100;
      camera.far = d * 20;
      camera.updateProjectionMatrix();
      controls.minDistance = d * 0.35;
      controls.maxDistance = d * 2.2;
      controls.update();
    }
    controls.maxPolarAngle = Math.PI * 0.53; // not under the floor
    let framed = rest;
    state.frameClip = (i, keep) => { framed = clipBounds[i] || rest; frameTo(framed, keep); };
    state.refit = () => frameTo(framed, true);

    // The bar.
    if (mixer.m) {
      bar.appendChild(play);
      if (gltf.animations.length > 1) {
        gltf.animations.forEach((c, i) => {
          const b = button(c.name || "Clip " + (i + 1), false);
          b.setAttribute("data-3d-clip", c.name || "");
          b.addEventListener("click", () => {
            startClip(i, true);
            state.frameClip(i, true);
            mixer.paused = false;
            setPlayLabel();
            wake();
          });
          clipButtons.push(b);
          bar.appendChild(b);
        });
      }
      const want = box.getAttribute("data-clip");
      let first = want ? gltf.animations.findIndex((c) => c.name === want) : 0;
      if (first < 0) first = 0;
      startClip(first, true);
      state.frameClip(first, false);
      mixer.paused = calm();
      setPlayLabel();
    }
    if (!mixer.m) state.frameClip(-1, false);
    box.appendChild(views);
    box.appendChild(bar);
    state.ready = true;
    box.setAttribute("data-state", "ready");
    box.setAttribute("data-view", "textured");
    last = 0;
    renderer.render(scene, camera);
    wake();
  }

  state.setView = (k) => setView(k);
  return state;
}

window.ScenarioViewer3D = { mount };
