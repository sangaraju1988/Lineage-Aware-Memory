"""
setup_db.py
===========
Downloads the Northwind SQLite database for the real-agent experiment.

Source: https://github.com/jpwhite3/northwind-SQLite3
License: MIT

The database contains fictional business data (customers, orders, products,
employees) with realistic schema structure widely used for SQL training and demos.
"""

from __future__ import annotations

import os
import sqlite3
import sys

NORTHWIND_DB_URL = (
    "https://github.com/jpwhite3/northwind-SQLite3/raw/main/dist/northwind.db"
)
NORTHWIND_DB_ALT = (
    "https://raw.githubusercontent.com/jpwhite3/northwind-SQLite3/main/dist/northwind.db"
)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "northwind.db"
)


def download_northwind(db_path: str = DEFAULT_DB_PATH, force: bool = False) -> str:
    """
    Download northwind.db from GitHub if not already present.
    Returns the path to the database file.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if os.path.exists(db_path) and not force:
        print(f"[setup_db] Northwind DB already exists at {db_path}")
        return db_path

    print(f"[setup_db] Downloading Northwind DB from GitHub...")

    try:
        import requests
        for url in [NORTHWIND_DB_URL, NORTHWIND_DB_ALT]:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                with open(db_path, "wb") as f:
                    f.write(r.content)
                print(f"[setup_db] Downloaded {len(r.content):,} bytes → {db_path}")
                return db_path
            except Exception as e:
                print(f"[setup_db] URL {url} failed: {e}. Trying alternate...")

    except ImportError:
        # Fallback: urllib (stdlib)
        import urllib.request
        try:
            urllib.request.urlretrieve(NORTHWIND_DB_URL, db_path)
            print(f"[setup_db] Downloaded (urllib) → {db_path}")
            return db_path
        except Exception as e:
            print(f"[setup_db] urllib fallback failed: {e}")

    # Download failed — fall back to local synthetic generator
    print("[setup_db] Download failed. Generating local Northwind-compatible DB...")
    from real_agent.create_northwind import create_northwind_local
    return create_northwind_local(db_path, force=True)


def verify_northwind(db_path: str) -> dict:
    """
    Verify the Northwind DB is complete and readable.
    Returns a dict with table names and row counts.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cur.fetchall()]

    counts = {}
    for table in tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cur.fetchone()[0]
        except Exception:
            counts[table] = -1

    conn.close()
    return {"tables": tables, "row_counts": counts}


def print_schema_summary(db_path: str):
    """Print a summary of the Northwind schema."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cur.fetchall()]

    print("\n=== Northwind Database Schema ===")
    for table in tables:
        cur.execute(f'PRAGMA table_info("{table}")')
        cols = [(row[1], row[2]) for row in cur.fetchall()]
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = cur.fetchone()[0]
        col_str = ", ".join(f"{c[0]}({c[1]})" for c in cols[:6])
        if len(cols) > 6:
            col_str += f" ... +{len(cols)-6} more"
        print(f"  {table:<20} {count:>5} rows  |  {col_str}")

    conn.close()


def get_db_path() -> str:
    """Return the default DB path, downloading if necessary."""
    path = DEFAULT_DB_PATH
    if not os.path.exists(path):
        download_northwind(path)
    return path


if __name__ == "__main__":
    force = "--force" in sys.argv
    path = download_northwind(force=force)
    info = verify_northwind(path)
    print(f"\n[verify] Tables found: {len(info['tables'])}")
    for t, c in info["row_counts"].items():
        print(f"  {t:<25} {c:>5} rows")
    print_schema_summary(path)
