# 0003 — Review, discovery, monitoring, Teams and exports (weeks 5–8)

**Date:** 2026-11-14 · **Status:** Accepted

## Review and the merged stack
- Everything the AI extracts or a user types in is `pending` until an admin verifies it. Admins can verify, edit and verify, or reject with a reason. Every action is written to the audit log.
- **Supersede:** verifying an adoption of a code (e.g. IPC 2021) marks the previously verified adoption of the same code in the same jurisdiction `superseded` and links the two rules, so a rule's history can be followed. Other rules supersede only when the admin names the old rule.
- **Bulk verify** applies only to items whose quote was found in the source snapshot. Items whose quote wasn't found must be reviewed one by one.
- **Merged view** (`/jurisdictions/{fips}/regulations`): rules from every layer of the stack (state → county → city). For the adopted-codes table, the most local layer wins, and the table notes which outer edition it replaces. A caller that resolved an address passes that address's stack, because a multi-county city has no county layer by default.
- **Coverage** (map shading): `changes_pending` if the jurisdiction has data and a relevant change is waiting; `verified` if every item is verified; `partial` if anything is recorded; otherwise `none`. The map draws counties only, so a county with no data of its own shows `partial` when one of its cities has data.

## AI discovery
- Uses the Azure OpenAI Responses API with the built-in `web_search` tool on the existing deployment, plus strict JSON output. This was tested against `jse-openai`/`gpt-4.1-mini`. A separate Bing resource is not needed.
- The tool is rate limited per resource (HTTP 429), so calls retry with backoff, and bulk runs pause 20 s between jurisdictions (`DISCOVERY_INTERVAL_S`). It costs about $0.01–0.02 per jurisdiction.
- Every candidate is fetched before it reaches the queue. Dead links are dropped, and pages behind bot protection are kept with a "save as PDF and upload it" note. Candidates are also dropped when:
  - the URL is already filed under any jurisdiction, in any status;
  - the model labels them `other` and the domain isn't an official one;
  - they would be a second link to the same code library for that jurisdiction.
- The prompt keeps each layer to its own government. State pages belong to the state run and city pages to the city run. Bulk runs go state → county → city.
- Results are only suggestions (`submitted`, origin `ai`). Nothing is monitored until approved. Official-domain suggestions can be approved in bulk.

## Text extraction fix
Trafilatura treats a list made up only of links as boilerplate, and an adopted-codes page is often exactly that, since each code links to the ICC viewer. When trafilatura keeps less than half of the page's text, we fall back to a block-aware tag strip that drops script, nav, header and footer. This was found on Tuscaloosa's adopted-codes page.

## Daily monitoring
- `python -m app.worker daily` (Container Apps Job, cron) re-fetches every approved web source.
  - Changed text produces a unified diff (truncated at 30k characters) and an LLM triage (`triage_v1`): whether the change is MEP-relevant, a summary, and proposed add/update/remove actions.
  - A page whose text size changes by more than half is always flagged for a person to look at.
  - A source that never got a snapshot is ingested and extracted as if new.
- Accepting a change re-extracts the new snapshot. The new and updated items arrive as pending, and verifying them supersedes the old ones.
- One failing source doesn't fail the run. The run fails, and an alert is posted, only when every source errors.

## Teams
- Adaptive Cards are posted to Workflows webhooks ("Post to a channel when a webhook request is received"). This needs no bot registration. Webhook URLs come from `TEAMS_WEBHOOK_URL` and/or channels added in the admin view.
- Only `*.logic.azure.com`, `*.api.powerplatform.com` and `*.webhook.office.com` over HTTPS are accepted.
- Webhook URLs are never returned in full, and error messages leave them out.
- Cards: daily digest (optionally filtered by metro), job-failure alert, new user submission.
- Interactive approve/reject from Teams stays P2, because it needs a bot.

## Exports
- A single JSON document (schema v1, `docs/export-schema.md`) is rendered as JSON, Word (python-docx) and PDF (reportlab).
- **Change from the plan:** PDF uses reportlab instead of Playwright/Chromium. That keeps the image small and avoids running a browser in the container. The trade-off is the built-in Helvetica font instead of Figtree/Inter, and Windows-1252 text, where unsupported characters become "?". If brand fonts become a requirement, register the TTFs with reportlab.
- Options: include pending (default on), filter by discipline, and pass an address with its stack.
