"""Clear stale fixed_version cache and re-run OSV enrichment for proxy health."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import connect  # noqa: E402
from app.services.osv import _is_newer  # noqa: E402
from app.services.proxy_health_store import get_proxy_health_cached  # noqa: E402


def clear_invalid_fixed_versions(*, slim_only: bool = False) -> int:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT ecosystem, artifact, version, problem_code, fixed_version "
            "FROM proxy_health_vulnerability "
            "WHERE fixed_version IS NOT NULL AND fixed_version != ''"
        ).fetchall()
        cleared = 0
        for row in rows:
            artifact = str(row["artifact"] or "")
            version = str(row["version"] or "")
            fixed = str(row["fixed_version"] or "")
            problem = str(row["problem_code"] or "")
            eco = str(row["ecosystem"] or "")
            should_clear = False

            if slim_only and not artifact.endswith("-slim"):
                continue

            # Same CVE: slim variants were missing repo match until osv.py fix.
            if artifact == "pydantic-ai-slim" and problem.upper() == "CVE-2026-65975":
                should_clear = True

            # Cached fix must be strictly newer than the vulnerable version.
            if fixed and version and not _is_newer(fixed, version):
                should_clear = True

            if should_clear:
                conn.execute(
                    "UPDATE proxy_health_vulnerability SET fixed_version = NULL "
                    "WHERE ecosystem = ? AND artifact = ? AND version = ? "
                    "AND problem_code = ?",
                    (eco, artifact, version, problem),
                )
                cleared += 1
        conn.commit()
        return cleared
    finally:
        conn.close()


async def refresh(ecosystems: list[str]) -> None:
    for eco in ecosystems:
        report = await get_proxy_health_cached(eco)
        hits = [
            v
            for v in report.vulnerabilities
            if v.artifact == "pydantic-ai-slim"
            and (v.problem_code or "").upper() == "CVE-2026-65975"
        ]
        print(f"[{eco}] vulnerabilities={len(report.vulnerabilities)}")
        for v in hits:
            print(
                f"  {v.artifact} {v.version} {v.problem_code} -> fixed={v.fixed_version}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ecosystem",
        action="append",
        default=["pypi"],
        help="Ecosystem to refresh (pypi, npm, nuget). Repeatable.",
    )
    parser.add_argument(
        "--all-ecosystems",
        action="store_true",
        help="Refresh pypi, npm, and nuget.",
    )
    parser.add_argument(
        "--slim-only",
        action="store_true",
        help="Only clear invalid cache rows for *-slim artifacts.",
    )
    args = parser.parse_args()
    ecosystems = ["pypi", "npm", "nuget"] if args.all_ecosystems else args.ecosystem

    cleared = clear_invalid_fixed_versions(slim_only=args.slim_only)
    print(f"Cleared {cleared} cached fixed_version row(s).")
    asyncio.run(refresh(ecosystems))


if __name__ == "__main__":
    main()
