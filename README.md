# boxd-script

Prepare new-film Letterboxd imports from your Google Doc exported as Word. Runs locally, without an AI agent, accounts, network access, or third-party Python packages.

## Start here

Double-click **Boxd.command** in this folder. It offers Prepare, Confirm, Status, and Open exports. If macOS asks which application to use, choose Terminal.

Your 333-film successful import is already initialized. Do not initialize it again or delete the private folder.

## Writing new entries

Continue using headings like `Movie Title (2026) - 3 stars` and ordinary Word bullet points. For each genuinely new film, add these separate lines immediately under its heading:

```text
[New film: yes]
[Letterboxd rating: 3.5]
[Watched: 2026-09-12]
[Liked: no]
```

- Letterboxd rating is the **final 0.5–5 rating**, not the old four-star rating. The script does not reinterpret your review or automatically bump new ratings.
- Watched accepts an exact date, a year such as `2026` (January 1 placeholder), or `unknown` (blank).
- New film: yes is your confirmation that this is not an existing entry with a corrected title or a rewatch. Similar existing titles are blocked for review even with this marker.
- Liked is optional, default no. It records a preference only; hearts must be applied manually.
- Existing entries need no extra metadata. Their approved ratings and dates are preserved.
- `[REDACT REVIEW FOR UPLOAD]` anywhere in a review blanks the entire outgoing review and removes the marker. It does not delete previously published text.
- Control lines must be separate paragraphs. Do not put movie entries in tables.

## Monthly workflow

1. Export the Google Doc as .docx.
2. Choose **Prepare** and select it. Read the report in `exports/`.
3. If there are new films, the script creates `exports/BATCH-ID/new-films.csv`. Only new films appear in that file. It also reports edits/redactions to existing films for manual handling.
4. Import that CSV **once** on Letterboxd. Inspect its matches and dates before completing the import.
5. Only after successful import, choose **Confirm** and enter the batch ID. This records success locally; it does not communicate with Letterboxd.

A pending batch blocks another Prepare, preventing overlapping files. Generating a file never marks films imported. If there are no new films, no CSV is created. If any entries need decisions, no CSV is created until they are resolved.

**The tool never edits or deletes anything on Letterboxd.** Changes to existing reviews, ratings, and dates stay out of new-film CSVs. Edit those existing Letterboxd entries directly. Change reports continue to compare against the last recorded imported version, so manual changes may remain in subsequent reports.

## Terminal commands

Run from this folder (or use the absolute path to `boxd`):

```sh
./boxd status
./boxd prepare '/path/to/Movie Blurbs.docx'
./boxd confirm BATCH-ID --all --yes
```

`--yes` means you have verified the specified rows actually imported. For partial success, use film row numbers starting at 1, excluding the CSV header:

```sh
./boxd confirm BATCH-ID --only 1,3,5 --yes
```

The batch stays pending until every row is confirmed. If the other rows were **not imported**, discard only the unconfirmed remainder:

```sh
./boxd discard BATCH-ID --remaining-not-imported
```

A later Prepare will export only the still-new films. Never upload an old full batch again. If you do not know whether an import succeeded, check your account before confirming or discarding.

## Corrected titles and identity matching

The initial source-to-import aliases are saved. Title and release year identify a film. Substantial title changes are not automatically trusted as new films: they need the explicit New film marker. Same-title/different-year and close spelling matches are blocked for review.

Use `./boxd list` to see existing identity keys. For a renamed existing film, map the new source key to its existing key:

```sh
./boxd alias newnormalizedtitle:1997 existingnormalizedtitle:1997
```

Keys are lowercase alphanumeric titles, without accents, followed by a colon and release year. Alias resolution never creates a new import. Distinct same-title films and separate rewatch entries are deliberately left for manual handling.

## Private files and recovery

`private/` and `exports/` are ignored by Git. They contain personal review text and must not be committed. Back up both folders privately.

- `private/imported-baseline.csv`: the revised CSV successfully imported into the new account.
- `private/source-baseline.docx`: corresponding document snapshot.
- `private/import-history.json`: successful import history, aliases, and pending batches; never used as the source of generation decisions.
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

## Editable conversion decisions

The generator no longer reads an import CSV. Its inputs are:

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

Decisions apply to historical films only. New entries still require explicit metadata as described above. Explicit document metadata takes precedence during maintenance. Editing a historical decision produces a manual-update report; it never resubmits the film or silently changes import history.

### Independent regression test

`./boxd audit` reconstructs all historical rows into `private/audit-reconstructed.csv` from DOCX + rules + decisions, without opening the saved CSV or using import history. This file is for comparison only, **not for reimport**.

The regression test alone reads `private/imported-baseline.csv` as a frozen golden reference and compares all generated bytes. It runs the generator in a temporary home with no reference CSV available. Changing a decision should fail the comparison; inspect the difference rather than updating the reference automatically.

The policy inputs were reconstructed from saved chat rating decisions and watch-year decisions. They were not extracted from the golden CSV. The imported baseline remains unchanged. Existing legacy `state.json` migrates to `import-history.json` while preserving all established history.

Policy files, the register, import history, reviews, and reports remain private and Git-ignored. Code, documentation, and synthetic tests are committed. Back up the private folder separately.
