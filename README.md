# Legal Case Data Warehouse

An end-to-end ETL demonstration in the legal domain: real U.S. Supreme Court
data, extracted from two authoritative public sources, transformed out of
wide/flat source files, and loaded into a normalized relational warehouse.

## Data sources

1. **[Supreme Court Database (SCDB)](https://scdb.la.psu.edu/)** — Washington
   University in St. Louis / Penn State. The standard academic dataset of
   U.S. Supreme Court decisions. Two releases are used to cover the Court's
   full history:
   - `SCDB_2025_01` — terms 1946–2024 (modern era)
   - `SCDB_Legacy_07` — terms 1791–1945 (legacy era)

   Each release ships two files: **case-centered** (one row per dispute) and
   **justice-centered** (one row per justice, per vote — the large table).

2. **[Federal Judicial Center — Biographical Directory of Article III Federal
   Judges](https://www.fjc.gov/history/judges)**. Official U.S. government
   source for every Article III judge's appointment history, filtered here to
   Supreme Court justices. Supplies `appointing_president` and
   `appointing_party` (Democratic/Republican/etc.) — SCDB itself deliberately
   avoids partisan labels, using an ideological "decision direction"
   (conservative/liberal) instead.

Citation (SCDB): Harold J. Spaeth, Lee Epstein, Michael J. Nelson, Andrew D.
Martin, et al. *2025 Supreme Court Database*, Version 2025 Release 1.

## Scale

| table | rows | grain |
|---|---:|---|
| `cases` | 29,202 | one Supreme Court dispute (1791–2024) |
| `case_parties` | 58,389 | one petitioner or respondent per case |
| `votes` | 297,676 | one justice's vote on one case issue |
| `justices` | 118 | one Supreme Court justice |

## Pipeline

```
etl/extract.py   -> downloads the 5 raw source files into data/raw/
etl/transform.py -> shared parsing helpers (dates, ints, null handling)
etl/load.py      -> builds sql/schema.sql, seeds reference tables,
                     resolves justices <-> FJC appointment records,
                     transforms + loads cases/case_parties/votes
etl/run_pipeline.py -> runs extract then load, prints a row-count summary
```

Run the whole thing (pure Python standard library — no dependencies to install):

```bash
python etl/run_pipeline.py
```

This is idempotent: `extract.py` skips files already present in `data/raw/`
(pass `--force` to re-download), and `load.py` rebuilds `db/legal_data.db`
from scratch each run, so raw source data always drives the warehouse rather
than the other way around. Output database is `db/legal_data.db` (SQLite,
git-ignored — regenerate it locally rather than pulling a binary from git).

## Schema

- **Reference tables** (`ref_issue_area`, `ref_decision_direction`,
  `ref_winning_party`, `ref_decision_type`, `ref_jurisdiction`,
  `ref_case_disposition`, `ref_law_type`, `ref_party_type`, `ref_vote_type`,
  `ref_opinion_type`) — small lookup tables decoded by hand from the [SCDB
  online codebook](https://scdb.la.psu.edu/online-codebook/), seeded from
  `sql/seeds/*.csv`.
- **`justices`** — one row per justice; SCDB tenure dates joined to FJC
  appointment data via `etl/load.py::_match_justices_to_fjc` (last-name
  match, disambiguated by first name / nearest appointment year for the five
  justices who share a surname: Harlan, Johnson, Marshall, Roberts, White).
- **`cases`** — one row per dispute, with categorical SCDB codes resolved to
  the reference tables above where a lookup was built.
- **`case_parties`** — the wide `petitioner`/`respondent` columns from the
  source CSV, unpivoted into one row per party role.
- **`votes`** — the large fact table: one row per justice's vote, joinable
  back to `cases` and `justices`.

See `sql/schema.sql` for full column definitions and comments.

## Known gaps

A handful of SCDB categorical columns reference large lookup lists (the
granular `issue` codes, `lawSupp`, `caseOrigin`/`caseSource` lower-court
codes, `certReason`, `authorityDecision1/2`, `splitVote`) that were **not**
transcribed into reference tables for this initial build — those columns are
loaded as raw SCDB integer codes. Foreign keys to the reference tables that
*do* exist are declared in `sql/schema.sql` for documentation but not
enforced during load (a few legacy-era rows use edge-case codes outside the
transcribed lists); run `PRAGMA foreign_keys = ON;` yourself if you want
enforcement once you've closed the gaps you care about.
