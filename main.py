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

STATE_ID = 2348


# IMPORTANT:
# Alliance tags are CASE-SENSITIVE.
#
# ONF = main ONF
# onf = ONF farm
# llc = lowercase LLC alliance

TARGET_ALLIANCES = {
    "COD",
    "WET",
    "ONF",
    "300",
    "DRY",
    "llc",
    "onf",
}


ALLIANCE_ORDER = {
    "COD": 1,
    "WET": 2,
    "ONF": 3,
    "300": 4,
    "DRY": 5,
    "llc": 6,
    "onf": 7,
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

    return oracle_get(
        f"/api/players/{fid}/standings"
    )


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

    standings = extract_standings_data(
        standings_data
    )


    fid = str(
        player.get(
            "id",
            base_player["fid"],
        )
    ).strip()


    # --------------------------------------------------------
    # PLAYER POWER
    #
    # Prefer /api/v1/players/{fid}.
    # Fall back to standings Personal Power.
    # Fall back to alliance roster power.
    # --------------------------------------------------------

    power = player.get(
        "power"
    )


    if power is None:

        power = standings.get(
            "personal_power"
        )


    if power is None:

        power = base_player.get(
            "power"
        )


    # --------------------------------------------------------
    # ALLIANCE
    # --------------------------------------------------------

    alliance = extract_alliance(
        player,
        base_player["alliance"],
    )


    # Preserve the alliance tag exactly.
    # No upper/lower conversion.

    if alliance not in TARGET_ALLIANCES:

        # The player may have moved after discovery.
        # Preserve the alliance from the roster scan for
        # consistency with this sync.

        alliance = base_player["alliance"]


    # --------------------------------------------------------
    # DATABASE ROW
    # --------------------------------------------------------

    return {

        "fid":
            int(fid),

        "player":
            player.get(
                "name",
                base_player["name"],
            ),

        "alliance":
            alliance,

        "state":
            player.get(
                "state",
                STATE_ID,
            ),

        "furnace_level":
            player.get(
                "furnace_level",
                base_player["furnace_level"],
            ),

        "power":
            power,

        "kills":
            player.get(
                "kills",
                0,
            ) or 0,

        "labyrinth_score":
            player.get(
                "labyrinth_score",
                0,
            ) or 0,

        "pet_power":
            standings.get(
                "pet_power"
            ),

        "island_prosperity":
            standings.get(
                "island_prosperity"
            ),

        "hero_power":
            standings.get(
                "hero_power"
            ),

        "hero_gear_power":
            standings.get(
                "hero_gear_power"
            ),

        "expert_power":
            standings.get(
                "expert_power"
            ),

        "active":
            player.get(
                "active"
            ),

        "api_updated":
            player.get(
                "updated_at"
            ),

        "standings_updated":
            standings.get(
                "standings_updated"
            ),

    }


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

def upsert_players(rows):

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
            f"SUPABASE NETWORK ERROR | {error}"
        )

        return False


    if 200 <= response.status_code < 300:

        print(
            f"DATABASE: "
            f"{len(rows)} players saved."
        )

        return True


    print()
    print(
        f"SUPABASE ERROR | HTTP "
        f"{response.status_code}"
    )

    print(response.text)
    print()

    return False


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

                pet_display = (
                    f"{row['pet_power']:,}"
                    if row["pet_power"] is not None
                    else "NULL"
                )

                hero_display = (
                    f"{row['hero_power']:,}"
                    if row["hero_power"] is not None
                    else "NULL"
                )

                gear_display = (
                    f"{row['hero_gear_power']:,}"
                    if row["hero_gear_power"] is not None
                    else "NULL"
                )

                expert_display = (
                    f"{row['expert_power']:,}"
                    if row["expert_power"] is not None
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
        "       NERD SIT WOS DATABASE"
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
