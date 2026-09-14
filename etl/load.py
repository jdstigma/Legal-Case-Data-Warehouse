"""Load step: build db/legal_data.db from the raw source files and reference seeds.

Order of operations:
  1. create tables from sql/schema.sql
  2. load the small ref_* lookup tables from sql/seeds/*.csv
  3. build the justices dimension: SCDB tenure data (sql/seeds/justices_scdb.csv)
     joined to FJC appointment/party data (data/raw/FJC_federal_judicial_service.csv)
  4. load cases + case_parties from the SCDB case-centered CSVs (modern + legacy)
  5. load votes from the SCDB justice-centered CSVs (modern + legacy)
"""

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

from transform import to_date, to_int, to_text

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
SEEDS_DIR = SQL_DIR / "seeds"
DB_PATH = ROOT / "db" / "legal_data.db"

REF_SEED_FILES = {
    "ref_issue_area": "ref_issue_area.csv",
    "ref_decision_direction": "ref_decision_direction.csv",
    "ref_winning_party": "ref_winning_party.csv",
    "ref_decision_type": "ref_decision_type.csv",
    "ref_jurisdiction": "ref_jurisdiction.csv",
    "ref_case_disposition": "ref_case_disposition.csv",
    "ref_law_type": "ref_law_type.csv",
    "ref_party_type": "ref_party_type.csv",
    "ref_vote_type": "ref_vote_type.csv",
    "ref_opinion_type": "ref_opinion_type.csv",
}

# (filename, source_release tag)
CASE_CENTERED_FILES = [
    ("SCDB_2025_01_caseCentered_Citation.csv", "SCDB_2025_01"),
    ("SCDB_Legacy_07_caseCentered_Citation.csv", "SCDB_Legacy_07"),
]
JUSTICE_CENTERED_FILES = [
    ("SCDB_2025_01_justiceCentered_Vote.csv", "SCDB_2025_01"),
    ("SCDB_Legacy_07_justiceCentered_Citation.csv", "SCDB_Legacy_07"),
]


def build_schema(conn: sqlite3.Connection) -> None:
    schema_sql = (SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def load_reference_tables(conn: sqlite3.Connection) -> None:
    for table, filename in REF_SEED_FILES.items():
        with open(SEEDS_DIR / filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [(int(r["code"]), r["label"]) for r in reader]
        conn.executemany(f"INSERT OR REPLACE INTO {table} (code, label) VALUES (?, ?)", rows)
    print(f"loaded reference tables: {', '.join(REF_SEED_FILES)}")


# ---------------------------------------------------------------------
# Justices: SCDB tenure data joined to FJC appointment/party data
# ---------------------------------------------------------------------

def _load_scdb_justices():
    with open(SEEDS_DIR / "justices_scdb.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_fjc_scotus_rows():
    path = RAW_DIR / "FJC_federal_judicial_service.csv"
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if row.get("Court Name", "").strip() == "Supreme Court of the United States"]


def _match_justices_to_fjc(scdb_justices, fjc_rows):
    """Match each SCDB justice to its FJC appointment record.

    Most surnames are unique. Five are not (Harlan, Johnson, Marshall,
    Roberts, White -- explicitly called out in the SCDB codebook), so
    ambiguous matches are broken first by first-name prefix, then by
    picking the FJC row whose commission/confirmation/nomination year is
    closest to the SCDB tenure_start year.
    """
    by_last = defaultdict(list)
    for j in scdb_justices:
        last = j["full_name"].split(",")[0].strip().lower()
        by_last[last].append(j)

    matches = {}
    for row in fjc_rows:
        name = row.get("Judge Name", "")
        if "," not in name:
            continue
        last, rest = name.split(",", 1)
        last = last.strip().lower()
        candidates = by_last.get(last, [])
        if not candidates:
            continue
        first_token = rest.strip().split()[0].strip(".,").lower() if rest.strip() else ""
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            named = [
                c for c in candidates
                if c["full_name"].split(",")[1].strip().lower().startswith(first_token)
            ] if first_token else []
            pool = named or candidates
            if len(pool) == 1:
                chosen = pool[0]
            else:
                fjc_year = None
                for datefield in ("Commission Date", "Confirmation Date", "Nomination Date"):
                    v = (row.get(datefield) or "").strip()
                    if v:
                        fjc_year = int(v[:4])
                        break
                if fjc_year is not None:
                    chosen = min(pool, key=lambda c: abs(int(c["tenure_start"][:4]) - fjc_year))
                else:
                    chosen = pool[0]
        matches[chosen["justice_id"]] = row
    return matches


def load_justices(conn: sqlite3.Connection) -> None:
    scdb_justices = _load_scdb_justices()
    fjc_rows = _load_fjc_scotus_rows()
    matches = _match_justices_to_fjc(scdb_justices, fjc_rows)

    rows = []
    unmatched = []
    for j in scdb_justices:
        fjc = matches.get(j["justice_id"])
        if fjc is None:
            unmatched.append(j["full_name"])
        rows.append((
            int(j["justice_id"]),
            j["abbreviation"],
            j["full_name"],
            to_date(j["tenure_start"]),
            to_date(j["tenure_end"]),
            to_text(fjc.get("Appointing President")) if fjc else None,
            to_text(fjc.get("Party of Appointing President")) if fjc else None,
            to_date(fjc.get("Nomination Date")) if fjc else None,
            to_date(fjc.get("Confirmation Date")) if fjc else None,
            to_text(fjc.get("ABA Rating")) if fjc else None,
            to_text(fjc.get("Seat ID")) if fjc else None,
        ))

    conn.executemany(
        """INSERT OR REPLACE INTO justices
           (justice_id, abbreviation, full_name, tenure_start, tenure_end,
            appointing_president, appointing_party, nomination_date,
            confirmation_date, aba_rating, seat_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    print(f"loaded {len(rows)} justices ({len(rows) - len(unmatched)} matched to FJC appointment data)")
    if unmatched:
        print(f"  no FJC match for: {', '.join(unmatched)}")


# ---------------------------------------------------------------------
# Cases + case_parties
# ---------------------------------------------------------------------

def _chief_name_to_justice_id(conn: sqlite3.Connection, chief_surname: str):
    if not chief_surname:
        return None
    row = conn.execute(
        "SELECT justice_id FROM justices WHERE full_name LIKE ? ORDER BY tenure_start DESC LIMIT 1",
        (f"{chief_surname}%",),
    ).fetchone()
    return row[0] if row else None


def load_cases(conn: sqlite3.Connection) -> None:
    case_rows = []
    party_rows = []
    chief_cache = {}

    for filename, source_release in CASE_CENTERED_FILES:
        with open(RAW_DIR / filename, newline="", encoding="latin-1") as f:
            reader = csv.DictReader(f)
            for r in reader:
                chief = to_text(r["chief"])
                if chief not in chief_cache:
                    chief_cache[chief] = _chief_name_to_justice_id(conn, chief)

                case_rows.append((
                    r["caseId"], to_text(r["docketId"]), to_text(r["caseIssuesId"]), to_text(r["voteId"]),
                    source_release, to_text(r["caseName"]), to_text(r["docket"]),
                    to_text(r["usCite"]), to_text(r["sctCite"]), to_text(r["ledCite"]), to_text(r["lexisCite"]),
                    to_int(r["term"]), to_int(r["naturalCourt"]), chief_cache[chief],
                    to_date(r["dateDecision"]), to_date(r["dateArgument"]), to_date(r["dateRearg"]),
                    to_int(r["decisionType"]), to_int(r["jurisdiction"]),
                    to_int(r["adminAction"]), to_int(r["adminActionState"]), to_int(r["threeJudgeFdc"]),
                    to_int(r["caseOrigin"]), to_int(r["caseOriginState"]),
                    to_int(r["caseSource"]), to_int(r["caseSourceState"]),
                    to_int(r["lcDisagreement"]), to_int(r["certReason"]),
                    to_int(r["lcDisposition"]), to_int(r["lcDispositionDirection"]),
                    to_int(r["declarationUncon"]), to_int(r["caseDisposition"]), to_int(r["caseDispositionUnusual"]),
                    to_int(r["partyWinning"]), to_int(r["precedentAlteration"]), to_int(r["voteUnclear"]),
                    to_int(r["issue"]), to_int(r["issueArea"]),
                    to_int(r["decisionDirection"]), to_int(r["decisionDirectionDissent"]),
                    to_int(r["authorityDecision1"]), to_int(r["authorityDecision2"]),
                    to_int(r["lawType"]), to_int(r["lawSupp"]), to_text(r["lawMinor"]),
                    to_int(r["majOpinWriter"]), to_int(r["majOpinAssigner"]),
                    to_int(r["splitVote"]), to_int(r["majVotes"]), to_int(r["minVotes"]),
                ))

                pet_type = to_int(r["petitioner"])
                if pet_type is not None:
                    party_rows.append((r["caseId"], "petitioner", pet_type, to_int(r["petitionerState"])))
                resp_type = to_int(r["respondent"])
                if resp_type is not None:
                    party_rows.append((r["caseId"], "respondent", resp_type, to_int(r["respondentState"])))

    case_columns = [
        "case_id", "docket_id", "case_issues_id", "vote_id", "source_release", "case_name", "docket_number",
        "us_cite", "sct_cite", "led_cite", "lexis_cite", "term", "natural_court", "chief_justice_id",
        "date_decision", "date_argument", "date_reargument", "decision_type_code", "jurisdiction_code",
        "admin_action_type_code", "admin_action_state", "three_judge_fdc",
        "case_origin_code", "case_origin_state", "case_source_code", "case_source_state",
        "lc_disagreement", "cert_reason_code", "lc_disposition_code", "lc_disposition_direction_code",
        "declaration_uncon", "case_disposition_code", "case_disposition_unusual",
        "winning_party_code", "precedent_alteration", "vote_unclear",
        "issue_code", "issue_area_code", "decision_direction_code", "decision_direction_dissent_code",
        "authority_decision1_code", "authority_decision2_code",
        "law_type_code", "law_supp_code", "law_minor",
        "maj_opinion_writer_id", "maj_opinion_assigner_id", "split_vote_code", "maj_votes", "min_votes",
    ]
    assert case_rows and len(case_rows[0]) == len(case_columns), (
        f"case_rows tuple has {len(case_rows[0])} values, expected {len(case_columns)}"
    )
    placeholders = ",".join("?" * len(case_columns))
    conn.executemany(
        f"INSERT OR REPLACE INTO cases ({', '.join(case_columns)}) VALUES ({placeholders})",
        case_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO case_parties (case_id, party_role, party_type_code, party_state) VALUES (?,?,?,?)",
        party_rows,
    )
    print(f"loaded {len(case_rows)} cases and {len(party_rows)} case_parties rows")


# ---------------------------------------------------------------------
# Votes (large fact table)
# ---------------------------------------------------------------------

def load_votes(conn: sqlite3.Connection, batch_size: int = 20000) -> None:
    total = 0
    for filename, source_release in JUSTICE_CENTERED_FILES:
        batch = []
        with open(RAW_DIR / filename, newline="", encoding="latin-1") as f:
            reader = csv.DictReader(f)
            for r in reader:
                batch.append((
                    r["caseId"], to_text(r["caseIssuesId"]), to_text(r["voteId"]), source_release,
                    to_int(r["justice"]), to_int(r["vote"]), to_int(r["opinion"]), to_int(r["direction"]),
                    to_int(r["majority"]), to_text(r["firstAgreement"]), to_text(r["secondAgreement"]),
                ))
                if len(batch) >= batch_size:
                    _insert_vote_batch(conn, batch)
                    total += len(batch)
                    batch = []
        if batch:
            _insert_vote_batch(conn, batch)
            total += len(batch)
    print(f"loaded {total} votes")


def _insert_vote_batch(conn, batch):
    conn.executemany(
        """INSERT INTO votes (
            case_id, case_issues_id, vote_id, source_release,
            justice_id, vote_code, opinion_code, direction_code,
            majority_code, first_agreement, second_agreement
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        batch,
    )


# ---------------------------------------------------------------------

def run(rebuild: bool = True) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if rebuild and DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    try:
        build_schema(conn)
        load_reference_tables(conn)
        load_justices(conn)
        load_cases(conn)
        load_votes(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"done -> {DB_PATH}")


if __name__ == "__main__":
    run()
