# Vendored packages

| Package | Version | License | Source | Why |
|---|---|---|---|---|
| truststore | 0.10.5 | MIT (`truststore/LICENSE`) | https://pypi.org/project/truststore/0.10.5/ | TLS verification against the OS trust store: Maya's Python finds no CA bundle on macOS, and studio proxies that inspect TLS install their root in the OS store |

Files are copied unchanged from the wheel. Update by replacing the folder and this table.

## Scenario SDK (`sdk/`, not in git)

`tools/vendor_sdk.py` unpacks Scenario's Python SDK and its dependencies here from the wheels pinned by SHA-256 in `tools/sdk_wheels.json`: pure-Python packages in `sdk/lib/`, the compiled `pydantic_core` in `sdk/native/<python>-<os>-<cpu>/` (Python 3.11 and 3.13 on macOS arm64 and x64, Windows x64, Linux x64). `core/sdk.py` puts `lib/` and the build for the running Maya at the end of `sys.path`. Each package keeps its license files in its `.dist-info` folder.

| Package | Version | License |
|---|---|---|
| scenario-sdk | 2.5.0 | MIT |
| pydantic, pydantic-core | 2.14.3, 2.50.4 | MIT |
| httpx, httpcore | 0.28.1, 1.0.9 | BSD-3-Clause |
| anyio | 4.16.0 | MIT |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| certifi | 2026.10.23 | MPL-2.0 (unchanged) |
| distro | 1.9.0 | Apache-2.0 |
| sniffio | 1.3.1 | MIT or Apache-2.0 |
| annotated-types | 0.8.0 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.5 | MIT |

Update: change `PINS` in `tools/vendor_sdk.py`, run it with `--update`, then update this table.
