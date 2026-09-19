# ============================================================
# COD GIFT CODE BOT
# Whiteout Survival
# ============================================================

import os
import time
import asyncio
import hashlib
from datetime import datetime, timezone

import requests
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not DISCORD_BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is missing.")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing.")


# ============================================================
# CONFIG
# ============================================================

ALLIANCE = "COD"

PLAYERS_TABLE = "players"
CODES_TABLE = "gift_codes"
REDEMPTIONS_TABLE = "gift_code_redemptions"

# WOS Gift Code API
BASE_URL = "https://wos-giftcode-api.centurygame.com"
REDEEM_URL = BASE_URL + "/api/gift_code"

ORIGIN = "https://wos-giftcode.centurygame.com"

WOS_ENCRYPT_KEY = "tB87#kPtkxqOS2"

# Delay between different players
PLAYER_DELAY = 1.25

# API transport retries
MAX_HTTP_RETRIES = 3

# WOS 40019 cooldown
RATE_LIMIT_WAIT = 60

# Maximum times we'll revisit a rate-limited player
MAX_RATE_LIMIT_RETRIES = 3

# Timeout for HTTP requests
HTTP_TIMEOUT = 30


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
    "accept": "application/json, text/plain, */*",
    "content-type": "application/x-www-form-urlencoded",
    "origin": ORIGIN,
    "referer": ORIGIN + "/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
})


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# Prevent two redemption jobs running simultaneously.
redemption_lock = asyncio.Lock()


# ============================================================
# TIME HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# WOS SIGNING
# ============================================================

def encode_data(data):
    """
    Sign request payload using the format expected by
    the current WOS gift-code API.
    """

    sorted_keys = sorted(data.keys())

    encoded = "&".join(
        f"{key}={data[key]}"
        for key in sorted_keys
    )

    sign = hashlib.md5(
        f"{encoded}{WOS_ENCRYPT_KEY}".encode()
    ).hexdigest()

    return {
        "sign": sign,
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

    if message == "SAME TYPE EXCHANGE" and error_code == 40011:
        return "success", "Successfully redeemed"

    if message == "RECEIVED" and error_code == 40008:
        return "already_redeemed", "Already redeemed"

    if message == "TIME ERROR" and error_code == 40007:
        return "expired", "Code has expired"

    if message == "CDK NOT FOUND" and error_code == 40014:
        return "invalid", "Gift code not found"

    if message == "USED" and error_code == 40005:
        return "claim_limit", "Claim limit reached"

    if message == "TOO FREQUENT" and error_code == 40019:
        return "rate_limited", "Rate limited"

    if message == "USER INFO ERROR" and error_code == 40020:
        return "wrong_state", "Wrong state for player"

    if error_code == 40001 and "not exist" in message.lower():
        return "player_not_found", "Player does not exist"

    if message == "STOVE_LV ERROR" and error_code == 40006:
        return "furnace_too_low", "Furnace level too low"

    if message == "RECHARGE_MONEY ERROR" and error_code == 40017:
        return "spending_requirement", "Spending requirement not met"

    if message == "RECHARGE_MONEY_VIP ERROR" and error_code == 40018:
        return "vip_requirement", "VIP requirement not met"

    if message == "TIMEOUT RETRY" and error_code == 40004:
        return "retry", "Server requested retry"

    if "sign error" in message.lower():
        return "sign_error", "Request signature rejected"

    return "failed", f"{message} ({error_code})"


# ============================================================
# REDEEM ONE REQUEST
# ============================================================

def redeem_request(fid, state, code):

    payload = encode_data({
        "fid": str(fid),
        "cdk": code,
        "kid": str(state),
        "time": str(int(time.time()))
    })

    last_error = None

    for attempt in range(1, MAX_HTTP_RETRIES + 1):

        try:

            response = session.post(
                REDEEM_URL,
                data=payload,
                timeout=HTTP_TIMEOUT
            )

            if response.status_code == 429:

                last_error = "HTTP 429"

                time.sleep(
                    2 * attempt
                )

                continue

            if response.status_code in (
                502,
                503,
                504
            ):

                last_error = (
                    f"HTTP {response.status_code}"
                )

                time.sleep(
                    2 * attempt
                )

                continue

            if response.status_code != 200:

                return (
                    "failed",
                    f"HTTP {response.status_code}"
                )

            try:
                data = response.json()

            except ValueError:

                return (
                    "failed",
                    "Invalid JSON response"
                )

            return classify_response(data)

        except requests.RequestException as exc:

            last_error = str(exc)

            if attempt < MAX_HTTP_RETRIES:
                time.sleep(2 * attempt)

    return (
        "failed",
        last_error or "Request failed"
    )


# ============================================================
# ASYNC WRAPPER
# ============================================================

async def redeem_request_async(
    fid,
    state,
    code
):

    return await asyncio.to_thread(
        redeem_request,
        fid,
        state,
        code
    )


# ============================================================
# LOAD ACTIVE COD PLAYERS
# ============================================================

def load_cod_players():

    response = (
        supabase
        .table(PLAYERS_TABLE)
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

    valid_players = []

    for player in players:

        fid = player.get("fid")
        state = player.get("state")

        if not fid:
            continue

        if not state:
            continue

        valid_players.append(player)

    return valid_players


# ============================================================
# CREATE / GET GIFT CODE
# ============================================================

def get_existing_code(code):

    response = (
        supabase
        .table(CODES_TABLE)
        .select("*")
        .eq(
            "code",
            code
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def create_code(
    code,
    user
):

    result = (
        supabase
        .table(CODES_TABLE)
        .insert({
            "code": code,
            "status": "pending",
            "submitted_by": str(user),
            "submitted_by_id": str(user.id),
            "created_at": utc_now()
        })
        .execute()
    )

    return result.data[0]


# ============================================================
# UPDATE GIFT CODE
# ============================================================

def update_code(
    gift_code_id,
    values
):

    (
        supabase
        .table(CODES_TABLE)
        .update(values)
        .eq(
            "id",
            gift_code_id
        )
        .execute()
    )


# ============================================================
# GET EXISTING REDEMPTION
# ============================================================

def get_redemption(
    code,
    fid
):

    result = (
        supabase
        .table(REDEMPTIONS_TABLE)
        .select("*")
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

    if result.data:
        return result.data[0]

    return None


# ============================================================
# SAVE REDEMPTION
# ============================================================

def save_redemption(
    gift_code_id,
    code,
    player,
    status,
    message,
    attempts
):

    now = utc_now()

    existing = get_redemption(
        code,
        player["fid"]
    )

    values = {
        "gift_code_id": gift_code_id,
        "code": code,
        "fid": player["fid"],
        "player_name": player.get(
            "player_name"
        ),
        "alliance": player.get(
            "alliance"
        ),
        "state": player["state"],
        "status": status,
        "message": message,
        "attempts": attempts,
        "last_attempt_at": now
    }

    if status == "success":
        values["redeemed_at"] = now

    if existing:

        (
            supabase
            .table(REDEMPTIONS_TABLE)
            .update(values)
            .eq(
                "id",
                existing["id"]
            )
            .execute()
        )

    else:

        values["first_attempt_at"] = now
        values["created_at"] = now

        (
            supabase
            .table(REDEMPTIONS_TABLE)
            .insert(values)
            .execute()
        )


# ============================================================
# DISCORD EMBED
# ============================================================

def make_progress_embed(
    code,
    total,
    processed,
    successful,
    already,
    failed,
    wrong_state,
    rate_limited=0
):

    embed = discord.Embed(
        title="🎁 COD Gift Code Redeemer",
        description=f"**Code:** `{code}`"
    )

    embed.add_field(
        name="Progress",
        value=f"{processed} / {total}",
        inline=False
    )

    embed.add_field(
        name="✅ Redeemed",
        value=str(successful),
        inline=True
    )

    embed.add_field(
        name="☑️ Already",
        value=str(already),
        inline=True
    )

    embed.add_field(
        name="❌ Failed",
        value=str(failed),
        inline=True
    )

    embed.add_field(
        name="⚠️ Wrong State",
        value=str(wrong_state),
        inline=True
    )

    embed.add_field(
        name="⏳ Cooling Down",
        value=str(rate_limited),
        inline=True
    )

    return embed


# ============================================================
# MAIN REDEMPTION JOB
# ============================================================

async def process_code(
    interaction,
    code,
    retry_failures=False
):

    code = code.strip()

    players = await asyncio.to_thread(
        load_cod_players
    )

    if not players:

        await interaction.edit_original_response(
            content=(
                "❌ No active COD players with a valid "
                "FID and state were found."
            ),
            embed=None
        )

        return

    existing_code = await asyncio.to_thread(
        get_existing_code,
        code
    )

    if existing_code:

        gift_code = existing_code

    else:

        gift_code = await asyncio.to_thread(
            create_code,
            code,
            interaction.user
        )

    gift_code_id = gift_code["id"]

    await asyncio.to_thread(
        update_code,
        gift_code_id,
        {
            "status": "processing",
            "total_players": len(players),
            "started_at": utc_now()
        }
    )

    successful = 0
    already = 0
    failed = 0
    wrong_state = 0
    processed = 0

    cooldown_queue = []

    # ========================================================
    # FIRST PASS
    # ========================================================

    for player in players:

        fid = player["fid"]

        existing = await asyncio.to_thread(
            get_redemption,
            code,
            fid
        )

        # Don't hit WOS again for completed players.
        if (
            existing
            and not retry_failures
            and existing.get("status")
            in (
                "success",
                "already_redeemed"
            )
        ):

            if existing["status"] == "success":
                successful += 1
            else:
                already += 1

            processed += 1
            continue

        status, message = (
            await redeem_request_async(
                fid,
                player["state"],
                code
            )
        )

        # --------------------------------------------
        # RATE LIMITED
        # --------------------------------------------

        if status == "rate_limited":

            cooldown_queue.append({
                "player": player,
                "attempts": 1
            })

            await asyncio.to_thread(
                save_redemption,
                gift_code_id,
                code,
                player,
                status,
                message,
                1
            )

            continue

        # --------------------------------------------
        # SAVE
        # --------------------------------------------

        await asyncio.to_thread(
            save_redemption,
            gift_code_id,
            code,
            player,
            status,
            message,
            1
        )

        processed += 1

        if status == "success":
            successful += 1

        elif status == "already_redeemed":
            already += 1

        elif status == "wrong_state":
            wrong_state += 1

        else:
            failed += 1

        # --------------------------------------------
        # GLOBAL BAD CODE
        # --------------------------------------------

        if status in (
            "expired",
            "invalid",
            "claim_limit"
        ):

            await asyncio.to_thread(
                update_code,
                gift_code_id,
                {
                    "status": status,
                    "successful": successful,
                    "already_redeemed": already,
                    "failed": failed,
                    "wrong_state": wrong_state,
                    "completed_at": utc_now()
                }
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title="🎁 Gift Code Stopped",
                    description=(
                        f"**Code:** `{code}`\n\n"
                        f"⚠️ {message}\n\n"
                        "Remaining COD players were not "
                        "processed."
                    )
                )
            )

            return

        # Update Discord periodically
        if processed % 10 == 0:

            await interaction.edit_original_response(
                content=None,
                embed=make_progress_embed(
                    code,
                    len(players),
                    processed,
                    successful,
                    already,
                    failed,
                    wrong_state,
                    len(cooldown_queue)
                )
            )

        await asyncio.sleep(
            PLAYER_DELAY
        )

    # ========================================================
    # RATE-LIMIT RETRIES
    # ========================================================

    for retry_round in range(
        MAX_RATE_LIMIT_RETRIES
    ):

        if not cooldown_queue:
            break

        await interaction.edit_original_response(
            content=None,
            embed=discord.Embed(
                title="⏳ WOS Cooldown",
                description=(
                    f"`{code}`\n\n"
                    f"{len(cooldown_queue)} player(s) were "
                    "rate limited.\n\n"
                    f"Waiting {RATE_LIMIT_WAIT} seconds "
                    "before retrying them."
                )
            )
        )

        await asyncio.sleep(
            RATE_LIMIT_WAIT
        )

        next_queue = []

        for item in cooldown_queue:

            player = item["player"]

            attempts = (
                item["attempts"] + 1
            )

            status, message = (
                await redeem_request_async(
                    player["fid"],
                    player["state"],
                    code
                )
            )

            await asyncio.to_thread(
                save_redemption,
                gift_code_id,
                code,
                player,
                status,
                message,
                attempts
            )

            if status == "rate_limited":

                next_queue.append({
                    "player": player,
                    "attempts": attempts
                })

            else:

                processed += 1

                if status == "success":
                    successful += 1

                elif status == "already_redeemed":
                    already += 1

                elif status == "wrong_state":
                    wrong_state += 1

                else:
                    failed += 1

            await asyncio.sleep(
                PLAYER_DELAY
            )

        cooldown_queue = next_queue

    # Anything still cooling down counts as failure.
    if cooldown_queue:

        failed += len(cooldown_queue)
        processed += len(cooldown_queue)

    # ========================================================
    # FINISH
    # ========================================================

    await asyncio.to_thread(
        update_code,
        gift_code_id,
        {
            "status": "completed",
            "total_players": len(players),
            "successful": successful,
            "already_redeemed": already,
            "failed": failed
