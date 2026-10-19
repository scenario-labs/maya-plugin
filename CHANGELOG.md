# Changelog

## Unreleased

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
- Import of an edit result places it over the mesh it came from, as a new group, fitted with one uniform scale and an offset (edit models return the mesh resized and centred), even when the mesh moved after it was sent. The mesh itself is not changed.
- Apply... on UV unwrap and Retexture results writes them onto the mesh itself after a review (what changes, what is kept, what needs a tick): Replace UVs fills the current UV set and keeps the old one as `<set>_scnPrev`; Replace textures assigns a new material built from the result's maps. The result is first proven to be the same surface as the mesh (vertices, faces, winding, one UV per face corner). One Ctrl+Z undoes the whole apply; deformed, referenced and locked meshes are refused in this version.
- `tools/render_glb.py --checker N` shows the UV layout with a checker instead of the materials.

### Fixes

- 3D results and Import GLB land at the right size in scenes set to metres or millimetres (they were 100 times too small in metres and 10 times too large in millimetres; centimetre scenes were right).

### Development

- `tools/lint.py` also checks files not yet added to git, so a local run before a commit finds what CI finds.
- The fake Scenario server answers the edit models like the live ones (the sent mesh back resized and centred, with new UVs, a texture or fewer triangles), so Edit selection is tested end to end without spending.
