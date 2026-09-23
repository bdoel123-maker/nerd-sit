#!/usr/bin/env python3
"""
Refresh every active row in public.sunfire_players from WOSOracle.

Uses FID as the stable key and updates:
- player_name
- alliance
- fc_level
- power
- pet_power
- island_prosperity
- hero_power
- hero_gear_power
- expert_power
- kills
- labyrinth_score
- api_updated
- standings_updated

Required environment variables:
    WOSORACLE_API_TOKEN
    SUPABASE_URL
    SUPABASE_KEY
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

WOS_BASE = "https://wosoracle.com"
MAX_RETRIES = 5
BATCH_SIZE = 6
BATCH_DELAY = 15.0


def load_dotenv_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ[key] = value
    return True


def find_and_load_env():
    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()
    candidates = [script_dir / ".env", cwd / ".env"]
    candidates += [p / ".env" for p in script_dir.parents]
    candidates += [p / ".env" for p in cwd.parents]
    seen = set()
    for p in candidates:
        rp = str(p.resolve())
        if rp in seen:
            continue
        seen.add(rp)
        if load_dotenv_file(p):
            print(f"Loaded .env: {p.resolve()}")
            return


find_and_load_env()


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable {name}")
    return value


def n(value: Any):
    if value in (None, ""):
        return None
    try:
        v = float(value)
        return int(v) if v.is_integer() else v
    except (TypeError, ValueError):
        return None


def norm_alliance(value: Any):
    if not value:
        return None
    s = str(value).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return s.upper() or None


def standings_map(data):
    if not data:
        return {}
    rows = data.get("standings")
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        try:
            out[int(row.get("board_type"))] = row
        except (TypeError, ValueError):
            pass
    return out


def board_value(board):
    if not board:
        return None
    if board.get("points") is not None:
        return n(board.get("points"))
    return n(board.get("score"))


def furnace_to_fc(level):
    level = n(level)
    if level is None:
        return None
    level = int(level)
    if level < 31:
        return str(level)
    if level <= 34: return "FC1"
    if level <= 39: return "FC2"
    if level <= 44: return "FC3"
    if level <= 49: return "FC4"
    if level <= 54: return "FC5"
    if level <= 59: return "FC6"
    if level <= 64: return "FC7"
    if level <= 69: return "FC8"
    if level <= 74: return "FC9"
    return "FC10"


class WOSClient:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "State2348-Sunfire-Updater/1.0",
        })

    def get(self, path):
        url = WOS_BASE + path
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(f"GET {path} failed: {e}") from e
                delay = min(60, 3 * (2 ** attempt)) + random.uniform(0, 1.5)
                print(f"    network error; retrying in {delay:.1f}s")
                time.sleep(delay)
                continue

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as e:
                    raise RuntimeError(f"GET {path}: HTTP 200 but response was not JSON") from e

            if r.status_code == 429 or r.status_code in (408, 425) or r.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(f"GET {path}: HTTP {r.status_code}: {r.text[:300]}")
                retry_after = r.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0
                except ValueError:
                    delay = 0
                if delay <= 0:
                    delay = min(120, 5 * (2 ** attempt)) + random.uniform(0, 2)
                print(f"    HTTP {r.status_code}; retrying in {delay:.1f}s")
                time.sleep(delay)
                continue

            raise RuntimeError(f"GET {path}: HTTP {r.status_code}: {r.text[:300]}")

        raise RuntimeError(f"GET {path} failed")


class SupabaseREST:
    def __init__(self, url, key):
        self.base = url.rstrip("/") + "/rest/v1"
        self.session = requests.Session()
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
            "User-Agent": "State2348-Sunfire-Updater/1.0",
        }
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        self.session.headers.update(headers)

    def check(self, r, action):
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"Supabase {action} failed HTTP {r.status_code}: {r.text[:1000]}")

    def select_players(self):
        r = self.session.get(
            f"{self.base}/sunfire_players",
            params={
                "select": "id,fid,player_name,alliance,fc_level,power,active",
                "active": "eq.true",
                "order": "player_name.asc",
            },
            timeout=45,
        )
        self.check(r, "select sunfire_players")
        return r.json()

    def patch_player(self, fid, payload):
        r = self.session.patch(
            f"{self.base}/sunfire_players",
            params={"fid": f"eq.{fid}"},
            headers={"Prefer": "return=minimal"},
            json=payload,
            timeout=45,
        )
        self.check(r, f"update FID {fid}")



    def select_ranking_players(self):
        r = self.session.get(
            f"{self.base}/sunfire_players",
            params={
                "select": (
                    "fid,player_name,power,pet_power,island_prosperity,"
                    "hero_gear_power,expert_power,active"
                ),
                "active": "eq.true",
            },
            timeout=45,
        )
        self.check(r, "select Sunfire ranking data")
        return r.json()

    def patch_rank(self, fid, draft_score, draft_rank):
        r = self.session.patch(
            f"{self.base}/sunfire_players",
            params={"fid": f"eq.{fid}"},
            headers={"Prefer": "return=minimal"},
            json={
                "draft_score": draft_score,
                "draft_rank": draft_rank,
            },
            timeout=45,
        )
        self.check(r, f"rank FID {fid}")


def calculate_draft_rankings(db):
    """
    Weighted Sunfire draft score:
      Pet Power          30%
      Expert Power       25%
      Hero Gear Power    20%
      Island Prosperity  15%
      Total Power        10%

    Hero Power is intentionally ignored.

    NULL handling:
      For each metric, a NULL is scored as 90% of the lowest
      non-NULL value in that metric. The database value itself
      remains NULL.
    """
    weights = {
        "pet_power": 0.30,
        "expert_power": 0.25,
        "hero_gear_power": 0.20,
        "island_prosperity": 0.15,
        "power": 0.10,
    }

    rows = db.select_ranking_players()
    if not rows:
        print("\nNo active players available for draft ranking.")
        return

    minimums = {}
    maximums = {}
    substitutes = {}

    for metric in weights:
        known = [
            float(r[metric])
            for r in rows
            if r.get(metric) is not None
        ]
        if not known:
            raise RuntimeError(
                f"Cannot rank: every player has NULL {metric}"
            )
        minimums[metric] = min(known)
        maximums[metric] = max(known)
        substitutes[metric] = minimums[metric] * 0.90

    print("\nDraft ranking NULL substitutes:")
    for metric in weights:
        print(
            f"  {metric:20} "
            f"min={minimums[metric]:,.0f} "
            f"NULL score value={substitutes[metric]:,.0f}"
        )

    scored = []

    for row in rows:
        score = 0.0
        used_null = False

        for metric, weight in weights.items():
            raw = row.get(metric)
            if raw is None:
                value = substitutes[metric]
                used_null = True
            else:
                value = float(raw)

            max_value = maximums[metric]
            normalized = (value / max_value) if max_value > 0 else 0
            score += normalized * weight * 100

        scored.append({
            "fid": str(row["fid"]),
            "player_name": row.get("player_name") or "",
            "draft_score": round(score, 3),
            "used_null": used_null,
        })

    # Higher score = better draft rank.
    # FID provides deterministic ordering if two scores are identical.
    scored.sort(
        key=lambda r: (-r["draft_score"], r["fid"])
    )

    print("\n" + "=" * 72)
    print("SUNFIRE DRAFT RANKING")
    print("=" * 72)

    for rank, row in enumerate(scored, start=1):
        db.patch_rank(
            row["fid"],
            row["draft_score"],
            rank,
        )
        null_note = " *" if row["used_null"] else ""
        print(
            f"{rank:2}. {row['player_name'][:28]:28} "
            f"{row['draft_score']:7.3f}{null_note}"
        )

    print("\n* = at least one NULL field used the 90%-of-lowest substitute")
    print(f"Ranked {len(scored)} active Sunfire players.")



def main():
    db = SupabaseREST(require_env("SUPABASE_URL"), require_env("SUPABASE_KEY"))
    wos = WOSClient(require_env("WOSORACLE_API_TOKEN"))

    players = db.select_players()
    print(f"Found {len(players)} active Sunfire players.")

    updated = renamed = failed = 0

    for start in range(0, len(players), BATCH_SIZE):
        batch = players[start:start + BATCH_SIZE]
        print(f"\nPlayers {start + 1}-{start + len(batch)} of {len(players)}")

        for old in batch:
            fid = str(old["fid"])
            old_name = old.get("player_name") or ""

            try:
                profile = wos.get(f"/api/v1/players/{fid}")

                try:
                    standings_data = wos.get(f"/api/v1/players/{fid}/standings?cached=1")
                    boards = standings_map(standings_data)
                except Exception as e:
                    print(f"  {fid}: standings unavailable: {e}")
                    standings_data = None
                    boards = {}

                alliance = None
                if isinstance(profile.get("alliance"), dict):
                    alliance = norm_alliance(profile["alliance"].get("abbr"))

                new_name = profile.get("name") or old_name

                payload = {}

                # Never overwrite a good DB value with None.
                values = {
                    "player_name": new_name,
                    "alliance": alliance,
                    "fc_level": furnace_to_fc(profile.get("furnace_level")),
                    "power": n(profile.get("power")),
                    "kills": n(profile.get("kills")),
                    "labyrinth_score": n(profile.get("labyrinth_score")),
                    "pet_power": board_value(boards.get(16)),
                    "island_prosperity": board_value(boards.get(18)),
                    "hero_power": board_value(boards.get(27)),
                    "hero_gear_power": board_value(boards.get(28)),
                    "expert_power": board_value(boards.get(29)),
                    "api_updated": profile.get("updated_at"),
                    "standings_updated": (
                        standings_data.get("searched_at")
                        if isinstance(standings_data, dict)
                        else None
                    ),
                }

                for key, value in values.items():
                    if value is not None:
                        payload[key] = value

                db.patch_player(fid, payload)
                updated += 1

                if new_name != old_name:
                    renamed += 1
                    print(f"  OK {fid}: {old_name} -> {new_name} | {int(payload.get('power') or 0):,}")
                else:
                    print(f"  OK {fid}: {new_name} | {int(payload.get('power') or 0):,}")

            except Exception as e:
                failed += 1
                print(f"  ERROR {fid} {old_name}: {e}")

        if start + BATCH_SIZE < len(players):
            print(f"Saved batch; waiting {BATCH_DELAY:.0f}s...")
            time.sleep(BATCH_DELAY)

    print("\nAPI refresh complete. Calculating draft rankings...")
    calculate_draft_rankings(db)

    print("\n" + "=" * 60)
    print("SUNFIRE UPDATE COMPLETE")
    print(f"Roster : {len(players)}")
    print(f"Updated: {updated}")
    print(f"Renamed: {renamed}")
    print(f"Failed : {failed}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        sys.exit(1)
