import asyncio
import json
import os
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

# ==========================================
# Configuration (sabit, env ile ezilebilir)
# ==========================================
OWNER_ID = int(os.environ.get("OWNER_ID", "917071733658386543"))
VOICE_CHANNEL_ID = int(os.environ.get("LAIN_VC_ID", "1534889821385003078"))
YOUTUBE_TOGETHER_APP_ID = 880218394199220334

EPISODES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "episodes.json")

# ==========================================
# Keep-alive web server (Render free tier)
# ==========================================
app = Flask("")

@app.route("/")
def home():
    return "LainBot is online — present day, present time."

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

def keep_alive():
    Thread(target=run_web, name="KeepAlive", daemon=True).start()

# ==========================================
# Bot (prefix: !)
# ==========================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

def load_episodes():
    with open(EPISODES_FILE, encoding="utf-8") as fh:
        return json.load(fh)

def save_episodes(data):
    with open(EPISODES_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

def _owner_only(ctx):
    return ctx.author.id == OWNER_ID

async def _launch_activity(vc):
    invite = await bot.http.create_invite(
        vc.id,
        max_age=0,
        max_uses=0,
        temporary=False,
        unique=True,
        target_type=2,
        target_application_id=YOUTUBE_TOGETHER_APP_ID,
    )
    return f"https://discord.gg/{invite['code']}"

# ==========================================
# Komutlar (sadece sahibi kullanabilir)
# ==========================================
@bot.command(name="help")
async def help_cmd(ctx):
    if not _owner_only(ctx):
        return
    embed = discord.Embed(
        title="🎬 LainBot Komutları",
        description="Serial Experiments Lain izleme partisi.",
        color=0x8B5CF6,
    )
    embed.add_field(name="!help", value="Bu listeyi gösterir", inline=False)
    embed.add_field(name="!episode", value="Bölüm listesini gösterir", inline=False)
    embed.add_field(name="!episode <sayı>", value="Belirtilen bölümü sesli kanalda başlatır", inline=False)
    embed.add_field(name="!watch <link>", value="İstediğin YouTube linkini birlikte izletir", inline=False)
    embed.add_field(name="!setepisode <sayı> <link>", value="Bir bölümün linkini değiştirir", inline=False)
    embed.add_field(name="!stop", value="Partiyi kapatır", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="episode")
async def episode(ctx, num: int = None):
    if not _owner_only(ctx):
        return
    eps = load_episodes()
    if num is None:
        lines = "\n".join(f"{i}. {e['title']} — {e['url']}" for i, e in enumerate(eps, 1))
        await ctx.send(embed=discord.Embed(
            title=f"📼 Serial Experiments Lain — {len(eps)} bölüm",
            description=lines,
            color=0x8B5CF6,
        ))
        return
    if not (1 <= num <= len(eps)):
        await ctx.send(f"❌ Bölüm 1 ile {len(eps)} arasında olmalı.")
        return
    vc = bot.get_channel(VOICE_CHANNEL_ID)
    if vc is None:
        await ctx.send(f"❌ Sesli kanal bulunamadı: `{VOICE_CHANNEL_ID}`")
        return
    ep = eps[num - 1]
    try:
        invite_url = await _launch_activity(vc)
    except Exception as e:
        await ctx.send(f"❌ Aktivite başlatılamadı: {e}")
        return
    embed = discord.Embed(
        title=f"🎬 Lain Bölüm {num}: {ep['title']}",
        url=ep["url"],
        color=0x8B5CF6,
    )
    embed.add_field(name="YouTube Together", value=invite_url, inline=False)
    embed.add_field(
        name="Nasıl izlenir",
        value=(
            f"1. Sesli kanala katıl: <#{vc.id}>\n"
            f"2. Linke tıkla → **Start Activity**\n"
            f"3. YouTube kutusuna bu linki yapıştır: {ep['url']}"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)

@bot.command(name="watch")
async def watch(ctx, url: str):
    if not _owner_only(ctx):
        return
    vc = bot.get_channel(VOICE_CHANNEL_ID)
    if vc is None:
        await ctx.send(f"❌ Sesli kanal bulunamadı: `{VOICE_CHANNEL_ID}`")
        return
    try:
        invite_url = await _launch_activity(vc)
    except Exception as e:
        await ctx.send(f"❌ Aktivite başlatılamadı: {e}")
        return
    embed = discord.Embed(title="🎬 Watch Party", url=url, color=0x8B5CF6)
    embed.add_field(name="YouTube Together", value=invite_url, inline=False)
    embed.add_field(
        name="Nasıl izlenir",
        value=(
            f"1. Sesli kanala katıl: <#{vc.id}>\n"
            f"2. Linke tıkla → **Start Activity**\n"
            f"3. YouTube kutusuna şu linki yapıştır: {url}"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)

@bot.command(name="setepisode")
async def setepisode(ctx, num: int, url: str):
    if not _owner_only(ctx):
        return
    eps = load_episodes()
    if not (1 <= num <= len(eps)):
        await ctx.send(f"❌ Bölüm 1 ile {len(eps)} arasında olmalı.")
        return
    eps[num - 1]["url"] = url
    save_episodes(eps)
    await ctx.send(f"✅ {num}. bölümün linki güncellendi: {url}")

@bot.command(name="stop")
async def stop(ctx):
    if not _owner_only(ctx):
        return
    await ctx.send("🛑 Aktivite, herkes sesli kanaldan çıkınca kapanır.")

# ==========================================
# Startup
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 LainBot online: {bot.user} | owner={OWNER_ID} | vc={VOICE_CHANNEL_ID}", flush=True)

async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN env değişkeni eksik!", flush=True)
        return
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Kapatılıyor.")
