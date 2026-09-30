# =========================================================
# Discord Server Management Bot
# bot.py
# =========================================================

import os
import asyncio
import json
import re
import random
import uuid

from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from dotenv import load_dotenv


# =========================================================
# 환경 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

try:

    GUILD_ID = int(
        os.getenv(
            "GUILD_ID",
            "1553419235701690428"
        )
    )

except ValueError:

    GUILD_ID = 1553419235701690428


# =========================================================
# 채널 설정
# =========================================================

LOG_CHANNEL_ID = 1553436251598626866

INTRO_CHANNEL_ID = 1553435494074023956

ROLE_CHANNEL_ID = 1553458747177967656

MAIN_CHAT_ID = 1553421449698480248

BODY_SHARE_ID = 1553432612377202849


# =========================================================
# 자기소개 설정
# =========================================================

INTRO_MINUTES = 30

# 2007년생까지 성인
ADULT_CUTOFF = 2007

# 2012년생부터 이용 제한
MIN_ALLOWED_BIRTH_YEAR = 2012


# =========================================================
# 역할 ID
# =========================================================

ROLES = {

    "unverified":
        1553440335751938118,

    "male":
        1553434350916206592,

    "female":
        1553434497213538304,

    "adult":
        1553440075830919238,

    "minor":
        1553438682298589284

}


# =========================================================
# 데이터 파일
# =========================================================

FILES = {

    "members":
        "members.json",

    "warnings":
        "warnings.json",

    "profiles":
        "profiles.json",

    "exceptions":
        "intro_exceptions.json",

    "dating":
        "dating_sessions.json"

}


# =========================================================
# 경고 설정
# =========================================================

WARNING_TIMEOUT = {

    3:
        60 * 60,

    4:
        24 * 60 * 60

}


# =========================================================
# Discord 설정
# =========================================================

intents = discord.Intents.default()

intents.guilds = True

intents.members = True

intents.messages = True

intents.message_content = True

intents.voice_states = True


bot = commands.Bot(

    command_prefix="!",

    intents=intents,

    help_command=None

)


# =========================================================
# 메모리 데이터
# =========================================================

members = {}

warnings = {}

profiles = {}

intro_exceptions = set()
pending_kicks = set()

# 소개팅 콘텐츠 데이터
dating_queue = []
dating_sessions = {}
dating_views_registered = False


# =========================================================
# JSON
# =========================================================

def load_json(filename, default):

    try:

        if not os.path.exists(filename):

            return default

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            f"[JSON LOAD ERROR] "
            f"{filename}: {e}"
        )

        return default


def save_json(filename, data):

    try:

        temp = filename + ".tmp"

        with open(
            temp,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp,
            filename
        )

    except Exception as e:

        print(
            f"[JSON SAVE ERROR] "
            f"{filename}: {e}"
        )


def load_data():

    global members
    global warnings
    global profiles
    global intro_exceptions
    global dating_queue
    global dating_sessions

    members = load_json(
        FILES["members"],
        {}
    )

    warnings = load_json(
        FILES["warnings"],
        {}
    )

    profiles = load_json(
        FILES["profiles"],
        {}
    )

    exception_data = load_json(
        FILES["exceptions"],
        []
    )

    intro_exceptions = set()

    for value in exception_data:

        try:

            intro_exceptions.add(
                int(value)
            )

        except Exception:

            pass

    dating_data = load_json(
        FILES["dating"],
        {"queue": [], "sessions": {}}
    )

    dating_queue = []
    for value in dating_data.get("queue", []):
        try:
            dating_queue.append(int(value))
        except Exception:
            pass

    dating_sessions = dating_data.get("sessions", {})
    if not isinstance(dating_sessions, dict):
        dating_sessions = {}

    print("=" * 50)

    print(
        f"[DATA] members : "
        f"{len(members)}"
    )

    print(
        f"[DATA] warnings : "
        f"{len(warnings)}"
    )

    print(
        f"[DATA] profiles : "
        f"{len(profiles)}"
    )

    print(
        f"[DATA] exceptions : "
        f"{len(intro_exceptions)}"
    )

    print("=" * 50)


# =========================================================
# 공통
# =========================================================

def now():

    return datetime.now(
        timezone.utc
    )


def iso(dt):

    return dt.isoformat()


def parse_dt(value):

    if not value:

        return None

    try:

        return datetime.fromisoformat(
            value
        )

    except Exception:

        return None


def is_admin(member):

    return member.guild_permissions.administrator


def age_type(year):

    if year <= ADULT_CUTOFF:

        return "성인"

    return "미성년자"


def gender_text(gender):

    return {

        "남":
            "남자",

        "여":
            "여자"

    }.get(
        gender,
        "미확인"
    )


# =========================================================
# 회원 데이터
# =========================================================

def member_data(member):

    member_id = str(
        member.id
    )

    if member_id not in members:

        members[member_id] = {

            "joined_at":
                iso(
                    member.joined_at
                    or now()
                ),

            "intro_completed":
                False,

            "birth_year":
                None,

            "gender":
                None,

            "last_activity":
                iso(now()),

            "is_existing_member":
                True,

            "kicked":
                False

        }

    return members[member_id]


# =========================================================
# 경고 개수
# =========================================================

def warning_count(member):

    data = warnings.get(

        str(member.id),

        {}

    )

    try:

        return int(
            data.get(
                "count",
                0
            )
        )

    except Exception:

        return 0


# =========================================================
# 로그 채널
# =========================================================

def get_log_channel(guild):

    channel = guild.get_channel(
        LOG_CHANNEL_ID
    )

    if isinstance(
        channel,
        discord.TextChannel
    ):

        return channel

    return None


# =========================================================
# 역할 관리
# =========================================================

async def manage_role(
    member,
    role_id,
    add=True
):

    role_obj = member.guild.get_role(
        role_id
    )

    if not role_obj:

        print(
            f"[ROLE ERROR] "
            f"역할 없음: {role_id}"
        )

        return

    try:

        if add:

            if role_obj not in member.roles:

                await member.add_roles(
                    role_obj
                )

        else:

            if role_obj in member.roles:

                await member.remove_roles(
                    role_obj
                )

    except Exception as e:

        print(
            f"[ROLE ERROR] {e}"
        )


