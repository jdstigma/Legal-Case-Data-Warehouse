"""Power BI data source script.

Power BI Desktop has no native SQLite connector, so this is the standard
workaround: Get Data > More... > Other > Python script, paste this file's
contents into the script editor, and run it. Power BI inspects the script's
global scope afterward and offers every pandas DataFrame left in it
(cases, case_parties, votes, justices) as a selectable table -- pick the
ones you want and they load into the Power BI data model like any other
source.

One-time setup in Power BI Desktop, if not already configured:
    File > Options and settings > Options > Python scripting
    -> set "Detected Python home directories" to the Python install that
       has pandas (run `python -c "import sys; print(sys.prefix)"` to find it).

Requires: pip install pandas (already used by this repo's ETL if you have
pandas installed; the ETL pipeline itself does not depend on it).

Re-run this script (Refresh in Power BI) any time db/legal_data.db is
rebuilt by etl/run_pipeline.py to pick up new data.

The tables below denormalize the small reference/lookup tables back into
their text labels -- convenient for direct use in visuals -- while the
underlying SQLite warehouse stays properly normalized for the ETL demo.
"""

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "legal_data.db"

conn = sqlite3.connect(DB_PATH)

cases = pd.read_sql_query(
    """
    SELECT
        c.case_id, c.case_name, c.term, c.date_decision, c.docket_number,
        c.us_cite, c.natural_court, c.source_release,
        cj.full_name  AS chief_justice,
        dt.label      AS decision_type,
        jr.label      AS jurisdiction,
        cd.label      AS case_disposition,
        wp.label      AS winning_party,
        ia.label      AS issue_area,
        iss.label     AS issue,
        dd.label      AS decision_direction,
        lt.label      AS law_type,
        ls.label      AS statute,
        oc.label      AS origin_court,
        sc.label      AS source_court,
        cr.label      AS cert_reason,
        ad1.label     AS authority_decision_1,
        ad2.label     AS authority_decision_2,
        sv.label      AS split_vote,
        mw.full_name  AS majority_opinion_writer,
        c.maj_votes, c.min_votes
    FROM cases c
    LEFT JOIN justices cj             ON cj.justice_id = c.chief_justice_id
    LEFT JOIN justices mw             ON mw.justice_id = c.maj_opinion_writer_id
    LEFT JOIN ref_decision_type dt    ON dt.code = c.decision_type_code
    LEFT JOIN ref_jurisdiction jr     ON jr.code = c.jurisdiction_code
    LEFT JOIN ref_case_disposition cd ON cd.code = c.case_disposition_code
    LEFT JOIN ref_winning_party wp    ON wp.code = c.winning_party_code
    LEFT JOIN ref_issue_area ia       ON ia.code = c.issue_area_code
    LEFT JOIN ref_issue iss           ON iss.code = c.issue_code
    LEFT JOIN ref_decision_direction dd ON dd.code = c.decision_direction_code
    LEFT JOIN ref_law_type lt         ON lt.code = c.law_type_code
    LEFT JOIN ref_law_supp ls         ON ls.code = c.law_supp_code
    LEFT JOIN ref_lower_court oc      ON oc.code = c.case_origin_code
    LEFT JOIN ref_lower_court sc      ON sc.code = c.case_source_code
    LEFT JOIN ref_cert_reason cr      ON cr.code = c.cert_reason_code
    LEFT JOIN ref_authority_decision ad1 ON ad1.code = c.authority_decision1_code
    LEFT JOIN ref_authority_decision ad2 ON ad2.code = c.authority_decision2_code
    LEFT JOIN ref_split_vote sv       ON sv.code = c.split_vote_code
    """,
    conn,
)

case_parties = pd.read_sql_query(
    """
    SELECT cp.case_id, cp.party_role, pt.label AS party_type, cp.party_state
    FROM case_parties cp
    LEFT JOIN ref_party_type pt ON pt.code = cp.party_type_code
    """,
    conn,
)

votes = pd.read_sql_query(
    """
    SELECT
        v.vote_pk, v.case_id, v.source_release,
        j.full_name AS justice, j.appointing_president, j.appointing_party,
        vt.label AS vote, ot.label AS opinion, dd.label AS vote_direction
    FROM votes v
    LEFT JOIN justices j              ON j.justice_id = v.justice_id
    LEFT JOIN ref_vote_type vt        ON vt.code = v.vote_code
    LEFT JOIN ref_opinion_type ot     ON ot.code = v.opinion_code
    LEFT JOIN ref_decision_direction dd ON dd.code = v.direction_code
    """,
    conn,
)

justices = pd.read_sql_query(
    """
    SELECT justice_id, full_name, tenure_start, tenure_end,
           appointing_president, appointing_party, aba_rating
    FROM justices
    """,
    conn,
)

conn.close()
