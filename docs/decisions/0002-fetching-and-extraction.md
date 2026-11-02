# 0002 — Source fetching and AI extraction (weeks 3–4)

**Date:** 2026-11-01 · **Status:** Accepted

## Code libraries block automated reading
Municode (`library.municode.com`) and American Legal (`codelibrary.amlegal.com`) return Cloudflare bot challenges ("Just a moment… Enable JavaScript and cookies") to plain HTTP requests. Some city CMS sites do the same (Alexander City, AL was seen during testing). We **do not** try to get past these challenges with headless browsers or similar tricks. The fetcher:
- detects challenge pages and marks the source `blocked` instead of saving junk;
- honors robots.txt, identifies itself (`JSE-RegsBot/0.1`), and spaces requests at least 2 seconds apart per domain.

Content from those libraries comes in by **PDF upload** (save the code section or ordinance as a PDF) or by **manual entry**. If JSE later licenses Municode or a similar service, its feed can be added as another source type. Government agency and department pages (state code offices, county/city building departments, PDF bulletins) fetch fine and should be the main monitored sources.

As a result, Playwright is not needed for the MVP. `FetchMode.BROWSER` stays in the schema but is unused.

## Safety
User-submitted URLs are fetched server-side, so every request hop, including redirects, must resolve to a public IP. Loopback, private ranges, link-local, and Azure metadata addresses are refused. Uploads must be real PDFs (≤ 25 MB).

## Extraction
- Model: whichever Azure OpenAI deployment `AZURE_OPENAI_DEPLOYMENT` names (currently `gpt-4.1-mini`, shared with MEP-QC), called with strict JSON-schema output at temperature 0. The prompt is versioned (`app/prompts/extract_v1.md`), and that version is stored on every `ai_runs` row along with tokens and cost.
- Page text is split into 40k-character chunks with 1.5k overlap, at most 8 chunks per document.
- Every item must include a verbatim excerpt, which is checked against the snapshot (`is_grounded`):
  - **exact or fuzzy (≥95) match** → grounded;
  - **multi-line excerpt** → grounded if each line appears verbatim, in order, within 1,500 characters. Models often quote a list heading together with one of its items.
  - Ungrounded items are kept but flagged for the reviewer, and items below 0.3 confidence are dropped.
- Everything AI-produced starts as `pending`. Re-running extraction on the same source does not create duplicates.

Measured on the Alabama DCM code-adoption bulletin (PDF): 9 code adoptions and 2 rules, all grounded, about 1.7k input tokens, about $0.002.

**Note for review:** that bulletin covers state-owned buildings under the Division of Construction Management. It is a good example of why a human reviewer must confirm the *scope* of a source, and not just whether the text was extracted correctly.
