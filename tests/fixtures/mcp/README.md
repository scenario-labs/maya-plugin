# Recorded Scenario MCP replies

Recorded from the hosted Scenario MCP (server 0.34.0) on 2026-10-18 with free calls only (schema reads, dry runs, a free upload), then scrubbed: ids, signed links and account fields are replaced with placeholders. Job rows are shaped from real replies with placeholder ids. The Meshy 7.1 Image to 3D and Tripo P2 schemas were recorded on 2026-10-19; they hold no ids, and the only change is one em dash in a server note replaced by a colon (house style). The schemas of the edit models (Tripo Retopology v3, Tripo Smart UV, Hunyuan UV Unwrapping, Meshy 7 Retexture, Tripo 3.0 Texturing) were recorded the same day, with the same change for one note. The multi-view schemas (Tripo P2 Multi View, Tripo 3.1 Multi View, Hunyuan 3D 3.1 Pro Multiview) were recorded the same day, with the same change in Tripo's left view note.

`tests/fake_backend/fake_scenario.py` serves them; `tools/contract_check.py` checks weekly that the live server still answers this way.
