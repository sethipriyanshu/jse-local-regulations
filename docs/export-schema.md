# Export schema v1

`GET /api/jurisdictions/{fips}/export.json` (and `.docx` / `.pdf`, built from the same data).

Query parameters:

| Param | Meaning |
|---|---|
| `stack` | Comma-separated FIPS for an address's stack, e.g. `13,13121,1304000`. Default: the jurisdiction's own stack. |
| `include_pending` | `true` (default) or `false` for verified items only. |
| `disciplines` | Comma-separated discipline keys, e.g. `mechanical,plumbing`. |
| `address` | Printed on the report only. |

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "2026-11-14T22:55:57+00:00",
  "generator": "JSE Local Regulations",
  "jurisdiction": { "fips": "0177256", "name": "Tuscaloosa city", "type": "city", "state": "AL" },
  "address": null,
  "stack": [ /* layers, outermost first, same shape as "jurisdiction" */ ],
  "filters": { "include_pending": true, "disciplines": null },
  "disclaimer": "…",
  "effective_codes": [{
    "code": "IEBC", "edition": "2021", "effective_on": null, "status": "verified",
    "layer": { /* jurisdiction that adopted it */ },
    "overrides": [{ "layer": { /* outer layer */ }, "edition": "2010" }],
    "rule_id": 42
  }],
  "rules": [{
    "id": 42, "layer": { … }, "title": "…", "summary": "…",
    "discipline": { "key": "plumbing", "label": "Plumbing" },
    "category": { "key": "adopted_code", "label": "Adopted code" },
    "code_ref": "IPC", "code_edition": "2021", "effective_on": "2024-03-01",
    "status": "verified | pending", "origin": "ai | user | admin | seed",
    "excerpt": "verbatim quote from the source",
    "source": { "id": 7, "url": "https://…", "title": "…", "kind": "web | upload", "last_checked": "…" },
    "verified_at": "…"
  }],
  "sources": [ /* approved sources for the stack, with "layer" and "health" */ ]
}
```

Rules:
- `status` is never `rejected` or `superseded` in an export.
- `type` is one of `state`, `county`, `city`, `consolidated`, `district`.
- Dates are ISO 8601. `effective_on` is a date, everything else is a timestamp.
- New fields may be added within v1. Anything that removes or renames a field bumps the major version.
