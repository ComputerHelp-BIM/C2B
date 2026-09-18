# MINI_TEMPLATE

A cut-down template description, written by hand to exercise the parser. It is not any real
template: the firm's own file changes whenever they edit their template, so the rules are
pinned here instead and the real one is only smoke-tested.

- **File** — `D:\somewhere\MINI.rvt`
- **Survey offset** — 50000 mm

## Datum

### Levels

| Name | Elevation (mm) |
| --- | ---: |
| `01 GROUND LVL.` | 0 |
| `02 FIRST FLOOR LVL.` | 3300 |

### Grids

| Name | From | To |
| --- | --- | --- |
| `1` | -2000, 0 | 26000, 0 |
| `A` | 0, -2000 | 0, 14000 |

## Families and types

### Structural Columns

- **Test-Rectangular-Column** _(loadable)_
  - `T-300 X 600` — b 300.000, h 600.000
  - `T-400 X 400` — b 400.000, h 400.000
- **Test-Round-Column** _(loadable)_
  - `T-300` — b 300.000

### Structural Framing

- **Test-Step-Beam-Bottom** _(loadable)_
  - `T-200 X 450/700`

### Floors

- **Floor** _(system)_
  - `150 THK. TEST SLAB` — Default Thickness 150.000

## Parameters

### Shared

| Name | Type | Per | Categories |
| --- | --- | --- | --- |
| `BOUND_EVERYWHERE` | spec.string | instance | Structural Columns, Structural Framing, Floors, Walls |
| `BOUND_ON_ROOMS_ONLY` | spec.string | instance | Rooms |

### Project

| Name | Type | Per | Categories |
| --- | --- | --- | --- |
| `A_PROJECT_PARAM` | spec.string | instance | Structural Columns |

### Family

<details><summary><strong>Test-Rectangular-Column</strong> — 4 parameters, 3 writable</summary>

| Name | Type | Shared | Writable |
| --- | --- | --- | --- |
| `b` | length | yes | yes |
| `h` | length | yes | yes |
| `Type Name` | spec.string | no | no |
| `Type Mark` | spec.string | no | yes |

</details>

<details><summary><strong>Test-Step-Beam-Bottom</strong> — 3 parameters, 3 writable</summary>

| Name | Type | Shared | Writable |
| --- | --- | --- | --- |
| `W` | length | yes | yes |
| `H` | length | yes | yes |
| `H1` | length | yes | yes |

</details>
