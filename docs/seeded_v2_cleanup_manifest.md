# Seeded-v2 Cleanup Manifest

## Canonical source

- Dataset: `dataset/abw-formal-nl-core`
- Version: `0.4.0`
- Families: seven paper-core families only
- Development split: 35 worlds, five per family
- Public-test split: 350 worlds, 50 per family
- Release archive: `dataset/abw-formal-nl-core.zip`

The seeded-v2 generator changes make structural parameters depend on the world
seed, record schema and content fingerprints, and enforce schema-disjoint dev
and public-test splits. The diversity audit reports 55 distinct schemas per
family across the two splits and no cross-split schema overlap.

## Preserved evaluation paths

- Stage 1: any model implementing the public target protocol on seeded-v2
  `dev`.
- Stage 2: zero-shot and two-example family-specific few-shot FD, NLD, and CT
  for any selected model on all 350 seeded-v2 `test_public` worlds.
- Robustness: paired zero-shot FD and CT views derived from seeded-v2.
- Difficulty: paired C0-C6 views derived from deterministic seeded-v2 source
  worlds; default 20 and maximum 50 source worlds per family.
- Recovery: failed invocations can be retried without rerunning successful
  worlds.

## Removed local material

- Pre-seeded-v2 datasets and their derived Natural-Language Direct,
  perturbation, and difficulty copies.
- Artifacts not rooted at `artifacts/paper_core_seeded_v2`.
- Historical NLD reclassification, old dataset-track builders, paper plotting,
  paper table rendering, and one-off statistical scripts.
- Legacy Slurm launchers tied to old paths or old run plans.
- The `mvp.yaml`, `paper_core.yaml`, and legacy few-shot configuration surfaces.
- Local logs, `.DS_Store` files, and obsolete dataset archives.

Paper source and current seeded-v2 result artifacts are outside this cleanup's
deletion set. Provider secrets and `.env` are never included in the archive.
