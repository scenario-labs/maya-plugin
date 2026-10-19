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
