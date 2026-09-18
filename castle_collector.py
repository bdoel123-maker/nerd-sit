# ============================================================
# CASTLE COLLECTOR
# STATE 2348
#
# Google Sheets
#   Castle Availability
#   roster_data
#       ↓
# WOS Oracle State 2348
#       ↓
# Merge by FID
#       ↓
# Supabase castle_players
# ============================================================

import os
import sys
import time
from io import StringIO
from datetime import datetime, timezone

import pandas as pd
import requests


# ============================================================
# CONFIG
# ============================================================

STATE_ID = 2348

SPREADSHEET_ID = (
    "1eR-gUtOlnvhS8Ixc8tSWjjoH-T21iQqd_VtYYbA_-3s"
)

# Actual GIDs from your spreadsheet
AVAILABILITY_GID = "37539478"
ROSTER_GID = "44400222"

SUPABASE_TABLE = "castle_players"

REQUEST_TIMEOUT = 45
MAX_RETRIES = 4
UPSERT_BATCH_SIZE = 100


# ============================================================
# ENVIRONMENT
# ============================================================

SUPABASE_URL = (
    os.environ.get("SUPABASE_URL", "")
    .strip()
    .rstrip("/")
)

SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY", "")
    .strip()
)

WOSORACLE_API_TOKEN = (
    os.environ.get("WOSORACLE_API_TOKEN", "")
    .strip()
)

WOSORACLE_BASE_URL = (
    os.environ.get(
        "WOSORACLE_BASE_URL",
        "https://wosoracle.com"
    )
    .strip()
    .rstrip("/")
)


# ============================================================
# LOGGING
# ============================================================

def log(message):
    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(
        f"[{timestamp}] {message}",
        flush=True
    )


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# VALIDATE ENVIRONMENT
# ============================================================

def validate_environment():

    missing = []

    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")

    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")

    if not WOSORACLE_API_TOKEN:
        missing.append(
            "WOSORACLE_API_TOKEN"
        )

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    log("Environment variables loaded")


# ============================================================
# VALUE CLEANING
# ============================================================

def clean_string(value):

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
        "#value!"
    }:
        return None

    return value


def clean_player_id(value):

    value = clean_string(value)

    if not value:
        return None

    # Pandas sometimes reads IDs as:
    # 345410747.0
    if value.endswith(".0"):
        value = value[:-2]

    # Remove commas if Sheets formatted it
    value = value.replace(",", "")

    if not value.isdigit():
        return None

    try:
        return int(value)

    except ValueError:
        return None


def clean_integer(value):

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except Exception:
        pass

    if isinstance(value, int):
        return value

    value = str(value)

    value = (
        value
        .replace(",", "")
        .replace(" ", "")
        .strip()
    )

    if not value:
        return None

    try:
        return int(float(value))

    except Exception:
        return None


def yes_no(value):

    value = clean_string(value)

    if not value:
        return False

    return value.casefold() in {
        "yes",
        "y",
        "true",
        "1"
    }


def same_text(a, b):

    a = clean_string(a)
    b = clean_string(b)

    if not a or not b:
        return True

    return (
        a.casefold()
        ==
        b.casefold()
    )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def google_csv_url(gid):

    return (
        "https://docs.google.com/"
        "spreadsheets/d/"
        f"{SPREADSHEET_ID}/export"
        f"?format=csv&gid={gid}"
    )


def download_google_sheet(gid):

    url = google_csv_url(gid)

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            log(
                f"Downloading Google Sheet "
                f"GID {gid}"
            )

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            if not response.text.strip():
                raise RuntimeError(
                    "Google returned an empty CSV"
                )

            return response.text

        except Exception as exc:

            if attempt >= MAX_RETRIES:
                raise

            wait = attempt * 3

            log(
                f"Google Sheet error: {exc}"
            )

            log(
                f"Retrying in {wait}s..."
            )

            time.sleep(wait)


# ============================================================
# CASTLE AVAILABILITY
# ============================================================

def load_castle_availability():

    log(
        "Loading Castle Availability"
    )

    csv_text = download_google_sheet(
        AVAILABILITY_GID
    )

    # Row 3 contains headers.
    #
    # CSV indexing:
    # row 1 = blank
    # row 2 = blank
    # row 3 = header
    #
    # Therefore header=2.
    df = pd.read_csv(
        StringIO(csv_text),
        header=2,
        dtype=str
    )

    log(
        f"Availability rows read: "
        f"{len(df)}"
    )

    required_columns = [
        "Player ID",
        "Alliance",
        "Player Name",
        "Role"
    ]

    for column in required_columns:

        if column not in df.columns:

            raise RuntimeError(
                "Castle Availability is "
                f"missing column: {column}"
            )

    players = {}

    duplicates = 0

    for _, row in df.iterrows():

        fid = clean_player_id(
            row.get("Player ID")
        )

        if not fid:
            continue

        if fid in players:

            duplicates += 1

            log(
                f"DUPLICATE FID | {fid} | "
                f"{clean_string(row.get('Player Name'))}"
            )

        player = {

            "player_id":
                fid,

            "sheet_player_name":
                clean_string(
                    row.get("Player Name")
                ),

            "sheet_alliance":
                clean_string(
                    row.get("Alliance")
                ),

            "role":
                clean_string(
                    row.get("Role")
                ),

            # ----------------------------------------
            # TROOPS
            # ----------------------------------------

            "infantry_level":
                clean_string(
                    row.get("Infa Level")
                ),

            "infantry_helios":
                yes_no(
                    row.get("Infa Helios?")
                ),

            "lancer_level":
                clean_string(
                    row.get("Lancer Level")
                ),

            "lancer_helios":
                yes_no(
                    row.get("Lancer Helios?")
                ),

            "marksman_level":
                clean_string(
                    row.get("MM Level")
                ),

            "marksman_helios":
                yes_no(
                    row.get("MM Helios?")
                ),

            # ----------------------------------------
            # JOINER HEROES
            # ----------------------------------------

            "renee":
                yes_no(
                    row.get("Renee")
                ),

            "hendrik":
                yes_no(
                    row.get("Hendrik")
                ),

            "philly":
                yes_no(
                    row.get("Philly")
                ),

            "gatot":
                yes_no(
                    row.get("Gatot")
                ),

            "wu_ming":
                yes_no(
                    row.get("Wu Ming")
                ),

            "mia":
                yes_no(
                    row.get("Mia")
                ),

            "lynn":
                yes_no(
                    row.get("Lynn")
                ),

            "norah":
                yes_no(
                    row.get("Norah")
                ),

            # ----------------------------------------
            # AVAILABILITY
            # ----------------------------------------

            "available_12_13":
                clean_string(
                    row.get("12-13")
                ),

            "available_13_14":
                clean_string(
                    row.get("13-14")
                ),

            "available_14_15":
                clean_string(
                    row.get("14-15")
                ),

            "available_15_16":
                clean_string(
                    row.get("15-16")
                ),

            "available_16_17":
                clean_string(
                    row.get("16-17")
                ),

            # ----------------------------------------
            # TEAM
            # ----------------------------------------

            "assigned_team":
                clean_string(
                    row.get(
                        "Assigned Team?"
                    )
                ),

            "sheet_updated_at":
                utc_now()
        }

        # Last duplicate wins.
        players[fid] = player

    log(
        f"Unique Castle players: "
        f"{len(players)}"
    )

    log(
        f"Duplicate Castle rows: "
        f"{duplicates}"
    )

    return players


# ============================================================
# ROSTER DATA
# ============================================================

def load_roster_data():

    log("Loading roster_data")

    csv_text = download_google_sheet(
        ROSTER_GID
    )

    df = pd.read_csv(
        StringIO(csv_text),
        header=0,
        dtype=str
    )

    log(
        f"roster_data rows read: "
        f"{len(df)}"
    )

    # --------------------------------------------------------
    # Team columns
    # --------------------------------------------------------

    team_columns = []

    for column in df.columns:

        name = str(column).strip()

        if name.lower().endswith(
            " team"
        ):
            team_columns.append(
                column
            )

    log(
        "Team columns found: "
        + ", ".join(
            str(x)
            for x in team_columns
        )
    )

    # --------------------------------------------------------
    # roster_data has multiple Player ID / Player pairs.
    #
    # Build FID <-> player name map.
    # --------------------------------------------------------

    roster = {}

    columns = list(df.columns)

    for column_index in range(
        len(columns)
    ):

        column_name = str(
            columns[column_index]
        ).strip()

        if not column_name.startswith(
            "Player ID"
        ):
            continue

        if (
            column_index + 1
            >= len(columns)
        ):
            continue

        for _, row in df.iterrows():

            fid = clean_player_id(
                row.iloc[column_index]
            )

            if not fid:
                continue

            player_name = clean_string(
                row.iloc[
                    column_index + 1
                ]
            )

            if fid not in roster:

                roster[fid] = {
                    "player_name":
                        player_name,

                    "team":
                        None
                }

            elif (
                not roster[fid]
                .get("player_name")
                and player_name
            ):

                roster[fid][
                    "player_name"
                ] = player_name

    # --------------------------------------------------------
    # Name -> FID
    # --------------------------------------------------------

    name_to_fid = {}

    for fid, info in roster.items():

        player_name = clean_string(
            info.get(
                "player_name"
            )
        )

        if player_name:

            name_to_fid[
                player_name.casefold()
            ] = fid

    # --------------------------------------------------------
    # Determine team assignment
    # --------------------------------------------------------

    for team_column in team_columns:

        raw_team_name = str(
            team_column
        ).strip()

        team_name = (
            raw_team_name
            .replace(
                " Team",
                ""
            )
            .strip()
        )

        for value in df[
            team_column
        ].tolist():

            player_name = clean_string(
                value
            )

            if not player_name:
                continue

            fid = name_to_fid.get(
                player_name.casefold()
            )

            if not fid:
                continue

            roster[fid][
                "team"
            ] = team_name

    assigned_count = sum(
        1
        for value
        in roster.values()
        if value.get("team")
    )

    log(
        f"Roster FIDs found: "
        f"{len(roster)}"
    )

    log(
        f"Roster team assignments: "
        f"{assigned_count}"
    )

    return roster


# ============================================================
# WOS ORACLE
# ============================================================

def oracle_headers():

    return {

        "Authorization":
            f"Bearer "
            f"{WOSORACLE_API_TOKEN}",

        "Accept":
            "application/json",

        "User-Agent":
            "State2348-CastleCollector"
    }


def oracle_get(path):

    url = (
        WOSORACLE_BASE_URL
        + "/"
        + path.lstrip("/")
    )

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = requests.get(
                url,
                headers=oracle_headers(),
                timeout=REQUEST_TIMEOUT
            )

            # ----------------------------------------
            # SUCCESS
            # ----------------------------------------

            if response.status_code == 200:

                try:
                    return response.json()

                except Exception:

                    raise RuntimeError(
                        "WOS Oracle returned "
                        "invalid JSON"
                    )

            # ----------------------------------------
            # RETRYABLE
            # ----------------------------------------

            if response.status_code in {
                408,
                429,
                500,
                502,
                503,
                504
            }:

                wait = attempt * 5

                log(
                    "WOS Oracle temporary "
                    f"HTTP "
                    f"{response.status_code}"
                )

                log(
                    f"Retrying in {wait}s..."
                )

                time.sleep(wait)

                continue

            # ----------------------------------------
            # PERMANENT
            # ----------------------------------------

            raise RuntimeError(
                "WOS Oracle error | "
                f"HTTP "
                f"{response.status_code} | "
                f"{response.text[:500]}"
            )

        except requests.RequestException as exc:

            if attempt >= MAX_RETRIES:
                raise

            wait = attempt * 5

            log(
                f"WOS request error: "
                f"{exc}"
            )

            log(
                f"Retrying in {wait}s..."
            )

            time.sleep(wait)

    raise RuntimeError(
        "WOS Oracle failed after "
        "maximum retries"
    )


# ============================================================
# EXTRACT STATE PLAYERS
# ============================================================

def extract_fid(player):

    if not isinstance(
        player,
        dict
    ):
        return None

    possibilities = [
        player.get("fid"),
        player.get("player_id"),
        player.get("playerId")
    ]

    for value in possibilities:

        fid = clean_player_id(
            value
        )

        if fid:
            return fid

    return None


def recursively_find_players(data):

    found = []

    if isinstance(data, list):

        for item in data:

            if isinstance(
                item,
                dict
            ):

                fid = extract_fid(
                    item
                )

                if fid:
                    found.append(
                        item
                    )

                found.extend(
                    recursively_find_players(
                        item
                    )
                )

    elif isinstance(
        data,
        dict
    ):

        for value in data.values():

            found.extend(
                recursively_find_players(
                    value
                )
            )

    return found


def get_state_players():

    log(
        "Fetching State "
        f"{STATE_ID} "
        "from WOS Oracle"
    )

    data = oracle_get(
        f"/api/v1/states/{STATE_ID}"
    )

    raw_players = (
        recursively_find_players(
            data
        )
    )

    players = {}

    for player in raw_players:

        fid = extract_fid(
            player
        )

        if not fid:
            continue

        existing = players.get(
            fid
        )

        # If duplicate versions exist,
        # keep the richer object.
        if (
            existing is None
            or len(player)
            > len(existing)
        ):

            players[fid] = player

    log(
        f"State {STATE_ID} "
        f"Oracle players found: "
        f"{len(players)}"
    )

    # IMPORTANT:
    #
    # Never continue with zero players.
    # Otherwise an Oracle/API problem could
    # cause us to treat every Castle player
    # as transferred out.
    if not players:

        raise RuntimeError(
            "WOS Oracle returned ZERO "
            f"players for State {STATE_ID}. "
            "Sync aborted for safety."
        )

    return players


# ============================================================
# WOS FIELD HELPERS
# ============================================================

def oracle_player_name(player):

    if not player:
        return None

    for key in [
        "player_name",
        "name",
        "nickname"
    ]:

        value = clean_string(
            player.get(key)
        )

        if value:
            return value

    return None


def oracle_alliance(player):

    if not player:
        return None

    possibilities = [

        player.get("alliance"),

        player.get(
            "alliance_name"
        ),

        player.get(
            "allianceName"
        ),

        player.get(
            "alliance_abbreviation"
        )
    ]

    for value in possibilities:

        if isinstance(
            value,
            dict
        ):

            for key in [
                "name",
                "abbreviation",
                "tag"
            ]:

                result = clean_string(
                    value.get(key)
                )

                if result:
                    return result

        else:

            result = clean_string(
                value
            )

            if result:
                return result

    return None


def oracle_furnace_level(player):

    if not player:
        return None

    for key in [
        "furnace_level",
        "furnaceLevel",
        "furnace"
    ]:

        value = clean_integer(
            player.get(key)
        )

        if value is not None:
            return value

    return None


def oracle_total_power(player):

    if not player:
        return None

    for key in [
        "total_power",
        "totalPower",
        "power"
    ]:

        value = clean_integer(
            player.get(key)
        )

        if value is not None:
            return value

    return None


# ============================================================
# MERGE DATA
# ============================================================

def merge_castle_data(
    availability,
    roster,
    state_players
):

    log(
        "Comparing Castle registrations "
        "against State 2348"
    )

    output = []

    missing_from_state = []

    name_changes = []
    alliance_changes = []

    checked_at = utc_now()

    for fid, sheet_player in (
        availability.items()
    ):

        oracle_player = (
            state_players.get(fid)
        )

        # ----------------------------------------------------
        # PLAYER NOT FOUND IN CURRENT STATE DATA
        #
        # Do NOT write them into the current castle table.
        # ----------------------------------------------------

        if oracle_player is None:

            missing_from_state.append(
                {
                    "fid": fid,
                    "name":
                        sheet_player.get(
                            "sheet_player_name"
                        )
                }
            )

            log(
                "NOT IN CURRENT STATE DATA | "
                f"{fid} | "
                f"{sheet_player.get('sheet_player_name')}"
            )

            continue

        # ----------------------------------------------------
        # START WITH SHEET DATA
        # ----------------------------------------------------

        record = dict(
            sheet_player
        )

        # ----------------------------------------------------
        # ROSTER DATA
        # ----------------------------------------------------

        roster_info = roster.get(
            fid,
            {}
        )

        record[
            "roster_team"
        ] = clean_string(
            roster_info.get(
                "team"
            )
        )

        # ----------------------------------------------------
        # CURRENT ORACLE DATA
        # ----------------------------------------------------

        current_name = (
            oracle_player_name(
                oracle_player
            )
        )

        current_alliance = (
            oracle_alliance(
                oracle_player
            )
        )

        furnace_level = (
            oracle_furnace_level(
                oracle_player
            )
        )

        total_power = (
            oracle_total_power(
                oracle_player
            )
        )

        record[
            "player_name"
        ] = (
            current_name
            or record.get(
                "sheet_player_name"
            )
        )

        record[
            "alliance"
        ] = (
            current_alliance
            or record.get(
                "sheet_alliance"
            )
        )

        record[
            "furnace_level"
        ] = furnace_level

        record[
            "total_power"
        ] = total_power

        # ----------------------------------------------------
        # NAME CHANGE
        # ----------------------------------------------------

        name_changed = False

        if (
            current_name
            and record.get(
                "sheet_player_name"
            )
        ):

            name_changed = (
                not same_text(
                    current_name,
                    record[
                        "sheet_player_name"
                    ]
                )
            )

        record[
            "name_changed"
        ] = name_changed

        if name_changed:

            name_changes.append(
                (
                    fid,
                    record[
                        "sheet_player_name"
                    ],
                    current_name
                )
            )

        # ----------------------------------------------------
        # ALLIANCE CHANGE
        # ----------------------------------------------------

        alliance_changed = False

        if (
            current_alliance
            and record.get(
                "sheet_alliance"
            )
        ):

            alliance_changed = (
                not same_text(
                    current_alliance,
                    record[
                        "sheet_alliance"
                    ]
                )
            )

        record[
            "alliance_changed"
        ] = alliance_changed

        if alliance_changed:

            alliance_changes.append(
                (
                    fid,
                    record[
                        "sheet_alliance"
                    ],
                    current_alliance
                )
            )

        # ----------------------------------------------------
        # NEEDS TEAM
        # ----------------------------------------------------

        assigned_team = clean_string(
            record.get(
                "assigned_team"
            )
        )

        roster_team = clean_string(
            record.get(
                "roster_team"
            )
        )

        role = clean_string(
            record.get(
                "role"
            )
        )

        role_is_lead = (
            role is not None
            and role.casefold()
            == "lead"
        )

        sheet_says_needs_team = (
            assigned_team is None
            or assigned_team.casefold()
            == "needs team"
        )

        record[
            "needs_team"
        ] = (
            not role_is_lead
            and sheet_says_needs_team
            and roster_team is None
        )

        # ----------------------------------------------------
        # TIMESTAMPS
        # ----------------------------------------------------

        record[
            "oracle_updated_at"
        ] = checked_at

        record[
            "database_updated_at"
        ] = checked_at

        output.append(
            record
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    log(
        "--------------------------------"
    )

    log(
        f"Registered players: "
        f"{len(availability)}"
    )

    log(
        f"Matched to State 2348: "
        f"{len(output)}"
    )

    log(
        f"Not found in State 2348: "
        f"{len(missing_from_state)}"
    )

    log(
        f"Name changes: "
        f"{len(name_changes)}"
    )

    log(
        f"Alliance changes: "
        f"{len(alliance_changes)}"
    )

    return output


# ============================================================
# SUPABASE
# ============================================================

def supabase_headers(
    prefer=None
):

    headers = {

        "apikey":
            SUPABASE_KEY,

        "Authorization":
            f"Bearer {SUPABASE_KEY}",

        "Content-Type":
            "application/json"
    }

    if prefer:

        headers[
            "Prefer"
        ] = prefer

    return headers


def supabase_request(
    method,
    url,
    **kwargs
):

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = requests.request(
                method,
                url,
                timeout=REQUEST_TIMEOUT,
                **kwargs
            )

            if response.status_code in {
                200,
                201,
                204
            }:

                return response

            if response.status_code in {
                408,
                429,
                500,
                502,
                503,
                504
            }:

                wait = attempt * 5

                log(
                    "Supabase temporary "
                    f"HTTP "
                    f"{response.status_code}"
                )

                time.sleep(wait)

                continue

            raise RuntimeError(
                "SUPABASE ERROR | "
                f"HTTP "
                f"{response.status_code}\n"
                f"{response.text}"
            )

        except requests.RequestException:

            if attempt >= MAX_RETRIES:
                raise

            time.sleep(
                attempt * 5
            )

    raise RuntimeError(
        "Supabase request failed"
    )


# ============================================================
# UPSERT
# ============================================================

def upsert_castle_players(
    players
):

    if not players:

        raise RuntimeError(
            "No Castle players to upsert"
        )

    log(
        f"Upserting {len(players)} "
        f"players into "
        f"{SUPABASE_TABLE}"
    )

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{SUPABASE_TABLE}"
        "?on_conflict=player_id"
    )

    total_written = 0

    for start in range(
        0,
        len(players),
        UPSERT_BATCH_SIZE
    ):

        batch = players[
            start:
            start + UPSERT_BATCH_SIZE
        ]

        supabase_request(

            "POST",

            url,

            headers=supabase_headers(
                "resolution=merge-duplicates,"
                "return=minimal"
            ),

            json=batch
        )

        total_written += len(
            batch
        )

        log(
            f"Supabase upsert: "
            f"{total_written}/"
            f"{len(players)}"
        )

    return total_written


# ============================================================
# REMOVE STALE DATABASE PLAYERS
# ============================================================

def get_existing_castle_fids():

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{SUPABASE_TABLE}"
        "?select=player_id"
    )

    response = supabase_request(

        "GET",

        url,

        headers=supabase_headers()
    )

    data = response.json()

    fids = set()

    for row in data:

        fid = clean_player_id(
            row.get(
                "player_id"
            )
        )

        if fid:
            fids.add(fid)

    return fids


def delete_stale_players(
    current_players
):

    current_fids = {
        int(
            player["player_id"]
        )
        for player
        in current_players
    }

    existing_fids = (
        get_existing_castle_fids()
    )

    stale_fids = (
        existing_fids
        -
        current_fids
    )

    if not stale_fids:

        log(
            "No stale Castle records"
        )

        return 0

    log(
        f"Stale records found: "
        f"{len(stale_fids)}"
    )

    deleted = 0

    for fid in stale_fids:

        url = (
            f"{SUPABASE_URL}"
            f"/rest/v1/"
            f"{SUPABASE_TABLE}"
            f"?player_id=eq.{fid}"
        )

        supabase_request(

            "DELETE",

            url,

            headers=supabase_headers(
                "return=minimal"
            )
        )

        log(
            f"STALE DELETE | {fid}"
        )

        deleted += 1

    return deleted


# ============================================================
# DISPLAY SUMMARY
# ============================================================

def display_summary(
    players
):

    by_alliance = {}
    by_team = {}

    needs_team = []

    for player in players:

        alliance = (
            clean_string(
                player.get(
                    "alliance"
                )
            )
            or "Unknown"
        )

        by_alliance[
            alliance
        ] = (
            by_alliance.get(
                alliance,
                0
            )
            + 1
        )

        team = (
            clean_string(
                player.get(
                    "roster_team"
                )
            )
            or clean_string(
                player.get(
                    "assigned_team"
                )
            )
            or "Unassigned"
        )

        by_team[
            team
        ] = (
            by_team.get(
                team,
                0
            )
            + 1
        )

        if player.get(
            "needs_team"
        ):

            needs_team.append(
                player
            )

    log("")
    log("========== ALLIANCES ==========")

    for alliance in sorted(
        by_alliance
    ):

        log(
            f"{alliance}: "
            f"{by_alliance[alliance]}"
        )

    log("")
    log("============ TEAMS ============")

    for team in sorted(
        by_team
    ):

        log(
            f"{team}: "
            f"{by_team[team]}"
        )

    log("")
    log("========== NEEDS TEAM =========")

    for player in needs_team:

        log(
            f"{player['player_id']} | "
            f"{player.get('player_name')} | "
            f"{player.get('alliance')}"
        )

    log(
        f"Total needing team: "
        f"{len(needs_team)}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "========================================"
    )

    log(
        "STATE 2348 CASTLE COLLECTOR"
    )

    log(
        "========================================"
    )

    # --------------------------------------------------------
    # Validate secrets
    # --------------------------------------------------------

    validate_environment()

    # --------------------------------------------------------
    # Google Sheet
    # --------------------------------------------------------

    availability = (
        load_castle_availability()
    )

    roster = (
        load_roster_data()
    )

    if not availability:

        raise RuntimeError(
            "Castle Availability returned "
            "zero valid players. "
            "Aborting for safety."
        )

    # --------------------------------------------------------
    # WOS Oracle
    # --------------------------------------------------------

    state_players = (
        get_state_players()
    )

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------

    castle_players = (
        merge_castle_data(
            availability,
            roster,
            state_players
        )
    )

    if not castle_players:

        raise RuntimeError(
            "ZERO Castle players matched "
            "State 2348. "
            "Aborting for safety."
        )

    # Extra safety:
    #
    # If almost everybody suddenly disappears,
    # don't destroy the Supabase table.
    match_ratio = (
        len(castle_players)
        /
        len(availability)
    )

    log(
        f"State match rate: "
        f"{match_ratio:.1%}"
    )

    if match_ratio < 0.50:

        raise RuntimeError(
            "Less than 50% of registered "
            "players matched State 2348. "
            "This probably indicates an "
            "Oracle/API parsing problem. "
            "Database update aborted."
        )

    # --------------------------------------------------------
    # Display what we're about to write
    # --------------------------------------------------------

    display_summary(
        castle_players
    )

    # --------------------------------------------------------
    # Supabase upsert
    # --------------------------------------------------------

    written = (
        upsert_castle_players(
            castle_players
        )
    )

    # --------------------------------------------------------
    # Remove stale records
    #
    # Only happens AFTER:
    #
    # Google Sheet succeeded
    # Oracle succeeded
    # match safety succeeded
    # Supabase upsert succeeded
    # --------------------------------------------------------

    deleted = (
        delete_stale_players(
            castle_players
        )
    )

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    log("")
    log(
        "========================================"
    )

    log(
        "CASTLE SYNC COMPLETE"
    )

    log(
        f"Players written: {written}"
    )

    log(
        f"Stale records removed: {deleted}"
    )

    log(
        "========================================"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        log("")
        log(
            "========================================"
        )

        log(
            "CASTLE SYNC FAILED"
        )

        log(
            "========================================"
        )

        log(
            str(exc)
        )

        raise
