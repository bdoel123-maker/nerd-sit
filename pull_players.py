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
    raise RuntimeError("Missing WOSORACLE_API_TOKEN in .env")

BASE_URL = "https://wosoracle.com/api/v1"

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN.strip()}",
    "Accept": "application/json",
}


# ============================================================
# PLAYERS
# ============================================================

PLAYERS = {
    343838722: "MelBrad",
    343183290: "wesam king1983",
    342347697: "CatDaddy",
    342832223: "HUNTER CLAN",
    339833256: "MinnieMe",
    483142309: "sparkong",
    339844246: "Warboy22",
    362486268: "Rozana",
}


# ============================================================
# FURNACE / FC CONVERSION
# ============================================================

def convert_furnace_level(raw_level):
    """
    Converts WOS Oracle raw furnace level into readable FC level.

    30-34 = FC1
    35-39 = FC2
    40-44 = FC3
    45-49 = FC4
    50-54 = FC5
    55-59 = FC6
    60-64 = FC7
    65-69 = FC8
    70-74 = FC9
    75-79 = FC10
    """

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

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:

                wait = (attempt + 1) * 10

                print(
                    f"Rate limited. Waiting {wait} seconds..."
                )

                time.sleep(wait)
                continue

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
# PLAYER PROFILE
# ============================================================

def get_player(fid):

    data = api_get(
        f"/players/{fid}"
    )

    if not data:
        return {}

    return unwrap(data)


# ============================================================
# STANDINGS
# ============================================================

def get_standings(fid):

    data = api_get(
        f"/players/{fid}/standings"
    )

    if not data:
        return {}

    return data


def parse_standings(data):

    result = {
        "total_power": None,
        "kills": None,
        "furnace_level": None
    }

    entries = []

    if isinstance(data, list):

        entries = data

    elif isinstance(data, dict):

        for key in [
            "data",
            "standings",
            "rankings",
            "results"
        ]:

            value = data.get(key)

            if isinstance(value, list):

                entries = value
                break

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
            ) or ""
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

def build_player_row(fid, expected_name):

    print()
    print("=" * 65)
    print(
        f"Pulling {expected_name} - {fid}"
    )
    print("=" * 65)

    profile = get_player(fid)

    if not profile:

        print("Player profile not found.")

        return {
            "fid": fid,
            "expected_name": expected_name,
            "player_name": None,
            "state": None,
            "alliance": None,
            "raw_furnace_level": None,
            "furnace_level": None,
            "total_power": None,
            "kills": None,
            "hero_power": None,
            "hero_gear_power": None,
            "pet_power": None,
            "expert_power": None,
            "island_prosperity": None,
        }

    standings_raw = get_standings(fid)

    standings = parse_standings(
        standings_raw
    )


    # ========================================================
    # RAW FURNACE LEVEL
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

        "fid":
            fid,

        "expected_name":
            expected_name,

        "player_name":
            first_value(
                profile,
                "player_name",
                "name",
                "nickname",
                "player"
            ),

        "state":
            first_value(
                profile,
                "state",
                "state_id",
                "server"
            ),

        "alliance":
            first_value(
                profile,
                "alliance",
                "alliance_name",
                "alliance_tag"
            ),

        "raw_furnace_level":
            raw_furnace,

        "furnace_level":
            convert_furnace_level(
                raw_furnace
            ),

        # Power = Total Power
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

        # Stage Power -> Hero Power
        "hero_power":
            first_value(
                profile,
                "stage_power",
                "stagePower",
                "hero_power",
                "heroPower"
            ),

        # Star Power -> Hero Gear Power
        "hero_gear_power":
            first_value(
                profile,
                "star_power",
                "starPower",
                "hero_gear_power",
                "heroGearPower"
            ),

        "pet_power":
            first_value(
                profile,
                "pet_power",
                "petPower"
            ),

        # Master Total Power -> Expert Power
        "expert_power":
            first_value(
                profile,
                "master_total_power",
                "masterTotalPower",
                "expert_power",
                "expertPower"
            ),

        "island_prosperity":
            first_value(
                profile,
                "island_prosperity",
                "islandProsperity"
            ),
    }

    return row


# ============================================================
# MAIN
# ============================================================

def main():

    results = []

    print()
    print("==================================================")
    print("          WOS ORACLE PLAYER DATA PULL")
    print("==================================================")

    for fid, expected_name in PLAYERS.items():

        row = build_player_row(
            fid,
            expected_name
        )

        results.append(row)

        print()

        print(
            f"{row['player_name'] or expected_name}"
        )

        print(
            f"FID: {fid}"
        )

        print(
            f"Alliance: {row['alliance']}"
        )

        print(
            f"State: {row['state']}"
        )

        print(
            f"Furnace: "
            f"{row['furnace_level']} "
            f"(raw {row['raw_furnace_level']})"
        )

        print(
            f"Power: {row['total_power']}"
        )

        print(
            f"Hero Power: {row['hero_power']}"
        )

        print(
            f"Hero Gear Power: "
            f"{row['hero_gear_power']}"
        )

        print(
            f"Pet Power: {row['pet_power']}"
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
            f"Kills: {row['kills']}"
        )

        time.sleep(1)


    # ========================================================
    # CSV
    # ========================================================

    filename = "requested_players.csv"

    fieldnames = [
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


    print()
    print("==================================================")
    print("COMPLETE")
    print("==================================================")

    print(
        f"Saved {len(results)} players "
        f"to {filename}"
    )


if __name__ == "__main__":
    main()
