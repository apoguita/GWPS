# ADR 0001 — Fork OpenTyria as `PreSearing` instead of patching upstream

- **Status:** Accepted
- **Date:** initial commit of this repo
- **Context:** OpenTyria (`apoguita/OpenTyria`) is a working-but-rough GW1 server
  stack. We want a private Pre-Searing server. Every implementation choice we
  need (map configs, config files, WAL, process model) conflicts with upstream's
  stated goal of staying "fairly simple".

## Decision

Maintain `PreSearing` as an independent project, importing the OpenTyria working
tree as its initial commit, with `apoguita/OpenTyria` kept as the `upstream`
git remote (reference only).

## Consequences

- We own the code and can restructure freely (config, process model, DB) without
  arguing simplicity with upstream.
- We can still cherry-pick upstream fixes.
- We inherit upstream's limitations; they are documented in
  `docs/02-scaling-limitations.md` rather than silently carried.
- The `LICENSE` is kept as-is; upstream attribution stays in the repo.
