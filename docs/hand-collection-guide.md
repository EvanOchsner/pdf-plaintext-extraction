# SERFF-MD hand-collection guide

Step-by-step instructions for downloading the pilot sample of ~30–60 MD SERFF
filings by hand through the sanctioned web interface. This guide is what
makes the project's acquisition strategy ToS-compliant: every download is a
human action through the intended workflow, not an automated bypass.

Background: see [findings/01-serff-tos-review.md](findings/01-serff-tos-review.md)
for why we cannot scrape. This document supersedes the original W1
"polite-scraper" plan.

## Quota

Target ~6–12 filings per line-of-business cell. Each filing typically contains
multiple PDF attachments (Forms, Rate/Rule, Supporting Documentation,
Correspondence), so one downloaded filing yields several documents for the
dataset. 30 filings → ~150–300 PDFs.

| LOB cell                    | Business Type      | Type of Insurance (multi-select) | Target filings |
|-----------------------------|--------------------|----------------------------------|---------------:|
| Personal auto               | Property & Casualty| 19.0 Personal Auto               | 8              |
| Homeowners / property       | Property & Casualty| 04.0 Homeowners + 01.0 Property  | 8              |
| Commercial P&C              | Property & Casualty| 17.0 CMP + 11.0 Med Mal + 16.0 Workers Comp (pick one or two) | 6 |
| Major medical / health      | Accident & Health  | H16 Group Major Medical + H14 Individual Major Medical | 6 |
| Dental                      | Accident & Health  | H10G + H10I Health - Dental      | 4              |
| Life — term & whole         | Life               | L04G + L07G + L08 (term/whole)   | 6              |
| Annuity                     | Annuity            | A02 + A03 Individual Annuity     | 4              |

Round up if a cell is sparse; round down if a cell drowns the others. If you
hit ~60 total filings before quotas fill, stop — that's plenty for the pilot.

The exact Type-of-Insurance codes the dropdown shows may vary by state;
SERFF uses NAIC's Uniform Product Coding (UPC) but the menu wording can
differ slightly. Pick the closest match in the dropdown and record the
exact label you selected so the manifest captures it.

## Procedure

### 0. One-time setup

- Use a desktop browser with a real download manager (Chrome, Firefox,
  Safari — all fine). Don't use a private/incognito window for the entire
  session because you'll need to re-accept the use agreement on every fresh
  session.
- Create a working directory: `serff-extraction/data/raw/` (this is
  gitignored). The downloads will land in your browser's default
  download folder; you'll move them here after each session.
- Open the manifest spreadsheet (see §3 below) and have it ready.

### 1. Accept the use agreement

1. Go to https://filingaccess.serff.com/sfa/home/MD
2. Click **Begin Search**.
3. Read the use agreement carefully, then click **Accept** if you agree.
   (You're agreeing on behalf of you-the-researcher, using the system as
   an intended public user.)

You'll be taken to the **Filing Search** page.

### 2. Run a stratified search

For each row in the quota table:

1. **Business Type:** select the corresponding value.
2. **Type of Insurance:** the dropdown will populate after Business Type is
   selected. Pick the relevant ToI(s) for the LOB cell.
3. **Submission Date range:** to keep results recent and manageable, default
   to `01/01/2022` → today. Narrow further if results overflow; widen if
   too sparse.
4. Leave Company Name, NAIC Company Code, Product Name, and Disposition
   Date blank.
5. Click **Search**.

The results page shows the matching filings. **Sort by SERFF Tracking Number
descending** so you see the most recent first.

#### Sampling rule

To avoid biasing the dataset toward a single carrier or product, do not
just take the first N filings off the list. Instead:

- Look at the result count. If it's, say, 200 matching filings and you need 8:
  pick every 25th row (200 ÷ 8) as you scroll down. This is a simple
  systematic sample.
- If a single Company Name dominates the results (more than half the visible
  rows), pick at most 3 filings per company; replace the excess by jumping
  to a different page of results for diverse carriers.
- Prefer filings with `Filing Status` = `Closed - FILED` or `Closed - Approved`
  — those are the most likely to be published in final form. Skip
  Withdrawn / Disapproved / Pending.

### 3. Download one filing

For each filing you've selected:

1. Click the row to open the **Filing Summary** page.
2. **Before downloading,** capture the Filing Summary metadata into the
   manifest spreadsheet (see schema below). The Filing Summary page shows
   the canonical values for everything we want in the manifest.
3. Scroll to the **Attachments** section near the bottom. You'll see up
   to four subsections:
   - Forms
   - Rate/Rule
   - Supporting Documentation
   - Correspondence
4. In each subsection, click **Select Current Version Only**. (Picking
   "Select All" is fine if you want every revision, but "Current Version
   Only" gives a cleaner per-filing dataset; the prevalence analysis
   doesn't need older revisions.)
5. Click **Download Zip File**. Save to your browser's default download
   folder.

The zip will be named `{SERFF_TRACKING_NUMBER}.zip`, e.g. `BLHI-126719733.zip`.
It contains:

- A top-level filing-summary PDF (`{tracking}.pdf`) with the Table of
  Contents.
- Up to four subfolders: `Form Attachments/`, `Rate-Rule Attachments/`,
  `Supporting Document Attachments/`, `Correspondence Attachments/`.
- A `User Usage Agreement Attachments/` folder (usually contains the
  carrier-side agreement; skip for the dataset).

### 4. After the session

Once you've downloaded a batch (every ~10 filings is a good cadence):

1. Move all `*.zip` files from your downloads folder into
   `serff-extraction/data/raw/`.
2. From the repo root:
   ```
   uv run python -m scripts.normalize.ingest_raw_zips
   ```
   (This script will exist after W2 is implemented — it unzips, normalizes
   filenames, computes SHA-256s, and appends to `data/manifest.jsonl`.)
3. Sanity-check the latest manifest rows match the spreadsheet you filled
   out.

For now, while W2 is under construction, just collect the zips and
spreadsheet rows. The ingest can run later — the raw zips are the
authoritative artifact.

## Manifest spreadsheet schema

Use a Google Sheet, Numbers, or a CSV — whatever is fastest. The columns
you fill out by hand mirror the manifest schema; the W2 ingest script
will join your spreadsheet with the bytes-derived fields (SHA-256, page
count, etc.).

| Column                | Required | Where from                                    |
|-----------------------|----------|-----------------------------------------------|
| `tracking_id`         | yes      | Filing Summary → SERFF Tracking Number         |
| `lob_cell`            | yes      | Which row of the quota table this came from   |
| `business_type`       | yes      | Filing Search criterion used                  |
| `type_of_insurance`   | yes      | Filing Summary → Type Of Insurance (verbatim) |
| `sub_type_insurance`  | no       | Filing Summary → Sub Type Of Insurance        |
| `product_name`        | yes      | Filing Summary → Product Name                 |
| `carrier`             | yes      | Filing Summary → Company Name                 |
| `naic_code`           | yes      | Filing Summary → Company Code                 |
| `filing_type`         | yes      | Filing Summary → Filing Type                  |
| `submission_date`     | yes      | Filing Summary → Submission Date              |
| `disposition_date`    | yes      | Filing Summary → Disposition Date             |
| `filing_status`       | yes      | Filing Summary → Filing Status                |
| `state_status`        | yes      | Filing Summary → State Status                 |
| `is_compact_filing`   | yes      | true if the page shows an IIPRC notice; else false |
| `download_iso`        | yes      | timestamp when you clicked Download Zip File  |
| `zip_filename`        | yes      | the filename your browser saved               |
| `notes`               | no       | free-text, e.g. "weird-looking watermark"     |

A `data/manifest_hand_intake.csv` template will be added when W2 lands
so you can paste straight into a known-good schema.

## Filings to skip

- **Compact filings.** If the Filing Summary shows an "Interstate Insurance
  Compact" notice (gray panel reading "This filing was submitted to the
  Interstate Insurance Compact. To obtain a copy of this filing, please go
  to insurancecompact.org"), the actual form PDFs are not in the SERFF
  download. Skip these and pick another.
- **Empty attachments.** A few filings have all four attachment sections
  empty (just correspondence, or just a single rate spreadsheet). Skip
  these — they're not useful for an extraction benchmark.
- **Anything you've already downloaded** (the tracking ID is unique). If
  you accidentally double-download, the SHA-256 dedup in W2 will catch
  it but it wastes your time.

## Estimated time

About 2 minutes per filing once you're in the rhythm: 30 seconds in the
search interface, 30 seconds capturing the manifest row, 30 seconds
clicking through the download, 30 seconds saving and moving on. ~30
filings ≈ 60 minutes of focused work. Do it in two or three sittings if
that's easier — the ToS reaccept on each session is the only annoyance.

## Why the granularity at all

For the prevalence study, we want roughly equal representation of LOBs
so that "X% of Maryland insurance filings are image-only" is a defensible
sentence. The stratification doesn't have to be perfect — within a factor
of 2 across cells is fine. The PDFs themselves are what matter; the
metadata is the index that lets us slice the prevalence numbers by LOB
and by carrier when the analysis goes in.
