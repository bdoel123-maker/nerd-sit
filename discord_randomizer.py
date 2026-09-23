import os
import random
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# Optional:
# Put your Discord server ID in GitHub Secrets for instant
# command syncing while testing.
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# ============================================================
# SUPABASE
# ============================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

TABLE = "discord_random_items"

# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# PERMISSIONS
# ============================================================

def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    permissions = interaction.user.guild_permissions
    return permissions.manage_guild or permissions.administrator


# ============================================================
# RANDOMIZER COMMAND GROUP
# ============================================================

class RandomGroup(app_commands.Group):

    def __init__(self):
        super().__init__(
            name="random",
            description="Random item generator"
        )

    # --------------------------------------------------------
    # /random pick
    # --------------------------------------------------------

    @app_commands.command(
        name="pick",
        description="Pick a random item"
    )
    async def pick(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer()

        try:

            response = (
                supabase
                .table(TABLE)
                .select("id,item")
                .eq("used", False)
                .execute()
            )

            items = response.data

            if not items:

                await interaction.followup.send(
                    "🎲 **No items remaining!**\n"
                    "An admin can use `/random reset` to restore the pool."
                )

                return

            selected = random.choice(items)

            # Mark it used
            (
                supabase
                .table(TABLE)
                .update({"used": True})
                .eq("id", selected["id"])
                .execute()
            )

            remaining = len(items) - 1

            await interaction.followup.send(
                f"🎲 **Random Pick**\n\n"
                f"# {selected['item']}\n\n"
                f"*{remaining} item(s) remaining*"
            )

        except Exception as e:

            print(f"Random error: {e}")

            await interaction.followup.send(
                "❌ Something went wrong while selecting an item."
            )

    # --------------------------------------------------------
    # /random add
    # --------------------------------------------------------

    @app_commands.command(
        name="add",
        description="Add an item to the randomizer"
    )
    async def add(
        self,
        interaction: discord.Interaction,
        item: str
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to do that.",
                ephemeral=True
            )

            return

        item = item.strip()

        if not item:

            await interaction.response.send_message(
                "❌ Item cannot be empty.",
                ephemeral=True
            )

            return

        try:

            supabase.table(TABLE).insert({
                "item": item,
                "used": False
            }).execute()

            await interaction.response.send_message(
                f"✅ Added **{item}** to the randomizer.",
                ephemeral=True
            )

        except Exception as e:

            print(f"Add error: {e}")

            await interaction.response.send_message(
                f"❌ **{item}** may already be in the list.",
                ephemeral=True
            )

    # --------------------------------------------------------
    # /random remove
    # --------------------------------------------------------

    @app_commands.command(
        name="remove",
        description="Remove an item from the randomizer"
    )
    async def remove(
        self,
        interaction: discord.Interaction,
        item: str
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to do that.",
                ephemeral=True
            )

            return

        try:

            result = (
                supabase
                .table(TABLE)
                .select("id,item")
                .ilike("item", item.strip())
                .execute()
            )

            if not result.data:

                await interaction.response.send_message(
                    f"❌ Couldn't find **{item}**.",
                    ephemeral=True
                )

                return

            record = result.data[0]

            (
                supabase
                .table(TABLE)
                .delete()
                .eq("id", record["id"])
                .execute()
            )

            await interaction.response.send_message(
                f"🗑️ Removed **{record['item']}**.",
                ephemeral=True
            )

        except Exception as e:

            print(f"Remove error: {e}")

            await interaction.response.send_message(
                "❌ Something went wrong.",
                ephemeral=True
            )

    # --------------------------------------------------------
    # /random list
    # --------------------------------------------------------

    @app_commands.command(
        name="list",
        description="Show the randomizer list"
    )
    async def list_items(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(ephemeral=True)

        try:

            response = (
                supabase
                .table(TABLE)
                .select("item,used")
                .order("item")
                .execute()
            )

            items = response.data

            if not items:

                await interaction.followup.send(
                    "The randomizer is empty.",
                    ephemeral=True
                )

                return

            available = [
                x["item"]
                for x in items
                if not x["used"]
            ]

            used = [
                x["item"]
                for x in items
                if x["used"]
            ]

            message = "🎲 **RANDOMIZER LIST**\n\n"

            message += (
                f"**Available ({len(available)}):**\n"
            )

            for item in available:
                message += f"• {item}\n"

            if used:

                message += (
                    f"\n**Already Picked ({len(used)}):**\n"
                )

                for item in used:
                    message += f"• {item}\n"

            # Discord message limit protection
            if len(message) > 1900:
                message = message[:1850]
                message += "\n\n*List truncated...*"

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        except Exception as e:

            print(f"List error: {e}")

            await interaction.followup.send(
                "❌ Couldn't retrieve the list.",
                ephemeral=True
            )

    # --------------------------------------------------------
    # /random reset
    # --------------------------------------------------------

    @app_commands.command(
        name="reset",
        description="Reset all previously selected items"
    )
    async def reset(
        self,
        interaction: discord.Interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to do that.",
                ephemeral=True
            )

            return

        try:

            (
                supabase
                .table(TABLE)
                .update({"used": False})
                .eq("used", True)
                .execute()
            )

            await interaction.response.send_message(
                "🔄 **Randomizer reset!**\n"
                "Every item is available again."
            )

        except Exception as e:

            print(f"Reset error: {e}")

            await interaction.response.send_message(
                "❌ Couldn't reset the randomizer.",
                ephemeral=True
            )


# ============================================================
# REGISTER COMMANDS
# ============================================================

random_group = RandomGroup()
bot.tree.add_command(random_group)


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print(f"Logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")

    try:

        if GUILD_ID:

            guild = discord.Object(
                id=int(GUILD_ID)
            )

            # Copy global commands to testing guild
            bot.tree.copy_global_to(
                guild=guild
            )

            synced = await bot.tree.sync(
                guild=guild
            )

            print(
                f"Synced {len(synced)} commands "
                f"to guild {GUILD_ID}"
            )

        else:

            synced = await bot.tree.sync()

            print(
                f"Synced {len(synced)} global commands"
            )

    except Exception as e:

        print(f"Command sync error: {e}")


# ============================================================
# START
# ============================================================

bot.run(DISCORD_TOKEN)
