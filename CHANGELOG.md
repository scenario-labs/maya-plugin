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
