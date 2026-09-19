import os
import asyncio
import hashlib
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import requests
from supabase import create_client
from dotenv import load_dotenv


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

BASE_URL = "https://wos-giftcode-api.centurygame.com"
REDEEM_URL = BASE_URL + "/api/gift_code"

ORIGIN = "https://wos-giftcode.centurygame.com"

WOS_ENCRYPT_KEY = "tB87#kPtkxqOS2"

PLAYER_DELAY = 1.25

TOO_FREQUENT_DELAY = 60

MAX_COOLDOWNS = 3

MAX_TRANSPORT_RETRIES = 3


# ============================================================
# SUPABASE
# ============================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
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
    "user-agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
})


# ============================================================
# WOS RESPONSE MAP
# ============================================================

RESULT_MESSAGES = {

    "SUCCESS":
        "Successfully redeemed",

    "RECEIVED":
        "Already redeemed",

    "SAME TYPE EXCHANGE":
        "Successfully redeemed",

    "TIME ERROR":
        "Code expired",

    "CDK NOT FOUND":
        "Invalid gift code",

    "USED":
        "Claim limit reached",

    "TIMEOUT RETRY":
        "Server requested retry",

    "TOO FREQUENT":
        "Rate limited",

    "USER INFO ERROR":
        "Wrong state",

    "ROLE NOT EXIST":
        "Player does not exist",

    "STOVE_LV ERROR":
        "Furnace level too low",

    "RECHARGE_MONEY ERROR":
        "Spending requirement not met",

    "RECHARGE_MONEY_VIP ERROR":
        "VIP requirement not met",

    "SIGN ERROR":
        "Request signature error",

    "NOT LOGIN":
        "Server rejected request"
}


SUCCESS_STATUSES = (
    "SUCCESS",
    "SAME TYPE EXCHANGE"
)


FATAL_STATUSES = (
    "TIME ERROR",
    "CDK NOT FOUND",
    "USED"
)


# ============================================================
# SIGN REQUEST
# ============================================================

def encode_data(data):

    sorted_keys = sorted(data.keys())

    encoded = "&".join(
        f"{key}={data[key]}"
        for key in sorted_keys
    )

    sign_string = (
        encoded +
        WOS_ENCRYPT_KEY
    )

    sign = hashlib.md5(
        sign_string.encode()
    ).hexdigest()

    return {
        "sign": sign,
        **data
    }


# ============================================================
# CLASSIFY WOS RESPONSE
# ============================================================

def classify_response(data):

    msg = str(
        data.get(
            "msg",
            "UNKNOWN"
        )
    ).strip(".")

    err_code = data.get(
        "err_code"
    )

    if msg == "SUCCESS":
        return "SUCCESS"

    if (
        msg == "RECEIVED"
        and err_code == 40008
    ):
        return "RECEIVED"

    if (
        msg == "SAME TYPE EXCHANGE"
        and err_code == 40011
    ):
        return "SAME TYPE EXCHANGE"

    if (
        msg == "TIME ERROR"
        and err_code == 40007
    ):
        return "TIME ERROR"

    if (
        msg == "CDK NOT FOUND"
        and err_code == 40014
    ):
        return "CDK NOT FOUND"

    if (
        msg == "USED"
        and err_code == 40005
    ):
        return "USED"

    if (
        msg == "TIMEOUT RETRY"
        and err_code == 40004
    ):
        return "TIMEOUT RETRY"

    if (
        msg == "TOO FREQUENT"
        and err_code == 40019
    ):
        return "TOO FREQUENT"

    if (
        msg == "USER INFO ERROR"
        and err_code == 40020
    ):
        return "USER INFO ERROR"

    if (
        err_code == 40001
        and "not exist" in msg.lower()
    ):
        return "ROLE NOT EXIST"

    if (
        msg == "STOVE_LV ERROR"
        and err_code == 40006
    ):
        return "STOVE_LV ERROR"

    if (
        msg == "RECHARGE_MONEY ERROR"
        and err_code == 40017
    ):
        return "RECHARGE_MONEY ERROR"

    if (
        msg == "RECHARGE_MONEY_VIP ERROR"
        and err_code == 40018
    ):
        return "RECHARGE_MONEY_VIP ERROR"

    if "sign error" in msg.lower():
        return "SIGN ERROR"

    if msg == "NOT LOGIN":
        return "NOT LOGIN"

    return msg


# ============================================================
# GET COD PLAYERS
# ============================================================

def get_cod_players():

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

    valid_players = []

    for player in players:

        fid = player.get("fid")
        state = player.get("state")

        if not fid:
            continue

        if not state:
            print(
                f"Skipping {fid}: "
                "no state recorded"
            )

            continue

        valid_players.append(
            player
        )

    return valid_players


# ============================================================
# REDEEM ONCE
# ============================================================

def redeem_once(
    fid,
    state,
    code
):

    payload = encode_data({

        "fid":
            str(fid),

        "cdk":
            code,

        "kid":
            str(state),

        "time":
            str(
                int(
                    time.time()
                )
            )
    })

    for attempt in range(
        MAX_TRANSPORT_RETRIES
    ):

        try:

            response = session.post(
                REDEEM_URL,
                data=payload,
                timeout=(10, 30)
            )

            if response.status_code == 200:

                data = response.json()

                return classify_response(
                    data
                )

            if response.status_code in (
                429,
                502,
                503,
                504
            ):

                time.sleep(
                    2 * (
                        attempt + 1
                    )
                )

                continue

            return (
                f"HTTP "
                f"{response.status_code}"
            )

        except requests.RequestException:

            if (
                attempt
                <
                MAX_TRANSPORT_RETRIES - 1
            ):

                time.sleep(
                    2 * (
                        attempt + 1
                    )
                )

                continue

            return "TRANSPORT ERROR"

        except ValueError:

            return "INVALID RESPONSE"

    return "TRANSPORT ERROR"


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_existing_code(code):

    result = (
        supabase
        .table(
            "gift_codes"
        )
        .select("*")
        .eq(
            "code",
            code
        )
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def create_gift_code(
    code,
    user
):

    result = (
        supabase
        .table(
            "gift_codes"
        )
        .insert({

            "code":
                code,

            "status":
                "pending",

            "submitted_by":
                str(user),

            "submitted_by_id":
                str(user.id)

        })
        .execute()
    )

    return result.data[0]


def update_gift_code(
    gift_id,
    values
):

    (
        supabase
        .table(
            "gift_codes"
        )
        .update(
            values
        )
        .eq(
            "id",
            gift_id
        )
        .execute()
    )


def save_redemption(
    gift_id,
    code,
    player,
    status,
    attempts
):

    now = datetime.now(
        timezone.utc
    ).isoformat()

    friendly = RESULT_MESSAGES.get(
        status,
        status
    )

    values = {

        "gift_code_id":
            gift_id,

        "code":
            code,

        "fid":
            int(
                player["fid"]
            ),

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
            friendly,

        "attempts":
            attempts,

        "last_attempt_at":
            now
    }

    if status in SUCCESS_STATUSES:

        values[
            "redeemed_at"
        ] = now

    existing = (
        supabase
        .table(
            "gift_code_redemptions"
        )
        .select(
            "id,"
            "first_attempt_at"
        )
        .eq(
            "code",
            code
        )
        .eq(
            "fid",
            int(
                player["fid"]
            )
        )
        .execute()
    )

    if existing.data:

        (
            supabase
            .table(
                "gift_code_redemptions"
            )
            .update(
                values
            )
            .eq(
                "id",
                existing.data[0]["id"]
            )
            .execute()
        )

    else:

        values[
            "first_attempt_at"
        ] = now

        (
            supabase
            .table(
                "gift_code_redemptions"
            )
            .insert(
                values
            )
            .execute()
        )


# ============================================================
# BUILD DISCORD EMBED
# ============================================================

def progress_embed(
    code,
    total,
    processed,
    success,
    received,
    wrong_state,
    failed
):

    embed = discord.Embed(
        title="🎁 COD Gift Code Redeemer",
        description=f"`{code}`"
    )

    embed.add_field(
        name="Progress",
        value=(
            f"{processed} / "
            f"{total}"
        ),
        inline=False
    )

    embed.add_field(
        name="✅ Redeemed",
        value=str(success)
    )

    embed.add_field(
        name="☑️ Already",
        value=str(received)
    )

    embed.add_field(
        name="⚠️ Wrong State",
        value=str(wrong_state)
    )

    embed.add_field(
        name="❌ Failed",
        value=str(failed)
    )

    return embed


# ============================================================
# PROCESS CODE
# ============================================================

async def process_code(
    interaction,
    code,
    gift
):

    gift_id = gift["id"]

    players = await asyncio.to_thread(
        get_cod_players
    )

    total = len(players)

    if total == 0:

        await interaction.edit_original_response(
            content=(
                "❌ No active COD players "
                "were found."
            )
        )

        update_gift_code(
            gift_id,
            {
                "status": "failed",
                "failed": 0,
                "total_players": 0
            }
        )

        return

    update_gift_code(
        gift_id,
        {

            "status":
                "processing",

            "total_players":
                total,

            "started_at":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }
    )

    success = 0
    received = 0
    wrong_state = 0
    failed = 0
    processed = 0

    cooldowns = {}

    queue = list(players)

    last_update = 0

    while queue:

        player = queue.pop(0)

        fid = str(
            player["fid"]
        )

        state = int(
            player["state"]
        )

        attempts = (
            cooldowns.get(
                fid,
                0
            )
            + 1
        )

        status = await asyncio.to_thread(
            redeem_once,
            fid,
            state,
            code
        )

        # ----------------------------------------
        # RATE LIMIT
        # ----------------------------------------

        if status == "TOO FREQUENT":

            cooldowns[fid] = (
                cooldowns.get(
                    fid,
                    0
                )
                + 1
            )

            if (
                cooldowns[fid]
                <=
                MAX_COOLDOWNS
            ):

                await asyncio.sleep(
                    TOO_FREQUENT_DELAY
                )

                queue.append(
                    player
                )

                continue

            failed += 1
            processed += 1

        # ----------------------------------------
        # SUCCESS
        # ----------------------------------------

        elif status in SUCCESS_STATUSES:

            success += 1
            processed += 1

        # ----------------------------------------
        # ALREADY REDEEMED
        # ----------------------------------------

        elif status == "RECEIVED":

            received += 1
            processed += 1

        # ----------------------------------------
        # WRONG STATE
        # ----------------------------------------

        elif status == "USER INFO ERROR":

            wrong_state += 1
            processed += 1

        # ----------------------------------------
        # FATAL CODE ERROR
        # ----------------------------------------

        elif status in FATAL_STATUSES:

            failed += 1
            processed += 1

            await asyncio.to_thread(
                save_redemption,
                gift_id,
                code,
                player,
                status,
                attempts
            )

            break

        # ----------------------------------------
        # OTHER ERROR
        # ----------------------------------------

        else:

            failed += 1
            processed += 1

        await asyncio.to_thread(
            save_redemption,
            gift_id,
            code,
            player,
            status,
            attempts
        )

        # ----------------------------------------
        # UPDATE DISCORD EVERY ~10 PLAYERS
        # ----------------------------------------

        if (
            processed - last_update >= 10
            or processed == total
        ):

            last_update = processed

            embed = progress_embed(
                code,
                total,
                processed,
                success,
                received,
                wrong_state,
                failed
            )

            try:

                await interaction.edit_original_response(
                    embed=embed,
                    content=None
                )

            except discord.HTTPException:
                pass

        await asyncio.sleep(
            PLAYER_DELAY
        )


    # ========================================================
    # FINAL STATUS
    # ========================================================

    completed_at = datetime.now(
        timezone.utc
    ).isoformat()

    update_gift_code(
        gift_id,
        {

            "status":
                "completed",

            "successful":
                success,

            "already_redeemed":
                received,

            "wrong_state":
                wrong_state,

            "failed":
                failed,

            "completed_at":
                completed_at

        }
    )

    embed = discord.Embed(
        title="🎁 COD Gift Code Complete",
        description=f"`{code}`"
    )

    embed.add_field(
        name="👥 COD Players",
        value=str(total),
        inline=False
    )

    embed.add_field(
        name="✅ Redeemed",
        value=str(success)
    )

    embed.add_field(
        name="☑️ Already Redeemed",
        value=str(received)
    )

    embed.add_field(
        name="⚠️ Wrong State",
        value=str(wrong_state)
    )

    embed.add_field(
        name="❌ Failed",
        value=str(failed)
    )

    await interaction.edit_original_response(
        content=None,
        embed=embed
    )


# ============================================================
# /GIFTCODE
# ============================================================

@bot.tree.command(
    name="giftcode",
    description="Redeem a WOS gift code for active COD members."
)
@app_commands.describe(
    code="Whiteout Survival gift code"
)
async def giftcode(
    interaction: discord.Interaction,
    code: str
):

    code = code.strip()

    if not code:

        await interaction.response.send_message(
            "❌ Enter a gift code.",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    existing = await asyncio.to_thread(
        get_existing_code,
        code
    )

    if existing:

        await interaction.edit_original_response(
            content=(
                "⚠️ This code is already "
                "in the database.\n\n"
                f"Status: `{existing['status']}`"
            )
        )

        return

    gift = await asyncio.to_thread(
        create_gift_code,
        code,
        interaction.user
    )

    await interaction.edit_original_response(
        content=(
            "🎁 Loading active COD players..."
        )
    )

    await process
