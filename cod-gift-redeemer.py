import os
import re
import time
import hashlib
from datetime import datetime, timezone

import requests
from supabase import create_client


# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

ALLIANCE = "COD"

GIFT_CODE_SOURCE = (
    "https://www.whiteoutsurvival-community.com/en/gift-codes.html"
)

WOS_BASE_URL = "https://wos-giftcode-api.centurygame.com"
WOS_REDEEM_URL = WOS_BASE_URL + "/api/gift_code"
WOS_ORIGIN = "https://wos-giftcode.centurygame.com"

WOS_ENCRYPT_KEY = "tB87#kPtkxqOS2"

PLAYER_DELAY = 1.25

TRANSPORT_RETRIES = 3
FID_RETRIES = 3

TOO_FREQUENT_DELAY = 60
MAX_COOLDOWNS = 3


# ============================================================
# SUPABASE
# ============================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# LOGGING
# ============================================================

def log(message):
    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
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
                "username": "COD Gift Codes",
                "content": content
            },
            timeout=20
        )

        if response.status_code not in (
            200,
            204
        ):
            log(
                "Discord webhook error: "
                f"{response.status_code} "
                f"{response.text[:200]}"
            )

    except Exception as exc:

        log(
            f"Discord webhook failed: {exc}"
        )


# ============================================================
# DISCOVER ACTIVE GIFT CODES
# ============================================================

def discover_gift_codes():

    log("Checking for active WOS gift codes...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/135.0 Safari/537.36"
        )
    }

    try:

        response = requests.get(
            GIFT_CODE_SOURCE,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

    except Exception as exc:

        log(
            f"Gift-code discovery failed: {exc}"
        )

        return []

    html = response.text


    # --------------------------------------------------------
    # Isolate active gift-code section when possible
    # --------------------------------------------------------

    active_section = html

    active_markers = [
        "Active gift codes",
        "Active Gift Codes",
        "active gift codes"
    ]

    for marker in active_markers:

        position = html.find(marker)

        if position >= 0:

            active_section = html[
                position:
                position + 50000
            ]

            break


    # --------------------------------------------------------
    # WSCO gift-code pages contain code values in several
    # HTML structures. Extract likely values.
    # --------------------------------------------------------

    candidates = set()


    patterns = [

        r'data-code=["\']([^"\']+)["\']',

        r'data-giftcode=["\']([^"\']+)["\']',

        r'<code[^>]*>\s*([^<\s]+)\s*</code>',

        r'Gift\s*[Cc]ode[^A-Za-z0-9]{0,100}'
        r'([A-Za-z0-9]{5,30})',

        r'Code:\s*</?[^>]*>?\s*'
        r'([A-Za-z0-9]{5,30})'
    ]


    for pattern in patterns:

        matches = re.findall(
            pattern,
            active_section,
            flags=re.IGNORECASE
        )

        for value in matches:

            code = str(value).strip()

            if valid_code_candidate(code):
                candidates.add(code)


    codes = sorted(candidates)

    log(
        f"Discovered {len(codes)} "
        "possible active gift code(s)."
    )

    for code in codes:
        log(f"  Gift code: {code}")

    return codes


def valid_code_candidate(code):

    if not code:
        return False

    if len(code) < 5:
        return False

    if len(code) > 30:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9]+",
        code
    ):
        return False


    blocked = {
        "discord",
        "facebook",
        "youtube",
        "instagram",
        "twitter",
        "whatsapp",
        "telegram",
        "copy",
        "redeem",
        "active",
        "expired",
        "giftcode",
        "whiteout",
        "survival"
    }

    if code.lower() in blocked:
        return False

    return True


# ============================================================
# GIFT CODE DATABASE
# ============================================================

def get_gift_code(code):

    result = (
        supabase
        .table("gift_codes")
        .select("*")
        .eq("code", code)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def create_gift_code(code):

    log(
        f"Writing new gift code "
        f"{code} to Supabase..."
    )

    result = (
        supabase
        .table("gift_codes")
        .insert({
            "code": code,
            "status": "pending",
            "submitted_by": "auto-discovery"
        })
        .execute()
    )

    if not result.data:
        raise RuntimeError(
            f"Could not create gift code {code}"
        )

    return result.data[0]


def update_gift_code(
    gift_id,
    **values
):

    (
        supabase
        .table("gift_codes")
        .update(values)
        .eq("id", gift_id)
        .execute()
    )


# ============================================================
# LOAD COD PLAYERS
# ============================================================

def load_cod_players():

    log(
        "Loading active COD players "
        "from Supabase..."
    )

    result = (
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

    players = result.data or []

    cleaned = []

    for player in players:

        fid = player.get("fid")
        state = player.get("state")

        if not fid:
            continue

        if not state:
            log(
                f"Skipping {fid}: "
                "no state in players table."
            )
            continue

        cleaned.append(player)


    cleaned.sort(
        key=lambda x: int(x["fid"])
    )


    log(
        f"Loaded {len(cleaned)} "
        "active COD players."
    )

    return cleaned


# ============================================================
# SIGN WOS REQUEST
# ============================================================

def encode_data(data):

    sorted_keys = sorted(
        data.keys()
    )

    encoded = "&".join(
        f"{key}={data[key]}"
        for key in sorted_keys
    )

    raw = (
        encoded +
        WOS_ENCRYPT_KEY
    )

    signature = hashlib.md5(
        raw.encode()
    ).hexdigest()

    return {
        "sign": signature,
        **data
    }


# ============================================================
# WOS REQUEST
# ============================================================

def redeem_once(
    fid,
    state,
    code
):

    payload = encode_data({

        "fid": str(fid),

        "cdk": code,

        "kid": str(state),

        "time": str(
            int(time.time())
        )

    })


    headers = {

        "accept":
            "application/json, text/plain, */*",

        "content-type":
            "application/x-www-form-urlencoded",

        "origin":
            WOS_ORIGIN,

        "referer":
            WOS_ORIGIN + "/",

        "user-agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/135.0 Safari/537.36"
    }


    for attempt in range(
        1,
        TRANSPORT_RETRIES + 1
    ):

        try:

            response = requests.post(

                WOS_REDEEM_URL,

                data=payload,

                headers=headers,

                timeout=(10, 30)
            )


            if response.status_code == 200:

                try:
                    return classify_response(
                        response.json()
                    )

                except ValueError:

                    return (
                        "failed",
                        "Invalid JSON response"
                    )


            if response.status_code in (
                429,
                502,
                503,
                504
            ):

                log(
                    f"{fid}: HTTP "
                    f"{response.status_code}; "
                    f"retry {attempt}/"
                    f"{TRANSPORT_RETRIES}"
                )

                time.sleep(
                    attempt * 3
                )

                continue


            return (
                "failed",
                "HTTP "
                f"{response.status_code}: "
                f"{response.text[:150]}"
            )


        except requests.RequestException as exc:

            log(
                f"{fid}: request error "
                f"{attempt}/"
                f"{TRANSPORT_RETRIES}: "
                f"{exc}"
            )

            if attempt < TRANSPORT_RETRIES:

                time.sleep(
                    attempt * 3
                )


    return (
        "failed",
        "WOS API request failed"
    )


# ============================================================
# CLASSIFY WOS RESPONSE
# ============================================================

def classify_response(data):

    message = str(
        data.get(
            "msg",
            "Unknown error"
        )
    ).strip(".")


    err_code = data.get(
        "err_code"
    )


    if message == "SUCCESS":

        return (
            "success",
            "Successfully redeemed"
        )


    if (
        message == "SAME TYPE EXCHANGE"
        and err_code == 40011
    ):

        return (
            "success",
            "Successfully redeemed"
        )


    if (
        message == "RECEIVED"
        and err_code == 40008
    ):

        return (
            "already_redeemed",
            "Already redeemed"
        )


    if (
        message == "TOO FREQUENT"
        and err_code == 40019
    ):

        return (
            "rate_limited",
            "Rate limited"
        )


    if (
        message == "USER INFO ERROR"
        and err_code == 40020
    ):

        return (
            "wrong_state",
            "Wrong state"
        )


    if (
        message == "TIME ERROR"
        and err_code == 40007
    ):

        return (
            "expired",
            "Code expired"
        )


    if (
        message == "CDK NOT FOUND"
        and err_code == 40014
    ):

        return (
            "invalid",
            "Code not found"
        )


    if (
        message == "USED"
        and err_code == 40005
    ):

        return (
            "claim_limit",
            "Claim limit reached"
        )


    if (
        message == "TIMEOUT RETRY"
        and err_code == 40004
    ):

        return (
            "retry",
            "Server requested retry"
        )


    if (
        message == "STOVE_LV ERROR"
        and err_code == 40006
    ):

        return (
            "failed",
            "Furnace level too low"
        )


    if (
        message == "RECHARGE_MONEY ERROR"
        and err_code == 40017
    ):

        return (
            "failed",
            "Spending requirement not met"
        )


    if (
        message == "RECHARGE_MONEY_VIP ERROR"
        and err_code == 40018
    ):

        return (
            "failed",
            "VIP requirement not met"
        )


    if (
        err_code == 40001
        and "not exist" in message.lower()
    ):

        return (
            "failed",
            "Player does not exist"
        )


    return (
        "failed",
        f"{message} ({err_code})"
    )


# ============================================================
# DATABASE REDEMPTION RECORD
# ============================================================

def existing_redemption(
    code,
    fid
):

    result = (
        supabase
        .table(
            "gift_code_redemptions"
        )
        .select("*")
        .eq(
            "code",
            code
        )
        .eq(
            "fid",
            int(fid)
        )
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def save_redemption(
    gift_code_id,
    code,
    player,
    status,
    message,
    attempts
):

    fid = int(
        player["fid"]
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()


    existing = existing_redemption(
        code,
        fid
    )


    payload = {

        "gift_code_id":
            gift_code_id,

        "code":
            code,

        "fid":
            fid,

        "player_name":
            player.get(
                "player_name"
            ),

        "alliance":
            player.get(
                "alliance"
            ),

        "state":
            int(
                player["state"]
            ),

        "status":
            status,

        "message":
            message,

        "attempts":
            attempts,

        "last_attempt_at":
            now
    }


    if status == "success":

        payload[
            "redeemed_at"
        ] = now


    if existing:

        if not existing.get(
            "first_attempt_at"
        ):
            payload[
                "first_attempt_at"
            ] = now

        (
            supabase
            .table(
                "gift_code_redemptions"
            )
            .update(payload)
            .eq(
                "id",
                existing["id"]
            )
            .execute()
        )

    else:

        payload[
            "first_attempt_at"
        ] = now

        (
            supabase
            .table(
                "gift_code_redemptions"
            )
            .insert(payload)
            .execute()
        )


# ============================================================
# REDEEM FOR ONE PLAYER
# ============================================================

def redeem_player(
    gift_code_id,
    code,
    player
):

    fid = str(
        player["fid"]
    )

    state = int(
        player["state"]
    )

    name = (
        player.get("player_name")
        or fid
    )


    cooldown_count = 0

    attempt = 0


    while attempt < FID_RETRIES:

        attempt += 1


        status, message = redeem_once(
            fid,
            state,
            code
        )


        log(
            f"{name} ({fid}) | "
            f"{status} | "
            f"{message}"
        )


        if status == "rate_limited":

            cooldown_count += 1


            if (
                cooldown_count
                <= MAX_COOLDOWNS
            ):

                log(
                    f"{fid}: waiting "
                    f"{TOO_FREQUENT_DELAY}s "
                    "before retry."
                )

                time.sleep(
                    TOO_FREQUENT_DELAY
                )

                attempt -= 1

                continue


        if status == "retry":

            if attempt < FID_RETRIES:

                time.sleep(
                    attempt * 2
                )

                continue


        save_redemption(
            gift_code_id,
            code,
            player,
            status,
            message,
            attempt
        )


        return (
            status,
            message
        )


    save_redemption(
        gift_code_id,
        code,
        player,
        "failed",
        "Maximum retries reached",
        attempt
    )


    return (
        "failed",
        "Maximum retries reached"
    )


# ============================================================
# PROCESS ONE CODE
# ============================================================

def process_code(
    gift_record,
    players
):

    gift_id = gift_record["id"]
    code = gift_record["code"]


    log(
        "=" * 60
    )

    log(
        f"PROCESSING GIFT CODE: {code}"
    )

    log(
        "=" * 60
    )


    now = datetime.now(
        timezone.utc
    ).isoformat()


    update_gift_code(

        gift_id,

        status="processing",

        started_at=now,

        total_players=len(players)
    )


    totals = {

        "success": 0,

        "already_redeemed": 0,

        "wrong_state": 0,

        "failed": 0

    }


    fatal_status = None


    for index, player in enumerate(
        players,
        start=1
    ):

        fid = player["fid"]

        name = (
            player.get(
                "player_name"
            )
            or str(fid)
        )


        log(
            f"[{index}/{len(players)}] "
            f"{name} | "
            f"FID {fid} | "
            f"
