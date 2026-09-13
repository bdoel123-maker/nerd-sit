import os
import time
import requests

from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "WOS.env"

# Local PC: load WOS.env if it exists
# GitHub Actions: use repository secrets/environment variables
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


WOS_TOKEN = (
    os.getenv(
        "WOSORACLE_API_TOKEN",
        ""
    )
    .strip()
)

SUPABASE_URL = (
    os.getenv(
        "SUPABASE_URL",
        ""
    )
    .strip()
    .rstrip("/")
)

SUPABASE_KEY = (
    os.getenv(
        "SUPABASE_KEY",
        ""
    )
    .strip()
)


# ============================================================
# VALIDATE ENVIRONMENT
# ============================================================

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


# ============================================================
# SETTINGS
# ============================================================

STATE_ID = 2348

TARGET_ALLIANCE = "COD"

MAX_RETRIES = 3

PLAYER_BATCH_SIZE = 8

PLAYER_BATCH_DELAY_SECONDS = 2

SUPABASE_BATCH_SIZE = 50

SUPABASE_TABLE = "cod_activity"


# ============================================================
# WOS ORACLE HEADERS
# ============================================================

WOS_HEADERS = {
    "Authorization": f"Bearer {WOS_TOKEN}",
    "Accept": "application/json"
}


# ============================================================
# SUPABASE HEADERS
# ============================================================

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


# ============================================================
# UTC TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# CHUNK LISTS
# ============================================================

def chunks(
    items,
    size
):

    for start in range(
        0,
        len(items),
        size
    ):

        yield items[
            start:
            start + size
        ]


# ============================================================
# GENERIC WOS ORACLE REQUEST
# ============================================================

def oracle_get(
    path,
    max_retries=MAX_RETRIES
):

    url = (
        f"https://wosoracle.com"
        f"{path}"
    )


    for attempt in range(
        1,
        max_retries + 2
    ):

        try:

            response = requests.get(
                url,
                headers=WOS_HEADERS,
                timeout=30
            )

        except requests.RequestException as error:

            print()
            print(
                f"Network error on {path}:"
            )
            print(error)

            if attempt > max_retries:

                print(
                    "Maximum retries reached."
                )

                return None

            wait_time = (
                attempt * 5
            )

            print(
                f"Waiting {wait_time} seconds..."
            )

            time.sleep(
                wait_time
            )

            continue


        # ====================================================
        # SUCCESS
        # ====================================================

        if response.status_code == 200:

            try:

                return response.json()

            except ValueError:

                print(
                    f"Invalid JSON returned "
                    f"from {path}"
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
                    f"Maximum retries reached "
                    f"for {path}. "
                    f"HTTP "
                    f"{response.status_code}"
                )

                return None

            wait_time = (
                attempt * 5
            )

            print(
                f"HTTP "
                f"{response.status_code} "
                f"on {path}."
            )

            print(
                f"Retrying in "
                f"{wait_time} seconds..."
            )

            time.sleep(
                wait_time
            )

            continue


        # ====================================================
        # NON-RETRYABLE ERROR
        # ====================================================

        print()

        print(
            f"Permanent error "
            f"on {path}: "
            f"HTTP "
            f"{response.status_code}"
        )

        print(
            response.text
        )

        return None


    return None


# ============================================================
# GET STATE
# ============================================================

def get_state(
    state_id
):

    return oracle_get(
        f"/api/v1/states/"
        f"{state_id}"
    )


# ============================================================
# GET ALLIANCE
# ============================================================

def get_alliance(
    alliance_id
):

    return oracle_get(
        f"/api/v1/alliances/"
        f"{alliance_id}"
    )


# ============================================================
# GET PLAYER
# ============================================================

def get_player(
    fid
):

    return oracle_get(
        f"/api/v1/players/"
        f"{fid}"
    )


# ============================================================
# DISCOVER COD ROSTER
# ============================================================

def discover_cod_players():

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


    # ========================================================
    # FIND COD
    # ========================================================

    cod_summary = None


    for alliance in alliances:

        abbreviation = str(
            alliance.get(
                "abbr",
                ""
            )
        ).strip().upper()


        if abbreviation == TARGET_ALLIANCE:

            cod_summary = alliance

            break


    if not cod_summary:

        print()

        print(
            "COD alliance was not found."
        )

        return []


    # ========================================================
    # COD SUMMARY
    # ========================================================

    alliance_id = (
        cod_summary.get(
            "id"
        )
    )


    alliance_name = (
        cod_summary.get(
            "name",
            ""
        )
    )


    alliance_power = (
        cod_summary.get(
            "power",
            0
        )
        or 0
    )


    print()

    print(
        "COD FOUND"
    )

    print(
        "----------------------------------------"
    )

    print(
        "Name:",
        alliance_name
    )

    print(
        "Power:",
        f"{alliance_power:,}"
    )


    if not alliance_id:

        print(
            "COD has no alliance ID."
        )

        return []


    # ========================================================
    # LOAD FULL ALLIANCE
    # ========================================================

    alliance = get_alliance(
        alliance_id
    )


    if not alliance:

        print(
            "Could not load COD roster."
        )

        return []


    members = alliance.get(
        "members",
        []
    )


    print()

    print(
        f"COD roster contains "
        f"{len(members)} members."
    )


    # ========================================================
    # BUILD BASE PLAYER LIST
    # ========================================================

    players = []


    for member in members:

        fid = str(
            member.get(
                "id",
                ""
            )
        ).strip()


        if not fid:

            continue


        players.append(
            {
                "fid":
                    fid,

                "name":
                    member.get(
                        "name",
                        ""
                    ),

                "alliance":
                    "COD",

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
        )


    # ========================================================
    # SORT BY POWER
    # ========================================================

    players.sort(
        key=lambda player:
            -(
                player.get(
                    "power",
                    0
                )
                or 0
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
        f"COD players found: "
        f"{len(players)}"
    )


    return players


# ============================================================
# FETCH FULL PLAYER PROFILES
# ============================================================

def fetch_full_player_profiles(
    players
):

    print()

    print(
        "========================================"
    )

    print(
        "       FETCHING COD PLAYER DATA"
    )

    print(
        "========================================"
    )


    full_profiles = []

    failed_profiles = []

    skipped_profiles = []


    total_players = len(
        players
    )


    # ========================================================
    # PROCESS IN BATCHES
    # ========================================================

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
            f"of "
            f"{total_players}"
        )

        print(
            "----------------------------------------"
        )


        # ====================================================
        # FETCH INDIVIDUAL PLAYERS
        # ====================================================

        for base_player in batch:

            fid = (
                base_player[
                    "fid"
                ]
            )


            player = get_player(
                fid
            )


            if not player:

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

                continue


            # =================================================
            # CURRENT ALLIANCE
            # =================================================

            alliance_data = (
                player.get(
                    "alliance"
                )
                or {}
            )


            current_alliance = str(
                alliance_data.get(
                    "abbr",
                    ""
                )
            ).strip().upper()


            # =================================================
            # SKIP IF NO LONGER COD
            # =================================================

            if current_alliance != "COD":

                skipped_profiles.append(
                    {
                        "fid":
                            fid,

                        "name":
                            player.get(
                                "name",
                                base_player[
                                    "name"
                                ]
                            ),

                        "alliance":
                            current_alliance
                    }
                )


                print(
                    "SKIPPED:",
                    player.get(
                        "name",
                        base_player[
                            "name"
                        ]
                    ),
                    "| Alliance:",
                    current_alliance
                )

                continue


            # =================================================
            # BUILD FULL PROFILE
            # =================================================

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
                    "COD",

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
                    )
                    or 0,

                "kills":
                    player.get(
                        "kills",
                        0
                    )
                    or 0,

                "labyrinth_score":
                    player.get(
                        "labyrinth_score",
                        0
                    )
                    or 0,

                "active":
                    player.get(
                        "active"
                    ),

                "updated_at":
                    player.get(
                        "updated_at"
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
                "| Power:",
                f'{full_profile["power"]:,}',
                "| Kills:",
                f'{full_profile["kills"]:,}'
            )


        # ====================================================
        # WAIT BETWEEN BATCHES
        # ====================================================

        if batch_end < total_players:

            print(
                f"Waiting "
                f"{PLAYER_BATCH_DELAY_SECONDS} "
                f"seconds before next batch..."
            )

            time.sleep(
                PLAYER_BATCH_DELAY_SECONDS
            )


    # ========================================================
    # FETCH SUMMARY
    # ========================================================

    print()

    print(
        "========================================"
    )

    print(
        "       PROFILE FETCH COMPLETE"
    )

    print(
        "========================================"
    )


    print(
        f"Successful: "
        f"{len(full_profiles)}"
    )


    print(
        f"Failed: "
        f"{len(failed_profiles)}"
    )


    print(
        f"Skipped because not COD: "
        f"{len(skipped_profiles)}"
    )


    return (
        full_profiles,
        failed_profiles,
        skipped_profiles
    )


# ============================================================
# WRITE COD ACTIVITY SNAPSHOT
# ============================================================

def write_cod_activity(
    profiles
):

    print()

    print(
        "========================================"
    )

    print(
        "        WRITING COD ACTIVITY"
    )

    print(
        "========================================"
    )


    if not profiles:

        print(
            "No COD profiles to write."
        )

        return False


    captured_at = utc_now()


    rows = []


    # ========================================================
    # BUILD DATABASE ROWS
    # ========================================================

    for player in profiles:

        row = {

            "fid":
                str(
                    player[
                        "fid"
                    ]
                ),

            "player_name":
                player[
                    "name"
                ],

            "alliance":
                "COD",

            "state":
                STATE_ID,

            "furnace_level":
                (
                    str(
                        player[
                            "furnace_level"
                        ]
                    )
                    if player.get(
                        "furnace_level"
                    ) is not None
                    else None
                ),

            "total_power":
                int(
                    player.get(
                        "power",
                        0
                    )
                    or 0
                ),

            "kills":
                int(
                    player.get(
                        "kills",
                        0
                    )
                    or 0
                ),

            "labyrinth_score":
                int(
                    player.get(
                        "labyrinth_score",
                        0
                    )
                    or 0
                ),

            "active":
                player.get(
                    "active"
                ),

            "api_updated":
                (
                    player.get(
                        "updated_at"
                    )
                    or None
                ),

            "captured_at":
                captured_at
        }


        rows.append(
            row
        )


    # ========================================================
    # SUPABASE URL
    # ========================================================

    url = (
        f"{SUPABASE_URL}"
        f"/rest/v1/"
        f"{SUPABASE_TABLE}"
    )


    success_count = 0

    failed_count = 0


    # ========================================================
    # WRITE BATCHES
    # ========================================================

    for batch_number, batch in enumerate(
        chunks(
            rows,
            SUPABASE_BATCH_SIZE
        ),
        start=1
    ):

        headers = (
            SUPABASE_HEADERS.copy()
        )


        headers[
            "Prefer"
        ] = (
            "return=minimal"
        )


        print()

        print(
            f"Writing Supabase batch "
            f"{batch_number} "
            f"({len(batch)} rows)..."
        )


        try:

            response = requests.post(
                url,
                headers=headers,
                json=batch,
                timeout=30
            )

        except requests.RequestException as error:

            print(
                f"COD activity batch "
                f"{batch_number} "
                f"connection error:"
            )

            print(
                error
            )


            failed_count += len(
                batch
            )

            continue


        print(
            "Supabase HTTP:",
            response.status_code
        )


        # ====================================================
        # SUCCESS
        # ====================================================

        if response.status_code in (
            200,
            201,
            204
        ):

            success_count += len(
                batch
            )


            print(
                f"Batch "
                f"{batch_number}: "
                f"SUCCESS"
            )


            print(
                f"{len(batch)} "
                f"COD snapshots written."
            )


        # ====================================================
        # ERROR
        # ====================================================

        else:

            failed_count += len(
                batch
            )


            print(
                f"Batch "
                f"{batch_number}: "
                f"FAILED"
            )


            print(
                "HTTP:",
                response.status_code
            )


            print(
                response.text
            )


    # ========================================================
    # WRITE SUMMARY
    # ========================================================

    print()

    print(
        "----------------------------------------"
    )


    print(
        f"COD activity written: "
        f"{success_count}/"
        f"{len(rows)}"
    )


    if failed_count:

        print(
            f"Failed writes: "
            f"{failed_count}"
        )


    return (
        success_count
        == len(rows)
    )


# ============================================================
# VERIFY COD ACTIVITY
# ============================================================

def verify_cod_activity():

    print()

    print(
        "========================================"
    )

    print(
        "       VERIFYING COD ACTIVITY"
    )

    print(
        "========================================"
    )


    print(
        "Supabase URL:",
        SUPABASE_URL
    )

    print(
        "Table:",
        SUPABASE_TABLE
    )


    url = (
        f"{SUPABASE_URL}"
        f"/rest/v1/"
        f"{SUPABASE_TABLE}"
    )


    headers = {

        "apikey":
            SUPABASE_KEY,

        "Authorization":
            f"Bearer {SUPABASE_KEY}",

        "Accept":
            "application/json"

    }


    params = {

        "select":
            (
                "id,"
                "fid,"
                "player_name,"
                "total_power,"
                "kills,"
                "captured_at"
            ),

        "order":
            "captured_at.desc",

        "limit":
            "10"

    }


    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=30
        )


    except requests.RequestException as error:

        print(
            "Verification request failed:"
        )

        print(
            error
        )

        return False


    print(
        "Verification HTTP:",
        response.status_code
    )


    if response.status_code != 200:

        print(
            "Verification failed."
        )

        print(
            response.text
        )

        return False


    try:

        rows = (
            response.json()
        )

    except ValueError:

        print(
            "Verification returned "
            "invalid JSON."
        )

        print(
            response.text
        )

        return False


    print(
        "Rows returned:",
        len(rows)
    )


    if not rows:

        print()

        print(
            "WARNING:"
        )

        print(
            "Insert reported success, "
            "but cod_activity returned "
            "zero rows."
        )

        return False


    print()

    print(
        "LATEST DATABASE ROWS"
    )

    print(
        "----------------------------------------"
    )


    for row in rows:

        power = (
            row.get(
                "total_power",
                0
            )
            or 0
        )


        kills = (
            row.get(
                "kills",
                0
            )
            or 0
        )


        print(
            row.get(
                "player_name"
            ),
            "| FID:",
            row.get(
                "fid"
            ),
            "| Power:",
            f"{power:,}",
            "| Kills:",
            f"{kills:,}",
            "| Captured:",
            row.get(
                "captured_at"
            )
        )


    print()

    print(
        "COD activity verification SUCCESS."
    )


    return True


# ============================================================
# DISPLAY CURRENT COD PLAYERS
# ============================================================

def display_profiles(
    profiles
):

    print()

    print(
        "========================================"
    )

    print(
        "          COD CURRENT ROSTER"
    )

    print(
        "========================================"
    )


    sorted_profiles = sorted(
        profiles,
        key=lambda player:
            -(
                player.get(
                    "power",
                    0
                )
                or 0
            )
    )


    for position, player in enumerate(
        sorted_profiles,
        start=1
    ):

        print(
            f"{position:>3}. ",
            player[
                "name"
            ],
            "|",
            player[
                "fid"
            ],
            "| Power:",
            f'{player["power"]:,}',
            "| Kills:",
            f'{player["kills"]:,}',
            "| Furnace:",
            player[
                "furnace_level"
            ]
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print(
        "########################################"
    )

    print(
        "#                                      #"
    )

    print(
        "#        COD ACTIVITY COLLECTOR        #"
    )

    print(
        "#                                      #"
    )

    print(
        "########################################"
    )


    print()

    print(
        f"State: {STATE_ID}"
    )

    print(
        f"Alliance: "
        f"{TARGET_ALLIANCE}"
    )

    print(
        f"Started: "
        f"{utc_now()}"
    )


    # ========================================================
    # DATABASE DESTINATION
    # ========================================================

    print()

    print(
        "DATABASE DESTINATION"
    )

    print(
        "----------------------------------------"
    )

    print(
        "Supabase URL:",
        SUPABASE_URL
    )

    print(
        "Table:",
        SUPABASE_TABLE
    )

    print()


    # ========================================================
    # STEP 1
    # DISCOVER COD
    # ========================================================

    players = (
        discover_cod_players()
    )


    if not players:

        print()

        print(
            "No COD players discovered."
        )

        print(
            "Stopping."
        )

        return


    # ========================================================
    # STEP 2
    # FETCH FULL PROFILES
    # ========================================================

    (
        full_profiles,
        failed_profiles,
        skipped_profiles
    ) = fetch_full_player_profiles(
        players
    )


    if not full_profiles:

        print()

        print(
            "No full COD profiles "
            "were successfully fetched."
        )

        print(
            "Nothing will be written "
            "to Supabase."
        )

        return


    # ========================================================
    # STEP 3
    # DISPLAY CURRENT COD ROSTER
    # ========================================================

    display_profiles(
        full_profiles
    )


    # ========================================================
    # STEP 4
    # WRITE SNAPSHOT TO SUPABASE
    # ========================================================

    cod_activity_success = (
        write_cod_activity(
            full_profiles
        )
    )


    # ========================================================
    # STEP 5
    # VERIFY DATABASE
    # ========================================================

    verification_success = False


    if cod_activity_success:

        verification_success = (
            verify_cod_activity()
        )


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()

    print(
        "========================================"
    )

    print(
        "             RUN SUMMARY"
    )

    print(
        "========================================"
    )


    print(
        "COD roster discovered:",
        len(players)
    )


    print(
        "Profiles fetched:",
        len(full_profiles)
    )


    print(
        "Profile failures:",
        len(failed_profiles)
    )


    print(
        "No longer COD:",
        len(skipped_profiles)
    )


    print(
        "Supabase cod_activity:",
        (
            "SUCCESS"
            if cod_activity_success
            else "CHECK ERRORS"
        )
    )


    print(
        "Supabase verification:",
        (
            "SUCCESS"
            if verification_success
            else "CHECK ERRORS"
        )
    )


    print()

    print(
        "Finished:",
        utc_now()
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
# RUN
# ============================================================

if __name__ == "__main__":

    main()
