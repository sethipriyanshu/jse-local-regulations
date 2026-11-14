# Admin guide

How to run the JSE Local Regulations portal day to day. Open `/admin` and enter the admin passcode. Without login (MVP), anyone with the passcode is "admin". Actions are logged as `admin`, and user submissions are logged under the name they typed.

## The review loop

```
AI discovery ─┐
User suggests ├─> Sources tab ──approve──> fetch + AI extraction ──> Rules tab ──verify──> shown as Verified
Admin adds  ──┘                                                         ▲
Daily monitor ──> Changes tab ──accept──> re-extract new version ───────┘
```

1. **Sources.** These are URLs or PDFs waiting for a decision.
   - Approve the official pages that state MEP-relevant rules: adopted codes, permit and submittal requirements, local amendments.
   - Reject anything else, with a short reason. A rejected URL is remembered and never suggested again.
   - *Site blocks bots* means the page can't be read automatically (Municode, American Legal and some city sites). Open it, save the relevant chapter as a PDF, and upload it from the jurisdiction's **Sources** tab on the map.
   - **Approve all N** approves AI suggestions on official government domains in one go.
2. **Rules.** These are items the AI extracted, or that people typed in, grouped by document.
   - Check each item against its quote. Use **Edit** to fix the edition, date or wording before verifying.
   - Watch the source's scope. The Alabama DCM bulletin, for example, covers state-owned buildings only.
   - **Verify N quoted items** verifies everything from that document whose quote was found word for word in the source. Items marked ⚠ always need individual review.
   - Verifying a new edition of a code replaces the previously verified one for that jurisdiction. The old one stays in the rule's history.
3. **Changes.** The daily monitor shows what changed on monitored pages, with the AI's summary and the raw diff.
   - **Accept & re-extract** runs the AI on the new version. Updated items then appear in the Rules tab.
   - **Dismiss** is for cosmetic changes.
   - Changes the AI judged irrelevant are hidden unless you tick the box.

## Seeding a new area

1. **AI discovery** tab: run it for one jurisdiction (search box) or for all pilot jurisdictions. It takes about 30 s per jurisdiction and costs roughly $0.02 each. Each layer is searched for its own government's pages:
   - the state: code council, fire marshal, energy code, licensing;
   - the county: its own site;
   - the city: its building department and code of ordinances.
2. **Sources** tab: approve the good candidates, reject the rest.
3. **Rules** tab: verify. A jurisdiction turns **Verified** (green on the map) once everything recorded for it is verified.
4. Fill gaps by hand: on the map, open the jurisdiction → **Sources** → *Upload PDF* or *Add manually*.

Aim for this per pilot jurisdiction: the adopted-codes table filled in for state, county and city, plus the commercial permit and submittal requirements.

## Teams

**Teams** tab:
1. In Teams, open the channel → ⋯ → **Workflows** → *Post to a channel when a webhook request is received*.
2. Paste the URL here.
3. Choose a metro to limit the channel to that office, or *All metros*.
4. Click **Send test** to check it.

- **Daily digest:** sources checked, MEP-relevant changes, broken sources, review backlog, AI spend.
- **Alerts:** job failures, new user submissions.

## Jobs & health

- **Last daily check** turns red if the monitor failed or hasn't run in 36 hours. In Azure, check *Container Apps Job → worker → Execution history*.
- **Sources needing attention:** 404s, fetch errors and bot-blocked pages. Find the new URL and add it, or replace the page with a PDF upload.
- **AI spend** for the last 30 days, by task: extract, triage, discover.

## Exports

On the map, open any jurisdiction or address → **Export** → PDF, Word or JSON. An export covers every layer that applies (for an address, its exact county and city). Untick *Include items pending review* for a verified-only report. The JSON format is documented in `docs/export-schema.md`.

## Running jobs by hand

```bash
cd backend
uv run python -m app.worker daily                 # monitor now (also posts the Teams digest)
uv run python -m app.worker discover 13121 1304000  # discovery for specific FIPS codes
```
