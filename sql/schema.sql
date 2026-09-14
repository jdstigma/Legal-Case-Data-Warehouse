-- Legal Case Data Warehouse
-- Normalized schema for the Supreme Court Database (SCDB), modern (1946-2024)
-- and legacy (1791-1945) releases, enriched with FJC appointment/party data.
--
-- Design: a handful of small reference/lookup tables (decoded from the SCDB
-- online codebook), a `justices` dimension, a `cases` table (grain: one row
-- per Supreme Court dispute), a `case_parties` junction table (unpivots the
-- wide petitioner/respondent columns into rows), and a `votes` fact table
-- (grain: one row per justice, per case issue, per vote -- the large table).
--
-- Columns suffixed `_code` that have no matching `ref_*` table are left as
-- the raw SCDB integer code; a few of the codebook's large lookup lists
-- (certReason, authorityDecision1/2, splitVote) were not transcribed for
-- this initial build. See README.md "Known gaps".
--
-- FK relationships are declared below for documentation, but are NOT
-- enforced during load (see etl/load.py) -- a handful of SCDB rows use
-- codes outside the transcribed reference lists (e.g. edge-case decision
-- directions on legacy-era cases). Enforce them yourself with
-- `PRAGMA foreign_keys = ON;` once you've resolved the gaps you care about.

-- ---------------------------------------------------------------------
-- Reference / lookup tables (seeded from sql/seeds/*.csv)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ref_issue_area (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_decision_direction (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_winning_party (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_decision_type (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_jurisdiction (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_case_disposition (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_law_type (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

-- Shared by petitioner, respondent, and adminAction (the SCDB codebook
-- confirms adminAction reuses the same code list as petitioner/respondent).
CREATE TABLE IF NOT EXISTS ref_party_type (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_vote_type (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_opinion_type (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

-- Shared by caseOrigin and caseSource (the SCDB codebook confirms both
-- variables use the same court code list).
CREATE TABLE IF NOT EXISTS ref_lower_court (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

-- Granular subject-matter issue (e.g. "Miranda warnings", "sex discrimination
-- in employment"); issue_area_code above is this variable's 14 broad buckets.
CREATE TABLE IF NOT EXISTS ref_issue (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

-- The specific constitutional provision, federal statute, or court rule at
-- issue (e.g. "Fourteenth Amendment (equal protection)", "Sherman Act");
-- law_type_code above is this variable's 8 broad buckets.
CREATE TABLE IF NOT EXISTS ref_law_supp (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- Justices dimension (SCDB tenure data joined to FJC appointment/party data)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS justices (
    justice_id INTEGER PRIMARY KEY,   -- SCDB justice ID
    abbreviation TEXT NOT NULL,       -- SCDB justiceName, e.g. "JGRoberts"
    full_name TEXT NOT NULL,          -- "Last, First"
    tenure_start DATE,
    tenure_end DATE,
    appointing_president TEXT,        -- from FJC federal-judicial-service.csv
    appointing_party TEXT,            -- Democratic / Republican / etc.
    nomination_date DATE,
    confirmation_date DATE,
    aba_rating TEXT,
    seat_id TEXT
);

-- ---------------------------------------------------------------------
-- Cases (grain: one row per Supreme Court dispute)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,             -- SCDB caseId
    docket_id TEXT,
    case_issues_id TEXT,
    vote_id TEXT,
    source_release TEXT NOT NULL,         -- 'SCDB_2025_01' | 'SCDB_Legacy_07'
    case_name TEXT,
    docket_number TEXT,
    us_cite TEXT,
    sct_cite TEXT,
    led_cite TEXT,
    lexis_cite TEXT,
    term INTEGER,
    natural_court INTEGER,
    chief_justice_id INTEGER REFERENCES justices(justice_id),
    date_decision DATE,
    date_argument DATE,
    date_reargument DATE,
    decision_type_code INTEGER REFERENCES ref_decision_type(code),
    jurisdiction_code INTEGER REFERENCES ref_jurisdiction(code),
    admin_action_type_code INTEGER REFERENCES ref_party_type(code),
    admin_action_state INTEGER,
    three_judge_fdc INTEGER,
    case_origin_code INTEGER REFERENCES ref_lower_court(code),
    case_origin_state INTEGER,
    case_source_code INTEGER REFERENCES ref_lower_court(code),
    case_source_state INTEGER,
    lc_disagreement INTEGER,
    cert_reason_code INTEGER,             -- raw SCDB cert-reason code (not enriched)
    lc_disposition_code INTEGER REFERENCES ref_case_disposition(code),
    lc_disposition_direction_code INTEGER REFERENCES ref_decision_direction(code),
    declaration_uncon INTEGER,
    case_disposition_code INTEGER REFERENCES ref_case_disposition(code),
    case_disposition_unusual INTEGER,
    winning_party_code INTEGER REFERENCES ref_winning_party(code),
    precedent_alteration INTEGER,
    vote_unclear INTEGER,
    issue_code INTEGER REFERENCES ref_issue(code),
    issue_area_code INTEGER REFERENCES ref_issue_area(code),
    decision_direction_code INTEGER REFERENCES ref_decision_direction(code),
    decision_direction_dissent_code INTEGER REFERENCES ref_decision_direction(code),
    authority_decision1_code INTEGER,     -- raw (not enriched)
    authority_decision2_code INTEGER,     -- raw (not enriched)
    law_type_code INTEGER REFERENCES ref_law_type(code),
    law_supp_code INTEGER REFERENCES ref_law_supp(code),
    law_minor TEXT,
    maj_opinion_writer_id INTEGER REFERENCES justices(justice_id),
    maj_opinion_assigner_id INTEGER REFERENCES justices(justice_id),
    split_vote_code INTEGER,              -- raw (not enriched)
    maj_votes INTEGER,
    min_votes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cases_term ON cases(term);
CREATE INDEX IF NOT EXISTS idx_cases_issue_area ON cases(issue_area_code);
CREATE INDEX IF NOT EXISTS idx_cases_issue ON cases(issue_code);
CREATE INDEX IF NOT EXISTS idx_cases_law_supp ON cases(law_supp_code);
CREATE INDEX IF NOT EXISTS idx_cases_chief ON cases(chief_justice_id);

-- ---------------------------------------------------------------------
-- Case parties: unpivots the wide petitioner/respondent columns into rows
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS case_parties (
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    party_role TEXT NOT NULL CHECK (party_role IN ('petitioner', 'respondent')),
    party_type_code INTEGER REFERENCES ref_party_type(code),
    party_state INTEGER,
    PRIMARY KEY (case_id, party_role)
);

-- ---------------------------------------------------------------------
-- Votes (grain: one row per justice, per case issue -- the large fact table)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS votes (
    vote_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    case_issues_id TEXT,
    vote_id TEXT,
    source_release TEXT NOT NULL,         -- 'SCDB_2025_01' | 'SCDB_Legacy_07'
    justice_id INTEGER REFERENCES justices(justice_id),
    vote_code INTEGER REFERENCES ref_vote_type(code),
    opinion_code INTEGER REFERENCES ref_opinion_type(code),
    direction_code INTEGER REFERENCES ref_decision_direction(code),
    majority_code INTEGER,                -- raw SCDB code (not independently decoded)
    first_agreement TEXT,                 -- raw justice abbreviation whose opinion was joined
    second_agreement TEXT
);

CREATE INDEX IF NOT EXISTS idx_votes_case ON votes(case_id);
CREATE INDEX IF NOT EXISTS idx_votes_justice ON votes(justice_id);
