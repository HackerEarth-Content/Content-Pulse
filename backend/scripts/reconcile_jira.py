"""Compare Jira against our database, effort first.

    uv run python -m scripts.reconcile_jira --from 2026-08-03

Read-only on both sides — it reports drift, it never fixes it. Run
`backfill_jira --refresh --incremental` to close whatever this finds.

Drift went unnoticed for weeks because nothing watched for it: the last clean
reconciliation was 1,177 = 1,177, and by the time anyone looked again we were
67.7 hours and 16 misfiled tickets adrift. Exit code is non-zero when anything
disagrees, so this works as a cron check rather than something to remember.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import sys
from datetime import date

import httpx
from sqlalchemy import select

from core.config import settings
from core.database import Session
from core.orm import DailyEntry, EntryItem, Member, MemberAlias
from scripts.backfill_jira import DEFAULT_FROM, UNASSIGNED, _auth, _val


async def jira_side(frm: date) -> dict[str, dict]:
    """Per-issue truth from Jira: assignee and effort."""
    out: dict[str, dict] = {}
    token = None
    async with httpx.AsyncClient(
        base_url=settings.JIRA_BASE_URL, headers=_auth(), timeout=90
    ) as c:
        # A rejected credential returns 200 with an empty issue list rather than
        # 401, so an expired token would otherwise read as "Jira is empty" and
        # this script would cheerfully report every one of our rows as extra.
        me = await c.get("/rest/api/3/myself")
        if me.status_code >= 400:
            raise RuntimeError(f"Jira auth failed: HTTP {me.status_code}")

        while True:
            params = {
                "jql": f'project = TCE AND created >= "{frm.isoformat()}" ORDER BY created ASC',
                "maxResults": 100,
                "fields": "assignee,customfield_10526,status,resolutiondate",
            }
            if token:
                params["nextPageToken"] = token
            r = await c.get("/rest/api/3/search/jql", params=params)
            if r.status_code >= 400:
                raise RuntimeError(f"Jira search failed: HTTP {r.status_code} {r.text[:200]}")
            body = r.json()
            for i in body.get("issues", []):
                f = i["fields"]
                eff = f.get("customfield_10526")
                out[i["key"]] = {
                    "who": (f.get("assignee") or {}).get("displayName") or UNASSIGNED,
                    "minutes": int(eff) if eff is not None else None,
                    "resolved": f.get("resolutiondate") is not None,
                }
            token = body.get("nextPageToken")
            if body.get("isLast") or not token:
                return out


async def db_side(frm: date) -> tuple[dict[str, dict], dict[str, str]]:
    """The same issues as we hold them, plus the Jira-name -> member map."""
    async with Session() as db:
        rows = await db.execute(
            select(EntryItem.jira_issue_key, Member.display_name, EntryItem.effort_minutes,
                   EntryItem.resolved_at)
            .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
            .join(Member, Member.id == DailyEntry.member_id)
            .where(EntryItem.jira_issue_key.isnot(None), DailyEntry.entry_date >= frm)
        )
        ours = {
            k: {"who": who, "minutes": mins, "resolved": res is not None}
            for k, who, mins, res in rows
        }
        names = {i: n for i, n in await db.execute(select(Member.id, Member.display_name))}
        alias = {
            a.strip().lower(): names[m]
            for a, m in await db.execute(select(MemberAlias.alias, MemberAlias.member_id))
            if m in names
        }
    return ours, alias


def _map(who: str, alias: dict[str, str]) -> str:
    return alias.get(who.strip().lower(), who)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=DEFAULT_FROM.isoformat())
    args = ap.parse_args()
    frm = date.fromisoformat(args.frm)

    jira, (ours, alias) = await asyncio.gather(jira_side(frm), db_side(frm))
    print(f"reconciling TCE since {frm}: jira={len(jira)} ours={len(ours)}\n")

    missing = sorted(set(jira) - set(ours))
    extra = sorted(set(ours) - set(jira))
    drift_effort, drift_owner = [], []
    for key in sorted(set(jira) & set(ours)):
        j, o = jira[key], ours[key]
        if (j["minutes"] or 0) != (o["minutes"] or 0):
            drift_effort.append((key, j["minutes"], o["minutes"]))
        if _map(j["who"], alias) != o["who"]:
            drift_owner.append((key, j["who"], o["who"]))

    per: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0, 0])
    for j in jira.values():
        row = per[_map(j["who"], alias)]
        row[0] += 1
        row[2] += j["minutes"] or 0
    for o in ours.values():
        row = per[o["who"]]
        row[1] += 1
        row[3] += o["minutes"] or 0

    print(f"  {'member':<20}{'jira n':>7}{'our n':>7}{'jira min':>10}{'our min':>9}  ok")
    tot = [0, 0, 0, 0]
    for who, (jn, on, jm, om) in sorted(per.items(), key=lambda x: -x[1][2]):
        for i, v in enumerate((jn, on, jm, om)):
            tot[i] += v
        print(f"  {who:<20}{jn:>7}{on:>7}{jm:>10}{om:>9}  "
              f"{'yes' if jn == on and jm == om else 'NO'}")
    print(f"  {'TOTAL':<20}{tot[0]:>7}{tot[1]:>7}{tot[2]:>10}{tot[3]:>9}")

    print(f"\n  missing from our db : {len(missing)} {missing[:8]}")
    print(f"  not in jira         : {len(extra)} {extra[:8]}")
    print(f"  effort drift        : {len(drift_effort)} {drift_effort[:5]}")
    print(f"  wrong assignee      : {len(drift_owner)} {drift_owner[:5]}")

    gap = tot[2] - tot[3]
    print(f"\n  effort gap: {gap} min ({gap / 60:.1f}h) of {tot[2] / 60:.1f}h "
          f"= {abs(gap) / tot[2] * 100 if tot[2] else 0:.2f}%")

    clean = not (missing or extra or drift_effort or drift_owner)
    print("\n  CLEAN" if clean else "\n  DRIFT — run backfill_jira --refresh --incremental")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
