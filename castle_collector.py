import os
from io import StringIO
from datetime import datetime, timezone

import pandas as pd
import requests

# Use the WORKING state discovery from main.py
from main import discover_players


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = "1eR-gUtOlnvhS8Ixc8tSWjjoH-T21iQqd_VtYYbA_-3s"

AVAILABILITY_GID = "37539478"
ROSTER_GID = "44400222"

SUPABASE_TABLE = "castle_players"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

REQUEST_TIMEOUT = 45
BATCH_SIZE = 100


if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL not found")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY not found")


# ============================================================
# HELPERS
# ============================================================

def log(message=""):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True,
    )


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    value = str(value).strip()

    if not value:
        return None

    if value.lower() in {
        "nan",
        "none",
        "null",
        "#n/a",
        "#ref!",
        "#value!",
    }:
        return None

    return value


def fid_value(value):
    value = clean(value)

    if not value:
        return None

    value = value.replace(",", "")

    if value.endswith(".0"):
        value = value[:-2]

    if not value.isdigit():
        return None

    return int(value)


def integer(value):
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def boolean(value):
    value = clean(value)

    return bool(
        value
        and value.casefold() in {
            "yes",
            "y",
            "true",
            "1",
        }
    )


def same(a, b):
    a = clean(a)
    b = clean(b)

    if not a or not b:
        return True

    return a.casefold() == b.casefold()


# ============================================================
# GOOGLE SHEETS
# ============================================================

def read_sheet(gid, header=0):
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/export"
        f"?format=csv&gid={gid}"
    )

    log(f"Downloading Google Sheet GID {gid}")

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return pd.read_csv(
        StringIO(response.text),
        header=header,
        dtype=str,
    )


# ============================================================
# CASTLE AVAILABILITY
# ============================================================

def load_availability():
    log("Loading Castle Availability")

    # Actual headers are row 3
    df = read_sheet(
        AVAILABILITY_GID,
        header=2,
    )

    log(f"Availability rows read: {len(df)}")

    players = {}
    duplicates = 0

    for _, row in df.iterrows():
        fid = fid_value(
            row.get("Player ID")
        )

        if not fid:
            continue

        if fid in players:
            duplicates += 1

            log(
                f"DUPLICATE FID | {fid} | "
                f"{clean(row.get('Player Name'))}"
            )

        players[fid] = {
            "player_id": fid,

            "sheet_player_name":
                clean(row.get("Player Name")),

            "sheet_alliance":
                clean(row.get("Alliance")),

            "role":
                clean(row.get("Role")),

            "infantry_level":
                clean(row.get("Infa Level")),

            "infantry_helios":
                boolean(row.get("Infa Helios?")),

            "lancer_level":
                clean(row.get("Lancer Level")),

            "lancer_helios":
                boolean(row.get("Lancer Helios?")),

            "marksman_level":
                clean(row.get("MM Level")),

            "marksman_helios":
                boolean(row.get("MM Helios?")),

            "renee":
                boolean(row.get("Renee")),

            "hendrik":
                boolean(row.get("Hendrik")),

            "philly":
                boolean(row.get("Philly")),

            "gatot":
                boolean(row.get("Gatot")),

            "wu_ming":
                boolean(row.get("Wu Ming")),

            "mia":
                boolean(row.get("Mia")),

            "lynn":
                boolean(row.get("Lynn")),

            "norah":
                boolean(row.get("Norah")),

            "available_12_13":
                clean(row.get("12-13")),

            "available_13_14":
                clean(row.get("13-14")),

            "available_14_15":
                clean(row.get("14-15")),

            "available_15_16":
                clean(row.get("15-16")),

            "available_16_17":
                clean(row.get("16-17")),

            "assigned_team":
                clean(row.get("Assigned Team?")),

            "sheet_updated_at":
                now(),
        }

    log(f"Unique Castle players: {len(players)}")
    log(f"Duplicate Castle rows: {duplicates}")

    return players


# ============================================================
# ROSTER DATA
# ============================================================

def load_roster():
    log("Loading roster_data")

    df = read_sheet(
        ROSTER_GID,
        header=0,
    )

    log(f"roster_data rows read: {len(df)}")

    roster = {}
    columns = list(df.columns)

    # --------------------------------------------------------
    # Collect every Player ID / Player Name pair
    #
    # Pandas renames duplicate columns:
    # Player ID
    # Player ID.1
    # Player ID.2
    # --------------------------------------------------------

    for index, column in enumerate(columns):
        if not str(column).strip().startswith("Player ID"):
            continue

        if index + 1 >= len(columns):
            continue

        for _, row in df.iterrows():
            fid = fid_value(
                row.iloc[index]
            )

            if not fid:
                continue

            name = clean(
                row.iloc[index + 1]
            )

            if fid not in roster:
                roster[fid] = {
                    "name": name,
                    "team": None,
                }

    # --------------------------------------------------------
    # Name -> FID
    # --------------------------------------------------------

    name_to_fid = {}

    for fid, player in roster.items():
        name = clean(player["name"])

        if name:
            name_to_fid[
                name.casefold()
            ] = fid

    # --------------------------------------------------------
    # Team columns
    # --------------------------------------------------------

    team_columns = [
        column
        for column in df.columns
        if str(column)
        .strip()
        .lower()
        .endswith(" team")
    ]

    log(
        "Team columns found: "
        + ", ".join(
            str(x)
            for x in team_columns
        )
    )

    # --------------------------------------------------------
    # Map names in each team column back to FID
    # --------------------------------------------------------

    for column in team_columns:
        team = (
            str(column)
            .replace(" Team", "")
            .strip()
        )

        for value in df[column]:
            name = clean(value)

            if not name:
                continue

            fid = name_to_fid.get(
                name.casefold()
            )

            if fid:
                roster[fid]["team"] = team

    assigned = sum(
        1
        for player in roster.values()
        if player["team"]
    )

    log(f"Roster FIDs found: {len(roster)}")
    log(f"Roster team assignments: {assigned}")

    return roster


# ============================================================
# STATE 2348
#
# main.py already knows how to:
#
# State
#   -> alliances
#   -> target alliances
#   -> alliance members
# ============================================================

def load_state_players():
    log("")
    log("========================================")
    log("USING MAIN.PY STATE DISCOVERY")
    log("========================================")

    discovered = discover_players()

    if not discovered:
        raise RuntimeError(
            "discover_players() returned zero players"
        )

    players = {}

    for player in discovered:
        fid = fid_value(
            player.get("fid")
        )

        if not fid:
            continue

        players[fid] = {
            "player_id": fid,
            "name": clean(
                player.get("name")
            ),
            "alliance": clean(
                player.get("alliance")
            ),
            "power": integer(
                player.get("power")
            ),
            "furnace_level": integer(
                player.get("furnace_level")
            ),
        }

    log(
        f"Current target-alliance players: "
        f"{len(players)}"
    )

    if not players:
        raise RuntimeError(
            "State player map is empty"
        )

    return players


# ============================================================
# MERGE
# ============================================================

def merge_data(
    availability,
    roster,
    state_players,
):
    log("")
    log("========================================")
    log("COMPARING CASTLE REGISTRATIONS")
    log("========================================")

    rows = []
    missing = []

    timestamp = now()

    for fid, sheet in availability.items():
        current = state_players.get(fid)

        # ----------------------------------------------------
        # Player isn't currently in one of our State 2348
        # target alliances.
        # ----------------------------------------------------

        if not current:
            missing.append(fid)

            log(
                f"NOT FOUND | {fid} | "
                f"{sheet['sheet_player_name']}"
            )

            continue

        row = dict(sheet)

        roster_player = roster.get(
            fid,
            {}
        )

        row["roster_team"] = clean(
            roster_player.get("team")
        )

        # ----------------------------------------------------
        # Current WOS data
        # ----------------------------------------------------

        row["player_name"] = (
            current["name"]
            or row["sheet_player_name"]
        )

        row["alliance"] = (
            current["alliance"]
            or row["sheet_alliance"]
        )

        row["furnace_level"] = (
            current["furnace_level"]
        )

        row["total_power"] = (
            current["power"]
        )

        # ----------------------------------------------------
        # Changes
        # ----------------------------------------------------

        row["name_changed"] = (
            bool(current["name"])
            and not same(
                current["name"],
                row["sheet_player_name"],
            )
        )

        row["alliance_changed"] = (
            bool(current["alliance"])
            and not same(
                current["alliance"],
                row["sheet_alliance"],
            )
        )

        # ----------------------------------------------------
        # Team status
        # ----------------------------------------------------

        role = clean(
            row["role"]
        )

        assigned = clean(
            row["assigned_team"]
        )

        roster_team = clean(
            row["roster_team"]
        )

        is_lead = (
            role
            and role.casefold() == "lead"
        )

        sheet_needs_team = (
            not assigned
            or assigned.casefold()
            == "needs team"
        )

        row["needs_team"] = bool(
            not is_lead
            and sheet_needs_team
            and not roster_team
        )

        row["oracle_updated_at"] = (
            timestamp
        )

        row["database_updated_at"] = (
            timestamp
        )

        rows.append(row)

    # --------------------------------------------------------
    # Safety
    # --------------------------------------------------------

    match_rate = (
        len(rows)
        / len(availability)
        if availability
        else 0
    )

    log("")
    log("========================================")
    log("COMPARISON SUMMARY")
    log("========================================")

    log(
        f"Castle registrations: "
        f"{len(availability)}"
    )

    log(
        f"Matched: {len(rows)}"
    )

    log(
        f"Not found: {len(missing)}"
    )

    log(
        f"Match rate: {match_rate:.1%}"
    )

    if match_rate < 0.50:
        raise RuntimeError(
            "Less than 50% of Castle players "
            "matched current State data. "
            "Supabase update aborted."
        )

    return rows


# ============================================================
# SUPABASE UPSERT
# ============================================================

def upsert_players(rows):
    if not rows:
        raise RuntimeError(
            "No Castle rows to write"
        )

    endpoint = (
        f"{SUPABASE_URL}"
        f"/rest/v1/{SUPABASE_TABLE}"
        f"?on_conflict=player_id"
    )

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization":
            f"Bearer {SUPABASE_KEY}",
        "Content-Type":
            "application/json",
        "Prefer":
            "resolution=merge-duplicates,"
            "return=minimal",
    }

    total = 0

    for start in range(
        0,
        len(rows),
        BATCH_SIZE,
    ):
        batch = rows[
            start:
            start + BATCH_SIZE
        ]

        response = requests.post(
            endpoint,
            headers=headers,
            json=batch,
            timeout=60,
        )

        if not (
            200
            <= response.status_code
            < 300
        ):
            raise RuntimeError(
                "SUPABASE ERROR | "
                f"HTTP {response.status_code}\n"
                f"{response.text}"
            )

        total += len(batch)

        log(
            f"Supabase: "
            f"{total}/{len(rows)} saved"
        )

    return total


# ============================================================
# DELETE STALE CASTLE RECORDS
# ============================================================

def delete_stale(current_rows):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization":
            f"Bearer {SUPABASE_KEY}",
    }

    endpoint = (
        f"{SUPABASE_URL}"
        f"/rest/v1/{SUPABASE_TABLE}"
        f"?select=player_id"
    )

    response = requests.get(
        endpoint,
        headers=headers,
        timeout=60,
    )

    if response.status_code != 200:
        raise RuntimeError(
            "Could not read existing "
            "castle_players records | "
            f"HTTP {response.status_code} | "
            f"{response.text}"
        )

    existing = {
        fid_value(row.get("player_id"))
        for row in response.json()
        if fid_value(
            row.get("player_id")
        )
    }

    current = {
        row["player_id"]
        for row in current_rows
    }

    stale = existing - current

    if not stale:
        log(
            "No stale Castle records."
        )
        return 0

    log(
        f"Stale records: {len(stale)}"
    )

    deleted = 0

    for fid in stale:
        endpoint = (
            f"{SUPABASE_URL}"
            f"/rest/v1/{SUPABASE_TABLE}"
            f"?player_id=eq.{fid}"
        )

        response = requests.delete(
            endpoint,
            headers=headers,
            timeout=60,
        )

        if not (
            200
            <= response.status_code
            < 300
        ):
            raise RuntimeError(
                f"Failed deleting {fid} | "
                f"HTTP {response.status_code} | "
                f"{response.text}"
            )

        log(
            f"STALE DELETE | {fid}"
        )

        deleted += 1

    return deleted


# ============================================================
# MAIN
# ============================================================

def main():
    log("========================================")
    log("STATE 2348 CASTLE COLLECTOR")
    log("========================================")

    # Google Sheets
    availability = load_availability()
    roster = load_roster()

    if not availability:
        raise RuntimeError(
            "No Castle registrations found"
        )

    # WOS Oracle via existing main.py
    state_players = (
        load_state_players()
    )

    # Merge
    rows = merge_data(
        availability,
        roster,
        state_players,
    )

    # Write first
    written = upsert_players(
        rows
    )

    # Only delete stale rows AFTER the entire
    # discovery/merge/upsert succeeds.
    deleted = delete_stale(
        rows
    )

    log("")
    log("========================================")
    log("CASTLE SYNC COMPLETE")
    log("========================================")
    log(
        f"Players written: {written}"
    )
    log(
        f"Stale records deleted: {deleted}"
    )


if __name__ == "__main__":
    main()
