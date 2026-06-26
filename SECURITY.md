# Security Policy

Axiomatic Bridge Worlds is primarily a local benchmark and evaluation harness,
not a hosted network service. The most relevant security-sensitive surfaces are:

- subprocess execution for target systems and prover backends
- filesystem access to public and private benchmark artifacts
- optional external solver integrations

## Supported Versions

Security fixes are applied on a best-effort basis to the current `main` branch.
Older snapshots and generated datasets should be treated as unsupported unless
they are explicitly maintained.

## Reporting A Vulnerability

Please do not open a public issue for a suspected vulnerability.

Instead:

1. Use private vulnerability reporting on the hosting platform if available.
2. Otherwise contact the maintainers privately through the repository owner or
   project page.

Include:

- the affected command, script, or module
- reproduction steps
- whether the issue requires a crafted dataset, candidate, or subprocess
- platform details such as OS, Python version, and whether `z3` or `cvc5` was involved

We will aim to acknowledge the report, reproduce it, and coordinate a fix
before public disclosure when that is practical.
