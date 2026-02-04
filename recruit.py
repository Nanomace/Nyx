import discord
import asyncio
import datetime
import os
from typing import Dict, Any
from dotenv import load_dotenv
from google import genai

# ============================================================
# CONFIG
# ============================================================

TEST_MODE = True   # Set to False for real server operation

ARETE_LANDING_CHANNEL_ID = 545292278550233090
OFFICER_CHAT_CHANNEL_ID = 545294570091446280

OFFICER_ROLE_NAME = "Officer"
GENERAL_ROLE_NAME = "General"
PALADINS_ROLE_NAME = "Paladins"

RECRUIT_PREFIX = "recruit-"

INTERVIEW_QUESTIONS = [
    "Do you agree on our Code of Conduct?",
    "What do you do if someone kills a mob you were waiting for?",
    "What do you do if killed by a fellow Clan?",
    "What do you do if you get offended in org chat?",
    "Do you have any questions for me or about AP?"
]

CODE_OF_CONDUCT_LINK = "https://www.athenpaladins.org/forums/viewtopic.php?t=69"

READINESS_PROMPT = (
    "Are you ready to start the application questions?"
)
READINESS_NOT_READY = (
    "That’s totally fine, take your time. Tell me when you’re ready and we’ll begin."
)

POSITIVE_READINESS = {
    "yes", "yeah", "yep", "yup", "y", "ready", "sure",
    "ok", "okay", "absolutely", "lets go", "let's go", "start"
}

# ============================================================
# STATE
# ============================================================

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

recruit_sessions: Dict[int, Dict[str, Any]] = {}

async def generate_ai_reply(user_text: str, context: str = "") -> str:
    prompt = (
        "You are Nyx, a warm, friendly, professional recruitment assistant.\n"
        "Respond briefly and positively. Do NOT ask follow-up questions. Do NOT ask for clarification. Do NOT repeat the question. Respond to the applicant's answer in a supportive and human-like way.\n\n"
        f"Context: {context}\n"
        f"Applicant's answer:\n{user_text}\n\n"
        "Your response:"
    )

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )

    return response.text

# ============================================================
# UTILITIES
# ============================================================

def is_recruit_channel(channel: discord.abc.Messageable) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.name.startswith(RECRUIT_PREFIX)

async def get_or_create_recruit_channel(guild: discord.Guild, user: discord.Member):
    if TEST_MODE:
        return None  # No real channels in test mode

    for ch in guild.text_channels:
        if ch.name == f"{RECRUIT_PREFIX}{user.name.lower()}":
            return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }

    officer_role = discord.utils.get(guild.roles, name=OFFICER_ROLE_NAME)
    general_role = discord.utils.get(guild.roles, name=GENERAL_ROLE_NAME)

    if officer_role:
        overwrites[officer_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if general_role:
        overwrites[general_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=f"{RECRUIT_PREFIX}{user.name.lower()}",
        overwrites=overwrites,
        reason="Nyx recruitment interview"
    )
    return channel

async def send_officer_summary(guild: discord.Guild, member: discord.Member, channel, answers: list[str]):
    # ============================================================
    # TEST MODE PREVIEW
    # ============================================================
    if TEST_MODE:
        embed = discord.Embed(
            title=f"(TEST MODE PREVIEW) Recruitment Application — {member.display_name}",
            description="This is what would be sent to the officer channel:",
            color=discord.Color.blurple()
        )

        # Add Q/A fields
        for i, (q, a) in enumerate(zip(INTERVIEW_QUESTIONS, answers), start=1):
            embed.add_field(name=f"Q{i}: {q}", value=a or "*No answer recorded*", inline=False)

        # ---------------------------------------------
        # Automatic Red-Flag Detection + Risk Level
        # ---------------------------------------------
        red_flag_keywords = {
            "aggression": ["fuck", "kill", "attack", "revenge", "hurt", "beat", "destroy"],
            "toxicity": ["idiot", "stupid", "moron", "trash"],
            "hostility": ["i'll get them", "i will get them", "i'm going to get them"],
            "slurs": []  # Add slurs if needed
        }

        detected_flags = []

        for i, answer in enumerate(answers, start=1):
            lower = answer.lower()
            for category, words in red_flag_keywords.items():
                for w in words:
                    if w in lower:
                        detected_flags.append(
                            f"Q{i}: '{answer}' — matched **{w}** ({category})"
                        )

        # Determine risk level
        if len(detected_flags) == 0:
            risk_level = "🟢 **Low Risk** — No concerning language detected."
        elif len(detected_flags) <= 2:
            risk_level = "🟡 **Medium Risk** — Some concerning language detected."
        else:
            risk_level = "🔴 **High Risk** — Multiple or severe red flags detected."

        # Add risk level
        embed.add_field(
            name="Risk Assessment",
            value=risk_level,
            inline=False
        )

        # Add red flags if any
        if detected_flags:
            embed.add_field(
                name="Detected Red Flags",
                value="\n".join(detected_flags),
                inline=False
            )

        # Officer instructions
        embed.add_field(
            name="Next Steps for Officers",
            value=(
                "• Review the applicant’s answers above.\n"
                "• Confirm the applicant is registered on the AP forums.\n"
                "• Check their forum history for any concerns.\n"
                "• Review their bot history and recent activity.\n"
                "• Discuss any issues in #officer-chat before making a decision."
            ),
            inline=False
        )

        await channel.send(embed=embed)
        return

    # ============================================================
    # REAL MODE (non-test)
    # ============================================================

    officer_chat = guild.get_channel(OFFICER_CHAT_CHANNEL_ID)
    if not officer_chat:
        return

    embed = discord.Embed(
        title=f"Recruitment Application — {member.display_name}",
        description=f"Private channel: {channel.mention}",
        color=discord.Color.blurple()
    )

    # Add Q/A fields
    for i, (q, a) in enumerate(zip(INTERVIEW_QUESTIONS, answers), start=1):
        embed.add_field(name=f"Q{i}: {q}", value=a or "*No answer recorded*", inline=False)

    # ---------------------------------------------
    # Automatic Red-Flag Detection + Risk Level
    # ---------------------------------------------
    red_flag_keywords = {
        "aggression": ["fuck", "kill", "attack", "revenge", "hurt", "beat", "destroy"],
        "toxicity": ["idiot", "stupid", "moron", "trash"],
        "hostility": ["i'll get them", "i will get them", "i'm going to get them"],
        "slurs": []
    }

    detected_flags = []

    for i, answer in enumerate(answers, start=1):
        lower = answer.lower()
        for category, words in red_flag_keywords.items():
            for w in words:
                if w in lower:
                    detected_flags.append(
                        f"Q{i}: '{answer}' — matched **{w}** ({category})"
                    )

    # Determine risk level
    if len(detected_flags) == 0:
        risk_level = "🟢 **Low Risk** — No concerning language detected."
    elif len(detected_flags) <= 2:
        risk_level = "🟡 **Medium Risk** — Some concerning language detected."
    else:
        risk_level = "🔴 **High Risk** — Multiple or severe red flags detected."

    embed.add_field(
        name="Risk Assessment",
        value=risk_level,
        inline=False
    )

    if detected_flags:
        embed.add_field(
            name="Detected Red Flags",
            value="\n".join(detected_flags),
            inline=False
        )

    # Officer instructions
    embed.add_field(
        name="Next Steps for Officers",
        value=(
            "• Review the applicant’s answers above.\n"
            "• Confirm the applicant is registered on the AP forums.\n"
            "• Check their forum history for any concerns.\n"
            "• Review their bot history and recent activity.\n"
            "• Discuss any issues in #officer-chat before making a decision."
        ),
        inline=False
    )

    officer_role = discord.utils.get(guild.roles, name=OFFICER_ROLE_NAME)
    mention = officer_role.mention if officer_role else "@Officer"

    await officer_chat.send(content=mention, embed=embed)

async def close_recruit_channel(channel: discord.TextChannel, delay: int = 30):
    if TEST_MODE:
        return  # No deletion in test mode

    await asyncio.sleep(delay)
    try:
        await channel.delete(reason="Nyx recruitment concluded")
    except Exception:
        pass

def get_session(channel_id: int):
    return recruit_sessions.get(channel_id)

def set_session(channel_id: int, data: Dict[str, Any]):
    recruit_sessions[channel_id] = data

def clear_session(channel_id: int):
    sess = recruit_sessions.pop(channel_id, None)
    if sess and sess.get("wait_task"):
        sess["wait_task"].cancel()

def is_positive_readiness(text: str) -> bool:
    cleaned = text.strip().lower()
    if cleaned in POSITIVE_READINESS:
        return True
    # handle small variations like "yes!" or "yeah!" etc.
    for token in POSITIVE_READINESS:
        if cleaned.startswith(token + " ") or cleaned.startswith(token + "!"):
            return True
    return False

def is_negative_readiness(text: str) -> bool:
    cleaned = text.strip().lower()
    negatives = {"no", "not yet", "hold on", "wait", "stop", "later"}
    return any(cleaned.startswith(n) for n in negatives)

# ============================================================
# INTERVIEW FLOW
# ============================================================

async def start_interview(channel_or_dm, member: discord.Member):
    # question_index = -1 means "Are you ready?" pre-question
    session = {
        "user_id": member.id,
        "question_index": -1,
        "answers": [],
        "buffer": [],
        "last_bot_message_time": datetime.datetime.now(datetime.timezone.utc),
        "wait_task": None,
        "dm_mode": TEST_MODE or isinstance(channel_or_dm, discord.DMChannel)
    }

    set_session(channel_or_dm.id, session)

    welcome = discord.Embed(
        title="Nyx Recruitment",
        description=(
            f"Welcome {member.mention}.\n\n"
            "Athen Paladins is one of the oldest and most respected organizations in Anarchy Online. For over two decades, we’ve been a pillar of the community, known for our welcoming atmosphere, mutual trust, and dedication to helping players thrive.You’re not just gaining an organization; you’re becoming part of a rich legacy. We provide a family of like-minded players dedicated to fun, teamwork, and growth.\n\n"
            "I am going to conduct a brief interview with you. This ensures the organization is a great fit for you, and vice versa.\n\n"
            "Please answer the following questions as best you can. For some questions, there is no right or wrong answers! These answers allow us to understand a little more about who you are."
        ),
        color=discord.Color.dark_teal()
    )
    await channel_or_dm.send(embed=welcome)

    await asyncio.sleep(2)

    # Ask readiness question first
    await ask_readiness_question(channel_or_dm, member)

async def ask_readiness_question(channel, member: discord.Member):
    session = get_session(channel.id)
    if not session:
        return

    embed = discord.Embed(
        title="Before we begin",
        description=f"{READINESS_PROMPT}\n\nPlease answer 'Yes' when ready, {member.mention}.",
        color=discord.Color.dark_teal()
    )
    await channel.send(embed=embed)

    session["buffer"] = []
    session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)

    if session.get("wait_task"):
        session["wait_task"].cancel()

    session["wait_task"] = asyncio.create_task(wait_for_readiness(channel, member))
    set_session(channel.id, session)

async def wait_for_readiness(channel, member: discord.Member):
    channel_id = channel.id

    while True:
        await asyncio.sleep(1)
        session = get_session(channel_id)
        if not session:
            return

        # In readiness phase, we don't use the 30s buffer; we react to each message
        # Messages are buffered in handle_recruit_message; here we just check if any exist
        if session["buffer"]:
            text = "\n".join(session["buffer"])
            session["buffer"] = []
            set_session(channel_id, session)

            if is_positive_readiness(text):
                # Move to first real question
                session["question_index"] = 0
                session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)
                set_session(channel_id, session)
                await asyncio.sleep(1)
                await ask_next_question(channel, member)
                return
            else:
                # Not clearly ready

                await channel.send(READINESS_NOT_READY)
                # Stay in readiness loop; wait for another message
                session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)
                set_session(channel_id, session)

async def ask_next_question(channel, member: discord.Member):
    session = get_session(channel.id)
    if not session:
        return

    idx = session["question_index"]
    if idx >= len(INTERVIEW_QUESTIONS):
        await conclude_interview(channel, member)
        return

    question = INTERVIEW_QUESTIONS[idx]

    # Build the question description
    if idx == 0:
        # Only Question 1 gets the Code of Conduct link
        description = (
            f"{question}\n\n"
            f"{CODE_OF_CONDUCT_LINK}\n\n"
            f"Please answer 'yes' or 'no', {member.mention}."
        )
    else:
        # All other questions do NOT get the link
        description = (
            f"{question}\n\n"
            f"Please answer in your own words, {member.mention}."
        )

    embed = discord.Embed(
        title=f"Question {idx + 1}",
        description=description,
        color=discord.Color.dark_teal()
    )
    await channel.send(embed=embed)

    session["buffer"] = []
    session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)

    if session.get("wait_task"):
        session["wait_task"].cancel()

    session["wait_task"] = asyncio.create_task(wait_for_user_buffer_and_reply(channel, member))
    set_session(channel.id, session)

async def wait_for_user_buffer_and_reply(channel, member: discord.Member):
    channel_id = channel.id

    while True:
        await asyncio.sleep(1)
        session = get_session(channel_id)
        if not session:
            return

        last_bot = session["last_bot_message_time"]
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = (now - last_bot).total_seconds()

        if delta >= 10 and session["buffer"]:
            buffer_text = "\n".join(session["buffer"])
            session["buffer"] = []
            set_session(channel_id, session)

            idx = session["question_index"]
            question = INTERVIEW_QUESTIONS[idx]

            # Require explicit agreement for Code of Conduct (Question 2, index 1)
            if idx == 0:
                lower = buffer_text.lower()

                positive = {"yes", "i agree", "agree", "yep", "yeah", "y"}
                if not any(p in lower for p in positive):
                    embed = discord.Embed(
                        title="Code of Conduct Confirmation Needed",
                        description=(
                            f"Before we continue, I need to confirm that you agree to our Code of Conduct, {member.mention}.\n\n"
                            f"Please read it here:\n{CODE_OF_CONDUCT_LINK}\n\n"
                            "When you're ready, reply with **yes** or **I agree** so we can continue."
                        ),
                        color=discord.Color.red()
                    )
                    await channel.send(embed=embed)

                    # Do NOT advance the interview
                    session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)
                    session["wait_task"] = asyncio.create_task(wait_for_user_buffer_and_reply(channel, member))
                    set_session(channel_id, session)
                    return


            ai_reply = await generate_ai_reply(
                user_text=buffer_text,
                context=f"Question: {question}\nUser: {member.display_name}"
            )

            reply_embed = discord.Embed(
                description=ai_reply,
                color=discord.Color.dark_teal()
            )
            await channel.send(embed=reply_embed)

            session = get_session(channel_id)
            session["answers"].append(buffer_text)
            session["question_index"] += 1
            session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)
            set_session(channel_id, session)

            await asyncio.sleep(5)
            await ask_next_question(channel, member)
            return

async def conclude_interview(channel, member: discord.Member):
    session = get_session(channel.id)
    if not session:
        return

    embed = discord.Embed(
        title="Application Complete",
        description=(
            "Thank you for taking the time to answer those questions.\n\n"
            "Your application has been recorded. An officer will review your responses shortly."
        ),
        color=discord.Color.dark_teal()
    )
    await channel.send(embed=embed)

    guild = channel.guild if hasattr(channel, "guild") else None
    await send_officer_summary(guild, member, channel, session["answers"])

    clear_session(channel.id)

# ============================================================
# OFFICER COMMANDS
# ============================================================

async def handle_accept(message: discord.Message):
    if TEST_MODE:
        await message.channel.send(
            "**(TEST MODE)**\n"
            "*Nyx would now assign the Paladins role to the applicant.*\n"
            "*Nyx would log acceptance to #officer-chat.*\n"
            "*Nyx would delete the channel in 30 seconds.*"
        )
        return

    channel = message.channel
    if not is_recruit_channel(channel):
        return

    guild = message.guild
    session = get_session(channel.id)
    target_member = guild.get_member(session["user_id"]) if session else None

    if not target_member:
        await channel.send("I couldn't find the applicant.")
        return

    paladins_role = discord.utils.get(guild.roles, name=PALADINS_ROLE_NAME)
    if paladins_role:
        await target_member.add_roles(paladins_role)

    officer_chat = guild.get_channel(OFFICER_CHAT_CHANNEL_ID)
    if officer_chat:
        embed = discord.Embed(
            title="Recruitment Decision — ACCEPTED",
            description=f"{target_member.mention} has been accepted.",
            color=discord.Color.green()
        )
        await officer_chat.send(embed=embed)

    confirm = discord.Embed(
        title="Application Accepted",
        description=f"Welcome to Arete, {target_member.mention}.\n\nThis channel will close shortly.",
        color=discord.Color.green()
    )
    await channel.send(embed=confirm)

    clear_session(channel.id)
    await close_recruit_channel(channel, delay=30)

async def handle_reject(message: discord.Message):
    if TEST_MODE:
        await message.channel.send(
            "**(TEST MODE)**\n"
            "*Nyx would now kick the applicant from the server.*\n"
            "*Nyx would log rejection to #officer-chat.*\n"
            "*Nyx would delete the channel in 30 seconds.*"
        )
        return

    channel = message.channel
    if not is_recruit_channel(channel):
        return

    guild = message.guild
    session = get_session(channel.id)
    target_member = guild.get_member(session["user_id"]) if session else None

    if not target_member:
        await channel.send("I couldn't find the applicant.")
        return

    officer_chat = guild.get_channel(OFFICER_CHAT_CHANNEL_ID)
    if officer_chat:
        embed = discord.Embed(
            title="Recruitment Decision — REJECTED",
            description=f"{target_member.mention} has been rejected and will be removed.",
            color=discord.Color.red()
        )
        await officer_chat.send(embed=embed)

    reject = discord.Embed(
        title="Application Rejected",
        description=f"Thank you for your interest, {target_member.mention}. You will now be removed from the server.",
        color=discord.Color.red()
    )
    await channel.send(embed=reject)

    clear_session(channel.id)

    try:
        await guild.kick(target_member, reason="Rejected by Officer")
    except Exception:
        pass

    await close_recruit_channel(channel, delay=30)

# ============================================================
# MAIN ENTRY POINT FOR bot.py
# ============================================================

async def handle_recruit_message(client, message: discord.Message):
    """
    Returns True if the message was handled by the recruitment system.
    """

    # TEST MODE: allow DM applications and full flow in DM
    if TEST_MODE and isinstance(message.channel, discord.DMChannel):

        # Start interview in DM
        if message.content.lower().startswith("$apply"):
            await message.channel.send(
                "**(TEST MODE)**\n"
                f"*Nyx would now create a private channel named `recruit-{message.author.name.lower()}` on the server.*\n\n"
                "Beginning simulated interview here in DM..."
            )
            await start_interview(message.channel, message.author)
            return True

        # If there's an active DM session, buffer messages
        session = get_session(message.channel.id)
        if session and message.author.id == session["user_id"]:
            session["buffer"].append(message.content)
            session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)

            # Ensure the wait task is always running
            if not session.get("wait_task") or session["wait_task"].done():
                session["wait_task"] = asyncio.create_task(
                    wait_for_user_buffer_and_reply(message.channel, message.author)
                )

            set_session(message.channel.id, session)
            return True

    # Normal server mode: $apply in landing channel
    if message.content.lower().startswith("$apply"):
        if message.channel.id != ARETE_LANDING_CHANNEL_ID:
            await message.channel.send("Please use this command in the landing channel.")
            return True

        guild = message.guild
        member = message.author

        recruit_channel = await get_or_create_recruit_channel(guild, member)

        if TEST_MODE:
            await message.channel.send(
                "**(TEST MODE)**\n"
                "*Nyx would now create a private channel for this application.*\n"
                "Beginning simulated interview here instead..."
            )
            await start_interview(message.channel, member)
            return True

        await message.channel.send(
            f"Thank you, {member.mention}. I’ve opened a private channel for your application: {recruit_channel.mention}"
        )

        await start_interview(recruit_channel, member)
        return True

    # Messages inside recruit channels (real server mode)
    if isinstance(message.channel, discord.TextChannel) and is_recruit_channel(message.channel):
        session = get_session(message.channel.id)

        # User message during interview (readiness or questions)
        if session and message.author.id == session["user_id"]:
            session["buffer"].append(message.content)
            session["last_bot_message_time"] = datetime.datetime.now(datetime.timezone.utc)
            set_session(message.channel.id, session)

        # Officer commands
        if message.content.lower().startswith("$accept"):
            roles = [r.name for r in message.author.roles]
            if OFFICER_ROLE_NAME in roles or GENERAL_ROLE_NAME in roles:
                await handle_accept(message)
            else:
                await message.channel.send("Only Officers or Generals can accept applications.")
            return True

        if message.content.lower().startswith("$reject"):
            roles = [r.name for r in message.author.roles]
            if OFFICER_ROLE_NAME in roles or GENERAL_ROLE_NAME in roles:
                await handle_reject(message)
            else:
                await message.channel.send("Only Officers or Generals can reject applications.")
            return True

        return True

    return False