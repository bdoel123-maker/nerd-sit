import os
import csv
import time
import requests
from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

API_TOKEN = os.getenv("WOSORACLE_API_TOKEN")

if not API_TOKEN:
    raise RuntimeError("Missing WOSORACLE_API_TOKEN")

BASE_URL = "https://wosoracle.com/api/v1"

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN.strip()}",
    "Accept": "application/json",
}


# ============================================================
# PLAYERS BY GROUP
# ============================================================

PLAYER_GROUPS = {

    # ========================================================
    # 300
    # ========================================================

    "300": {
        343838722: "MelBrad",
        343183290: "wesam king1983",
        342347697: "CatDaddy",
        342832223: "HUNTER CLAN",
        339833256: "MinnieMe",
        483142309: "sparkong",
        339844246: "Warboy22",
        362486268: "Rozana",
    },


    # ========================================================
    # WET
    # ========================================================

    "WET": {
        254969117: "nebula",
        254723316: "Yams",
        281453401: "NinjaCat",
        253461751: "Rilax",
        302613181: "Dobby",
        277449539: "Oxnaive",
        253445229: "Agnar",
        320271058: "Oxigen",
        254461369: "janoski",
        255362395: "Eskanax",
        348685514: "Tehanu",
    },


    # ========================================================
    # COD
    # ========================================================

    "COD": {
        295463775: "Smaug",
        304107106: "ArtofGhost",
        309655718: "Sera",
        308181409: "DK",
        305028156: "Czar*",
        302194607: "Wiggle",
        331965858: "Luna",
        307968328: "Teizen",
        242846693: "Hannibal",
        239553250: "Snowball",
        240339491: "Ottaria",
        235613099: "Waz",
        242698529: "TeeJay",
        232478285: "Mad",
        240011554: "Sonny",
        232921068: "Nightmare",
    },


    # ========================================================
    # ONF
    # ========================================================

    "ONF": {
        361345469: "Age",
        354940450: "DragonPop",
        266741049: "Analbuttketchup",
    },
}


# ============================================================
# FURNACE / FIRE CRYSTAL CONVERSION
# ============================================================

def convert_furnace_level(raw_level):

    if raw_level is None:
        return None

    try:
        level = int(raw_level)

    except (ValueError, TypeError):
        return str(raw_level)

    if level < 30:
        return f"Furnace {level}"

    if 30 <= level <= 34:
        return "FC1"

    if 35 <= level <= 39:
        return "FC2"

    if 40 <= level <= 44:
        return "FC3"

    if 45 <= level <= 49:
        return "FC4"

    if 50 <= level <= 54:
        return "FC5"

    if 55 <= level <= 59:
        return "FC6"

    if 60 <= level <= 64:
        return "FC7"

    if 65 <= level <= 69:
        return "FC8"

    if 70 <= level <= 74:
        return "FC9"

    if 75 <= level <= 79:
        return "FC10"

    return f"Raw {level}"


# ============================================================
# API REQUEST
# ============================================================

def api_get(endpoint):

    url = f"{BASE_URL}{endpoint}"

    for attempt in range(5):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            if response.status_code == 200:

                try:
                    return response.json()

                except ValueError:

                    print(
                        f"Invalid JSON returned for {endpoint}"
                    )

                    return None


            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if response.status_code == 429:

                wait = (attempt + 1) * 10

                print(
                    f"Rate limited. Waiting {wait} seconds..."
                )

                time.sleep(wait)

                continue


            # ------------------------------------------------
            # OTHER HTTP ERROR
            # ------------------------------------------------

            print(
                f"HTTP {response.status_code} "
                f"for {endpoint}: "
                f"{response.text[:300]}"
            )

            return None


        except requests.RequestException as exc:

            wait = (attempt + 1) * 5

            print(
                f"Network error: {exc}"
            )

            print(
                f"Waiting {wait} seconds..."
            )

            time.sleep(wait)


    print(
        f"Maximum retries reached for {endpoint}"
    )

    return None


# ============================================================
# HELPERS
# ============================================================

def unwrap(data):

    if (
        isinstance(data, dict)
        and isinstance(data.get("data"), dict)
    ):

        return data["data"]

    if isinstance(data, dict):

        return data

    return {}


def first_value(data, *keys):

    if not isinstance(data, dict):

        return None

    for key in keys:

        value = data.get(key)

        if value is not None:

            return value

    return None


# ============================================================
# GET PLAYER PROFILE
# ============================================================

def get_player(fid):

    data = api_get(
        f"/players/{fid}"
    )

    if not data:

        return {}

    return unwrap(data)


# ============================================================
# GET PLAYER STANDINGS
# ============================================================

def get_standings(fid):

    data = api_get(
        f"/players/{fid}/standings"
    )

    if not data:

        return {}

    return data


# ============================================================
# PARSE STANDINGS
# ============================================================

def parse_standings(data):

    result = {

        "total_power": None,

        "kills": None,

        "furnace_level": None,

    }


    entries = []


    # --------------------------------------------------------
    # RESPONSE IS DIRECT LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        entries = data


    # --------------------------------------------------------
    # RESPONSE WRAPPED IN DICTIONARY
    # --------------------------------------------------------

    elif isinstance(data, dict):

        for key in [

            "data",

            "standings",

            "rankings",

            "results",

        ]:

            value = data.get(key)

            if isinstance(value, list):

                entries = value

                break


    # --------------------------------------------------------
    # READ STANDINGS
    # --------------------------------------------------------

    for row in entries:

        if not isinstance(row, dict):

            continue


        category = str(

            first_value(

                row,

                "category",

                "name",

                "type",

                "ranking",

                "leaderboard"

            )

            or ""

        ).lower()


        score = first_value(

            row,

            "score",

            "value",

            "power",

            "amount"

        )


        if (

            "personal power" in category

            or category == "power"

        ):

            result["total_power"] = score


        elif "kill" in category:

            result["kills"] = score


        elif "furnace" in category:

            result["furnace_level"] = score


    return result


# ============================================================
# BUILD PLAYER ROW
# ============================================================

def build_player_row(
    group,
    fid,
    expected_name
):

    print()

    print("=" * 70)

    print(
        f"[{group}] "
        f"Pulling {expected_name} "
        f"- {fid}"
    )

    print("=" * 70)


    # ========================================================
    # PLAYER PROFILE
    # ========================================================

    profile = get_player(fid)


    if not profile:

        print(
            "Player profile not found."
        )

        return {

            "group":
                group,

            "fid":
                fid,

            "expected_name":
                expected_name,

            "player_name":
                None,

            "state":
                None,

            "alliance":
                None,

            "raw_furnace_level":
                None,

            "furnace_level":
                None,

            "total_power":
                None,

            "hero_power":
                None,

            "hero_gear_power":
                None,

            "pet_power":
                None,

            "expert_power":
                None,

            "island_prosperity":
                None,

            "kills":
                None,

        }


    # ========================================================
    # STANDINGS
    # ========================================================

    standings_raw = get_standings(fid)

    standings = parse_standings(
        standings_raw
    )


    # ========================================================
    # RAW FURNACE
    # ========================================================

    raw_furnace = (

        first_value(

            profile,

            "furnace_level",

            "furnaceLevel",

            "furnace"

        )

        or standings.get(
            "furnace_level"
        )

    )


    # ========================================================
    # BUILD OUTPUT
    # ========================================================

    row = {


        # ----------------------------------------------------
        # GROUP
        # ----------------------------------------------------

        "group":
            group,


        # ----------------------------------------------------
        # FID
        # ----------------------------------------------------

        "fid":
            fid,


        # ----------------------------------------------------
        # PROVIDED NAME
        # ----------------------------------------------------

        "expected_name":
            expected_name,


        # ----------------------------------------------------
        # CURRENT PLAYER NAME
        # ----------------------------------------------------

        "player_name":

            first_value(

                profile,

                "player_name",

                "name",

                "nickname",

                "player"

            ),


        # ----------------------------------------------------
        # STATE
        # ----------------------------------------------------

        "state":

            first_value(

                profile,

                "state",

                "state_id",

                "server"

            ),


        # ----------------------------------------------------
        # ALLIANCE
        # ----------------------------------------------------

        "alliance":

            first_value(

                profile,

                "alliance",

                "alliance_name",

                "alliance_tag"

            ),


        # ----------------------------------------------------
        # RAW FURNACE
        # ----------------------------------------------------

        "raw_furnace_level":
            raw_furnace,


        # ----------------------------------------------------
        # DISPLAY FURNACE / FC
        # ----------------------------------------------------

        "furnace_level":

            convert_furnace_level(
                raw_furnace
            ),


        # ----------------------------------------------------
        # TOTAL POWER
        #
        # Oracle Power -> Total Power
        # ----------------------------------------------------

        "total_power":

            first_value(

                profile,

                "power",

                "total_power",

                "totalPower"

            )

            or standings.get(
                "total_power"
            ),


        # ----------------------------------------------------
        # HERO POWER
        #
        # Oracle Stage Power -> Hero Power
        # ----------------------------------------------------

        "hero_power":

            first_value(

                profile,

                "stage_power",

                "stagePower",

                "hero_power",

                "heroPower"

            ),


        # ----------------------------------------------------
        # HERO GEAR POWER
        #
        # Oracle Star Power -> Hero Gear Power
        # ----------------------------------------------------

        "hero_gear_power":

            first_value(

                profile,

                "star_power",

                "starPower",

                "hero_gear_power",

                "heroGearPower"

            ),


        # ----------------------------------------------------
        # PET POWER
        # ----------------------------------------------------

        "pet_power":

            first_value(

                profile,

                "pet_power",

                "petPower"

            ),


        # ----------------------------------------------------
        # EXPERT POWER
        #
        # Oracle Master Total Power -> Expert Power
        # ----------------------------------------------------

        "expert_power":

            first_value(

                profile,

                "master_total_power",

                "masterTotalPower",

                "expert_power",

                "expertPower"

            ),


        # ----------------------------------------------------
        # ISLAND PROSPERITY
        # ----------------------------------------------------

        "island_prosperity":

            first_value(

                profile,

                "island_prosperity",

                "islandProsperity"

            ),


        # ----------------------------------------------------
        # KILLS
        # ----------------------------------------------------

        "kills":

            first_value(

                profile,

                "kills",

                "kill_count",

                "killCount"

            )

            or standings.get(
                "kills"
            ),

    }


    return row


# ============================================================
# MAIN
# ============================================================

def main():

    results = []


    print()

    print(
        "============================================================"
    )

    print(
        "          WOS ORACLE GROUP PLAYER DATA PULL"
    )

    print(
        "============================================================"
    )


    # ========================================================
    # COUNT PLAYERS
    # ========================================================

    total_players = sum(

        len(players)

        for players
        in PLAYER_GROUPS.values()

    )


    print()

    print(
        f"Total players to pull: "
        f"{total_players}"
    )


    print()

    for group, players in PLAYER_GROUPS.items():


        # ====================================================
        # GROUP HEADER
        # ====================================================

        print()

        print(
            "#" * 70
        )

        print(
            f"GROUP: {group}"
        )

        print(
            f"PLAYERS: {len(players)}"
        )

        print(
            "#" * 70
        )


        # ====================================================
        # PLAYERS
        # ====================================================

        for fid, expected_name in players.items():


            row = build_player_row(

                group,

                fid,

                expected_name

            )


            results.append(row)


            # =================================================
            # PRINT RESULT
            # =================================================

            print()

            print(
                f"[{group}] "
                f"{row['player_name'] or expected_name}"
            )


            print(
                f"FID: "
                f"{fid}"
            )


            print(
                f"Alliance: "
                f"{row['alliance']}"
            )


            print(
                f"State: "
                f"{row['state']}"
            )


            print(
                f"Furnace: "
                f"{row['furnace_level']} "
                f"(raw {row['raw_furnace_level']})"
            )


            print(
                f"Total Power: "
                f"{row['total_power']}"
            )


            print(
                f"Hero Power: "
                f"{row['hero_power']}"
            )


            print(
                f"Hero Gear Power: "
                f"{row['hero_gear_power']}"
            )


            print(
                f"Pet Power: "
                f"{row['pet_power']}"
            )


            print(
                f"Expert Power: "
                f"{row['expert_power']}"
            )


            print(
                f"Island Prosperity: "
                f"{row['island_prosperity']}"
            )


            print(
                f"Kills: "
                f"{row['kills']}"
            )


            # =================================================
            # API DELAY
            # =================================================

            time.sleep(1)


    # ========================================================
    # SAVE CSV
    # ========================================================

    filename = "requested_players.csv"


    fieldnames = [

        "group",

        "fid",

        "expected_name",

        "player_name",

        "state",

        "alliance",

        "raw_furnace_level",

        "furnace_level",

        "total_power",

        "hero_power",

        "hero_gear_power",

        "pet_power",

        "expert_power",

        "island_prosperity",

        "kills",

    ]


    with open(

        filename,

        "w",

        newline="",

        encoding="utf-8-sig"

    ) as file:


        writer = csv.DictWriter(

            file,

            fieldnames=fieldnames

        )


        writer.writeheader()


        writer.writerows(
            results
        )


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()

    print(
        "============================================================"
    )

    print(
        "COMPLETE"
    )

    print(
        "============================================================"
    )


    print()

    print(
        f"Saved {len(results)} players "
        f"to {filename}"
    )


    print()

    print(
        "GROUP SUMMARY"
    )

    print(
        "------------------------------------------------------------"
    )


    for group, players in PLAYER_GROUPS.items():


        group_results = [

            row

            for row in results

            if row["group"] == group

        ]


        successful = len([

            row

            for row in group_results

            if row["player_name"] is not None

        ])


        failed = (
            len(players)
            - successful
        )


        print(

            f"{group}: "

            f"{successful}/{len(players)} returned"

            f" | Failed: {failed}"

        )


    print()

    print(
        "============================================================"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
