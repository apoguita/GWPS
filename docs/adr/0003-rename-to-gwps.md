# ADR 0003 — Project name is GWPS; game-data identifiers keep "PreSearing"

- **Status:** Accepted
- **Context:** The project was forked as "PreSearing", which collides with the
  *name of the game region* it serves. That ambiguity showed up immediately:
  grepping for `presearing` returns both project references and Guild Wars data
  identifiers, so a blanket rename would have corrupted game data.

## Decision

- The **project** is called **GWPS** — Guild Wars Private Server, which in this
  deployment also reads as Guild Wars Pre-Searing. It is the name of the GitHub
  repository, the CMake project, and the binary (`gwps_server.exe`).
- **Guild Wars data identifiers keep their original spelling.** These are not
  ours to rename and mean something different:

  | Identifier | Where | Meaning |
  |-----------|-------|---------|
  | `Region_Presearing` | `GmMap.h:168` | the region enum value (7) |
  | `MapId_AscalonCityPreSearing` | `GmMaps.h:152` | map id 148 |
  | `MapId_RegentValleyPreSearing` | `GmMaps.h:166` | map id 162 |
  | `MapId_FortRanikPreSearingOutpost` | `GmMaps.h:170` | map id 166 |
  | `REGION_PRESEARING`, `PRESEARING_TARGETS`, `PRESEARING_IDS` | `tools/*.py` | the same game region |

- Prose keeps "Pre-Searing" (hyphenated, capital P/S) when it means the
  *place* — "Pre-Searing Ascalon", "the Pre-Searing outposts". It becomes "GWPS"
  only when it means the *project*.

## Applied rename

`PreSearing` → `GWPS`, `presearing_` → `gwps_`, `PRESEARING_ROOT` → `GWPS_ROOT`
across `README.md`, `CMakeLists.txt`, `docs/**`, `scripts/**`, and `tools/**` —
16 files. CMake targets: `gwps_server`, `gwps_tests`, `gwps_sqlite`
(`gwdat_scan` and `portal` are named for what they do, not for the project).

## Consequences

- `code/OpenTyria/**` was deliberately untouched: it contains no project-name
  references, only game-data identifiers.
- A grep for `PreSearing` outside `code/` should return only game-region prose and
  the identifiers above. Anything else is a missed rename.
- The local checkout folder may still be named `PreSearing`; that is independent
  of the repository name and is not worth churning unless it bothers someone.
