# ============================================================
# COD AUTOMATIC WOS GIFT CODE REDEEMER
# State 2348
#
# Flow:
#   1. Discover active public WOS gift codes
#   2. Save new codes to Supabase
#   3. Load active COD players
#   4. Redeem codes
#   5. Save individual results
#   6. Update gift-code totals
#   7. Post Discord webhook summary
#
# Designed for GitHub Actions every 6 hours.
# ============================================================

import os
import re
import time
import hashlib
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing.")


# ============================================================
# CONFIG
# ============================================================

ALLIANCE = "COD"

DEFAULT_STATE = 2348


# ------------------------------------------------------------
# WOS API
# ------------------------------------------------------------

WOS_BASE_URL = (
    "https://wos-giftcode-api.centurygame.com"
)

WOS_REDEEM_URL = (
    WOS_BASE_URL + "/api/gift_code"
)

WOS_ORIGIN = (
    "https://wos-giftcode.centurygame.com"
)

WOS_ENCRYPT_KEY = (
    "tB87#kPtkxqOS2"
)


# ------------------------------------------------------------
# PUBLIC CODE SOURCE
# ------------------------------------------------------------

CODE_SOURCE_URL = (
    "https://www.whiteoutsurvival-community.com/"
    "en/gift-codes.html"
)


# ------------------------------------------------------------
# TIMING
# ------------------------------------------------------------

PLAYER_DELAY = 1.25

TRANSPORT_RETRIES = 3

TRANSPORT_RETRY_DELAY = 3

RATE_LIMIT_WAIT = 60

MAX_RATE_LIMIT_RETRIES = 3


# ============================================================
# SUPABASE
# ============================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()


session.headers.update({

    "accept":
        "application/json, text/plain, */*",

    "accept-language":
        "en-US,en;q=0.9",

    "content-type":
        "application/x-www-form-urlencoded",

    "origin":
        WOS_ORIGIN,

    "referer":
        WOS_ORIGIN + "/",

    "user-agent":
        (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/153.0.0.0 "
            "Safari/537.36"
        ),

})


# ============================================================
# LOGGING
# ============================================================

def log(message):

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    print(
        f"{timestamp} | {message}",
        flush=True
    )


# ============================================================
# DISCORD
# ============================================================

def discord_message(content):

    if not DISCORD_WEBHOOK_URL:

        log(
            "DISCORD_WEBHOOK_URL not configured. "
            "Skipping Discord message."
        )

        return

    try:

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={
                "content": content
            },
            timeout=20
        )

        if response.status_code not in (
            200,
            204
        ):

            log(
                "Discord webhook error "
                f"{response.status_code}: "
                f"{response.text[:200]}"
            )

    except Exception as exc:

        log(
            f"Discord webhook failed: {exc}"
        )


# ============================================================
# GIFT CODE DISCOVERY
# ============================================================

def discover_gift_codes():

    log(
        "Checking public WOS gift-code source..."
    )

    try:

        response = requests.get(
            CODE_SOURCE_URL,
            headers={
                "User-Agent":
                    (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/153.0 Safari/537.36"
                    )
            },
            timeout=30
        )

        response.raise_for_status()

    except Exception as exc:

        log(
            f"Gift-code discovery failed: {exc}"
        )

        return []


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    discovered = []


    # --------------------------------------------------------
    # PRIMARY METHOD
    #
    # WSCO currently presents gift codes inside code elements.
    # --------------------------------------------------------

    for element in soup.find_all("code"):

        value = element.get_text(
            strip=True
        )

        if is_possible_code(value):

            discovered.append(
                value
            )


    # --------------------------------------------------------
    # FALLBACK
    #
    # Look for gift-code card text if site HTML changes slightly.
    # --------------------------------------------------------

    if not discovered:

        text = soup.get_text(
            "\n",
            strip=True
        )

        matches = re.findall(
            r"Gift code\s+([A-Za-z0-9_-]{4,40})",
            text,
            flags=re.IGNORECASE
        )

        discovered.extend(
            matches
        )


    # --------------------------------------------------------
    # DEDUPLICATE
    # --------------------------------------------------------

    clean_codes = []

    seen = set()


    for code in discovered:

        code = code.strip()

        key = code.lower()

        if key in seen:
            continue

        seen.add(key)

        clean_codes.append(
            code
        )


    log(
        f"Discovered {len(clean_codes)} "
        "public gift code(s)."
    )


    for code in clean_codes:

        log(
            f"  Gift code: {code}"
        )


    return clean_codes


def is_possible_code(value):

    if not value:
        return False

    if len(value) < 4:
        return False

    if len(value) > 40:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9_-]+",
        value
    ):
        return False


    blocked = {
        "android",
        "ios",
        "discord",
        "copy",
        "redeem",
        "giftcode",
        "giftcodes",
    }


    if value.lower() in blocked:
        return False


    return True


# ============================================================
# SUPABASE - GIFT CODES
# ============================================================

def get_existing_code(code):

    response = (
        supabase
        .table("gift_codes")
        .select("*")
        .eq("code", code)
        .limit(1)
        .execute()
    )


    if response.data:

        return response.data[0]


    return None


def create_gift_code(code):

    log(
        f"Writing new gift code "
        f"{code} to Supabase..."
    )


    response = (
        supabase
        .table("gift_codes")
        .insert({

            "code":
                code,

            "status":
                "pending",

            "submitted_by":
                "automatic",

            "submitted_by_id":
                "github-actions",

        })
        .execute()
    )


    if not response.data:

        raise RuntimeError(
            f"Could not create gift code {code}"
        )


    return response.data[0]


# ============================================================
# LOAD COD PLAYERS
# ============================================================

def get_cod_players():

    log(
        "Loading active COD players "
        "from Supabase..."
    )


    response = (
        supabase
        .table("players")
        .select(
            "fid,"
            "player_name,"
            "alliance,"
            "state,"
            "active"
        )
        .eq(
            "alliance",
            ALLIANCE
        )
        .eq(
            "active",
            True
        )
        .execute()
    )


    players = response.data or []


    # --------------------------------------------------------
    # VALIDATE / DEDUPLICATE
    # --------------------------------------------------------

    cleaned = {}

    for player in players:

        fid = player.get(
            "fid"
        )

        if fid is None:
            continue


        fid = str(
            fid
        ).strip()


        if not fid.isdigit():
            continue


        state = player.get(
            "state"
        )


        if state is None:

            state = DEFAULT_STATE


        try:

            state = int(
                state
            )

        except Exception:

            state = DEFAULT_STATE


        cleaned[fid] = {

            "fid":
                fid,

            "player_name":
                player.get(
                    "player_name"
                )
                or
                f"Player {fid}",

            "alliance":
                ALLIANCE,

            "state":
                state,

        }


    result = list(
        cleaned.values()
    )


    result.sort(
        key=lambda p: int(
            p["fid"]
        )
    )


    log(
        f"Loaded {len(result)} "
        "active COD player(s)."
    )


    return result


# ============================================================
# WOS SIGNATURE
# ============================================================

def sign_payload(data):

    sorted_keys = sorted(
        data.keys()
    )


    encoded = "&".join(

        f"{key}={data[key]}"

        for key in sorted_keys

    )


    raw = (
        encoded
        +
        WOS_ENCRYPT_KEY
    )


    signature = hashlib.md5(
        raw.encode()
    ).hexdigest()


    return {

        "sign":
            signature,

        **data

    }


# ============================================================
# WOS RESPONSE CLASSIFICATION
# ============================================================

def classify_response(data):

    msg = str(
        data.get(
            "msg",
            "UNKNOWN"
        )
    ).strip(
        "."
    )


    err_code = data.get(
        "err_code"
    )


    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if msg == "SUCCESS":

        return (
            "success",
            "Successfully redeemed"
        )


    if (
        msg == "SAME TYPE EXCHANGE"
        and
        err_code == 40011
    ):

        return (
            "success",
            "Successfully redeemed"
        )


    # --------------------------------------------------------
    # ALREADY REDEEMED
    # --------------------------------------------------------

    if (
        msg == "RECEIVED"
        and
        err_code == 40008
    ):

        return (
            "already_redeemed",
            "Already redeemed"
        )


    # --------------------------------------------------------
    # WRONG STATE
    # --------------------------------------------------------

    if (
        msg == "USER INFO ERROR"
        and
        err_code == 40020
    ):

        return (
            "wrong_state",
            "Wrong state for player"
        )


    # --------------------------------------------------------
    # RATE LIMIT
    # --------------------------------------------------------

    if (
        msg == "TOO FREQUENT"
        and
        err_code == 40019
    ):

        return (
            "rate_limited",
            "Too frequent"
        )


    # --------------------------------------------------------
    # SERVER ASKS US TO RETRY
    # --------------------------------------------------------

    if (
        msg == "TIMEOUT RETRY"
        and
        err_code == 40004
    ):

        return (
            "retry",
            "Server requested retry"
        )


    # --------------------------------------------------------
    # EXPIRED
    # --------------------------------------------------------

    if (
        msg == "TIME ERROR"
        and
        err_code == 40007
    ):

        return (
            "expired",
            "Gift code expired"
        )


    # --------------------------------------------------------
    # INVALID
    # --------------------------------------------------------

    if (
        msg == "CDK NOT FOUND"
        and
        err_code == 40014
    ):

        return (
            "invalid",
            "Gift code not found"
        )


    # --------------------------------------------------------
    # GLOBAL CLAIM LIMIT
    # --------------------------------------------------------

    if (
        msg == "USED"
        and
        err_code == 40005
    ):

        return (
            "claim_limit",
            "Gift code claim limit reached"
        )


    # --------------------------------------------------------
    # PLAYER DOES NOT EXIST
    # --------------------------------------------------------

    if (
        err_code == 40001
        and
        "not exist" in msg.lower()
    ):

        return (
            "failed",
            "Player does not exist"
        )


    # --------------------------------------------------------
    # FURNACE REQUIREMENT
    # --------------------------------------------------------

    if (
        msg == "STOVE_LV ERROR"
        and
        err_code == 40006
    ):

        return (
            "failed",
            "Furnace level too low"
        )


    # --------------------------------------------------------
    # SPENDING REQUIREMENT
    # --------------------------------------------------------

    if (
        msg == "RECHARGE_MONEY ERROR"
        and
        err_code == 40017
    ):

        return (
            "failed",
            "Spending requirement not met"
        )


    # --------------------------------------------------------
    # VIP REQUIREMENT
    # --------------------------------------------------------

    if (
        msg == "RECHARGE_MONEY_VIP ERROR"
        and
        err_code == 40018
    ):

        return (
            "failed",
            "VIP requirement not met"
        )


    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    return (
        "failed",
        f"{msg} ({err_code})"
    )


# ============================================================
# REDEEM ONE REQUEST
# ============================================================

def redeem_request(
    fid,
    state,
    code
):

    payload = sign_payload({

        "fid":
            str(fid),

        "cdk":
            str(code),

        "kid":
            str(state),

        "time":
            str(
                int(
                    time.time()
                )
            ),

    })


    for attempt in range(
        1,
        TRANSPORT_RETRIES + 1
    ):

        try:

            response = session.post(

                WOS_REDEEM_URL,

                data=payload,

                timeout=30

            )


            # -----------------------------------------------
            # HTTP RATE LIMIT
            # -----------------------------------------------

            if response.status_code == 429:

                log(
                    "HTTP 429. "
                    f"Transport retry {attempt}/"
                    f"{TRANSPORT_RETRIES}"
                )

                time.sleep(
                    TRANSPORT_RETRY_DELAY
                    *
                    attempt
                )

                continue


            # -----------------------------------------------
            # TEMPORARY SERVER ERRORS
            # -----------------------------------------------

            if response.status_code in (
                502,
                503,
                504
            ):

                log(
                    f"HTTP {response.status_code}. "
                    "Retrying..."
                )

                time.sleep(
                    TRANSPORT_RETRY_DELAY
                    *
                    attempt
                )

                continue


            if response.status_code != 200:

                return (
                    "failed",
                    (
                        f"HTTP "
                        f"{response.status_code}: "
                        f"{response.text[:150]}"
                    )
                )


            try:

                data = response.json()

            except Exception:

                return (
                    "failed",
                    "WOS returned invalid JSON"
                )


            return classify_response(
                data
            )


        except requests
