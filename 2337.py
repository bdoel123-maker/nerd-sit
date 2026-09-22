#!/usr/bin/env python3
"""
enemy_svs.py
Whiteout Survival / WOSOracle enemy-state collector for SvS scouting.

Required values, preferably stored in a .env file beside this script:
    WOSORACLE_API_TOKEN
    SUPABASE_URL
    SUPABASE_KEY

Examples:
    python enemy_svs_2337.py 2337
    python enemy_svs_2337.py 2337 --resume
    python enemy_svs_2337.py 2337 --update
    python enemy_svs_2337.py 2337 --discover
    python enemy_svs_2337.py 2337 --report
    python enemy_svs_2337.py 2337 --top-alliances 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

def load_dotenv_file(path: Path) -> bool:
    """Load KEY=VALUE pairs from a .env file. Returns True if loaded."""
    if not path.exists() or not path.is_file():
        return False

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key.startswith("export "):
            key = key[7:].strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        if key:
            # .env should take precedence for this script.
            os.environ[key] = value

    print(f"Loaded .env: {path.resolve()}")
    return True


def find_and_load_env() -> Path | None:
    """Search likely project locations for .env."""
    candidates = []

    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()

    candidates.append(script_dir / ".env")
    candidates.append(cwd / ".env")

    for parent in script_dir.parents:
        candidates.append(parent / ".env")

    for parent in cwd.parents:
        candidates.append(parent / ".env")

    seen = set()

    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)

        if load_dotenv_file(candidate):
            return candidate

    print("WARNING: No .env file found.")
    print(f"Script folder: {script_dir}")
    print(f"Current folder: {cwd}")
    return None


ENV_FILE = find_and_load_env()

WOS_BASE = "https://wosoracle.com"
DEFAULT_TOP_ALLIANCES = 5
DEFAULT_BATCH_SIZE = 6
DEFAULT_BATCH_DELAY = 15.0
MAX_RETRIES = 5

BOARD_TYPES = {
    3: "personal_power",
    4: "kill_count",
    16: "pet_power",
    18: "island_prosperity",
    27: "stage_power",
    28: "star_power",
    29: "master_total_power",
}

CHECKPOINT_DIR = Path(".svs_checkpoints")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def n(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        v = float(value)
        return int(v) if v.is_integer() else v
    except (TypeError, ValueError):
        return None


def norm_alliance(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return s.upper() or None


class WOSClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "State2348-SvS-Collector/1.0",
        })

    def get(self, path: str) -> dict[str, Any]:
        url = WOS_BASE + path
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                last_error = e
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(f"GET {path} failed: {e}") from e
                delay = min(60, 3 * (2 ** attempt)) + random.uniform(0, 1.5)
                print(f"  network error; retrying in {delay:.1f}s")
                time.sleep(delay)
                continue

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as e:
                    raise RuntimeError(
                        f"GET {path}: HTTP 200 but response was not JSON"
                    ) from e

            if r.status_code == 429 or r.status_code in (408, 425) or r.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(
                        f"GET {path}: HTTP {r.status_code}: {r.text[:300]}"
                    )
                retry_after = r.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0
                except ValueError:
                    delay = 0
                if delay <= 0:
                    delay = min(120, 5 * (2 ** attempt)) + random.uniform(0, 2)
                print(f"  HTTP {r.status_code}; retrying in {delay:.1f}s")
                time.sleep(delay)
                continue

            raise RuntimeError(f"GET {path}: HTTP {r.status_code}: {r.text[:300]}")

        raise RuntimeError(str(last_error or f"GET {path} failed"))


class SupabaseREST:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.session = requests.Session()
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
            "User-Agent": "State2348-SvS-Collector/1.0",
        }

        # New Supabase sb_secret_... keys are opaque API keys, not user JWTs.
        # Sending them only as `apikey` ensures PostgREST uses service_role.
        # Legacy service_role keys are JWTs and may still use Authorization.
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"

        self.session.headers.update(headers)

    def _check(self, r: requests.Response, action: str) -> None:
        if not (200 <= r.status_code < 300):
            raise RuntimeError(
                f"Supabase {action} failed HTTP {r.status_code}: {r.text[:1000]}"
            )

    def upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        if not rows:
            return
        r = self.session.post(
            f"{self.base}/{table}",
            params={"on_conflict": conflict},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows,
            timeout=45,
        )
        self._check(r, f"upsert {table}")

    def insert(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        r = self.session.post(
            f"{self.base}/{table}",
            headers={"Prefer": "return=minimal"},
            json=rows,
            timeout=45,
        )
        self._check(r, f"insert {table}")

    def select(
        self,
        table: str,
        params: dict[str, str] | None = None,
    ) -> list[dict]:
        r = self.session.get(
            f"{self.base}/{table}",
            params=params or {},
            timeout=45,
        )
        self._check(r, f"select {table}")
        return r.json()


def alliance_power(a: dict[str, Any]) -> float:
    for key in ("power", "total_power", "alliance_power", "combat_power", "score"):
        value = n(a.get(key))
        if value is not None:
            return float(value)
    return 0.0


def discover_players(
    wos: WOSClient,
    state_id: int,
    top_alliances: int,
) -> tuple[list[dict], list[dict]]:
    print(f"\nFetching State {state_id}...")
    state = wos.get(f"/api/v1/states/{state_id}")
    alliance_summaries = state.get("alliances") or []

    if not alliance_summaries:
        raise RuntimeError(f"No alliances returned for State {state_id}")

    def sort_key(a: dict[str, Any]):
        rank = n(a.get("rank"))
        if rank is not None and rank > 0:
            return (0, rank)
        return (1, -alliance_power(a))

    selected = sorted(alliance_summaries, key=sort_key)[:top_alliances]

    print(f"Top {len(selected)} alliances:")
    for i, a in enumerate(selected, 1):
        print(
            f"  {i}. {a.get('abbr') or a.get('name') or a.get('id')} "
            f"power={int(alliance_power(a)):,}"
        )

    player_map: dict[str, dict] = {}
    alliance_rows: list[dict] = []
    captured_at = utc_now()

    for idx, summary in enumerate(selected, 1):
        aid = summary.get("id")
        label = summary.get("abbr") or summary.get("name") or aid
        print(f"\n[{idx}/{len(selected)}] Loading alliance {label}...")

        alliance = wos.get(f"/api/v1/alliances/{aid}")
        members = alliance.get("members") or []
        abbr = norm_alliance(
            alliance.get("abbr")
            or summary.get("abbr")
            or alliance.get("name")
            or summary.get("name")
        )

        alliance_rows.append({
            "state": state_id,
            "alliance_id": str(aid) if aid is not None else None,
            "alliance": abbr,
            "alliance_name": alliance.get("name") or summary.get("name"),
            "member_count": len(members),
            "total_power": n(
                alliance.get("power")
                or alliance.get("total_power")
                or summary.get("power")
                or summary.get("total_power")
            ),
            "captured_at": captured_at,
        })

        print(f"  {abbr or label}: {len(members)} members")

        for m in members:
            fid = str(m.get("id") or m.get("fid") or "").strip()
            if not fid:
                continue
            player_map[fid] = {
                "fid": fid,
                "alliance": abbr,
                "roster_name": m.get("name"),
                "roster_power": n(m.get("power")),
                "roster_furnace": n(m.get("furnace_level")),
            }

        time.sleep(1.0)

    players = list(player_map.values())
    print(f"\nUnique players discovered: {len(players)}")
    return players, alliance_rows


def standings_map(data: dict[str, Any] | None) -> dict[int, dict]:
    if not data:
        return {}
    rows = data.get("standings")
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        try:
            bt = int(row.get("board_type"))
        except (TypeError, ValueError):
            continue
        out[bt] = row
    return out


def board_value(board: dict | None):
    if not board:
        return None
    if board.get("points") is not None:
        return n(board.get("points"))
    return n(board.get("score"))


def fetch_one_player(
    wos: WOSClient,
    base: dict,
    expected_state: int,
) -> tuple[dict | None, dict | None]:
    fid = base["fid"]

    profile = wos.get(f"/api/v1/players/{fid}")

    current_state = n(profile.get("state"))
    if current_state is not None and int(current_state) != expected_state:
        print(f"  {fid} moved to State {current_state}; skipped")
        return None, None

    try:
        standings_data = wos.get(f"/api/v1/players/{fid}/standings?cached=1")
        boards = standings_map(standings_data)
    except Exception as e:
        print(f"  standings unavailable for {fid}: {e}")
        standings_data = None
        boards = {}

    captured_at = utc_now()
    alliance = norm_alliance(
        (profile.get("alliance") or {}).get("abbr")
        if isinstance(profile.get("alliance"), dict)
        else base.get("alliance")
    ) or base.get("alliance")

    total_power = n(profile.get("power"))
    kills = n(profile.get("kills"))
    furnace = n(profile.get("furnace_level"))

    player_row = {
        "state": expected_state,
        "fid": fid,
        "player": profile.get("name") or base.get("roster_name"),
        "alliance": alliance,
        "furnace_level": furnace if furnace is not None else base.get("roster_furnace"),
        "total_power": total_power if total_power is not None else base.get("roster_power"),
        "kills": kills,
        "active": profile.get("active") is not False,
        "avatar_url": profile.get("avatar_url"),
        "labyrinth_score": n(profile.get("labyrinth_score")),
        "pet_power": board_value(boards.get(16)),
        "island_prosperity": board_value(boards.get(18)),
        "stage_power": board_value(boards.get(27)),
        "star_power": board_value(boards.get(28)),
        "master_total_power": board_value(boards.get(29)),
        "api_updated": profile.get("updated_at"),
        "standings_updated": (
            standings_data.get("searched_at")
            if isinstance(standings_data, dict)
            else None
        ),
        "last_seen": captured_at,
    }

    history_row = {
        "state": expected_state,
        "fid": fid,
        "player": player_row["player"],
        "alliance": alliance,
        "total_power": player_row["total_power"],
        "kills": kills,
        "furnace_level": player_row["furnace_level"],
        "pet_power": player_row["pet_power"],
        "island_prosperity": player_row["island_prosperity"],
        "stage_power": player_row["stage_power"],
        "star_power": player_row["star_power"],
        "master_total_power": player_row["master_total_power"],
        "captured_at": captured_at,
    }

    return player_row, history_row


def checkpoint_path(state_id: int) -> Path:
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    return CHECKPOINT_DIR / f"state_{state_id}.json"


def save_checkpoint(state_id: int, data: dict) -> None:
    p = checkpoint_path(state_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def load_checkpoint(state_id: int) -> dict | None:
    p = checkpoint_path(state_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def clear_checkpoint(state_id: int) -> None:
    p = checkpoint_path(state_id)
    if p.exists():
        p.unlink()


def save_discovery_file(state_id: int, players: list[dict], alliances: list[dict]):
    p = checkpoint_path(state_id)
    payload = {
        "state": state_id,
        "players": players,
        "alliances": alliances,
        "next_index": 0,
        "discovered_at": utc_now(),
    }
    save_checkpoint(state_id, payload)
    return p


def collect(
    wos: WOSClient,
    db: SupabaseREST,
    state_id: int,
    players: list[dict],
    alliances: list[dict],
    start_index: int,
    batch_size: int,
    batch_delay: float,
):
    if alliances:
        db.upsert("enemy_alliances", alliances, "state,alliance")

    total = len(players)
    success = 0
    failed = 0

    for start in range(start_index, total, batch_size):
        end = min(start + batch_size, total)
        batch = players[start:end]
        print(f"\nPlayers {start + 1}-{end} of {total}")

        player_rows = []
        history_rows = []

        for base in batch:
            fid = base["fid"]
            try:
                player_row, history_row = fetch_one_player(wos, base, state_id)
                if player_row:
                    player_rows.append(player_row)
                    history_rows.append(history_row)
                    success += 1
                    print(
                        f"  OK {fid} {player_row.get('player') or ''} "
                        f"{int(player_row.get('total_power') or 0):,}"
                    )
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  ERROR {fid}: {e}")

        # IMPORTANT: save this batch immediately.
        if player_rows:
            db.upsert("enemy_players", player_rows, "state,fid")
        if history_rows:
            db.insert("enemy_player_history", history_rows)

        save_checkpoint(state_id, {
            "state": state_id,
            "players": players,
            "alliances": alliances,
            "next_index": end,
            "updated_at": utc_now(),
        })

        print(f"  SAVED batch. Checkpoint {end}/{total}")

        if end < total:
            time.sleep(batch_delay)

    clear_checkpoint(state_id)
    print(
        f"\nCOMPLETE State {state_id}: "
        f"{success} successful, {failed} failed, {total} discovered."
    )


def update_existing(
    wos: WOSClient,
    db: SupabaseREST,
    state_id: int,
    batch_size: int,
    batch_delay: float,
):
    existing = db.select(
        "enemy_players",
        {
            "select": "fid,player,alliance,total_power,furnace_level",
            "state": f"eq.{state_id}",
            "order": "total_power.desc.nullslast",
        },
    )
    if not existing:
        raise RuntimeError(
            f"No enemy_players rows found for State {state_id}. Run a full scan first."
        )

    players = [{
        "fid": str(r["fid"]),
        "alliance": r.get("alliance"),
        "roster_name": r.get("player"),
        "roster_power": r.get("total_power"),
        "roster_furnace": r.get("furnace_level"),
    } for r in existing]

    collect(
        wos, db, state_id, players, [],
        start_index=0,
        batch_size=batch_size,
        batch_delay=batch_delay,
    )


def fmt_power(v: Any) -> str:
    v = n(v) or 0
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:,.0f}"


def report(db: SupabaseREST, state_id: int):
    players = db.select(
        "enemy_players",
        {
            "select": "*",
            "state": f"eq.{state_id}",
            "order": "total_power.desc.nullslast",
        },
    )
    if not players:
        raise RuntimeError(f"No data stored for State {state_id}")

    alliances: dict[str, list[dict]] = defaultdict(list)
    for p in players:
        alliances[p.get("alliance") or "NO ALLIANCE"].append(p)

    print("\n" + "=" * 72)
    print(f"STATE {state_id} SVS SCOUTING REPORT")
    print("=" * 72)
    print(f"Tracked players : {len(players)}")
    print(f"1B+ players     : {sum((n(p.get('total_power')) or 0) >= 1_000_000_000 for p in players)}")
    print(f"750M+ players   : {sum((n(p.get('total_power')) or 0) >= 750_000_000 for p in players)}")
    print(f"500M+ players   : {sum((n(p.get('total_power')) or 0) >= 500_000_000 for p in players)}")

    print("\nTOP ALLIANCES")
    alliance_stats = []
    for tag, rows in alliances.items():
        powers = sorted(
            [n(r.get("total_power")) or 0 for r in rows],
            reverse=True,
        )
        alliance_stats.append((
            sum(powers),
            tag,
            len(rows),
            sum(powers[:10]),
            sum(powers[:20]),
        ))
    for total, tag, count, top10, top20 in sorted(alliance_stats, reverse=True):
        print(
            f"  {tag:8} members={count:3} "
            f"total={fmt_power(total):>7} "
            f"top10={fmt_power(top10):>7} "
            f"top20={fmt_power(top20):>7}"
        )

    print("\nTOP 25 PLAYERS")
    for i, p in enumerate(players[:25], 1):
        print(
            f"  {i:2}. {str(p.get('player') or '')[:22]:22} "
            f"[{str(p.get('alliance') or '-'):5}] "
            f"{fmt_power(p.get('total_power')):>7} "
            f"kills={fmt_power(p.get('kills')):>7} "
            f"FC={p.get('furnace_level') or '-'}"
        )

    print("\nLIKELY RALLY-LEAD CANDIDATES")
    # Simple scouting heuristic: top power plus developed secondary systems.
    def rally_score(p):
        return (
            (n(p.get("total_power")) or 0)
            + 0.65 * (n(p.get("master_total_power")) or 0)
            + 0.45 * (n(p.get("pet_power")) or 0)
            + 0.25 * (n(p.get("star_power")) or 0)
        )
    for i, p in enumerate(sorted(players, key=rally_score, reverse=True)[:15], 1):
        print(
            f"  {i:2}. {str(p.get('player') or '')[:22]:22} "
            f"[{str(p.get('alliance') or '-'):5}] "
            f"power={fmt_power(p.get('total_power')):>7} "
            f"master={fmt_power(p.get('master_total_power')):>7}"
        )

    print("=" * 72)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing environment variable {name}. "
            f"Set it before running the collector."
        )
    return value


def parse_args():
    p = argparse.ArgumentParser(
        description="Collect enemy-state data from WOSOracle for SvS scouting."
    )
    p.add_argument("state", type=int, nargs="?", default=2337, help="Enemy state number (default: 2337)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true", help="Resume saved checkpoint")
    mode.add_argument("--update", action="store_true", help="Refresh stored players only")
    mode.add_argument("--discover", action="store_true", help="Discover roster only; do not fetch player profiles")
    mode.add_argument("--report", action="store_true", help="Print report from Supabase only")
    p.add_argument("--top-alliances", type=int, default=DEFAULT_TOP_ALLIANCES)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--batch-delay", type=float, default=DEFAULT_BATCH_DELAY)
    return p.parse_args()


def main():
    args = parse_args()

    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_KEY")
    db = SupabaseREST(supabase_url, supabase_key)

    if args.report:
        report(db, args.state)
        return

    token = require_env("WOSORACLE_API_TOKEN")
    wos = WOSClient(token)

    if args.update:
        update_existing(
            wos, db, args.state, args.batch_size, args.batch_delay
        )
        return

    if args.resume:
        cp = load_checkpoint(args.state)
        if not cp:
            raise RuntimeError(
                f"No checkpoint exists for State {args.state}. Run a normal scan first."
            )
        players = cp.get("players") or []
        alliances = cp.get("alliances") or []
        start_index = int(cp.get("next_index") or 0)
        print(f"Resuming State {args.state} at {start_index}/{len(players)}")
        collect(
            wos, db, args.state, players, alliances,
            start_index=start_index,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
        )
        return

    players, alliances = discover_players(
        wos, args.state, args.top_alliances
    )
    cp_path = save_discovery_file(args.state, players, alliances)
    print(f"Discovery checkpoint saved: {cp_path}")

    if args.discover:
        print("Discovery complete. No player profiles were fetched.")
        return

    collect(
        wos, db, args.state, players, alliances,
        start_index=0,
        batch_size=args.batch_size,
        batch_delay=args.batch_delay,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user. Run again with --resume.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        sys.exit(1)
