# ADR 0002 — Build with CMake instead of the checked-in MSVC project

- **Status:** Accepted
- **Date:** initial commit of this repo
- **Context:** Upstream ships `vc/OpenTyria.vcxproj`, but it is **stale**: it still
  lists `..\code\OpenTyria\CtrlProto.c` (line 71), a file that no longer exists,
  so the checked-in Visual Studio build does not work on a clean checkout. There
  is no Linux build file at all, and no CI. GWPS needs to build both here
  (Windows/MSVC) and eventually on Linux, reproducibly.

## Decision

Add a top-level `CMakeLists.txt` as the single build definition:

- One target for the server (`gwps_server`) building
  `code/OpenTyria/build_open_tyria.c` (the single translation unit upstream uses).
- SQLite compiled from the vendored amalgamation as its own static library.
- Mbed TLS pulled in via its own `add_subdirectory`, with tests/programs off.
- `scripts/build.ps1` for Windows (finds MSVC via `vswhere`), plain
  `cmake -B build` everywhere else.

The hand-rolled single-translation-unit `#include` chain is **kept for now** — it
is what upstream tests, and splitting it is a separate, riskier change. Note it
as technical debt (see `docs/02-scaling-limitations.md` §10).

`vc/*.vcxproj` stays in the tree for reference but is not the supported path.

## Consequences

- `cmake -B build && cmake --build build` works on Windows and Linux.
- The stale MSVC project can no longer silently break the build.
- Deleting/splitting the single-TU build remains possible as a follow-up; the
  CMake target list makes that a mechanical change.
