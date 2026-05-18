# Finding 01 — SERFF Filing Access Terms of Use prohibit automated download

**Date:** 2026-05-18
**Status:** Blocking. Original W1 (automated stratified scrape of the MD SERFF
portal) cannot proceed as planned. Pivot required.

## What we read

The MD SERFF home page at https://filingaccess.serff.com/sfa/home/MD requires
clicking "Begin Search," which routes through `/sfa/userAgreement.xhtml`. The
user agreement displayed there (and which every user must accept to view any
filing) contains the following verbatim language:

> The SERFF Filing Access Interface ("Interface") is the property of the NAIC.
> This system is intended to facilitate an alternative means of access to rate
> and form filings and health plan binders as made available by the State
> Insurance Department. The State has chosen to make this Interface available
> as an option for members of the public to use when obtaining publically
> available rate and form filings and health plan binders. **These rate and
> form filings and health plan binders are also available directly from the
> State.**
>
> This Use Agreement is the exclusive statement of the terms under which the
> NAIC grants access to a user ("you"). You agree that you will not reverse
> engineer, reverse assemble or reverse compile the applications. **You
> further acknowledge that circumvention or bypass of the intended workflow
> of the system in order to automate the download of data is prohibited.**
> You also agree to observe all copyrights associated with the rate and form
> filings, health plan binders or any other materials or documents you access
> by use of the Interface. By clicking on the "Agree" button below you are
> accepting all terms of this agreement and understand that any unauthorized
> use or dissemination of the data or information from the system or
> violation of these terms may result in immediate termination of access and
> possibly other legal action.

(Source: archived locally at `.tmp/serff-recon/userAgreement.html`, fetched
2026-05-18.)

Additional context from the MD home page:

- Public-access scope: "life and health filings that have been approved on
  or after November 1, 2014, and all property and casualty filings."
- The MIA explicitly directs anyone needing bulk or non-public-access
  filings to the Maryland Public Records Center at
  http://insurance.maryland.gov/Pages/PublicRecordsCenter.aspx or
  PIArequests.mia@maryland.gov.
- `robots.txt` returns 404 (the user agreement governs, not robots).

## Implications

Three things to call out:

1. **The "no automated download" clause is unambiguous.** Any scraper —
   rate-limited or not — that walks the SERFF search interface and pulls
   attached PDFs is a ToS violation. A polite-scraper defense is unavailable
   here because the agreement specifically prohibits automation, not
   intensity.

2. **NAIC explicitly disclaims responsibility for filing copyright.** Each
   filing's copyright belongs to the filing carrier, not to NAIC or the
   State. Even PDFs lawfully obtained may not be redistributable under
   CC-BY-4.0 without per-filing analysis or affirmative permission.

3. **Maryland directs bulk requesters to the PIA process.** The state has
   essentially answered the question of how to get bulk access: file a
   Public Information Act request.

## Pivot options

In order of cleanest-legal to most-pragmatic:

### Option A — Maryland PIA request

File a Public Information Act request with the MIA for a stratified sample
of recent filings. State expects this for bulk access. Tradeoffs:

- Pros: Legally unambiguous. Treats MIA as the data provider, not NAIC.
- Cons: Weeks-to-months turnaround. Fee-bearing (MIA may charge per-page or
  per-file). Cannot iterate quickly. May still face copyright restriction on
  redistribution of carrier-authored content.

### Option B — Hand collection through the sanctioned interface

A human accepts the ToS and downloads ~30–100 filings by clicking through
the site. Strictly speaking the ToS prohibits "automation" of downloads,
not human-paced clicking. Tradeoffs:

- Pros: Stays within ToS. Same legal posture as any researcher using the
  portal as intended.
- Cons: Scale-limited (~50–100 docs realistic, not 400). Lossy provenance.
- Notes: Still no resolution of redistribution rights — see "Distribution"
  below.

### Option C — Pivot to a different state's portal

Some SERFF-Access states may have less restrictive terms (the agreement we
read is NAIC-issued, applied uniformly per state, but each state's home
page can add or modify language; we'd have to read each one). California,
Washington, and Colorado all run their own filingaccess.serff.com instances.
Tradeoffs:

- Pros: Avoids the ToS issue if a friendlier state exists.
- Cons: Loses the MD-specific framing of the project. Same NAIC ToS text
  may be the binding one regardless of state.

### Option D — Reach out to NAIC / MIA directly

Email sfahelp@naic.org and the MIA PIA coordinator describing the academic
research and asking for a sanctioned bulk-access exception or alternate
channel. Tradeoffs:

- Pros: If granted, fully sanctioned. May surface a research-data channel
  we don't know about.
- Cons: Indefinite calendar time. No guarantee.

### Option E — Re-scope to non-SERFF documents

The project's research thesis (PDF poisoning in insurance disclosures) is
not strictly dependent on SERFF as the source. Alternatives:

- **NAIC model laws + state insurance codes** — already authoritative plain
  text from public sources (and these are W4's synthetic-set source corpus
  anyway).
- **Insurance carriers' published consumer-facing PDFs** — policies, claim
  forms, and rate-summary disclosures that carriers post on their own
  websites. These are not the same as SERFF filings but exhibit the same
  obfuscation patterns.
- **State PIA-released filings from prior FOIA datasets** — projects like
  Klein/Reporters Committee or MuckRock sometimes host released
  insurance-filing PDFs under their own redistribution terms.

## Distribution question (separate from acquisition)

Even with sanctioned acquisition, **redistribution of carrier-authored
filings under CC-BY-4.0 is not safe**: the NAIC agreement explicitly
preserves carrier copyright. To redistribute a PDF, we'd need either
(a) a determination that the document is uncopyrightable government work
(many filings are private-party submissions and are not), (b) per-carrier
permission, or (c) a fair-use posture for academic critique.

Even under best-case acquisition, the safe default is:

- **Manifest + analysis ship under CC-BY-4.0 in this repo.**
- **PDFs themselves do not get redistributed.** Users reacquire from the
  source under that source's ToS.

This matches Option B from the pre-project distribution question, not
Option 1 (HuggingFace bundle including PDFs).

## Recommendation

Take all of these in parallel:

1. **Continue Phase B work that doesn't depend on real-SERFF data:**
   W3 (obfuscation fingerprinter), W4 (synthetic gold set), W5 (benchmark
   harness). These can be developed and tested end-to-end against the
   synthetic gold set alone, which is independently valuable.
2. **Pursue Option D in the background:** email NAIC / MIA explaining the
   academic project and asking about sanctioned bulk access. Use the
   response to inform the long-term acquisition strategy.
3. **In the short term, use Option B (hand collection) for a ~30-doc
   pilot** so we have a small real-MD-SERFF set to validate the
   obfuscation fingerprinter against.
4. **Re-scope deliverable framing:** instead of "400-doc curated SERFF
   dataset," lead with "obfuscation taxonomy + benchmark + small MD-SERFF
   case study + synthetic gold set." This is more honest about what the
   ToS will actually allow.

## Action items

- [ ] User decides whether to pursue Option D (NAIC/MIA outreach) and
      whether to greenlight Option B (hand-collected pilot).
- [ ] Update README and project plan to reflect re-scoped deliverables.
- [ ] Proceed with W3/W4/W5 implementation against synthetic data.

## Artifacts

- `.tmp/serff-recon/userAgreement.html` — verbatim ToS as of 2026-05-18.
- `.tmp/serff-recon/md-home.html` — MD portal home page.
- `.tmp/serff-recon/OnlineHelp.pdf` — official SFA help PDF (4.7 MB).
