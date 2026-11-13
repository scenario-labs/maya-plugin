# Changelog

## 1.0.0 (2026-11-13)


### Features

* **3d:** 3D lane, text to 3D; GLB-only download; import on the ground ([16ec376](https://github.com/scenario-labs/maya-plugin/commit/16ec376965d8e154f6d05821c49806fcada96f84))
* **3d:** Apply UV unwrap and Retexture results onto the mesh itself ([4386ee7](https://github.com/scenario-labs/maya-plugin/commit/4386ee7f9a11cb761eb72217c754167d1721e61f))
* **3d:** check an imported edit result against the mesh by surface distance ([1746ebb](https://github.com/scenario-labs/maya-plugin/commit/1746ebbfb6ba13649a645d2dec6e0b84fe53a8a5))
* **3d:** Edit selection, remesh, UV unwrap or retexture a mesh of the scene ([5859a72](https://github.com/scenario-labs/maya-plugin/commit/5859a722152c3a162b2c35d749785dfd41588f24))
* **3d:** image to 3D, the 3D tab's Image mode ([4952aee](https://github.com/scenario-labs/maya-plugin/commit/4952aee0895a3cc2b32b8ac82d100326b00f0665))
* **3d:** import FBX results, so quad meshes land in the scene ([ee2dabf](https://github.com/scenario-labs/maya-plugin/commit/ee2dabf21cddfd68e1da2189364c6c3dd1268aba))
* **3d:** Motion mode, a prompt to a character that moves ([eaf2923](https://github.com/scenario-labs/maya-plugin/commit/eaf29238900dcf1cfaecea57302cc8d9e958add3))
* **3d:** Multi-view mode, views captured around an object into a 3D model ([577ae27](https://github.com/scenario-labs/maya-plugin/commit/577ae273a30883b755c8a9a4a70cd43d68ba8f15))
* **3d:** Replace geometry, apply a remesh result onto the mesh itself ([a69e8fc](https://github.com/scenario-labs/maya-plugin/commit/a69e8fc2b5a491ea427304c40c715a5c29dc5d97))
* **core:** call Scenario's REST API through its Python SDK ([#16](https://github.com/scenario-labs/maya-plugin/issues/16)) ([1da19cb](https://github.com/scenario-labs/maya-plugin/commit/1da19cb03b3f33daf500129f17e60ec0f4ba9914))
* **core:** GLB reader and format sniffing for 3D results ([931045b](https://github.com/scenario-labs/maya-plugin/commit/931045bd37f8359110754e46c15d5645f4c19173))
* **core:** result delivery, downloads with receipts, catalog cache, lanes, provenance ([503397c](https://github.com/scenario-labs/maya-plugin/commit/503397c3110416ac8e47abbab56d8f795ab6f84d))
* **core:** Scenario MCP client, sign-in, credential stores, quotes and job ledger ([8fdf7d5](https://github.com/scenario-labs/maya-plugin/commit/8fdf7d5ac97f82fbc0a900dae963adac1813c6eb))
* **core:** sign in as Maya's registered OAuth application ([#7](https://github.com/scenario-labs/maya-plugin/issues/7)) ([9b8ab16](https://github.com/scenario-labs/maya-plugin/commit/9b8ab16a44cfec8fb97b1eff0332411c5f449730))
* **maya:** GLB import as one undo step; Scenario &gt; Import GLB... ([2f3b727](https://github.com/scenario-labs/maya-plugin/commit/2f3b7276e64dd89f372e2696e6fc3debc95375a3))
* **maya:** job runner from quote to landed result, with restart recovery ([6521b2d](https://github.com/scenario-labs/maya-plugin/commit/6521b2dc314836007649258487c92af5e50b9b73))
* **maya:** land images as a card, a material on the selection or an image plane ([92bbf4f](https://github.com/scenario-labs/maya-plugin/commit/92bbf4f845f65c35683e1d76bfb17a81d405b293))
* **maya:** plug-in entry, runtime, main-thread dispatcher, panel, menu and installer ([6569c7f](https://github.com/scenario-labs/maya-plugin/commit/6569c7fcf191d4aa09ee4e91bb7ce68e63cd1af8))
* **ui:** Image lane in the panel: model picker, settings, priced Generate, result cards ([22937ac](https://github.com/scenario-labs/maya-plugin/commit/22937acb439dfe5c277d26f4ca413f3a27684876))


### Bug Fixes

* **3d:** land GLB results at the right size in metre and millimetre scenes ([b120574](https://github.com/scenario-labs/maya-plugin/commit/b120574a972d183e3c985c7e1b3c9d0560b83307))
* **core:** a paid call refused with 429 is reported as not sent ([fd697d9](https://github.com/scenario-labs/maya-plugin/commit/fd697d95be83538c4eea58b24d37af96ddab51fe))
* **core:** count a job's add-on charges in what it cost ([1da19cb](https://github.com/scenario-labs/maya-plugin/commit/1da19cb03b3f33daf500129f17e60ec0f4ba9914))
* **core:** forget the session on sign-out even when offline ([9b8ab16](https://github.com/scenario-labs/maya-plugin/commit/9b8ab16a44cfec8fb97b1eff0332411c5f449730))
* **lanes:** fetch a 3D result's preview after the download; card placeholder ([4ecc332](https://github.com/scenario-labs/maya-plugin/commit/4ecc332413b1e980134e3fb734eb29e4cdaf00de))
* **lint:** scan new files too; drop an em dash from a recorded schema ([b6fe46f](https://github.com/scenario-labs/maya-plugin/commit/b6fe46fb82e0869891ace84d9d7c1adc03819196))
* **maya:** show textures after landing; stack example prompts ([3094d76](https://github.com/scenario-labs/maya-plugin/commit/3094d76b78ae05e36a953c95edfb04e42d78dfe0))
* **ui:** bring the panel tab to the front, keep the sign-in links whole, scale pixel fonts ([3e7a174](https://github.com/scenario-labs/maya-plugin/commit/3e7a17467d622a83781b15ebd523c0b268bd5656))
* **ui:** each lane starts with its own example prompt until used ([e8974fc](https://github.com/scenario-labs/maya-plugin/commit/e8974fc58219ea4f3401f1b88a1249ff8d221a01))
* **ui:** grow the sign-in dialogs when their text wraps ([#10](https://github.com/scenario-labs/maya-plugin/issues/10)) ([c95bf12](https://github.com/scenario-labs/maya-plugin/commit/c95bf1276b3c958823af8de11efda2e084bb10ac))
* **ui:** open one project picker at a time ([#12](https://github.com/scenario-labs/maya-plugin/issues/12)) ([676068c](https://github.com/scenario-labs/maya-plugin/commit/676068c898296d8f8a8681bcefa1d082caf9028c))
* **ui:** workspace question opens without a nested event loop ([539ab44](https://github.com/scenario-labs/maya-plugin/commit/539ab441bde15df18ed19b27aaeebc1655ba598f))


### Documentation

* **3d:** edit results sent off-centre, Meshy UV Unwrap in place ([61255b8](https://github.com/scenario-labs/maya-plugin/commit/61255b8fe58688dc00fe167c89c1ede623d3b0c7))
* README with pictures, recordings and diagrams from a real Maya session ([5e4efc2](https://github.com/scenario-labs/maya-plugin/commit/5e4efc26bef82fc1788316389fc75d5160bf044a))
* spec v1 draft and privacy page draft ([0c7c0ff](https://github.com/scenario-labs/maya-plugin/commit/0c7c0ff8b942200493987e84b1a3c0f23afe1eb8))
* **spec:** record decisions of 2026-10-19 ([fa10cb6](https://github.com/scenario-labs/maya-plugin/commit/fa10cb6263b9cb6da291c8c017a78e9544994f87))


### Miscellaneous Chores

* **deps:** Bump the python group with 2 updates ([#14](https://github.com/scenario-labs/maya-plugin/issues/14)) ([bfdedaf](https://github.com/scenario-labs/maya-plugin/commit/bfdedaf30cd549031b05fac4922274f4ea57fca9))
* **repo:** align with the shared open source practices ([#6](https://github.com/scenario-labs/maya-plugin/issues/6)) ([f83f60b](https://github.com/scenario-labs/maya-plugin/commit/f83f60b4521eb1813b8a6af16804d6aaa1b61ce8))
* **repo:** policies, templates, CI, lint, free contract check and GUI test driver ([bacc4be](https://github.com/scenario-labs/maya-plugin/commit/bacc4be9785331e54d8ba858c03b93d32aaa24b3))
* ruff lint and format settings, formatting pass ([cd5d5b5](https://github.com/scenario-labs/maya-plugin/commit/cd5d5b52ff16346fbc14e7c6f717e410665aabc0))


### Continuous Integration

* **ci:** publish maya.scenario.com behind a Vercel proxy ([#18](https://github.com/scenario-labs/maya-plugin/issues/18)) ([e7a804e](https://github.com/scenario-labs/maya-plugin/commit/e7a804e6ed0c934a584011d793c3f473d5b33835))
* **deps:** Bump astral-sh/setup-uv from 10.3.0 to 10.3.2 in the actions group ([#8](https://github.com/scenario-labs/maya-plugin/issues/8)) ([8208ba5](https://github.com/scenario-labs/maya-plugin/commit/8208ba5bdfbf495bb13a8719a0f68398e5d876cc))
* **deps:** Bump the actions group with 5 updates ([#15](https://github.com/scenario-labs/maya-plugin/issues/15)) ([c3ce0a3](https://github.com/scenario-labs/maya-plugin/commit/c3ce0a37096dcea269770da4435db37b0eacfab7))
* **release:** release the plug-in as a checked ZIP with release-please ([#17](https://github.com/scenario-labs/maya-plugin/issues/17)) ([53bdda4](https://github.com/scenario-labs/maya-plugin/commit/53bdda40e654cff615518a493a72bd767e259d36))


### Tests

* **core:** compare texture file names with os.path.basename so the test passes on Windows ([45ba9b3](https://github.com/scenario-labs/maya-plugin/commit/45ba9b3284fa067ba24de59571cbd0832fd95a61))
* **gui:** live generate stage; docs for the Image lane ([f43ff24](https://github.com/scenario-labs/maya-plugin/commit/f43ff24b838f2b9a56184fdfc27fc2eb651cc0d6))
* **tools:** GUI stages check that Maya quits by itself; name the slowest main-thread call ([291b3bc](https://github.com/scenario-labs/maya-plugin/commit/291b3bc0a3fbd3602c93cd8c29dbdd20b08a5ba7))

## Changelog

## Hand-written history

Written before release automation. From the first release on, release-please writes each entry above this one from the pull request titles.

### Features

- Sign in to Scenario with the browser (OAuth with PKCE), a code on another device, or an API key; secrets kept in the system keychain.
- Scenario panel docked beside the Channel Box, restored with the workspace; team and project picker; job list.
- Durable job ledger shared by every Maya session of the user, with recovery after a crash: a request cut off while being sent shows as Not confirmed and blocks an identical request until checked.
- Drag-and-drop installer with upgrade and uninstall; module file for studio deployment.
- Image lane: choose a model (search, team models, legacy), write a prompt, adjust the model's settings, see the exact price on Generate before sending. Results download into the project's `sourceimages/scenario` folder with a checksum and a `scenario.json` record, and land as a textured card facing the camera, a material on the selected meshes or faces, or an image plane, each removed by one Ctrl+Z.
- Results that finish while Maya is closed are offered for download when the panel opens; interrupted downloads resume where they stopped.
- Every landed node carries its Scenario provenance (asset, job, model, prompt, price) as plain attributes, so scenes open without the plug-in.
- 3D results land through the plug-in's own GLB builder as one undo step: welded meshes with UVs and normals, PBR materials with textures written to the project, joints with rest orientation in `jointOrient`, skins, blend shapes and the first animation clip; import checks report faces, size, UV sets, non-manifold edges, missing textures, joints, clips and targets.
- Scenario > Import GLB... brings any local GLB into the scene the same way, without signing in.
- Updating the plug-in while a Scenario import sits in the undo history finishes after a Maya restart instead of failing.
- 3D lane: text to 3D with Meshy 7.1 (preset to a 30,000-face game mesh), Meshy T2.5 Smart Topology, Tripo P2 or Rodin Gen-2.5. Only the GLB of each result is downloaded (chosen by the asset's format, not its position), with its preview picture for the card; Import places the model on the ground below the camera's centre of interest and reports the import checks.
- The model catalog is cached per kind of model, so refreshing the 3D list keeps the image list.
- A 3D result whose preview Scenario renders after the download gets it a few seconds later; until then its card shows "3D" instead of an empty square.
- Import checks read "1 material, 3 textures" instead of "1 material(s), 3 texture(s)".
- 3D tab, Image mode: turn one image, or up to four views of an object, into a textured model with Meshy 7.1 Image to 3D (preset to a 30,000-face game mesh), Tripo P2, Rodin Gen-2.5, Tripo 3.1 or Hunyuan 3D Pro 3.1. Add the image from a file, a capture of the viewport (grid and selection highlight hidden, no undo step) or a result of the Image tab, which is used as it is without a new upload. Files are sent to Scenario when you add them, once per session and project.
- Image tab results have "Make a 3D model from this image" in their menu.
- The 3D tab has a Text and an Image mode, sharing one results list; it reopens on the mode used last. Re-run fills the right mode, images included.
- The prompt box follows the model: hidden when the model takes no prompt, marked optional when it only guides the texture.
- A form that misses its image says "Add an image".
- `tools/render_glb.py` renders a GLB in Viewport 2.0 without a window, through the plug-in's importer: stills or a turntable GIF for documentation.
- 3D tab, Edit selection mode: remesh, UV unwrap or retexture a mesh of the scene (Tripo Retopology v3, Meshy Remesh, Tripo Smart UV, Hunyuan UV Unwrapping, Meshy UV Unwrap, Meshy 7 Retexture, Tripo 3.0 Texturing). Use selection writes the selected mesh as a GLB (object space, metres, neutral names, its UVs and base colour textures), checks it against the model's limits (format, triangle cap) before anything is sent, and sends it once per unchanged mesh. Each task remembers its own model; Retexture asks for a prompt. One mesh at a time in this version.
- Import of an edit result places it over the mesh it came from, as a new group, fitted with one uniform scale and an offset (most edit models return the mesh resized and centred), even when the mesh moved after it was sent. The mesh itself is not changed. The fit is checked by surface distance both ways; a result that is not the same shape still lands, and the import message says so.
- Apply... on UV unwrap and Retexture results writes them onto the mesh itself after a review (what changes, what is kept, what needs a tick): Replace UVs fills the current UV set and keeps the old one as `<set>_scnPrev`; Replace textures assigns a new material built from the result's maps. The result is first proven to be the same surface as the mesh (vertices, faces, winding, one UV per face corner). One Ctrl+Z undoes the whole apply; deformed, referenced and locked meshes are refused in this version.
- `tools/render_glb.py --checker N` shows the UV layout with a checker instead of the materials.
- Apply... on Remesh results replaces the mesh's geometry after a review: the result's mesh becomes the shape under your transform, with your shape's name and outgoing connections; it gets the result's material when the result has textures, otherwise keeps yours. The old shape stays, hidden, as `<shape>_scnPrev` with its history. The result must be the same shape by the surface-distance check; instanced meshes are refused in this version. One Ctrl+Z undoes it.
- `tools/render_glb.py --wire` draws every edge, to show a topology.
- FBX results import through Maya's own FBX importer as one Ctrl+Z, so a Tripo result with the quad setting (delivered as FBX only) can be imported. The scene's unit, up axis, playback range and frame rate are kept; textures go under `sourceimages`; escaped names (`FBXASC045`) are cleaned; the importer's materials stay, with data textures Raw and normal maps read as normals. The 3D tab downloads the GLB when a job returns one, else the FBX. `tools/render_glb.py` renders FBX files too.
- 3D tab, Multi-view mode: views of one object from the front, left, back and right (and top, bottom and 45 degree views where the model takes them) into a textured model, with Tripo P2 Multi View, Tripo 3.1 Multi View or Hunyuan 3D 3.1 Pro Multiview. **Capture views** renders the selection from each side the model takes with temporary orthographic cameras, at one scale, clipped to the selection's box so neighbours stay out; nothing stays in the scene or the undo queue. Each view can also take a file or an Image result. Tripo P2 Multi View is the default (a clean mesh of a few thousand faces); Tripo 3.1 Multi View is the low-cost choice; Hunyuan starts at its lightest mesh (40,000 faces). Import places a result made from captured views over the object they show, at its size and facing the same way.

- 3D tab, Motion mode: a prompt to a character that moves, with Meshy Text to Motion (the default: its own mannequin, from the prompt alone), Uthana Text to Motion 3.0 (your character or its own) or Cartwheel Text to Motion (your character, as Maya FBX). **Use selection** sends the selected character (a group or its meshes) as one GLB, once; Cartwheel waits for one. The model's frame-rate setting starts at the scene's rate when the model offers it. Import brings the character in with its joints, skin and clip, over the character it was made from when one was sent. The model picker of the Text and Edit selection modes no longer lists motion models.
- `tools/render_glb.py --play STEP` renders a landed clip over time, for animated GIFs.
- A clip whose keys fall between the scene's frames (made at 30 fps, imported into a 24 fps scene) is reported in the import checks.

### Fixes

- A rigged FBX lands in one piece: its skinned meshes no longer inherit the group's transform, which turned them twice in a Z-up scene (the character came in upside down) and moved them twice when placed on the ground or fitted over an object. Its clip now starts on the scene's start frame, as a GLB clip does.
- A GLB with vertex colours imports (creating the colour set failed on its arguments).
- 3D results and Import GLB land at the right size in scenes set to metres or millimetres (they were 100 times too small in metres and 10 times too large in millimetres; centimetre scenes were right).

### Development

- `tools/lint.py` also checks files not yet added to git, so a local run before a commit finds what CI finds.
- The fake Scenario server answers the motion models like the live ones (Cartwheel refuses to price without a character, Uthana prices one in, results are a skinned, keyed character), and serves their recorded schemas.
- The fake Scenario server answers the edit models like the live ones (the sent mesh back resized and centred, with new UVs, a texture or other triangles over the same shape), so Edit selection is tested end to end without spending.
