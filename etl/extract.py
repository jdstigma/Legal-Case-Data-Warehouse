"""Extract step: download the raw source files this warehouse is built from.

Sources:
  - Supreme Court Database (SCDB) -- Washington University / Penn State
    https://scdb.la.psu.edu/  (modern 1946-2024 release + legacy 1791-1945 release,
    each as case-centered and justice-centered/vote-level CSVs)
  - Federal Judicial Center -- Biographical Directory of Article III Federal Judges
    https://www.fjc.gov/history/judges  (appointing president / party per justice)

Re-running this script is a no-op if the files already exist in data/raw/;
pass --force to re-download.
"""

import argparse
import io
import urllib.request
import zipfile
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# filename -> (source URL, "zip" if the URL returns a zip archive containing
# a single CSV member, "csv" if it returns the CSV directly)
SOURCES = {
    "SCDB_2025_01_caseCentered_Citation.csv": (
        "https://scdb.la.psu.edu/?jet_download=ed98e2f718f46e42eddeb8d7724c77f61c84fc89",
        "zip",
    ),
    "SCDB_2025_01_justiceCentered_Vote.csv": (
        "https://scdb.la.psu.edu/?jet_download=0bab50af97bca2aa080e9f7e4935ce3294a0a7c8",
        "zip",
    ),
    "SCDB_Legacy_07_caseCentered_Citation.csv": (
        "https://scdb.la.psu.edu/?jet_download=d470117951f58ce1b30f87c2fc242335903ee5b4",
        "zip",
    ),
    "SCDB_Legacy_07_justiceCentered_Citation.csv": (
        "https://scdb.la.psu.edu/?jet_download=89e8b7129b92c67db3a887b4354bf25a7dbcb47f",
        "zip",
    ),
    "FJC_federal_judicial_service.csv": (
        "https://www.fjc.gov/sites/default/files/history/federal-judicial-service.csv",
        "csv",
    ),
}


def download_all(force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (url, kind) in SOURCES.items():
        dest = RAW_DIR / filename
        if dest.exists() and not force:
            print(f"skip   {filename} (already present)")
            continue
        print(f"fetch  {filename}")
        req = urllib.request.Request(url, headers={"User-Agent": "legal-etl-demo/1.0"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        if kind == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                member = zf.namelist()[0]
                dest.write_bytes(zf.read(member))
        else:
            dest.write_bytes(data)
        print(f"saved  {dest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if files exist")
    args = parser.parse_args()
    download_all(force=args.force)
