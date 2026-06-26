# Changelog

All notable changes to this repository should be recorded here.

The project is still pre-1.0, so entries describe benchmark-surface and
repository-shape changes rather than strict semantic-version guarantees.

## Unreleased

### Added

- public benchmark packaging and reporting documentation surface
- public, model-agnostic robustness and C0-C6 difficulty-shape helper scripts
- contributor-facing repository files for contribution, security, and conduct
- a documentation index and repository-layout guide for top-level source shape
- directory-level READMEs plus a repository-layout guide for top-level folders
- citation metadata for software reuse

### Changed

- normalized the top-level README around benchmark use, docs navigation, and
  contributor entry points
- clarified generated-versus-checked-in artifact boundaries for datasets and
  report outputs
- expanded package metadata so the project reads more like a publishable
  benchmark library and less like an internal prototype
- removed Prism-specific and Codex-environment support material so the
  repository centers the ABW core framework
- removed paper-run orchestration, generated corpora, and result artifacts from
  the disclosure branch while preserving local copies on disk
