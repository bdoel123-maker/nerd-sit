import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path
from dotenv import load_dotenv


# ============================================================
# LOAD WOS TOKEN
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "WOS.env"

load_dotenv(ENV_FILE)

TOKEN = os.getenv("WOSORACLE_API_TOKEN")

if not TOKEN:
    raise ValueError(
        "WOSORACLE_API_TOKEN not found in WOS.env"
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

MAX_RETRIES = 3

PLAYER_BATCH_SIZE = 8

BATCH_DELAY_SECONDS = 2


HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
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
                headers=HEADERS,
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


print()
print("========================================")
print("              ALL DONE")
print("========================================")