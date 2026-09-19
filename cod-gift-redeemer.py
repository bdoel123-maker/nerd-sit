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

CODE_SOURCE_URL = "https://wosoracle.com/api/codes"


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
        "Checking WOS Oracle for active gift codes..."
    )

    try:

        response = requests.get(
            CODE_SOURCE_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "COD-Gift-Code-Redeemer/1.0",
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:

        log(
            f"WOS Oracle gift-code request failed: {exc}"
        )

        return []

    except ValueError as exc:

        log(
            f"WOS Oracle returned invalid JSON: {exc}"
        )

        return []


    if not isinstance(data, list):

        log(
            "Unexpected WOS Oracle response format. "
            "Expected a list."
        )

        return []


    active_codes = []

    seen = set()


    for item in data:

        if not isinstance(item, dict):
            continue

        code = item.get("Code")

        is_active = item.get("IsActive", False)

        if not code:
            continue

        if is_active is not True:
            continue

        code = str(code).strip()

        if not is_possible_code(code):
            continue

        key = code.lower()

        if key in seen:
            continue

        seen.add(key)

        active_codes.append(code)


    log(
        f"WOS Oracle returned "
        f"{len(active_codes)} active gift code(s)."
    )


    for code in active_codes:

        log(
            f"  Active gift code: {code}"
        )


    return active_codes


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

        except requests.RequestException as exc:

            log(
                f"WOS request error "
                f"(attempt {attempt}/{TRANSPORT_RETRIES}): "
                f"{exc}"
            )

            if attempt < TRANSPORT_RETRIES:

                time.sleep(
                    TRANSPORT_RETRY_DELAY * attempt
                )

                continue

            return (
                "failed",
                f"Transport error: {exc}"
            )


        except Exception as exc:

            return (
                "failed",
                f"Unexpected redemption error: {exc}"
            )


    return (
        "failed",
        "Transport retries exhausted"
    )


# ============================================================
# REDEMPTION DATABASE HELPERS
# ============================================================

def get_existing_redemption(code, fid):

    response = (
        supabase
        .table("gift_code_redemptions")
        .select("*")
        .eq("code", code)
        .eq("fid", int(fid))
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def save_redemption(
    gift_code_id,
    code,
    player,
    status,
    message,
    attempts=1
):

    now = datetime.now(
        timezone.utc
    ).isoformat()

    existing = get_existing_redemption(
        code,
        player["fid"]
    )

    values = {

        "gift_code_id":
            gift_code_id,

        "code":
            code,

        "fid":
            int(player["fid"]),

        "player_name":
            player["player_name"],

        "alliance":
            player["alliance"],

        "state":
            int(player["state"]),

        "status":
            status,

        "message":
            message,

        "attempts":
            attempts,

        "last_attempt_at":
            now,
    }


    if status in (
        "success",
        "already_redeemed"
    ):

        values["redeemed_at"] = now


    if existing:

        old_attempts = (
            existing.get("attempts")
            or 0
        )

        values["attempts"] = (
            old_attempts + attempts
        )

        (
            supabase
            .table("gift_code_redemptions")
            .update(values)
            .eq(
                "id",
                existing["id"]
            )
            .execute()
        )

    else:

        values["first_attempt_at"] = now

        (
            supabase
            .table("gift_code_redemptions")
            .insert(values)
            .execute()
        )


# ============================================================
# UPDATE GIFT CODE SUMMARY
# ============================================================

def update_gift_code_summary(
    gift_code_id,
    status,
    total_players,
    successful,
    already_redeemed,
    failed,
    wrong_state
):

    values = {

        "status":
            status,

        "total_players":
            total_players,

        "successful":
            successful,

        "already_redeemed":
            already_redeemed,

        "failed":
            failed,

        "wrong_state":
            wrong_state,
    }


    if status in (
        "completed",
        "expired",
        "invalid",
        "claim_limit",
        "failed"
    ):

        values["completed_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )


    (
        supabase
        .table("gift_codes")
        .update(values)
        .eq(
            "id",
            gift_code_id
        )
        .execute()
    )


# ============================================================
# PROCESS ONE GIFT CODE
# ============================================================

def process_gift_code(
    gift_code,
    players
):

    code = gift_code["code"]

    gift_code_id = gift_code["id"]


    log(
        "=" * 60
    )

    log(
        f"Processing gift code: {code}"
    )

    log(
        "=" * 60
    )


    (
        supabase
        .table("gift_codes")
        .update({

            "status":
                "processing",

            "started_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "total_players":
                len(players),

        })
        .eq(
            "id",
            gift_code_id
        )
        .execute()
    )


    successful = 0
    already_redeemed = 0
    failed = 0
    wrong_state = 0

    processed = 0


    # --------------------------------------------------------
    # PROCESS PLAYERS
    # --------------------------------------------------------

    for index, player in enumerate(
        players,
        start=1
    ):

        fid = player["fid"]

        name = player["player_name"]

        state = player["state"]


        # ----------------------------------------------------
        # SKIP FINAL RESULTS ALREADY SAVED
        # ----------------------------------------------------

        existing = get_existing_redemption(
            code,
            fid
        )


        if existing:

            existing_status = (
                existing.get("status")
            )


            if existing_status in (
                "success",
                "already_redeemed"
            ):

                log(
                    f"[{index}/{len(players)}] "
                    f"{name} ({fid}) "
                    f"already processed "
                    f"[{existing_status}]"
                )


                if (
                    existing_status
                    == "success"
                ):

                    successful += 1

                else:

                    already_redeemed += 1


                processed += 1

                continue


        # ----------------------------------------------------
        # REDEEM
        # ----------------------------------------------------

        log(
            f"[{index}/{len(players)}] "
            f"Redeeming {code} for "
            f"{name} ({fid}) "
            f"State {state}"
        )


        status = None
        message = None

        attempt_count = 0


        for rate_attempt in range(
            MAX_RATE_LIMIT_RETRIES + 1
        ):

            attempt_count += 1


            status, message = redeem_request(
                fid,
                state,
                code
            )


            # ------------------------------------------------
            # PER-PLAYER RATE LIMIT
            # ------------------------------------------------

            if status == "rate_limited":

                if (
                    rate_attempt
                    < MAX_RATE_LIMIT_RETRIES
                ):

                    log(
                        f"{name} ({fid}) "
                        "is rate limited. "
                        f"Waiting "
                        f"{RATE_LIMIT_WAIT}s..."
                    )

                    time.sleep(
                        RATE_LIMIT_WAIT
                    )

                    continue


                status = "failed"

                message = (
                    "Rate limit retries exhausted"
                )


            # ------------------------------------------------
            # SERVER RETRY
            # ------------------------------------------------

            if status == "retry":

                if (
                    rate_attempt
                    < MAX_RATE_LIMIT_RETRIES
                ):

                    log(
                        f"{name} ({fid}) "
                        "requested retry. "
                        "Waiting 5 seconds..."
                    )

                    time.sleep(5)

                    continue


                status = "failed"

                message = (
                    "Server retry limit exhausted"
                )


            break


        # ----------------------------------------------------
        # SAVE RESULT
        # ----------------------------------------------------

        save_redemption(
            gift_code_id,
            code,
            player,
            status,
            message,
            attempt_count
        )


        processed += 1


        log(
            f"    -> {status}: {message}"
        )


        # ----------------------------------------------------
        # COUNTERS
        # ----------------------------------------------------

        if status == "success":

            successful += 1


        elif status == "already_redeemed":

            already_redeemed += 1


        elif status == "wrong_state":

            wrong_state += 1


        else:

            failed += 1


        # ----------------------------------------------------
        # CODE-WIDE TERMINAL RESPONSES
        # ----------------------------------------------------

        if status in (
            "expired",
            "invalid",
            "claim_limit"
        ):

            log(
                f"Gift code {code} returned "
                f"{status}. Stopping this code."
            )


            update_gift_code_summary(
                gift_code_id,
                status,
                len(players),
                successful,
                already_redeemed,
                failed,
                wrong_state
            )


            post_summary(
                code,
                status,
                len(players),
                processed,
                successful,
                already_redeemed,
                failed,
                wrong_state
            )


            return


        # ----------------------------------------------------
        # DELAY BETWEEN PLAYERS
        # ----------------------------------------------------

        if index < len(players):

            time.sleep(
                PLAYER_DELAY
            )


    # --------------------------------------------------------
    # COMPLETED
    # --------------------------------------------------------

    update_gift_code_summary(
        gift_code_id,
        "completed",
        len(players),
        successful,
        already_redeemed,
        failed,
        wrong_state
    )


    post_summary(
        code,
        "completed",
        len(players),
        processed,
        successful,
        already_redeemed,
        failed,
        wrong_state
    )


# ============================================================
# DISCORD SUMMARY
# ============================================================

def post_summary(
    code,
    status,
    total,
    processed,
    successful,
    already_redeemed,
    failed,
    wrong_state
):

    if status == "completed":

        title = "🎁 COD Gift Code Complete"

    elif status == "expired":

        title = "⌛ COD Gift Code Expired"

    elif status == "invalid":

        title = "❌ Invalid COD Gift Code"

    elif status == "claim_limit":

        title = "⚠️ Gift Code Claim Limit Reached"

    else:

        title = "🎁 COD Gift Code Result"


    content = (
        f"**{title}**\n\n"
        f"**Code:** `{code}`\n"
        f"**Status:** `{status}`\n\n"
        f"👥 COD Players: **{total}**\n"
        f"🔄 Processed: **{processed}**\n"
        f"✅ Redeemed: **{successful}**\n"
        f"☑️ Already redeemed: "
        f"**{already_redeemed}**\n"
        f"🗺️ Wrong state: "
        f"**{wrong_state}**\n"
        f"❌ Failed: **{failed}**"
    )


    discord_message(
        content
    )


# ============================================================
# FIND CODES TO PROCESS
# ============================================================

def get_codes_to_process():

    discovered = discover_gift_codes()


    if not discovered:

        log(
            "No active gift codes discovered from WOS Oracle."
        )

        return []


    codes_to_process = []


    for code in discovered:

        existing = get_existing_code(
            code
        )


        # ----------------------------------------------------
        # BRAND NEW CODE
        # ----------------------------------------------------

        if not existing:

            new_code = create_gift_code(
                code
            )

            codes_to_process.append(
                new_code
            )

            continue


        # ----------------------------------------------------
        # RETRY UNFINISHED CODE
        # ----------------------------------------------------

        status = existing.get(
            "status"
        )


        if status in (
            "pending",
            "processing",
            "failed"
        ):

            log(
                f"Gift code {code} has "
                f"status {status}. "
                "Adding to processing queue."
            )

            codes_to_process.append(
                existing
            )

            continue


        log(
            f"Gift code {code} already "
            f"finished with status "
            f"{status}. Skipping."
        )


    return codes_to_process


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "COD WOS Gift Code Redeemer starting..."
    )


    try:

        players = get_cod_players()


        if not players:

            log(
                "No active COD players found. "
                "Nothing to redeem."
            )

            discord_message(
                "⚠️ **COD Gift Code Redeemer**\n\n"
                "No active COD players were found "
                "in Supabase."
            )

            return


        codes = get_codes_to_process()


        if not codes:

            log(
                "No new gift codes to process."
            )

            return


        log(
            f"{len(codes)} gift code(s) "
            "queued for processing."
        )


        for gift_code in codes:

            try:

                process_gift_code(
                    gift_code,
                    players
                )

            except Exception as exc:

                code = gift_code.get(
                    "code",
                    "UNKNOWN"
                )

                log(
                    f"Fatal error processing "
                    f"{code}: {exc}"
                )


                try:

                    update_gift_code_summary(
                        gift_code["id"],
                        "failed",
                        len(players),
                        0,
                        0,
                        1,
                        0
                    )

                except Exception as db_exc:

                    log(
                        "Could not update failed "
                        f"gift code: {db_exc}"
                    )


                discord_message(
                    "❌ **COD Gift Code Error**\n\n"
                    f"Code: `{code}`\n"
                    f"Error: `{str(exc)[:500]}`"
                )


        log(
            "COD WOS Gift Code Redeemer finished."
        )


    except Exception as exc:

        log(
            f"Fatal application error: {exc}"
        )


        discord_message(
            "❌ **COD Gift Code Redeemer Failed**\n\n"
            f"`{str(exc)[:1000]}`"
        )


        raise


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
