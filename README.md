# boxd-script

Compare your Google Doc exported as Word with a fresh Letterboxd export, and prepare new-film imports and existing-review updates. Runs locally, without an AI agent, accounts, network access, or third-party Python packages.

## Start here

Double-click **Boxd.command** in this folder. Drop the latest DOCX and Letterboxd export ZIP directly in `exports/`, then choose option 1. It selects the most recently modified file of each type and records their paths in the report. Option 9 lets you choose files manually. Other options include opening reports and resolving legacy batches. If macOS asks which application to use, choose Terminal.

Your 333-film successful import is already initialized. Do not initialize it again or delete the private folder.

## Writing new entries

Your document is the source for ratings, watched years, reviews, and tier-based hearts. Use this format for favourites:

```text
Tier 1: Favourite
Movie Title (2020) - 5 / 5 stars
[Watched in 2021]
Your review, using ordinary bullet points.
```

In Tiers 1–3, each film needs its own watched tag. In Tier 4+, use year headings that apply to all following films until the next year heading:

```text
Tier 4+: All
2026 Log
Movie Title (2025) - 3.5 / 5 stars
Your review.
Another Movie (2026) - 4 / 5 stars
[New film: yes]
Your review.
```

- Current reviews use a single HTML line break between paragraphs/bullets, without an added blank line. Legacy baseline reconstruction retains its original spacing.
- `/ 5` is the final Letterboxd rating: no conversion, bump, or old decision override. Ratings must be 0.5–5 in half-star steps. Fonts and sizes do not affect parsing.
- `2026 Log` means January 1, 2026. Repeated or out-of-order year headings are allowed. `[Watched in 2026]` also works as a boundary in Tier 4+.
- Use `[Watched in unknown]` for an individual favourite, or `Unknown Log` for a chronological block, to leave dates blank. Missing dates stop preparation rather than falling back to historical guesses.
- An optional `[Watched: 2026-09-12]` under a film overrides its block for that film only.
- Add `[New film: yes]` for genuinely new films, after checking they are not renamed entries or rewatches. No separate rating marker is needed.
- Tiers 1 and 2 imply a heart; other tiers do not. `[Liked: yes]` or `[Liked: no]` overrides this per film. Apply hearts manually on Letterboxd.
- `[REDACT REVIEW FOR UPLOAD]` removes the whole outgoing review. Already-published redactions remain manual tasks.
- Headings and control tags must be separate paragraphs. Keep entries out of tables. A missing closing bracket in an individual watched tag or extra closing brackets on a redaction marker are recognized and reported as formatting notes; other unrecognized control markers stop processing.
- Legacy headings without `/ 5` still use the original conversion workflow. Do not mix the old notation into new entries.

## Regular workflow: document + fresh account export

1. Export your latest Google Doc as `.docx` and download a fresh Letterboxd account export ZIP.
2. Double-click **Boxd.command**, choose **1** after dropping those two files into `exports/` (or use option **9** to select them manually). The terminal displays the selected paths.
3. Read `exports/sync-ID/report.md`. The comparison uses the supplied account export, not the previous upload CSV or remembered review text.
4. If all identity/metadata issues are resolved, import **upload.csv** once, with both watched-date diary entries and Import reviews enabled. Complete any correction cleanup listed in the report first. This combines the following separate files; do not import both the combined and separate versions:
   - `new-films.csv`: genuinely new films. Inspect title/year matches in Letterboxd before confirming.
   - `review-updates.csv`: changed existing dated reviews, identified by their exact existing entry URI and original watched date. Check **both** “Create diary entries based on watched dates” and “Import reviews”. This file deliberately has no rating column.
5. Follow the report for manual changes. Verify imports by opening the original entries and checking for duplicates.
6. Download a **new export after importing or editing Letterboxd**. Select that export on the next run. Completed review changes disappear from the report automatically; no Confirm step is needed for these sync folders.

The script never writes to Letterboxd itself. Generating a CSV does not establish that an import succeeded. Reusing an old export can regenerate already-completed changes: filenames, paths, source hashes, and output hashes are recorded in each sync manifest for traceability, but the script cannot know whether a selected export is current.

Ratings are compared separately for the current film and existing diary/review entries. Rating differences are manual tasks. Review updates do not apply simultaneous rating changes. Redactions, missing/deleted reviews, multiple entries for one film, undated review updates, and watched-date changes remain manual. Date conflicts prevent automated review updates for that film. Deleted and orphaned export folders are never treated as active entries.

Unresolved identities or missing required new-film metadata block all CSV generation; the report is still produced. Previously imported films missing from the export are never automatically added again. A document deletion never deletes a Letterboxd entry.

The ZIP may contain the CSVs at its root or inside one enclosing folder. From the terminal, an extracted account folder also works:

```sh
./boxd prepare '/path/to/Movie Blurbs.docx' '/path/to/letterboxd-export.zip'
./boxd prepare '/path/to/Movie Blurbs.docx' '/path/to/extracted-export'
```

## Legacy pending batches

The older import-history workflow remains available for resolving batches generated before export comparison was added. A pending legacy batch must be resolved before the new preparation workflow runs.

```sh
./boxd status
./boxd confirm BATCH-ID --all --yes
# For partial success, use one-based film row numbers, excluding the header:
./boxd confirm BATCH-ID --only 1,3,5 --yes
# Only if the remaining rows were NOT imported:
./boxd discard BATCH-ID --remaining-not-imported
```

Do not use these confirmation commands for `sync-...` folders. Use a fresh export to verify their results.

## Corrected titles and identity matching

The initial source-to-import aliases are saved. Title and release year identify a film. Substantial title changes are not automatically trusted as new films: they need the explicit New film marker. Same-title/different-year and close spelling matches are blocked for review.

Use `./boxd list` to see existing identity keys. For a renamed existing film, map the new source key to its existing key:

```sh
./boxd alias newnormalizedtitle:1997 existingnormalizedtitle:1997
```

Keys are lowercase alphanumeric titles, without accents, followed by a colon and release year. Alias resolution never creates a new import. Distinct same-title films and separate rewatch entries are deliberately left for manual handling.

### Verify translated titles and corrected identities

The comparison only trusts exact normalized title/year matches, existing aliases, or manually verified film URI mappings. It never treats matching review text as proof of film identity: some earlier imports put the correct review on the wrong film.

For a differently named film, first verify the actual film page is correct, then save its **film URI** (from `watched.csv` or `ratings.csv`, not its review URI):

```sh
./boxd identify sourcenormalizedtitle:1997 'https://boxd.it/VERIFIED_FILM_ID' '/path/to/export.zip'
```

The report folder includes `proposed-film-identities.json` for inspecting exact matches. It is not automatically adopted. Confirmed mappings live in `private/film-identities.json`; these are technical identifiers, not rating or review decisions.

## Private files and recovery

`private/` and `exports/` are ignored by Git. They contain personal review text and must not be committed. Back up both folders privately.

- `private/imported-baseline.csv`: the revised CSV successfully imported into the new account.
- `private/source-baseline.docx`: corresponding document snapshot.
- `private/import-history.json`: successful import history, aliases, and pending batches; never used as the source of generation decisions.
- `private/export-observations.json`: source films seen in supplied account exports, used to prevent accidental re-addition if they later disappear. This stores no editorial decisions and does not replace fresh export comparison.
- `private/backups/`: snapshots before state updates.
- `exports/BATCH-ID/manifest.json`: immutable batch details and item order.

State updates are atomic, and only one command can update state at a time. Corrupt state stops processing rather than silently resetting import history. Do not blindly restore an older backup: it may omit successful imports and cause duplicates. Reconcile it with your actual account first. A leftover `private/.lock` after a crash may be removed only when no other run is active.

## Runtime and tests

Python 3.9 or later. `boxd` uses the existing bundled Python on this Mac when available, otherwise `python3` on PATH. No pip installation required. The wrapper can be adjusted when moving this repo to another computer.

```sh
./boxd --help
python3 -m unittest discover -s tests -v
```

Tests use synthetic documents and temporary state. They cover repeat preparation, partial confirmation, redactions, aliases, malformed headings, CSV escaping, tampering, corruption, and locking.

## Legacy conversion decisions

For current `/ 5` documents, edit the document itself. Saved rating and date decisions do not affect those entries. The following files support only the archived four-star format and its regression test; they are not your ongoing editing workflow.

The legacy generator does not read an import CSV. Its inputs are:

- `private/rules.json`: tier/numerical conversion rules, heart tiers, and approved watch-year partitions. `historical_order` freezes the historical ordering so moving a film around your document does not change its date.
- `private/decisions.json`: individual overrides, keyed by original normalized title/year. Each rating or watch-year override includes a reason and source. Identity corrections are here too.
- Your Word document: titles, original numerical ratings, tiers, review text, and redaction markers.

Open `private/decision-register.md` to see all 333 resolved decisions in one table. It includes old/final ratings, rating reasons, watch years, date reasons, and whether a review is redacted. Regenerate it after edits:

```sh
./boxd decisions
```

To change an individual film, edit its object under `films` in `private/decisions.json`. For example:

```json
"mirror:1975": {
  "rating": {"final": 3.5, "reason": "User explicitly approved upgrade"},
  "watched": {"year": 2024, "reason": "Confirmed first viewing"}
}
```

Omitting `rating` uses the tier/numerical rule. Omitting `watched` uses the approved chronological partition. Use `"year": null` to explicitly keep a date unknown; this overrides partitions. Preserve `identity` corrections when editing other fields. Redactions still belong in the Word document.

Decisions apply to historical films only. New entries still require explicit metadata as described above. Explicit document metadata takes precedence during maintenance. Editing a historical rating/date decision produces a manual-update report. Review edits are compared to the selected account export and can produce an entry-targeted review-update CSV.

### Independent regression test

`./boxd audit` reconstructs all historical rows into `private/audit-reconstructed.csv` from DOCX + rules + decisions, without opening the saved CSV or using import history. This file is for comparison only, **not for reimport**.

The regression test alone reads `private/imported-baseline.csv` as a frozen golden reference and compares all generated bytes. It runs the generator in a temporary home with no reference CSV available. Changing a decision should fail the comparison; inspect the difference rather than updating the reference automatically.

The policy inputs were reconstructed from saved chat rating decisions and watch-year decisions. They were not extracted from the golden CSV. The imported baseline remains unchanged. Existing legacy `state.json` migrates to `import-history.json` while preserving all established history.

Policy files, the register, import history, reviews, and reports remain private and Git-ignored. Code, documentation, and synthetic tests are committed. Back up the private folder separately.

## Approved corrections and missing imports

One-time, verified additions live in `private/import-approvals.json`. These contain film identities and the hashes of the account export inspected when approving them, never ratings, dates, or reviews. Current document text supplies those values. They bypass historical missing-film protection only for that exact inspected export. If a later export still lacks the film, preparation stops for renewed verification; once the film appears under its verified title/year, normal comparison resumes.

`corrected-films.csv` contains replacements for reviews mistakenly imported onto other films. Remove the misplaced reviews/diary entries and ratings using the report links before importing this file once. This script does not delete anything on Letterboxd. Verified additions include a `LetterboxdURI` identifying the intended film, avoiding title guessing. `new-films.csv` contains the separately approved missing/new films.

The saved alternate-title matches can be reviewed in `private/film-matches.md`. They let you retain French and other preferred titles in the document. Back up these private files yourself; they are excluded from commits. Always supply a fresh export on your next run; reusing the same pre-import export can repeat an already prepared batch.

Run `./boxd prepare-latest` to use the newest DOCX and ZIP directly in `exports/`. Generated subfolders are ignored; ties stop with a request to choose explicitly. New films still require `[New film: yes]` or a verified one-time import approval. Existing ratings and dates remain manual changes, and unresolved film identities stop CSV generation.
