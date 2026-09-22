import os
import time
import requests

from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "WOS.env"

# Local PC uses WOS.env.
# GitHub Actions supplies environment variables through Secrets.
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


WOS_TOKEN = os.getenv("WOSORACLE_API_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not WOS_TOKEN:
    raise ValueError(
        "WOSORACLE_API_TOKEN not found"
    )

if not SUPABASE_URL:
    raise ValueError(
        "SUPABASE_URL not found"
    )

if not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_KEY not found"
    )


SUPABASE_URL = SUPABASE_URL.rstrip("/")


# ============================================================
# CONFIGURATION
# ============================================================

STATE_ID = 2337


# IMPORTANT:
# Alliance tags are CASE-SENSITIVE.
#
# ONF = main ONF
# onf = ONF farm
# llc = lowercase LLC alliance

TARGET_ALLIANCES = {
    "MOK",
}


ALLIANCE_ORDER = {
    "MOK": 1,
}


PLAYER_BATCH_SIZE = 8

BATCH_DELAY_SECONDS = 2

MAX_RETRIES = 3

SUPABASE_BATCH_SIZE = 100


# ============================================================
# STANDINGS BOARD TYPES
# ============================================================

# Personal Power
BOARD_PERSONAL_POWER = 3

# Total Pet Power
BOARD_PET_POWER = 16

# Island Prosperity
BOARD_ISLAND_PROSPERITY = 18

# Stage Leaderboard
# We display this as Hero Power
BOARD_HERO_POWER = 27

# Star Leaderboard
# We display this as Hero Gear Power
BOARD_HERO_GEAR_POWER = 28

# Master Total Power
# We display this as Expert Power
BOARD_EXPERT_POWER = 29


# ============================================================
# HEADERS
# ============================================================

WOS_HEADERS = {
    "Authorization": f"Bearer {WOS_TOKEN}",
    "Accept": "application/json",
}


SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}


# ============================================================
# GENERIC WOS ORACLE GET
# ============================================================

def oracle_get(path, max_retries=MAX_RETRIES):

    url = f"https://wosoracle.com{path}"

    for attempt in range(1, max_retries + 2):

        try:

            response = requests.get(
                url,
                headers=WOS_HEADERS,
                timeout=30,
            )

        except requests.RequestException as error:

            print(
                f"NETWORK ERROR | {path} | {error}"
            )

            if attempt > max_retries:
                return None

            wait_time = attempt * 5

            print(
                f"Retrying in {wait_time}s..."
            )

            time.sleep(wait_time)

            continue


        # ====================================================
        # SUCCESS
        # ====================================================

        if response.status_code == 200:

            try:

                return response.json()

            except ValueError:

                print(
                    f"INVALID JSON | {path}"
                )

                return None


        # ====================================================
        # RETRYABLE ERRORS
        # ====================================================

        if (
            response.status_code == 429
            or response.status_code == 408
            or response.status_code == 425
            or response.status_code >= 500
        ):

            if attempt > max_retries:

                print(
                    f"GAVE UP | {path} | "
                    f"HTTP {response.status_code}"
                )

                return None


            retry_after = response.headers.get(
                "Retry-After"
            )

            if retry_after:

                try:
                    wait_time = int(retry_after)

                except ValueError:
                    wait_time = attempt * 5

            else:
                wait_time = attempt * 5


            print(
                f"HTTP {response.status_code} "
                f"| {path} "
                f"| retrying in {wait_time}s..."
            )

            time.sleep(wait_time)

            continue


        # ====================================================
        # NON-RETRYABLE ERROR
        # ====================================================

        print(
            f"PERMANENT ERROR | {path} | "
            f"HTTP {response.status_code}"
        )

        print(response.text)

        return None


    return None


# ============================================================
# WOS ENDPOINT HELPERS
# ============================================================

def get_state(state_id):

    return oracle_get(
        f"/api/v1/states/{state_id}"
    )


def get_alliance(alliance_id):

    return oracle_get(
        f"/api/v1/alliances/{alliance_id}"
    )


def get_player(fid):

    return oracle_get(
        f"/api/v1/players/{fid}"
    )


def get_standings(fid):

    path = f"/api/players/{fid}/standings"
    url = f"https://wosoracle.com{path}"

    for attempt in range(1, MAX_RETRIES + 2):

        try:
            response = requests.get(
                url,
                headers=WOS_HEADERS,
                timeout=30,
            )

        except requests.RequestException as error:
            print(
                f"STANDINGS NETWORK ERROR | {fid} | {error}"
            )

            if attempt > MAX_RETRIES:
                return None

            wait_time = attempt * 5
            print(f"Standings retry in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                print(f"STANDINGS INVALID JSON | {fid}")
                return None

        if response.status_code == 401:
            print(
                f"STANDINGS AUTH REQUIRED | {fid} | "
                "preserving existing standings"
            )
            return None

        if (
            response.status_code == 429
            or response.status_code == 408
            or response.status_code == 425
            or response.status_code >= 500
        ):
            if attempt > MAX_RETRIES:
                print(
                    f"STANDINGS GAVE UP | {fid} | "
                    f"HTTP {response.status_code} | "
                    "preserving existing standings"
                )
                return None

            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    wait_time = int(retry_after)
                except ValueError:
                    wait_time = attempt * 5
            else:
                wait_time = attempt * 5

            print(
                f"STANDINGS HTTP {response.status_code} | {fid} | "
                f"retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
            continue

        print(
            f"STANDINGS UNAVAILABLE | {fid} | "
            f"HTTP {response.status_code} | "
            "preserving existing standings"
        )
        return None

    return None


# ============================================================
# UNIX TIMESTAMP -> ISO TIMESTAMP
# ============================================================

def unix_to_iso(timestamp):

    if timestamp is None:
        return None

    try:

        return datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc,
        ).isoformat()

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):

        return None


# ============================================================
# EXTRACT STANDINGS DATA
# ============================================================

def extract_standings_data(standings_data):

    result = {
        "personal_power": None,
        "pet_power": None,
        "island_prosperity": None,
        "hero_power": None,
        "hero_gear_power": None,
        "expert_power": None,
        "standings_updated": None,
    }


    if not standings_data:
        return result


    standings = standings_data.get(
        "standings",
        [],
    )


    latest_timestamp = None


    for board in standings:

        board_type = board.get(
            "board_type"
        )

        score = board.get(
            "score"
        )

        update_ts = board.get(
            "update_ts"
        )


        # ----------------------------------------------------
        # PERSONAL POWER
        # ----------------------------------------------------

        if board_type == BOARD_PERSONAL_POWER:

            result["personal_power"] = score


        # ----------------------------------------------------
        # PET POWER
        # ----------------------------------------------------

        elif board_type == BOARD_PET_POWER:

            result["pet_power"] = score


        # ----------------------------------------------------
        # ISLAND PROSPERITY
        # ----------------------------------------------------

        elif board_type == BOARD_ISLAND_PROSPERITY:

            result["island_prosperity"] = score


        # ----------------------------------------------------
        # HERO POWER
        # Stage Leaderboard - Board 27
        # ----------------------------------------------------

        elif board_type == BOARD_HERO_POWER:

            result["hero_power"] = score


        # ----------------------------------------------------
        # HERO GEAR POWER
        # Star Leaderboard - Board 28
        # ----------------------------------------------------

        elif board_type == BOARD_HERO_GEAR_POWER:

            result["hero_gear_power"] = score


        # ----------------------------------------------------
        # EXPERT POWER
        # Master Total Power - Board 29
        # ----------------------------------------------------

        elif board_type == BOARD_EXPERT_POWER:

            result["expert_power"] = score


        # ----------------------------------------------------
        # NEWEST STANDINGS UPDATE
        # ----------------------------------------------------

        if update_ts is not None:

            try:

                update_ts_int = int(update_ts)

                if (
                    latest_timestamp is None
                    or update_ts_int > latest_timestamp
                ):

                    latest_timestamp = update_ts_int

            except (
                ValueError,
                TypeError,
            ):

                pass


    result["standings_updated"] = unix_to_iso(
        latest_timestamp
    )


    return result


# ============================================================
# DISCOVER TARGET ALLIANCES
# ============================================================

def find_target_alliances(alliances):

    target_alliances = []


    for alliance in alliances:

        # DO NOT uppercase this.
        #
        # ONF and onf are intentionally separate alliances.

        abbreviation = str(
            alliance.get(
                "abbr",
                "",
            )
        ).strip()


        if abbreviation not in TARGET_ALLIANCES:
            continue


        target_alliances.append(
            alliance
        )


    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    target_alliances.sort(

        key=lambda alliance:

            ALLIANCE_ORDER.get(

                str(
                    alliance.get(
                        "abbr",
                        "",
                    )
                ).strip(),

                999,

            )

    )


    return target_alliances


# ============================================================
# DISCOVER PLAYERS
# ============================================================

def discover_players():

    print()
    print(
        "========================================"
    )
    print(
        f"        SCANNING STATE {STATE_ID}"
    )
    print(
        "========================================"
    )
    print()


    # ========================================================
    # LOAD STATE
    # ========================================================

    state = get_state(
        STATE_ID
    )


    if not state:

        print(
            "Could not load state."
        )

        return []


    alliances = state.get(
        "alliances",
        [],
    )


    print(
        f"State returned "
        f"{len(alliances)} alliances."
    )


    # ========================================================
    # FIND TARGET ALLIANCES
    # ========================================================

    target_alliances = (
        find_target_alliances(
            alliances
        )
    )


    print()
    print(
        "TARGET ALLIANCES"
    )
    print(
        "----------------------------------------"
    )


    for alliance in target_alliances:

        abbreviation = str(
            alliance.get(
                "abbr",
                "???",
            )
        ).strip()

        name = alliance.get(
            "name",
            "",
        )

        power = alliance.get(
            "power",
            0,
        ) or 0


        print(
            f"{abbreviation} "
            f"| {name} "
            f"| {power:,}"
        )


    print()

    print(
        f"Found "
        f"{len(target_alliances)} "
        f"target alliances."
    )


    if not target_alliances:
        return []


    # ========================================================
    # WARN ABOUT MISSING ALLIANCES
    # ========================================================

    found_tags = {
        str(
            alliance.get(
                "abbr",
                "",
            )
        ).strip()
        for alliance in target_alliances
    }


    missing_tags = (
        TARGET_ALLIANCES
        - found_tags
    )


    if missing_tags:

        print()
        print(
            "WARNING - TARGET ALLIANCES NOT FOUND:"
        )

        for tag in sorted(missing_tags):

            print(
                f"  {tag}"
            )

        print()


    # ========================================================
    # PLAYER MAP
    # ========================================================

    player_map = {}


    # ========================================================
    # LOAD EACH ALLIANCE ROSTER
    # ========================================================

    for position, alliance_summary in enumerate(
        target_alliances,
        start=1,
    ):

        alliance_id = alliance_summary.get(
            "id"
        )

        abbreviation = str(
            alliance_summary.get(
                "abbr",
                "???",
            )
        ).strip()


        print()

        print(
            f"[{position}/"
            f"{len(target_alliances)}] "
            f"Loading {abbreviation}..."
        )


        if not alliance_id:

            print(
                f"{abbreviation} "
                f"has no alliance ID."
            )

            continue


        alliance = get_alliance(
            alliance_id
        )


        if not alliance:

            print(
                f"Could not load "
                f"{abbreviation}"
            )

            continue


        members = alliance.get(
            "members",
            [],
        )


        print(
            f"{abbreviation}: "
            f"{len(members)} members"
        )


        # ====================================================
        # EXTRACT MEMBERS
        # ====================================================

        for member in members:

            fid = str(
                member.get(
                    "id",
                    "",
                )
            ).strip()


            if not fid:
                continue


            player_map[fid] = {

                "fid":
                    fid,

                "alliance":
                    abbreviation,

                "name":
                    member.get(
                        "name",
                        "",
                    ),

                "power":
                    member.get(
                        "power",
                        0,
                    ) or 0,

                "furnace_level":
                    member.get(
                        "furnace_level"
                    ),

            }


        # Small delay between alliance requests

        time.sleep(1)


    players = list(
        player_map.values()
    )


    # ========================================================
    # SORT PLAYERS
    # ========================================================

    players.sort(

        key=lambda player: (

            ALLIANCE_ORDER.get(
                str(
                    player.get(
                        "alliance",
                        "",
                    )
                ).strip(),
                999,
            ),

            -(
                player.get(
                    "power",
                    0,
                )
                or 0
            ),

        )

    )


    print()
    print(
        "========================================"
    )
    print(
        "          DISCOVERY COMPLETE"
    )
    print(
        "========================================"
    )

    print(
        f"Alliances scanned: "
        f"{len(target_alliances)}"
    )

    print(
        f"Unique players found: "
        f"{len(players)}"
    )


    return players


# ============================================================
# EXTRACT ALLIANCE ABBREVIATION
# ============================================================

def extract_alliance(player, fallback):

    alliance = player.get(
        "alliance"
    )


    if isinstance(
        alliance,
        dict,
    ):

        abbreviation = alliance.get(
            "abbr"
        )

        if abbreviation:
            return str(
                abbreviation
            ).strip()


    if isinstance(
        alliance,
        str,
    ):

        if alliance.strip():
            return alliance.strip()


    return fallback


# ============================================================
# CREATE DATABASE ROW
# ============================================================

def make_database_row(
    player,
    standings_data,
    base_player,
):

    standings = extract_standings_data(standings_data)

    fid = str(
        player.get(
            "id",
            base_player["fid"],
        )
    ).strip()

    # Prefer profile power, then standings Personal Power, then roster power.
    power = player.get("power")

    if power is None:
        power = standings.get("personal_power")

    if power is None:
        power = base_player.get("power")

    alliance = extract_alliance(
        player,
        base_player["alliance"],
    )

    # Preserve the roster alliance for this sync if the profile reports
    # an alliance outside our target set. Case is intentionally preserved.
    if alliance not in TARGET_ALLIANCES:
        alliance = base_player["alliance"]

    # Base fields are always safe to update.
    row = {
        "fid": int(fid),
        "player": player.get("name", base_player["name"]),
        "alliance": alliance,
        "state": player.get("state", STATE_ID),
        "furnace_level": player.get(
            "furnace_level",
            base_player["furnace_level"],
        ),
        "power": power,
        "kills": player.get("kills", 0) or 0,
        "labyrinth_score": player.get("labyrinth_score", 0) or 0,
        # A player discovered in one of our tracked State 2337 alliances
        # is active for this sync. This also automatically reactivates a
        # player who previously left the state and later returned.
        "active": True,
        "api_updated": player.get("updated_at"),
    }

    # Only include standings columns when the standings endpoint succeeded.
    # If standings is unavailable (including HTTP 401), these keys are
    # omitted so an upsert cannot replace existing values with NULL.
    if standings_data is not None:
        row.update({
            "pet_power": standings.get("pet_power"),
            "island_prosperity": standings.get("island_prosperity"),
            "hero_power": standings.get("hero_power"),
            "hero_gear_power": standings.get("hero_gear_power"),
            "expert_power": standings.get("expert_power"),
            "standings_updated": standings.get("standings_updated"),
        })

    return row


# ============================================================
# FETCH COMPLETE PLAYER
# ============================================================

def fetch_complete_player(base_player):

    fid = base_player[
        "fid"
    ]


    # ========================================================
    # PLAYER PROFILE
    # ========================================================

    player = get_player(
        fid
    )


    if not player:
        return None


    # ========================================================
    # STANDINGS
    # ========================================================

    standings = get_standings(
        fid
    )


    # We still return the player if standings are unavailable.
    # Missing standings fields become NULL in Supabase.

    return make_database_row(
        player,
        standings,
        base_player,
    )


# ============================================================
# SUPABASE UPSERT
# ============================================================

def _upsert_player_group(rows, label):

    if not rows:
        return True

    endpoint = (
        f"{SUPABASE_URL}"
        f"/rest/v1/players"
        f"?on_conflict=fid"
    )

    try:
        response = requests.post(
            endpoint,
            headers=SUPABASE_HEADERS,
            json=rows,
            timeout=60,
        )

    except requests.RequestException as error:
        print(
            f"SUPABASE NETWORK ERROR | {label} | {error}"
        )
        return False

    if 200 <= response.status_code < 300:
        print(
            f"DATABASE: {len(rows)} players saved "
            f"({label})."
        )
        return True

    print()
    print(
        f"SUPABASE ERROR | {label} | "
        f"HTTP {response.status_code}"
    )
    print(response.text)
    print()
    return False


def upsert_players(rows):

    if not rows:
        return True

    # PostgREST bulk payloads are safest when every object has the same
    # column set. Split rows so a standings failure never causes mixed-key
    # payloads and never overwrites previously collected standings with NULL.
    rows_with_standings = []
    rows_without_standings = []

    for row in rows:
        if "standings_updated" in row:
            rows_with_standings.append(row)
        else:
            rows_without_standings.append(row)

    success = True

    for start in range(0, len(rows_with_standings), SUPABASE_BATCH_SIZE):
        group = rows_with_standings[
            start:start + SUPABASE_BATCH_SIZE
        ]
        if not _upsert_player_group(group, "with standings"):
            success = False

    for start in range(0, len(rows_without_standings), SUPABASE_BATCH_SIZE):
        group = rows_without_standings[
            start:start + SUPABASE_BATCH_SIZE
        ]
        if not _upsert_player_group(group, "standings preserved"):
            success = False

    return success


# ============================================================
# STATE-WIDE PLAYER PRESENCE / GONE PLAYER CLEANUP
# ============================================================

def discover_all_state_player_ids():

    print()
    print(
        "========================================"
    )
    print(
        f"   CHECKING ALL PLAYERS IN STATE {STATE_ID}"
    )
    print(
        "========================================"
    )
    print()

    state = get_state(STATE_ID)

    if not state:
        print(
            "Could not load state for inactive-player check. "
            "Skipping cleanup."
        )
        return None

    alliances = state.get("alliances", [])

    if not isinstance(alliances, list) or not alliances:
        print(
            "State returned no alliances for inactive-player check. "
            "Skipping cleanup."
        )
        return None

    state_player_ids = set()
    failed_alliances = []

    print(
        f"Checking {len(alliances)} alliances in State {STATE_ID}..."
    )

    for position, alliance_summary in enumerate(
        alliances,
        start=1,
    ):

        alliance_id = alliance_summary.get("id")

        abbreviation = str(
            alliance_summary.get(
                "abbr",
                "???",
            )
        ).strip()

        if not alliance_id:
            print(
                f"[{position}/{len(alliances)}] "
                f"{abbreviation}: no alliance ID - "
                "cleanup will be skipped for safety."
            )
            failed_alliances.append(abbreviation)
            continue

        alliance = get_alliance(alliance_id)

        if not alliance:
            print(
                f"[{position}/{len(alliances)}] "
                f"{abbreviation}: FAILED - "
                "cleanup will be skipped for safety."
            )
            failed_alliances.append(abbreviation)
            continue

        members = alliance.get("members")

        if not isinstance(members, list):
            print(
                f"[{position}/{len(alliances)}] "
                f"{abbreviation}: invalid member list - "
                "cleanup will be skipped for safety."
            )
            failed_alliances.append(abbreviation)
            continue

        for member in members:

            fid = str(
                member.get(
                    "id",
                    "",
                )
            ).strip()

            if fid:
                state_player_ids.add(fid)

        print(
            f"[{position}/{len(alliances)}] "
            f"{abbreviation}: {len(members)} members"
        )

        # Keep this conservative so the state-wide check does not
        # hammer WOS Oracle with every alliance at once.
        time.sleep(0.5)

    if failed_alliances:

        print()
        print(
            "WARNING: One or more State 2337 alliances could not "
            "be verified."
        )
        print(
            "No players will be marked inactive during this run."
        )
        print(
            "Failed alliances: "
            + ", ".join(failed_alliances)
        )

        return None

    if not state_player_ids:

        print(
            "State-wide player scan returned zero players. "
            "Skipping cleanup for safety."
        )
        return None

    print()
    print(
        f"State-wide presence check found "
        f"{len(state_player_ids)} players."
    )

    return state_player_ids


def get_tracked_database_players():

    endpoint = (
        f"{SUPABASE_URL}"
        f"/rest/v1/players"
    )

    params = {
        "select": "fid,player,alliance,state,active",
        "state": f"eq.{STATE_ID}",
    }

    try:

        response = requests.get(
            endpoint,
            headers=SUPABASE_HEADERS,
            params=params,
            timeout=60,
        )

    except requests.RequestException as error:

        print(
            f"SUPABASE NETWORK ERROR | "
            f"loading existing players | {error}"
        )

        return None

    if not 200 <= response.status_code < 300:

        print(
            f"SUPABASE ERROR | "
            f"loading existing players | "
            f"HTTP {response.status_code}"
        )
        print(response.text)

        return None

    try:
        data = response.json()

    except ValueError:

        print(
            "SUPABASE INVALID JSON | "
            "loading existing players"
        )

        return None

    if not isinstance(data, list):

        print(
            "SUPABASE returned an invalid player list. "
            "Skipping inactive-player cleanup."
        )

        return None

    return data


def mark_players_no_longer_in_state_inactive(state_player_ids):

    if state_player_ids is None:

        print()
        print(
            "Inactive-player cleanup skipped because "
            "the complete state roster was not verified."
        )

        return True, 0

    existing_players = get_tracked_database_players()

    if existing_players is None:

        print()
        print(
            "Inactive-player cleanup skipped because "
            "existing Supabase players could not be loaded."
        )

        return False, 0

    gone_players = []

    for player in existing_players:

        fid = str(
            player.get(
                "fid",
                "",
            )
        ).strip()

        if not fid:
            continue

        if fid not in state_player_ids:

            # Avoid repeatedly PATCHing players that were already
            # marked inactive by an earlier successful sync.
            if player.get("active") is False:
                continue

            gone_players.append(player)

    print()
    print(
        "========================================"
    )
    print(
        "        GONE PLAYER CHECK"
    )
    print(
        "========================================"
    )

    if not gone_players:

        print(
            "No newly departed State 2337 players found."
        )

        return True, 0

    print(
        f"Players no longer in State {STATE_ID}: "
        f"{len(gone_players)}"
    )
    print()

    endpoint = (
        f"{SUPABASE_URL}"
        f"/rest/v1/players"
    )

    success = True
    marked_count = 0

    for player in gone_players:

        fid = str(player["fid"])
        name = player.get("player") or "Unknown"
        alliance = player.get("alliance") or "???"

        params = {
            "fid": f"eq.{fid}",
        }

        try:

            response = requests.patch(
                endpoint,
                headers=SUPABASE_HEADERS,
                params=params,
                json={
                    "active": False,
                },
                timeout=30,
            )

        except requests.RequestException as error:

            print(
                f"FAILED TO MARK GONE: "
                f"{name} | {fid} | {error}"
            )

            success = False
            continue

        if 200 <= response.status_code < 300:

            marked_count += 1

            print(
                f"GONE: "
                f"{name} "
                f"| {fid} "
                f"| Former alliance {alliance} "
                f"| active = false"
            )

        else:

            print(
                f"FAILED TO MARK GONE: "
                f"{name} "
                f"| {fid} "
                f"| HTTP {response.status_code}"
            )
            print(response.text)

            success = False

    print()
    print(
        f"Players marked inactive/gone: "
        f"{marked_count}"
    )

    return success, marked_count


# ============================================================
# FETCH + SAVE ALL PLAYERS
# ============================================================

def fetch_and_save_players(players):

    total_players = len(players)

    successful_profiles = 0
    failed_profiles = []
    database_failures = 0


    print()
    print(
        "========================================"
    )
    print(
        "       FETCHING PLAYER DATA"
    )
    print(
        "========================================"
    )


    # ========================================================
    # PROCESS BATCHES
    # ========================================================

    for start in range(
        0,
        total_players,
        PLAYER_BATCH_SIZE,
    ):

        batch = players[
            start:
            start + PLAYER_BATCH_SIZE
        ]

        batch_end = min(
            start + PLAYER_BATCH_SIZE,
            total_players,
        )


        print()
        print(
            f"BATCH "
            f"{start + 1}-"
            f"{batch_end} "
            f"OF {total_players}"
        )

        print(
            "----------------------------------------"
        )


        database_rows = []


        # ====================================================
        # CONCURRENT REQUESTS
        # ====================================================

        with ThreadPoolExecutor(
            max_workers=PLAYER_BATCH_SIZE
        ) as executor:

            future_map = {

                executor.submit(
                    fetch_complete_player,
                    base_player,
                ):
                    base_player

                for base_player in batch

            }


            # =================================================
            # HANDLE RESULTS
            # =================================================

            for future in as_completed(
                future_map
            ):

                base_player = future_map[
                    future
                ]


                try:

                    row = future.result()

                except Exception as error:

                    print(
                        f"ERROR: "
                        f"{base_player['name']} "
                        f"| {base_player['fid']} "
                        f"| {error}"
                    )

                    failed_profiles.append(
                        base_player
                    )

                    continue


                if not row:

                    print(
                        f"FAILED: "
                        f"{base_player['name']} "
                        f"| {base_player['fid']}"
                    )

                    failed_profiles.append(
                        base_player
                    )

                    continue


                # =============================================
                # SUCCESS
                # =============================================

                database_rows.append(
                    row
                )

                successful_profiles += 1


                power_display = (
                    f"{row['power']:,}"
                    if row["power"] is not None
                    else "NULL"
                )

                pet_power = row.get("pet_power")
                hero_power = row.get("hero_power")
                gear_power = row.get("hero_gear_power")
                expert_power = row.get("expert_power")

                standings_preserved = (
                    "standings_updated" not in row
                )

                if standings_preserved:
                    pet_display = "PRESERVED"
                    hero_display = "PRESERVED"
                    gear_display = "PRESERVED"
                    expert_display = "PRESERVED"
                else:
                    pet_display = (
                        f"{pet_power:,}"
                        if pet_power is not None
                        else "NULL"
                    )
                    hero_display = (
                        f"{hero_power:,}"
                        if hero_power is not None
                        else "NULL"
                    )
                    gear_display = (
                        f"{gear_power:,}"
                        if gear_power is not None
                        else "NULL"
                    )
                    expert_display = (
                        f"{expert_power:,}"
                        if expert_power is not None
                        else "NULL"
                    )


                print(
                    f"OK: "
                    f"{row['player']} "
                    f"| {row['fid']} "
                    f"| {row['alliance']} "
                    f"| Power {power_display} "
                    f"| Pet {pet_display} "
                    f"| Hero {hero_display} "
                    f"| Gear {gear_display} "
                    f"| Expert {expert_display}"
                )


        # ====================================================
        # WRITE BATCH TO SUPABASE
        # ====================================================

        if database_rows:

            print()

            print(
                f"Saving "
                f"{len(database_rows)} "
                f"players to Supabase..."
            )


            database_success = upsert_players(
                database_rows
            )


            if not database_success:

                database_failures += 1

                print(
                    "WARNING: "
                    "Database write failed "
                    "for this batch."
                )


        # ====================================================
        # DELAY BEFORE NEXT BATCH
        # ====================================================

        if batch_end < total_players:

            print(
                f"Waiting "
                f"{BATCH_DELAY_SECONDS}s..."
            )

            time.sleep(
                BATCH_DELAY_SECONDS
            )


    # ========================================================
    # FINAL REPORT
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        "             SYNC COMPLETE"
    )
    print(
        "========================================"
    )


    print(
        f"Players discovered: "
        f"{total_players}"
    )

    print(
        f"Profiles fetched: "
        f"{successful_profiles}"
    )

    print(
        f"Failed profiles: "
        f"{len(failed_profiles)}"
    )

    print(
        f"Database batch failures: "
        f"{database_failures}"
    )


    return (
        failed_profiles,
        database_failures,
    )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    start_time = time.time()


    print()
    print(
        "========================================"
    )
    print(
        "       STATE 2337 MOK SYNC"
    )
    print(
        "========================================"
    )

    print(
        f"State: {STATE_ID}"
    )

    print(
        "Alliances: "
        + ", ".join(
            sorted(
                TARGET_ALLIANCES,
                key=lambda tag:
                    ALLIANCE_ORDER.get(
                        tag,
                        999,
                    ),
            )
        )
    )


    # ========================================================
    # DISCOVER
    # ========================================================

    players = discover_players()


    if not players:

        print(
            "No players discovered."
        )

        raise SystemExit(1)


    # ========================================================
    # FETCH + SAVE
    # ========================================================

    (
        failed_profiles,
        database_failures,

    ) = fetch_and_save_players(
        players
    )


    # ========================================================
    # MARK PLAYERS WHO LEFT STATE 2337 AS INACTIVE / GONE
    # ========================================================

    inactive_cleanup_success = True
    players_marked_gone = 0

    # Only run the cleanup after all target-player database writes
    # succeeded. This prevents a partial/failed sync from changing
    # player status.
    if database_failures == 0:

        state_player_ids = discover_all_state_player_ids()

        (
            inactive_cleanup_success,
            players_marked_gone,

        ) = mark_players_no_longer_in_state_inactive(
            state_player_ids
        )

    else:

        print()
        print(
            "Skipping inactive-player cleanup because "
            "one or more database batches failed."
        )


    # ========================================================
    # RUNTIME
    # ========================================================

    elapsed = round(
        time.time() - start_time,
        1,
    )


    print()

    print(
        f"Runtime: "
        f"{elapsed} seconds"
    )


    # ========================================================
    # FAILED PLAYERS
    # ========================================================

    if failed_profiles:

        print()
        print(
            "FAILED PLAYERS"
        )

        print(
            "----------------------------------------"
        )


        for player in failed_profiles:

            print(
                player["fid"],
                "|",
                player["name"],
                "|",
                player["alliance"],
            )


    # ========================================================
    # FAIL ACTION IF DATABASE WRITES FAILED
    # ========================================================

    if database_failures > 0:

        print()
        print(
            "One or more Supabase "
            "database writes failed."
        )

        raise SystemExit(1)


    if not inactive_cleanup_success:

        print()
        print(
            "One or more inactive-player "
            "database updates failed."
        )

        raise SystemExit(1)


    print()
    print(
        f"Players marked gone this run: "
        f"{players_marked_gone}"
    )


    print()
    print(
        "========================================"
    )
    print(
        "              ALL DONE"
    )
    print(
        "========================================"
    )


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":

    main()
