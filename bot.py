# -*- coding: utf-8 -*-
"""
Bot Discord pentru pontaj - versiune hosting (Render, 24/7)
"""

import json
import os
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from aiohttp import web

# ================== CONFIGURARE ==================
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GUILD_ID = 1484617874273206292
CHANNEL_ID = 1566873640471887912
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pontaj.json")
# =================================================

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


def fmt_hours(seconds: float) -> str:
    hours = seconds / 3600
    h = int(hours)
    m = int((hours - h) * 60)
    return f"{h}h {m}m"


def get_entry(data, user_id: str) -> dict:
    return data.setdefault(user_id, {"total_seconds": 0.0, "clock_in": None})


def is_clocked_in(entry) -> bool:
    return entry.get("clock_in") is not None


def panel_embed(guild: discord.Guild, data: dict) -> discord.Embed:
    e = discord.Embed(
        title="⏰ Panou Pontaj",
        description=(
            "Apasă butonul **🟢 Clock In** când începi tura,\n"
            "și **🔴 Clock Out** când o termini.\n\n"
            "Orele se adună automat în pontaj."
        ),
        color=discord.Color.green(),
    )
    e.set_footer(text=f"Server: {guild.name}")
    return e


def status_view():
    return PanelView()


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Clock In", style=discord.ButtonStyle.green, emoji="🟢", custom_id="pontaj_clockin")
    async def clock_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        uid = str(interaction.user.id)
        entry = get_entry(data, uid)
        if is_clocked_in(entry):
            await interaction.response.send_message(
                "⚠️ Ești deja băgat în pontaj! Apasă mai întâi 🔴 **Clock Out**.",
                ephemeral=True,
            )
            return
        entry["clock_in"] = datetime.now(timezone.utc).isoformat()
        save_data(data)
        await interaction.response.send_message(
            f"🟢 **Clock In** la {discord.utils.format_dt(interaction.created_at, 't')} — Spor la treabă!",
            ephemeral=True,
        )

    @discord.ui.button(label="Clock Out", style=discord.ButtonStyle.red, emoji="🔴", custom_id="pontaj_clockout")
    async def clock_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        uid = str(interaction.user.id)
        entry = get_entry(data, uid)
        if not is_clocked_in(entry):
            await interaction.response.send_message(
                "⚠️ Nu ești băgat în pontaj! Apasă mai întâi 🟢 **Clock In**.",
                ephemeral=True,
            )
            return
        start = datetime.fromisoformat(entry["clock_in"])
        now = datetime.now(timezone.utc)
        seconds = (now - start).total_seconds()
        entry["total_seconds"] = entry.get("total_seconds", 0.0) + seconds
        entry["clock_in"] = None
        save_data(data)
        await interaction.response.send_message(
            f"🔴 **Clock Out** — ai adăugat **{fmt_hours(seconds)}** în pontaj.\n"
            f"📊 Total: **{fmt_hours(entry['total_seconds'])}**",
            ephemeral=True,
        )


async def start_health_server():
    async def health(request):
        return web.Response(text="Bot Pontaj OK ✅")

    app = web.Application()
    app.router.add_get("/", health)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Server de sanatate pornit pe portul {port}")


@client.event
async def on_ready():
    print(f"✅ Bot conectat ca {client.user}")
    guild = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    print(f"✅ Comenzi sincronizate pe guild {GUILD_ID}")

    client.add_view(status_view())
    try:
        channel = client.get_channel(CHANNEL_ID)
        if channel:
            async for msg in channel.history(limit=20):
                if msg.author == client.user and msg.components:
                    await msg.edit(view=status_view())
                    print("✅ Panou restaurat")
                    break
    except Exception as exc:
        print(f"Nu am putut restaura panoul: {exc}")


@tree.command(name="verifica", description="Vezi câte ore are un membru pe pontaj")
@app_commands.describe(membru="Membrul căruia vrei să-i verifici orele")
async def verifica(interaction: discord.Interaction, membru: discord.Member):
    data = load_data()
    entry = data.get(str(membru.id))
    if not entry:
        await interaction.response.send_message(
            f"❌ {membru.mention} nu are nicio oră pe pontaj.", ephemeral=True
        )
        return
    total = entry.get("total_seconds", 0.0)
    status = "🟢 **este în pontaj acum** (cea sesiune nu e încă adăugată)" if is_clocked_in(entry) else "🔴 nu e în pontaj"
    await interaction.response.send_message(
        f"📊 **{membru.display_name}** — total pontaj: **{fmt_hours(total)}**\n"
        f"Status: {status}",
        ephemeral=True,
    )


@tree.command(name="addore", description="Adaugă ore la pontajul unui membru (admin)")
@app_commands.describe(membru="Membrul", ore="Câte ore să adaug (ex: 1.5)")
@app_commands.default_permissions(administrator=True)
async def addore(interaction: discord.Interaction, membru: discord.Member, ore: float):
    if ore <= 0:
        await interaction.response.send_message("❌ Numărul de ore trebuie să fie pozitiv.", ephemeral=True)
        return
    data = load_data()
    entry = get_entry(data, str(membru.id))
    entry["total_seconds"] = entry.get("total_seconds", 0.0) + ore * 3600
    save_data(data)
    await interaction.response.send_message(
        f"➕ Am adăugat **{fmt_hours(ore * 3600)}** pentru {membru.mention}.\n"
        f"📊 Total nou: **{fmt_hours(entry['total_seconds'])}**",
    )


@tree.command(name="rmvore", description="Scoate ore din pontajul unui membru (admin)")
@app_commands.describe(membru="Membrul", ore="Câte ore să scot (ex: 1.5)")
@app_commands.default_permissions(administrator=True)
async def rmvore(interaction: discord.Interaction, membru: discord.Member, ore: float):
    if ore <= 0:
        await interaction.response.send_message("❌ Numărul de ore trebuie să fie pozitiv.", ephemeral=True)
        return
    data = load_data()
    entry = get_entry(data, str(membru.id))
    entry["total_seconds"] = max(0.0, entry.get("total_seconds", 0.0) - ore * 3600)
    save_data(data)
    await interaction.response.send_message(
        f"➖ Am scos **{fmt_hours(ore * 3600)}** pentru {membru.mention}.\n"
        f"📊 Total nou: **{fmt_hours(entry['total_seconds'])}**",
    )


@tree.command(name="panoupntj", description="Afișează panoul pontajului cu butoanele Clock In / Clock Out")
async def panoupntj(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("❌ Comanda funcționează doar pe server.", ephemeral=True)
        return
    embed = panel_embed(guild, load_data())
    await interaction.channel.send(embed=embed, view=status_view())
    await interaction.response.send_message("✅ Panoul a fost afișat în acest canal.", ephemeral=True)


@tree.command(name="topore", description="Top 3 cei mai activi membri pe pontaj")
async def topore(interaction: discord.Interaction):
    data = load_data()
    ranking = sorted(
        ((uid, e.get("total_seconds", 0.0)) for uid, e in data.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:3]
    if not ranking:
        await interaction.response.send_message("❌ Nimeni nu are ore pe pontaj încă.", ephemeral=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, secs) in enumerate(ranking):
        member = interaction.guild.get_member(int(uid)) if interaction.guild else None
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"{medals[i]} {name if member else f'<@{uid}>'} — **{fmt_hours(secs)}**")
    e = discord.Embed(title="🏆 Top 3 — Pontaj", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=e)


async def main():
    asyncio.create_task(start_health_server())
    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
