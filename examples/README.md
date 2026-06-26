# Examples

The smallest public, inspectable tour of ABW. It exists to show one concrete
bridge pattern per family, provide candidate fixtures for docs and smoke tests,
and keep at least one packaged world small enough to read by hand.

| Path | Purpose |
| --- | --- |
| `tiny_world/` | A packaged world for quick inspection, validation, and scoring demos. |
| `<family>/gold_candidate.abw` | A strong candidate for that family's hidden bridge. |
| `<family>/trivial_candidate.abw` | A deliberately weaker baseline for contrast. |

## Editing Guidance

- Keep examples small, readable, and intentionally public.
- Favor teaching one idea clearly over maximizing benchmark difficulty.
- When a family changes semantically, update the paired candidate so the docs
  still tell the truth.
