import os
import time
import hashlib
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

ALLIANCE = "COD"

BASE_URL = "https://wos-giftcode-api.centurygame.com"
REDEEM_URL = f"{BASE_URL}/api/gift_code"
ORIGIN = "https://wos-giftcode.centurygame.com"

WOS_ENCRYPT_KEY = "tB87#kPtkxqOS2"

PLAYER_DELAY = 1.5
RETRY_DELAY = 3
MAX_TRANSPORT_RETRIES = 3

TOO_FREQUENT_DELAY = 60
MAX_RATE_LIMIT_RETRIES = 3


# ============================================================
# VALIDATE ENVIRONMENT
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing.")


# ============================================================
# CLIENTS
# ============================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

session = requests.Session()

session.headers.update({
    "accept": "application/json, text/plain, */*",
    "content-type": "application/x-www-form-urlencoded",
    "origin": ORIGIN,
    "referer": f"{ORIGIN}/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
})


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        f" | {message}",
        flush=True
    )


# ============================================================
# DISCORD
# ============================================================

def discord_message(content):

    if not DISCORD_WEBHOOK_URL:
        log("DISCORD_WEBHOOK_URL not configured. Skipping Discord.")
        return

    try:

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={
                "content": content,
                "username": "COD Gift Codes"
            },
            timeout=20
        )

        if response.status_code not in (200, 204):
            log(
                f"Discord webhook returned "
                f"HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

    except requests.RequestException as exc:

        log(
            f"Discord webhook error: {exc}"
        )


# ============================================================
# WOS SIGNING
# ============================================================

def encode_data(data):

    encoded = "&".join(
        f"{key}={data[key]}"
        for key in sorted(data.keys())
    )

    sign_source = (
        encoded +
        WOS_ENCRYPT_KEY
    )

    signature = hashlib.md5(
        sign_source.encode()
    ).hexdigest()

    return {
        "sign": signature,
        **data
    }


# ============================================================
# WOS RESPONSE CLASSIFICATION
# ============================================================

def classify_response(data):

    message = str(
        data.get("msg", "UNKNOWN")
    ).strip(".")

    error_code = data.get("err_code")

    if message == "SUCCESS":
        return "success", "Successfully redeemed"

    if (
        message == "SAME TYPE EXCHANGE"
        and error_code == 40011
    ):
        return "success", "Successfully redeemed"

    if (
        message == "RECEIVED"
        and error_code == 40008
    ):
        return "already_redeemed", "Already redeemed"

    if (
        message == "TOO FREQUENT"
        and error_code == 40019
    ):
        return "rate_limited", "Rate limited"

    if (
        message == "USER INFO ERROR"
        and error_code == 40020
    ):
        return "wrong_state", "Wrong state"

    if (
        message == "TIME ERROR"
        and error_code == 40007
    ):
        return "expired", "Gift code expired"

    if (
        message == "CDK NOT FOUND"
        and error_code == 40014
    ):
        return "invalid", "Gift code not found"

    if (
        message == "USED"
        and error_code == 40005
    ):
        return "claim_limit", "Claim limit reached"

    if (
        message == "TIMEOUT RETRY"
        and error_code == 40004
    ):
        return "retry", "Server requested retry"

    if (
        error_code == 40001
        and "not exist" in message.lower()
    ):
        return "failed", "Player does not exist"

    if message == "STOVE_LV ERROR":
        return "failed", "Furnace level too low"

    if message == "RECHARGE_MONEY ERROR":
        return "failed", "Spending requirement not met"

    if message == "RECHARGE_MONEY_VIP ERROR":
        return "failed", "VIP requirement not met"

    return (
        "failed",
        f"{message} ({error_code})"
    )


# ============================================================
# SEND REDEMPTION REQUEST
# ============================================================

def redeem_once(fid, state, code):

    payload = encode_data({
        "fid": str(fid),
        "cdk": code,
        "kid": str(state),
        "time": str(int(time.time())),
    })

    for attempt in range(
        1,
        MAX_TRANSPORT_RETRIES + 1
    ):

        try:

            response = session.post(
                REDEEM_URL,
                data=payload,
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
                        "WOS returned invalid JSON"
                    )

            if response.status_code == 429:

                log(
                    f"HTTP 429. Transport retry "
                    f"{attempt}/{MAX_TRANSPORT_RETRIES}"
                )

            elif response.status_code in (
                502,
                503,
                504
            ):

                log(
                    f"WOS HTTP {response.status_code}. "
                    f"Retrying."
                )

            else:

                log(
                    f"WOS HTTP {response.status_code}: "
                    f"{response.text[:150]}"
                )

        except requests.RequestException as exc:

            log(
                f"WOS request error: {exc}"
            )

        if attempt < MAX_TRANSPORT_RETRIES:

            time.sleep(
                RETRY_DELAY * attempt
            )

    return (
        "failed",
        "Redemption request failed"
    )


# ============================================================
# REDEEM PLAYER
# ============================================================

def redeem_player(fid, state, code):

    rate_limit_attempts = 0

    while True:

        status, message = redeem_once(
            fid,
            state,
            code
        )

        if status == "retry":

            log(
                f"{fid}: server requested retry."
            )

            time.sleep(RETRY_DELAY)

            continue

        if status != "rate_limited":

            return status, message

        rate_limit_attempts += 1

        if (
            rate_limit_attempts >
            MAX_RATE_LIMIT_RETRIES
        ):

            return (
                "failed",
                "Rate limit retries exhausted"
            )

        log(
            f"{fid}: rate limited. "
            f"Waiting {TOO_FREQUENT_DELAY}s "
            f"before retry."
        )

        time.sleep(
            TOO_FREQUENT_DELAY
        )


# ============================================================
# GET ACTIVE COD PLAYERS
# ============================================================

def get_cod_players():

    log(
        "Loading active COD players from Supabase..."
    )

    response = (
        supabase
        .table("players")
        .select(
            "fid,player_name,alliance,state,active"
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

    valid = []

    for player in players:

        fid = player.get("fid")
        state = player.get("state")

        if not fid:
            log(
                f"Skipping player without FID: "
                f"{player}"
            )
            continue

        if not state:
            log(
                f"Skipping {fid}: state missing."
            )
            continue

        valid.append(player)

    log(
        f"Found {len(valid)} active COD players."
    )

    return valid


# ============================================================
# GET PENDING CODES
# ============================================================

def get_pending_codes():

    response = (
        supabase
        .table("gift_codes")
        .select("*")
        .eq(
            "status",
            "pending"
        )
        .order(
            "created_at"
        )
        .execute()
    )

    return response.data or []


# ============================================================
# SAVE INDIVIDUAL RESULT
# ============================================================

def save_redemption(
    gift_code_id,
    code,
    player,
    status,
    message
):

    fid = int(player["fid"])
    state = int(player["state"])

    existing = (
        supabase
        .table("gift_code_redemptions")
        .select(
            "id,attempts,first_attempt_at"
        )
        .eq(
            "code",
            code
        )
        .eq(
            "fid",
            fid
        )
        .limit(1)
        .execute()
    )

    rows = existing.data or []

    timestamp = now_iso()

    if rows:

        row = rows[0]

        attempts = (
            row.get("attempts") or 0
        ) + 1

        update = {
            "status": status,
            "message": message,
            "attempts": attempts,
            "last_attempt_at": timestamp
        }

        if status == "success":
            update["redeemed_at"] = timestamp

        (
            supabase
            .table("gift_code_redemptions")
            .update(update)
            .eq(
                "id",
                row["id"]
            )
            .execute()
        )

        return

    payload = {
        "gift_code_id": gift_code_id,
        "code": code,
        "fid": fid,
        "player_name": player.get(
            "player_name"
        ),
        "alliance": player.get(
            "alliance"
        ),
        "state": state,
        "status": status,
        "message": message,
        "attempts": 1,
        "first_attempt_at": timestamp,
        "last_attempt_at": timestamp
    }

    if status == "success":
        payload["redeemed_at"] = timestamp

    (
        supabase
        .table("gift_code_redemptions")
        .insert(payload)
        .execute()
    )


# ============================================================
# PROCESS CODE
# ============================================================

def process_code(gift_code, players):

    gift_code_id = gift_code["id"]

    code = str(
        gift_code["code"]
    ).strip()

    log(
        "=" * 60
    )

    log(
        f"Processing gift code: {code}"
    )

    log(
        f"COD players: {len(players)}"
    )

    (
        supabase
        .table("gift_codes")
        .update({
            "status": "processing",
            "started_at": now_iso(),
            "total_players": len(players)
        })
        .eq(
            "id",
            gift_code_id
        )
        .execute()
    )

    counters = {
        "success": 0,
        "already_redeemed": 0,
        "wrong_state": 0,
        "failed": 0
    }

    fatal_status = None

    for position, player in enumerate(
        players,
        start=1
    ):

        fid = player["fid"]

        state = player["state"]

        name = (
            player.get("player_name")
            or str(fid)
        )

        log(
            f"[{position}/{len(players)}] "
            f"{name} | "
            f"FID {fid} | "
            f"State {state}"
        )

        status, message = redeem_player(
            fid,
            state,
            code
        )

        log(
            f"{name}: {status} - {message}"
        )

        # These statuses apply to the code itself,
        # not just this individual player.
        if status in (
            "expired",
            "invalid",
            "claim_limit"
        ):

            fatal_status = status

            save_redemption(
                gift_code_id,
                code,
                player,
                status,
                message
            )

            break

        save_redemption(
            gift_code_id,
            code,
            player,
            status,
            message
        )

        if status == "success":

            counters["success"] += 1

        elif status == "already_redeemed":

            counters[
                "already_redeemed"
            ] += 1

        elif status == "wrong_state":

            counters[
                "wrong_state"
            ] += 1

        else:

            counters["failed"] += 1

        time.sleep(
            PLAYER_DELAY
        )

    if fatal_status:

        final_status = fatal_status

    else:

        final_status = "completed"

    (
        supabase
        .table("gift_codes")
        .update({
            "status": final_status,
            "successful": counters[
                "success"
            ],
            "already_redeemed": counters[
                "already_redeemed"
            ],
            "wrong_state": counters[
                "wrong_state"
            ],
            "failed": counters[
                "failed"
            ],
            "completed_at": now_iso()
        })
        .eq(
            "id",
            gift_code_id
        )
        .execute()
    )

    if fatal_status:

        discord_message(
            "🎁 **COD Gift Code Check**\n\n"
            f"**Code:** `{code}`\n"
            f"**Status:** {fatal_status}\n\n"
            "Processing stopped because WOS "
            "reported a code-wide error."
        )

    else:

        discord_message(
            "🎁 **COD Gift Code Complete**\n\n"
            f"**Code:** `{code}`\n"
            f"👥 COD Players: **{len(players)}**\n\n"
            f"✅ Redeemed: **{counters['success']}**\n"
            f"☑️ Already redeemed: "
            f"**{counters['already_redeemed']}**\n"
            f"⚠️ Wrong state: "
            f"**{counters['wrong_state']}**\n"
            f"❌ Failed: **{counters['failed']}**"
        )

    log(
        f"Finished {code}: {final_status}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "COD Gift Code Redeemer starting."
    )

    players = get_cod_players()

    if not players:

        log(
            "No active COD players found. Exiting."
        )

        discord_message(
            "⚠️ COD Gift Code Redeemer found "
            "no active COD players."
        )

        return

    pending_codes = get_pending_codes()

    if not pending_codes:

        log(
            "No pending gift codes."
        )

        return

    log(
        f"Found {len(pending_codes)} "
        f"pending gift code(s)."
    )

    for gift_code in pending_codes:

        try:

            process_code(
                gift_code,
                players
            )

        except Exception as exc:

            code = gift_code.get(
                "code",
                "UNKNOWN"
            )

            log(
                f"ERROR processing {code}: {exc}"
            )

            (
                supabase
                .table("gift_codes")
                .update({
                    "status": "failed",
                    "completed_at": now_iso()
                })
                .eq(
                    "id",
                    gift_code["id"]
                )
                .execute()
            )

            discord_message(
                "❌ **COD Gift Code Error**\n\n"
                f"Code: `{code}`\n"
                f"Error: `{str(exc)[:500]}`"
            )

    log(
        "COD Gift Code Redeemer finished."
    )


if __name__ == "__main__":
    main()
