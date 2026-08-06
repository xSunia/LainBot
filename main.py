import asyncio
import os
import random
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask
import yt_dlp

try:
    from imageio_ffmpeg import get_ffmpeg_exe
    FFMPEG_BINARY = get_ffmpeg_exe()
except ImportError:
    FFMPEG_BINARY = "ffmpeg"

# ==========================================
# Configuration
# ==========================================
OWNER_ID = int(os.environ.get("OWNER_ID", "917071733658386543"))

# ==========================================
# Keep-alive web server (Render free tier)
# ==========================================
app = Flask("")

@app.route("/")
def home():
    return "Wired Radio — now playing: silence."

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

def keep_alive():
    Thread(target=run_web, name="KeepAlive", daemon=True).start()

# ==========================================
# Bot
# ==========================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

queue = {}       # guild_id -> [entry]
volume = {}      # guild_id -> percent (default 100)

# ==========================================
# Helpers
# ==========================================
def _search_sync(query):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        try:
            if query.startswith(("http://", "https://")):
                info = ydl.extract_info(query, download=False)
            else:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        except Exception:
            return None
        if "entries" in info:
            info = info["entries"][0]
        if not info or not info.get("url"):
            return None
        seconds = info.get("duration") or 0
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        dur = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        return {
            "title": info.get("title", "Unknown"),
            "url": info.get("url"),
            "duration": dur,
        }

async def _search(query):
    return await asyncio.get_running_loop().run_in_executor(None, _search_sync, query)

def _source_for(entry, vol):
    opts = dict(FFMPEG_OPTS)
    if vol != 100:
        opts["options"] = f"-vn -af volume={vol / 100.0}"
    return discord.FFmpegPCMAudio(entry["url"], executable=FFMPEG_BINARY, **opts)

def _after(guild_id):
    def callback(err):
        if err:
            print(f"⚠️ playback error: {err}", flush=True)
        asyncio.run_coroutine_threadsafe(_advance(guild_id), bot.loop)
    return callback

async def _play_next(guild_id):
    guild = bot.get_guild(guild_id)
    vc = guild.voice_client if guild else None
    if vc is None:
        return
    q = queue.get(guild_id, [])
    if not q:
        await vc.disconnect()
        return
    vc.play(_source_for(q[0], volume.get(guild_id, 100)), after=_after(guild_id))

async def _advance(guild_id):
    q = queue.get(guild_id, [])
    if q:
        q.pop(0)
    await _play_next(guild_id)

# ==========================================
# Commands
# ==========================================
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🎧 Wired Radio Commands",
        description="Plays music from YouTube in your voice channel.",
        color=0x8B5CF6,
    )
    embed.add_field(name="!play <song or link>", value="Search and play / queue a song", inline=False)
    embed.add_field(name="!skip", value="Skip the current song", inline=False)
    embed.add_field(name="!queue", value="Show the upcoming queue", inline=False)
    embed.add_field(name="!nowplaying", value="Show the current song", inline=False)
    embed.add_field(name="!pause / !resume", value="Pause or resume playback", inline=False)
    embed.add_field(name="!volume <0-200>", value="Set playback volume", inline=False)
    embed.add_field(name="!shuffle", value="Shuffle the queue", inline=False)
    embed.add_field(name="!clear", value="Clear the queue (keep playing current)", inline=False)
    embed.add_field(name="!leave", value="Stop and leave the voice channel", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query):
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("🔇 You must be in a voice channel first.")
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
    entry = await _search(query)
    if entry is None:
        return await ctx.send("❌ Couldn't find anything for that.")
    q = queue.setdefault(ctx.guild.id, [])
    q.append(entry)
    vc = ctx.voice_client
    if vc.is_playing() or vc.is_paused():
        await ctx.send(f"➕ Queued **{entry['title']}** (position {len(q)})")
    else:
        await _play_next(ctx.guild.id)
        await ctx.send(f"🎵 Now playing: **{entry['title']}**")

@bot.command(name="skip")
async def skip(ctx):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭ Skipped.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name="queue", aliases=["q"])
async def queue_cmd(ctx):
    q = queue.get(ctx.guild.id, [])
    if not q:
        return await ctx.send("Queue is empty.")
    lines = [f"**Now:** {q[0]['title']} ({q[0]['duration']})"]
    for i, e in enumerate(q[1:16], 1):
        lines.append(f"{i}. {e['title']} ({e['duration']})")
    if len(q) > 16:
        lines.append(f"...and {len(q) - 16} more.")
    await ctx.send("\n".join(lines))

@bot.command(name="nowplaying", aliases=["np"])
async def nowplaying(ctx):
    vc = ctx.voice_client
    q = queue.get(ctx.guild.id, [])
    if vc and vc.is_playing() and q:
        await ctx.send(f"🎶 Now playing: **{q[0]['title']}**")
    else:
        await ctx.send("Nothing playing.")

@bot.command(name="pause")
async def pause(ctx):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸ Paused.")
    else:
        await ctx.send("Nothing playing.")

@bot.command(name="resume")
async def resume(ctx):
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("▶ Resumed.")
    else:
        await ctx.send("Nothing paused.")

@bot.command(name="volume", aliases=["vol"])
async def volume_cmd(ctx, vol: int):
    if not 0 <= vol <= 200:
        return await ctx.send("Volume must be between 0 and 200.")
    volume[ctx.guild.id] = vol
    vc = ctx.voice_client
    q = queue.get(ctx.guild.id, [])
    if vc and q:
        vc.play(_source_for(q[0], vol), after=_after(ctx.guild.id))
    await ctx.send(f"🔊 Volume set to {vol}%.")

@bot.command(name="shuffle")
async def shuffle(ctx):
    q = queue.get(ctx.guild.id, [])
    if len(q) > 2:
        head = q[:1]
        tail = q[1:]
        random.shuffle(tail)
        queue[ctx.guild.id] = head + tail
        await ctx.send("🔀 Queue shuffled.")
    else:
        await ctx.send("Not enough songs to shuffle.")

@bot.command(name="clear")
async def clear(ctx):
    q = queue.get(ctx.guild.id, [])
    if q:
        queue[ctx.guild.id] = q[:1]
        await ctx.send("🧹 Queue cleared.")
    else:
        await ctx.send("Queue is already empty.")

@bot.command(name="leave", aliases=["stop", "dc"])
async def leave(ctx):
    vc = ctx.voice_client
    if vc:
        queue.pop(ctx.guild.id, None)
        await vc.disconnect()
        await ctx.send("👋 Left the voice channel.")
    else:
        await ctx.send("I'm not in a voice channel.")

# ==========================================
# Startup
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 Wired Radio online: {bot.user} | owner={OWNER_ID}", flush=True)

async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN env var is missing!", flush=True)
        return
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down.")
