import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "WOS.env"

# Loads WOS.env locally.
# In GitHub Actions, existing environment variables still work.
load_dotenv(ENV_FILE)


TOKEN = os.getenv("WOSORACLE_API_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not TOKEN:
    raise ValueError(
        "WOSORACLE_API_TOKEN not found."
    )

if not SUPABASE_URL:
    raise ValueError(
        "SUPABASE_URL not found."
    )

if not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_KEY not found."
    )


# ============================================================
# SETTINGS
# ============================================================

STATE_ID = 2348

TARGET_ALLIANCES = {
    "COD",
    "WET",
    "ONF",
    "300"
}

SUPABASE_TABLE = "players"

MAX_RETRIES = 3

PLAYER_BATCH_SIZE = 8

BATCH_DELAY_SECONDS = 2

SUPABASE_BATCH_SIZE = 100


# ============================================================
# HEADERS
# ============================================================

ORACLE_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}


SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal"
}


# ============================================================
# GENERIC WOS ORACLE REQUEST
# ============================================================

def oracle_get(path, max_retries=MAX_RETRIES):

    url = f"https://wosoracle.com{path}"

    for attempt in range(1, max_retries + 2):

        try:

            response = requests.get(
                url,
                headers=ORACLE_HEADERS,
                timeout=30
            )

        except requests.RequestException as error:

            print(
                f"Network error on {path}: {error}"
            )

            if attempt > max_retries:

                print(
                    "Maximum retries reached."
                )

                return None

            wait_time = attempt * 5

            print(
                f"Waiting {wait_time} seconds..."
            )

            time.sleep(wait_time)

            continue


        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:

                return response.json()

            except ValueError:

                print(
                    f"Invalid JSON returned from {path}"
                )

                return None


        # ----------------------------------------------------
        # RETRYABLE ERRORS
        # ----------------------------------------------------

        if (
            response.status_code == 429
            or response.status_code == 408
            or response.status_code == 425
            or response.status_code >= 500
        ):

            if attempt > max_retries:

                print(
                    f"Maximum retries reached "
                    f"for {path}. "
                    f"HTTP {response.status_code}"
                )

                return None


            wait_time = attempt * 5

            print(
                f"HTTP {response.status_code} "
                f"on {path}. "
                f"Retrying in {wait_time} seconds..."
            )

            time.sleep(wait_time)

            continue


        # ----------------------------------------------------
        # NON-RETRYABLE ERROR
        # ----------------------------------------------------

        print(
            f"Permanent error on {path}: "
            f"HTTP {response.status_code}"
        )

        print(response.text)

        return None


    return None


# ============================================================
# STATE REQUEST
# ============================================================

def get_state(state_id):

    return oracle_get(
        f"/api/v1/states/{state_id}"
    )


# ============================================================
# ALLIANCE REQUEST
# ============================================================

def get_alliance(alliance_id):

    return oracle_get(
        f"/api/v1/alliances/{alliance_id}"
    )


# ============================================================
# PLAYER REQUEST
# ============================================================

def get_player(fid):

    return oracle_get(
        f"/api/v1/players/{fid}"
    )


# ============================================================
# DISCOVER PLAYERS FROM MAIN 4 ALLIANCES
# ============================================================

def discover_players():

    print()
    print("========================================")
    print(f"        SCANNING STATE {STATE_ID}")
    print("========================================")
    print()


    # --------------------------------------------------------
    # GET STATE
    # --------------------------------------------------------

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
        []
    )


    print(
        f"State returned "
        f"{len(alliances)} alliances."
    )


    if not alliances:

        print(
            "No alliances returned."
        )

        return []


    # --------------------------------------------------------
    # FIND TARGET ALLIANCES
    # --------------------------------------------------------

    target_alliances = []


    for alliance in alliances:

        abbreviation = str(
            alliance.get(
                "abbr",
                ""
            )
        ).strip().upper()


        if abbreviation in TARGET_ALLIANCES:

            target_alliances.append(
                alliance
            )


    # --------------------------------------------------------
    # SORT TARGET ALLIANCES
    # --------------------------------------------------------

    alliance_order = {
        "COD": 1,
        "WET": 2,
        "ONF": 3,
        "300": 4
    }


    target_alliances.sort(
        key=lambda alliance:
            alliance_order.get(
                str(
                    alliance.get(
                        "abbr",
                        ""
                    )
                ).upper(),
                999
            )
    )


    print()
    print("TARGET ALLIANCES")
    print("----------------------------------------")


    for alliance in target_alliances:

        abbreviation = alliance.get(
            "abbr",
            "???"
        )

        name = alliance.get(
            "name",
            ""
        )

        power = alliance.get(
            "power",
            0
        ) or 0


        print(
            f"{abbreviation} "
            f"- {name} "
            f"- {power:,} power"
        )


    print()
    print(
        f"Found "
        f"{len(target_alliances)} "
        f"target alliances."
    )


    # --------------------------------------------------------
    # PLAYER MAP
    #
    # FID is the dictionary key so duplicates are removed.
    # --------------------------------------------------------

    player_map = {}


    # --------------------------------------------------------
    # LOAD ALLIANCE ROSTERS
    # --------------------------------------------------------

    for position, alliance_summary in enumerate(
        target_alliances,
        start=1
    ):

        alliance_id = alliance_summary.get(
            "id"
        )

        abbreviation = str(
            alliance_summary.get(
                "abbr",
                "???"
            )
        ).strip().upper()


        print()
        print(
            f"[{position}/{len(target_alliances)}] "
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
                f"{abbreviation}."
            )

            continue


        # ----------------------------------------------------
        # MEMBERS
        # ----------------------------------------------------

        members = alliance.get(
            "members",
            []
        )


        print(
            f"{abbreviation}: "
            f"{len(members)} members"
        )


        # ----------------------------------------------------
        # EXTRACT MEMBER DATA
        # ----------------------------------------------------

        for member in members:

            fid = str(
                member.get(
                    "id",
                    ""
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
                        ""
                    ),

                "power":
                    member.get(
                        "power",
                        0
                    ) or 0,

                "furnace_level":
                    member.get(
                        "furnace_level",
                        ""
                    )

            }


        # Small delay between alliance calls

        time.sleep(1)


    # --------------------------------------------------------
    # CONVERT TO LIST
    # --------------------------------------------------------

    players = list(
        player_map.values()
    )


    # --------------------------------------------------------
    # SORT PLAYERS BY ALLIANCE + POWER
    # --------------------------------------------------------

    players.sort(
        key=lambda player: (

            alliance_order.get(
                str(
                    player.get(
                        "alliance",
                        ""
                    )
                ).upper(),
                999
            ),

            -(
                player.get(
                    "power",
                    0
                ) or 0
            )

        )
    )


    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    print()
    print("========================================")
    print("          DISCOVERY COMPLETE")
    print("========================================")

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
# FETCH FULL PLAYER PROFILES
# ============================================================

def fetch_full_player_profiles(players):

    print()
    print("========================================")
    print("       FETCHING FULL PLAYER DATA")
    print("========================================")
    print()


    full_profiles = []

    failed_profiles = []

    total_players = len(
        players
    )


    # --------------------------------------------------------
    # PROCESS IN BATCHES
    # --------------------------------------------------------

    for start in range(
        0,
        total_players,
        PLAYER_BATCH_SIZE
    ):

        batch = players[
            start:
            start + PLAYER_BATCH_SIZE
        ]


        batch_end = min(
            start + PLAYER_BATCH_SIZE,
            total_players
        )


        print()
        print(
            f"Batch "
            f"{start + 1}-"
            f"{batch_end} "
            f"of {total_players}"
        )

        print(
            "----------------------------------------"
        )


        # ----------------------------------------------------
        # FETCH EACH PLAYER
        # ----------------------------------------------------

        for base_player in batch:

            fid = base_player[
                "fid"
            ]


            player = get_player(
                fid
            )


            if player:

                alliance_data = (
                    player.get(
                        "alliance"
                    )
                    or {}
                )


                full_profile = {

                    "fid":
                        str(
                            player.get(
                                "id",
                                fid
                            )
                        ),

                    "name":
                        player.get(
                            "name",
                            base_player[
                                "name"
                            ]
                        ),

                    "alliance":
                        alliance_data.get(
                            "abbr",
                            base_player[
                                "alliance"
                            ]
                        ),

                    "state":
                        player.get(
                            "state",
                            STATE_ID
                        ),

                    "furnace_level":
                        player.get(
                            "furnace_level",
                            base_player[
                                "furnace_level"
                            ]
                        ),

                    "power":
                        player.get(
                            "power",
                            base_player[
                                "power"
                            ]
                        ) or 0,

                    "kills":
                        player.get(
                            "kills",
                            0
                        ) or 0,

                    "labyrinth_score":
                        player.get(
                            "labyrinth_score",
                            0
                        ) or 0,

                    "active":
                        player.get(
                            "active"
                        ),

                    "updated_at":
                        player.get(
                            "updated_at",
                            ""
                        )

                }


                full_profiles.append(
                    full_profile
                )


                print(
                    "OK:",
                    full_profile[
                        "name"
                    ],
                    "|",
                    full_profile[
                        "fid"
                    ]
                )


            else:

                failed_profiles.append(
                    base_player
                )


                print(
                    "FAILED:",
                    base_player[
                        "name"
                    ],
                    "|",
                    fid
                )


        # ----------------------------------------------------
        # WAIT BETWEEN BATCHES
        # ----------------------------------------------------

        if batch_end < total_players:

            print(
                f"Waiting "
                f"{BATCH_DELAY_SECONDS} "
                f"seconds before next batch..."
            )

            time.sleep(
                BATCH_DELAY_SECONDS
            )


    # --------------------------------------------------------
    # FINAL RESULTS
    # --------------------------------------------------------

    print()
    print("========================================")
    print("       PROFILE FETCH COMPLETE")
    print("========================================")


    print(
        f"Successful: "
        f"{len(full_profiles)}"
    )


    print(
        f"Failed: "
        f"{len(failed_profiles)}"
    )


    return (
        full_profiles,
        failed_profiles
    )


# ============================================================
# CONVERT ORACLE PROFILE TO PLAYERS TABLE ROW
# ============================================================

def build_supabase_row(player):

    return {

        "fid":
            player["fid"],

        "player_name":
            player["name"],

        "alliance":
            player["alliance"],

        "state":
            player["state"],

        "furnace_level":
            player["furnace_level"],

        "power":
            player["power"],

        "active":
            player["active"]

    }


# ============================================================
# UPSERT PLAYERS INTO SUPABASE
# ============================================================

def upsert_players_to_supabase(players):

    print()
    print("========================================")
    print("        WRITING TO SUPABASE")
    print("========================================")
    print()

    if not players:

        print(
            "No player profiles to write."
        )

        return False


    rows = [
        build_supabase_row(player)
        for player in players
    ]


    url = (
        f"{SUPABASE_URL.rstrip('/')}"
        f"/rest/v1/{SUPABASE_TABLE}"
        f"?on_conflict=fid"
    )


    total_rows = len(rows)

    successful_rows = 0


    for start in range(
        0,
        total_rows,
        SUPABASE_BATCH_SIZE
    ):

        batch = rows[
            start:
            start + SUPABASE_BATCH_SIZE
        ]


        batch_end = min(
            start + SUPABASE_BATCH_SIZE,
            total_rows
        )


        print(
            f"Writing rows "
            f"{start + 1}-{batch_end} "
            f"of {total_rows}..."
        )


        try:

            response = requests.post(
                url,
                headers=SUPABASE_HEADERS,
                json=batch,
                timeout=60
            )

        except requests.RequestException as error:

            print()
            print(
                "SUPABASE NETWORK ERROR:"
            )

            print(error)

            return False


        if response.status_code not in (
            200,
            201,
            204
        ):

            print()
            print(
                "SUPABASE WRITE FAILED"
            )

            print(
                f"HTTP {response.status_code}"
            )

            print(
                response.text
            )

            return False


        successful_rows += len(batch)

        print(
            f"OK: {len(batch)} rows upserted."
        )


    print()
    print("----------------------------------------")

    print(
        f"Successfully upserted "
        f"{successful_rows} players "
        f"into '{SUPABASE_TABLE}'."
    )

    return True


# ============================================================
# RUN PROGRAM
# ============================================================

players = discover_players()


if not players:

    print()
    print(
        "No players discovered. "
        "Stopping."
    )

    raise SystemExit


full_profiles, failed_profiles = (
    fetch_full_player_profiles(
        players
    )
)


# ============================================================
# SHOW FIRST 10 FULL PROFILES
# ============================================================

print()
print("FIRST 10 FULL PROFILES")
print("========================================")


for player in full_profiles[:10]:

    print(
        player["fid"],
        "|",
        player["name"],
        "|",
        player["alliance"],
        "| Power:",
        f'{player["power"]:,}',
        "| Kills:",
        f'{player["kills"]:,}',
        "| Furnace:",
        player["furnace_level"]
    )


# ============================================================
# WRITE TO SUPABASE
# ============================================================

supabase_success = (
    upsert_players_to_supabase(
        full_profiles
    )
)


# ============================================================
# SHOW FAILURES
# ============================================================

if failed_profiles:

    print()
    print("FAILED PLAYERS")
    print("========================================")


    for player in failed_profiles:

        print(
            player["fid"],
            "|",
            player["name"],
            "|",
            player["alliance"]
        )


# ============================================================
# FINAL STATUS
# ============================================================

print()
print("========================================")

if supabase_success:

    print(
        " COLLECTION + DATABASE UPDATE COMPLETE"
    )

else:

    print(
        " COLLECTION COMPLETE / DATABASE FAILED"
    )

print("========================================")
