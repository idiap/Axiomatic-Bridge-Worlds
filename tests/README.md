# Tests

This directory holds regression coverage for the public ABW runtime contract.

## Test Areas

| Path | Purpose |
| --- | --- |
| `unit/` | Narrow behavior checks for core runtime modules and repository contracts. |
| `integration/` | End-to-end command and workflow checks. |

## Editing Guidance

- Put the narrowest useful test in the narrowest useful layer.
- Keep fixtures deterministic and easy to inspect.
- When docs or repository-surface contracts matter to public use, it is fine to
  add light regression tests for those too.
