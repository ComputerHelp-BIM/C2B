# samples/

Put client DXF files here for local testing. They are ignored by git on purpose:
client drawings are confidential and too large for source control.

The integration tests in `tests/test_samples.py` run against every `*.dxf` in
this
folder and are skipped automatically when the folder is empty.

Expected conventions (all optional, but they make multi-floor drawings work):

| Convention | Layer | Entity | Purpose |
| --- | --- | --- | --- |
| Floor frame | `Boundary` | closed LWPOLYLINE | one rectangle around each floor plan drawn side by side in model space |
| Floor origin | `Origin` | POINT | the point that becomes (0, 0) of that floor, so floors stack in 3D |

The layer names are configurable in the profile (`floor.boundary_layer`,
`floor.origin_layer`).
