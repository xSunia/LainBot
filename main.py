import asyncio
import json
import os
import random
from collections import defaultdict
from datetime import datetime, timezone
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

# ==========================================
# Configuration
# ==========================================
OWNER_ID = int(os.environ.get("OWNER_ID", "917071733658386543"))
NEWSPAPER_HOUR = int(os.environ.get("NEWSPAPER_HOUR", "9"))
LOCAL_OFFSET = int(os.environ.get("NEWS_OFFSET_HOURS", "3"))
DEFAULT_NEWS_CHANNEL = int(os.environ.get("NEWS_CHANNEL_ID", "0"))

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "data.json")
CONFIG_FILE = os.path.join(BASE, "config.json")

HEADLINES = [
    "The Wired is silent today. Mostly.",
    "Present day... present time.",
    "They're all connected. You just can't see it yet.",
    "One day, the network will become conscious.",
    "A new layer of reality has been observed.",
    "Don't worry. Everything is fine. Probably.",
]

FOOTERS = [
    "✦ Do you dream of a Wired world?",
    "✦ This is just the beginning...",
    "✦ The protocol requires daily updates.",
    "✦ Lain is watching. Everyone is connected.",
]

MILESTONE_PRAISE = [
    "descended deeper into the Wired",
    "surpassed the protocol",
    "enhanced their presence in the Wired",
    "reached a new layer of consciousness",
    "synced with the network core",
]

# ==========================================
# Keep-alive web server (Render free tier)
# ==========================================
app = Flask("")

@app.route("/")
def home():
    return "Wired Gazette — press day is every day."

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

def keep_alive():
    Thread(target=run_web, name="KeepAlive", daemon=True).start()

# ==========================================
# Bot
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ---- day state ---------------------------------------------------
stats = {
    "day": "",
    "messages": 0,
    "per_user": {},
    "per_channel": {},
    "vc_minutes": {},
    "joins": [],
    "milestones": [],
    "top": {"content": "", "author": "", "reactions": 0, "jump_url": ""},
}
msg_snapshots = {}
vc_sessions = {}
total_msgs = defaultdict(int)
last_posted_day = None
config = {"news_channel": DEFAULT_NEWS_CHANNEL}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default

def persist():
    save_json(DATA_FILE, {
        "stats": stats,
        "total_msgs": dict(total_msgs),
        "last_posted_day": last_posted_day,
    })

def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def local_hour():
    return (datetime.now(timezone.utc).hour + LOCAL_OFFSET) % 24

def reset_day():
    global stats, msg_snapshots, vc_sessions
    stats = {
        "day": today_str(),
        "messages": 0,
        "per_user": {},
        "per_channel": {},
        "vc_minutes": {},
        "joins": [],
        "milestones": [],
        "top": {"content": "", "author": "", "reactions": 0, "jump_url": ""},
    }
    msg_snapshots = {}
    vc_sessions = {}
    persist()

def _owner_only(ctx):
    return ctx.author.id == OWNER_ID

# ==========================================
# Events
# ==========================================
@bot.event
async def on_ready():
    global stats, total_msgs, last_posted_day, config
    config.update(load_json(CONFIG_FILE, {}))
    data = load_json(DATA_FILE, None)
    if data:
        stats = data.get("stats", stats)
        total_msgs = defaultdict(int, data.get("total_msgs", {}))
        last_posted_day = data.get("last_posted_day")
    if stats.get("day") != today_str():
        reset_day()
    print(f"🤖 Wired Gazette online: {bot.user} | owner={OWNER_ID} | paper hour={NEWSPAPER_HOUR}:00", flush=True)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if stats.get("day") != today_str():
        reset_day()
    uid = str(message.author.id)
    cid = str(message.channel.id)
    stats["messages"] += 1
    stats["per_user"][uid] = stats["per_user"].get(uid, 0) + 1
    stats["per_channel"][cid] = stats["per_channel"].get(cid, 0) + 1

    total_msgs[uid] += 1
    if total_msgs[uid] % 500 == 0:
        stats["milestones"].append(
            f"**{message.author.display_name}** {random.choice(MILESTONE_PRAISE)} "
            f"— {total_msgs[uid]}th message ({stats['day']})"
        )

    if message.content:
        msg_snapshots[message.id] = {
            "content": message.content[:200],
            "author": message.author.display_name,
            "reactions": 0,
            "jump_url": message.jump_url,
            "day": stats["day"],
        }
    if len(msg_snapshots) > 5000:
        for mid in list(msg_snapshots)[:1000]:
            msg_snapshots.pop(mid, None)

    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload):
    snap = msg_snapshots.get(payload.message_id)
    if not snap or snap.get("day") != stats.get("day"):
        return
    snap["reactions"] += 1
    if snap["reactions"] > stats["top"]["reactions"]:
        stats["top"] = {
            "content": snap["content"],
            "author": snap["author"],
            "reactions": snap["reactions"],
            "jump_url": snap["jump_url"],
        }
        persist()

@bot.event
async def on_member_join(member):
    if stats.get("day") != today_str():
        reset_day()
    stats["joins"].append({"name": member.display_name, "id": member.id, "at": today_str()})
    persist()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    uid = str(member.id)
    if after.channel and uid not in vc_sessions:
        vc_sessions[uid] = {"channel": after.channel.id, "start": time_seconds()}
    elif before.channel and not after.channel:
        _close_vc_session(uid)
    elif before.channel and after.channel and before.channel.id != after.channel.id:
        _close_vc_session(uid)
        vc_sessions[uid] = {"channel": after.channel.id, "start": time_seconds()}

def time_seconds():
    return datetime.now(timezone.utc).timestamp()

def _close_vc_session(uid):
    sess = vc_sessions.pop(uid, None)
    if not sess:
        return
    minutes = (time_seconds() - sess["start"]) / 60.0
    if minutes >= 0.5:
        stats["vc_minutes"][uid] = stats["vc_minutes"].get(uid, 0) + minutes
        persist()

# ==========================================
# Newspaper
# ==========================================
def build_paper():
    top_user = max(stats["per_user"].items(), key=lambda kv: kv[1], default=("0", 0))
    top_channel = max(stats["per_channel"].items(), key=lambda kv: kv[1], default=("0", 0))
    top_vc = sorted(stats["vc_minutes"].items(), key=lambda kv: kv[1], reverse=True)[:3]

    embed = discord.Embed(
        title=f"📰 THE WIRED GAZETTE — {stats['day']}",
        description=random.choice(HEADLINES),
        color=0x8B5CF6,
    )
    embed.add_field(
        name="📊 Today's Numbers",
        value=(
            f"**{stats['messages']}** messages · **{len(stats['per_user'])}** active members\n"
            f"🔥 Top writer: <@{top_user[0]}> ({top_user[1]} messages)\n"
            f"💬 Busiest channel: <#{top_channel[0]}>"
        ),
        inline=False,
    )
    if stats["top"]["reactions"] > 0:
        embed.add_field(
            name=f"🌟 Message of the Day ({stats['top']['reactions']} reactions)",
            value=f"*{stats['top']['content']}*\n— {stats['top']['author']}  [jump]({stats['top']['jump_url']})",
            inline=False,
        )
    if top_vc:
        vc_lines = "\n".join(f"<@{uid}> — {round(m)} min" for uid, m in top_vc)
        embed.add_field(name="🎙 Most time spent in voice", value=vc_lines, inline=False)
    if stats["joins"]:
        join_lines = "\n".join(f"👋 **{j['name']}** joined the server" for j in stats["joins"])
        embed.add_field(name="New Arrivals", value=join_lines, inline=False)
    if stats["milestones"]:
        embed.add_field(name="🏆 Wired Achievements", value="\n".join(stats["milestones"]), inline=False)
    embed.set_footer(text=random.choice(FOOTERS))
    return embed

async def post_newspaper(channel):
    if channel is None:
        return
    await channel.send(embed=build_paper())
    global last_posted_day
    last_posted_day = today_str()
    persist()
    reset_day()

async def newspaper_loop():
    await bot.wait_until_ready()
    while True:
        try:
            if local_hour() == NEWSPAPER_HOUR and last_posted_day != today_str():
                ch = bot.get_channel(config.get("news_channel") or 0)
                if ch:
                    await post_newspaper(ch)
                    print(f"🗞 Gazette published -> #{ch.name}", flush=True)
        except Exception as e:
            print(f"⚠️ newspaper loop: {e}", flush=True)
        await asyncio.sleep(60)

# ==========================================
# Commands
# ==========================================
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="📰 Wired Gazette Commands",
        description="The server's daily newspaper. Published automatically every day at the set time.",
        color=0x8B5CF6,
    )
    embed.add_field(name="!newspaper", value="Show today's paper right now (everyone)", inline=False)
    embed.add_field(name="!newspaper now", value="Publish the paper now and start a new day (owner)", inline=False)
    embed.add_field(name="!setnewspaper <#channel>", value="Set the channel for automatic publishing (owner)", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="newspaper", aliases=["paper", "gazete"])
async def newspaper(ctx, mode: str = None):
    if mode == "now":
        if not _owner_only(ctx):
            return
        await post_newspaper(ctx.channel)
        await ctx.send("🗞 Paper published. A new day has begun.")
        return
    if ctx.author.id == OWNER_ID:
        await ctx.send(embed=build_paper())
    else:
        await ctx.send("🔒 This command is for the paper's editor only. (The paper is published automatically.)")

@bot.command(name="setnewspaper", aliases=["setpaper"])
async def setnewspaper(ctx, channel: discord.TextChannel):
    if not _owner_only(ctx):
        return
    config["news_channel"] = channel.id
    save_json(CONFIG_FILE, config)
    await ctx.send(f"✅ The paper will now be published automatically in {channel.mention}.")

# ==========================================
# Startup
# ==========================================
async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN env var is missing!", flush=True)
        return
    asyncio.get_running_loop().create_task(newspaper_loop())
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down.")
