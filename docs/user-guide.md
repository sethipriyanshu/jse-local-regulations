# User guide

This guide is for JSE engineers and designers who want to look up the local rules for a project. You don't need an account. Just open the site.

## What this tool is for

Every city and county can change the building codes it uses. One place might be on the 2021 plumbing code while the next town over is still on 2018. Some places also have their own permit and drawing requirements.

This site keeps all of that in one place. Pick a location and it shows you:

- which code editions apply (IBC, IMC, IPC, NEC, IECC and others)
- local changes and permit or submittal requirements
- where each piece of information came from, with the exact quote from the source

## Finding a place

There are three ways to find a place:

1. **Type a project address** in the search box, for example "2201 University Blvd, Tuscaloosa AL". This is the most accurate option. The site works out the exact state, county and city for that address.
2. **Type a place name**, like "Fulton County" or "Charlotte NC".
3. **Click a county** on the map, or click one of the office buttons (Atlanta, Charlotte, Dallas and so on).

The colors on the map show how much information we have:

| Color | Meaning |
|---|---|
| Light peach | A pilot area we're still collecting information for |
| Orange | Some information, not all of it checked yet |
| Green | Everything recorded has been checked by a reviewer |
| Yellow | The source website changed recently and is waiting for review |
| White | No information yet |

## Reading the panel

When you select a place, a panel opens on the right.

**Rules that apply here** lists the layers of government: usually the state, then the county, then the city. Rules from all of them can apply to your project.

Below that are four tabs:

- **Overview**: the adopted codes table. When the state and the city adopt different editions of the same code, the city's edition wins, and the table says so ("replaces state 2010"). A green dot means a reviewer checked it. An orange dot means it's still waiting for review.
- **Rules**: permit, submittal, inspection and local change requirements. You can search them, filter by discipline (mechanical, electrical, plumbing and so on), or show only checked items. Click **Show source quote** to see the exact text the rule came from.
- **Changes**: a timeline of recent updates, such as a source page changing or an item being checked.
- **Sources**: the websites and documents the information came from.

**Tip:** if a city sits in more than one county (Atlanta, Dallas and others), search by address. That way the site knows which county applies.

## Downloading a report

Click **Export** in the panel and choose:

- **PDF**: a JSE-branded report, good for sharing or printing
- **Word**: the same report as an editable .docx
- **JSON**: the raw data, for other tools

The report covers every layer that applies to the place or address you picked. Untick **Include items pending review** if you only want checked information.

Always confirm with the city or county before you rely on something for design or permitting. The report says this too.

## Helping out

If you know of a page or document we're missing, open the place, go to the **Sources** tab and choose one of these:

- **Suggest a source**: paste a link to an official page, like the building department's adopted-codes page.
- **Upload PDF**: for ordinances or code sections. This is the best option for Municode and similar code libraries, because they block automated reading. Save the page as a PDF and upload it.
- **Add manually**: type a rule in yourself.

You can add your name so the admin knows who sent it. Everything you submit goes to an admin to review before it shows up as checked.

## Questions

- **Why does something say "Pending review"?** The AI read it from an official source, but a person hasn't checked it yet. It's probably right, but double-check before you rely on it.
- **Why is a place blank?** We haven't collected anything for it yet. Suggest a source and an admin will take a look.
- **Is this the final word?** No. The city or county (the authority having jurisdiction) always has the final say.
