"""Run the full ETL pipeline end to end: extract raw sources, then load the warehouse.

    python etl/run_pipeline.py
"""

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract
import load


def print_summary(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    tables = ["cases", "case_parties", "votes", "justices"]
    print("\n--- summary ---")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:14s} {count:>10,} rows")
    term_range = conn.execute("SELECT MIN(term), MAX(term) FROM cases").fetchone()
    print(f"terms covered: {term_range[0]}-{term_range[1]}")
    conn.close()


def main() -> None:
    start = time.time()
    print("=== extract ===")
    extract.download_all()
    print("\n=== load ===")
    load.run()
    print_summary(load.DB_PATH)
    print(f"\ntotal time: {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
