# Tests

This directory holds focused regression coverage for the public ABW evaluation
contract.

## Test Areas

| Path | Purpose |
| --- | --- |
| `unit/` | Generation, scoring, prompt contracts, few-shot banks, robustness, C0-C6, and retries. |
| `integration/` | End-to-end dataset, scoring, benchmark, and experiment-runner checks. |

## Editing Guidance

- Keep tests tied to a public evaluation workflow or a scoring dependency.
- Keep fixtures deterministic and easy to inspect.
- Avoid broad coverage-only tests and paper/report-generation tests.
