"""
bot.py — Nyx Discord Bot
------------------------

Modules included:
- External file loaders (rules.txt, moderationguide.txt, wisdom.txt)
- Darknet moderation system (Gemini-based)
- Summary system ($summary) with DM support
- Wisdom system ($wisdom) with random quotes
- Message caching for summaries
- Topic analysis and summarization via Gemini
- Clean structure for maintainability

This file is generated as a complete, unified bot script.
"""

import os
import json
import random
import discord
from discord.ext import commands
from dotenv import load_dotenv
from google import genai
from datetime import datetime, timedelta, timezone
import asyncio
import re
from collections import Counter
from recruit import handle_recruit_message

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini client
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

# Discord intents
intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix="!", intents=intents)

# Channel + role settings
DARKNET_CHANNEL_ID = 1327958045099294730
TARGET_USERNAME = "nadyap"
MOD_ROLE_ID = 1387473445536661585

# Rolling caches (max 1000 messages each)
MAX_CACHE = 1000
generals_cache: list[tuple[str, str, datetime]] = []
officer_cache: list[tuple[str, str, datetime]] = []

# --- Darknet Moderation Allowlist Rules ---

# Allow WTS posts that contain "free" (AO trading convention)
ALLOW_WTS_FREE = re.compile(
    r"^\[WTS\].*\bfree\b.*",
    re.IGNORECASE
)

# Allow AO character names followed by [Ignore]
ALLOW_AO_NAME_IGNORE = re.compile(
    r"\[[A-Za-z]{3,12}\]\s*\[Ignore\]",
    re.IGNORECASE
)

# ---------------------------------------------------------
# Load external files
# ---------------------------------------------------------
def load_rules():
    try:
        with open("rules.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "No rules found."

def load_moderation_guidance():
    try:
        with open("moderationguide.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "You are an automated moderation system."

def load_wisdom_quotes():
    try:
        with open("wisdom.txt", "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            return lines
    except FileNotFoundError:
        return []

RULES_TEXT = load_rules()
MODERATION_GUIDANCE = load_moderation_guidance()
WISDOM_QUOTES = load_wisdom_quotes()

# ---------------------------------------------------------
# Extract text from message + embeds
# ---------------------------------------------------------
def extract_message_text(message: discord.Message) -> str:
    parts = []

    if message.content:
        parts.append(message.content)

    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"{field.name}: {field.value}")
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)

    return "\n".join(parts).strip()
# ---------------------------------------------------------
# GEMINI MODERATION (Darknet ONLY)
# ---------------------------------------------------------
async def analyse_message_moderation(message_text: str) -> dict:
    system_prompt = (
        MODERATION_GUIDANCE
        + "\n\nRules:\n"
        + RULES_TEXT
    )

    try:
        response = client_gemini.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[{
                "role": "user",
                "parts": [{"text": system_prompt + "\n\nMessage:\n" + message_text}]
            }]
        )

        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

        return json.loads(raw)

    except Exception:
        return {
            "violation": False,
            "rule": "",
            "reason": "Gemini API error",
            "recommended_action": "No Action",
            "short_summary": "No violation detected.",
            "confidence": 0.0
        }

# ---------------------------------------------------------
# GEMINI SUMMARIZER
# ---------------------------------------------------------
async def summarise_text(text: str) -> str:
    prompt = (
        "Summarize the following Discord messages in under 100 words. "
        "Include usernames when relevant. Focus on the main themes and actions.\n\n"
        + text
    )

    try:
        response = client_gemini.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}]
        )
        return (response.text or "").strip()

    except Exception:
        return "Summary unavailable due to AI error."

# ---------------------------------------------------------
# GEMINI TOPIC ANALYSIS
# ---------------------------------------------------------
async def summarise_topics(text: str) -> str:
    prompt = (
        "Identify the main discussion topics in the following Discord messages. "
        "List 3–6 themes with short explanations. "
        "Do NOT include usernames.\n\n"
        + text
    )

    try:
        response = client_gemini.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}]
        )
        return (response.text or "").strip()

    except Exception:
        return "Topic analysis unavailable due to AI error."

# ---------------------------------------------------------
# Build summary text from message tuples
# ---------------------------------------------------------
async def summarize_messages(messages: list[tuple[str, str, datetime]]) -> str:
    if not messages:
        return "No messages available to summarize."
    text_block = "\n".join([f"{author}: {content}" for author, content, ts in messages])
    return await summarise_text(text_block)

# ---------------------------------------------------------
# Safe history fetch
# ---------------------------------------------------------
async def safe_fetch_history(channel: discord.TextChannel, limit: int) -> list[tuple[str, str, datetime]]:
    messages: list[tuple[str, str, datetime]] = []
    try:
        async for msg in channel.history(limit=limit):
            messages.append((msg.author.display_name, msg.content, msg.created_at))
    except discord.HTTPException:
        await asyncio.sleep(1)
    return messages

# ---------------------------------------------------------
# Cache handler
# ---------------------------------------------------------
def add_to_cache(channel_id: int, author: str, content: str, timestamp: datetime):
    cache = generals_cache if channel_id == 1417799716275621989 else officer_cache
    cache.append((author, content, timestamp))
    if len(cache) > MAX_CACHE:
        cache.pop(0)
# ---------------------------------------------------------
# Discord events
# ---------------------------------------------------------
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):

    if message.author == client.user:
        return
    # -----------------------------------
    # RECRUITMENT SYSTEM HOOK (ADD THIS)
    # -----------------------------------
    handled = await handle_recruit_message(client, message)
    if handled:
        return
    # Cache messages for summary commands
    if message.channel.id == 1417799716275621989:
        add_to_cache(1417799716275621989, message.author.display_name, message.content, message.created_at)

    if message.channel.id == 545294570091446280:
        add_to_cache(545294570091446280, message.author.display_name, message.content, message.created_at)

    # -----------------------------------------------------
    # $wisdom command (global)
    # -----------------------------------------------------
    if message.content.strip().lower() == "$wisdom":
        if not WISDOM_QUOTES:
            await message.channel.send("No wisdom available.")
            return

        quote = random.choice(WISDOM_QUOTES)

        embed = discord.Embed(
            title="A word of wisdom",
            description=quote,
            color=discord.Color.from_rgb(255, 255, 255)
        )

        await message.channel.send(embed=embed)
        return

    # -----------------------------------------------------
    # SUMMARY COMMANDS (GLOBAL + ROLE-LOCKED)
    # -----------------------------------------------------
    if message.content.startswith("$summary"):

        allowed_roles = ["officer", "general"]
        user_roles = [role.name.lower() for role in message.author.roles]

        if not any(role in allowed_roles for role in user_roles):
            await message.channel.send("You don’t have permission to use this command.")
            return

        parts = message.content.split()
        channel_name = message.channel.name

        # Determine which cache to use
        if message.channel.id == 545294570091446280:
            cache = officer_cache
        else:
            cache = generals_cache

        # -------------------------------------------------
        # $summary <number>
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].isdigit():
            count = int(parts[1])

            if len(cache) >= count:
                history = cache[-count:]
            else:
                missing = count - len(cache)
                fetched = await safe_fetch_history(message.channel, missing + 1)
                history = fetched + cache
                history = history[-count:]

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"Summary of #{channel_name} — Last {count} Messages",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary daily
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].lower() == "daily":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            fetched = await safe_fetch_history(message.channel, 1000)
            history = [(a, c, ts) for (a, c, ts) in fetched if ts >= cutoff]

            if not history:
                await message.author.send("No messages found in the last 24 hours.")
                return

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"Daily Summary of #{channel_name}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary weekly
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].lower() == "weekly":
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            fetched = await safe_fetch_history(message.channel, 3000)
            history = [(a, c, ts) for (a, c, ts) in fetched if ts >= cutoff]

            if not history:
                await message.author.send("No messages found in the last 7 days.")
                return

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"Weekly Summary of #{channel_name}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary monthly
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].lower() == "monthly":
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            fetched = await safe_fetch_history(message.channel, 5000)
            history = [(a, c, ts) for (a, c, ts) in fetched if ts >= cutoff]

            if not history:
                await message.author.send("No messages found in the last 30 days.")
                return

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"Monthly Summary of #{channel_name}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary keyword <word>
        # -------------------------------------------------
        if len(parts) == 3 and parts[1].lower() == "keyword":
            keyword = parts[2].lower()
            fetched = await safe_fetch_history(message.channel, 500)
            history = [(a, c, ts) for (a, c, ts) in fetched if keyword in c.lower()]

            if not history:
                await message.author.send(f"No messages found containing '{keyword}'.")
                return

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"Keyword Summary of #{channel_name}: {keyword}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary user <nickname>
        # -------------------------------------------------
        if len(parts) == 3 and parts[1].lower() == "user":
            target = parts[2].lower()
            fetched = await safe_fetch_history(message.channel, 2000)
            history = [(a, c, ts) for (a, c, ts) in fetched if a.lower() == target]

            if not history:
                await message.author.send(f"No messages found from user '{target}'.")
                return

            summary = await summarize_messages(history)

            embed = discord.Embed(
                title=f"User Summary of #{channel_name}: {target}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary active
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].lower() == "active":
            fetched = await safe_fetch_history(message.channel, 1000)
            names = [a for (a, c, ts) in fetched]
            counts = Counter(names).most_common(10)

            if not counts:
                await message.author.send("No activity found.")
                return

            lines = [f"**{name}** — {count} messages" for name, count in counts]
            summary = "\n".join(lines)

            embed = discord.Embed(
                title=f"Most Active Users in #{channel_name}",
                description=summary,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # $summary topics
        # -------------------------------------------------
        if len(parts) == 2 and parts[1].lower() == "topics":
            fetched = await safe_fetch_history(message.channel, 500)
            text_block = "\n".join([c for (a, c, ts) in fetched])
            topics = await summarise_topics(text_block)

            embed = discord.Embed(
                title=f"Topic Analysis of #{channel_name}",
                description=topics,
                color=discord.Color.blue()
            )

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

        # -------------------------------------------------
        # Invalid usage
        # -------------------------------------------------
        await message.channel.send(
            "Usage:\n"
            "`$summary <number>`\n"
            "`$summary daily`\n"
            "`$summary weekly`\n"
            "`$summary monthly`\n"
            "`$summary keyword <word>`\n"
            "`$summary user <nickname>`\n"
            "`$summary active`\n"
            "`$summary topics`"
        )
        return

    # -----------------------------------------------------
    # DARKNET MODERATION LOGIC
    # -----------------------------------------------------
    if message.channel.id == DARKNET_CHANNEL_ID:

        # Only evaluate messages from the target user
        if message.author.name.lower() != TARGET_USERNAME:
            return

        # Ignore these names entirely
        if "Macer" in message.content or "Peacehammer" in message.content:
            return

        text_to_check = extract_message_text(message)
        
        # --- Allowlist Filters (False-Flag Prevention) ---
        # 1. Allow WTS posts that include "free"
        if ALLOW_WTS_FREE.search(text_to_check):
            return  # Skip moderation entirely

        # 2. Allow AO player names like [NAME] [Ignore]
        if ALLOW_AO_NAME_IGNORE.search(text_to_check):
            return  # Skip moderation entirely
        # -------------------------------------------------

        analysis = await analyse_message_moderation(text_to_check)

        # Build embed
        if analysis.get("violation"):
            embed = discord.Embed(
                title="Violation Detected",
                description=analysis.get("short_summary", "No summary provided."),
                color=discord.Color.red()
            )
        else:
            embed = discord.Embed(
                title="No Violation Detected",
                description=analysis.get("short_summary", "Message appears compliant."),
                color=discord.Color.green()
            )

        embed.add_field(name="Rule", value=analysis.get("rule", "None"), inline=False)
        embed.add_field(name="Reason", value=analysis.get("reason", "None"), inline=False)
        embed.add_field(name="Recommended Action", value=analysis.get("recommended_action", "None"), inline=False)
        embed.add_field(name="Confidence", value=f"{analysis.get('confidence', 0.0):.2f}", inline=False)

        try:
            # Ping mod role only if violation
            if analysis.get("violation"):
                role = message.guild.get_role(MOD_ROLE_ID)
                allowed = discord.AllowedMentions(roles=True)

                await message.channel.send(
                    content=role.mention,
                    allowed_mentions=allowed
                )

                await message.channel.send(embed=embed)

            else:
                await message.channel.send(embed=embed)

        except discord.Forbidden:
            print("Bot lacks permission to send embeds or mentions.")

# ---------------------------------------------------------
# Run bot
# ---------------------------------------------------------
client.run(DISCORD_TOKEN)