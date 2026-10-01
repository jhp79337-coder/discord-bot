# =========================================================
# Discord Server Management Bot
# core.py
# =========================================================

import os
import asyncio
import json
import re
import random
import uuid
import asyncpg

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

# 10만 EXP 해금 채널
EXP_CHANNEL_ID = 1554764029493379124


# =========================================================
# 자기소개 설정
# =========================================================

INTRO_MINUTES = 30

# 2007년생까지 성인
ADULT_CUTOFF = 2007


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
        1553438682298589284,

    # 자기소개 완료 보너스 역할
    "intro_complete":
        1554818010777391286,

    # 100,000 EXP 달성 역할
    "exp_100k":
        1554762930883665931

}


# =========================================================
# EXP 설정
# =========================================================

EXP_CHAT = 1

EXP_VOICE_PER_MINUTE = 5

EXP_BUMP = 10

EXP_TARGET = 100000

# 채팅 EXP 도배 방지
CHAT_EXP_COOLDOWN = 5


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

db_pool = None

intro_exceptions = set()

pending_kicks = set()

# 소개팅 콘텐츠 데이터
dating_queue = []

dating_sessions = {}

dating_views_registered = False

# 채팅 EXP 쿨다운
exp_chat_cooldowns = {}

# 음성 EXP 지급 기록
exp_voice_last = {}


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


# =========================================================
# PostgreSQL
# =========================================================

async def init_database():

    global db_pool

    database_url = os.getenv("DATABASE_URL")

    if not database_url:

        print(
            "[DB ERROR] "
            "DATABASE_URL이 없습니다."
        )

        return

    try:

        db_pool = await asyncpg.create_pool(

            database_url,

            min_size=1,

            max_size=5

        )

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    user_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experience (
                    user_id TEXT PRIMARY KEY,
                    exp BIGINT NOT NULL DEFAULT 0
                )
                """
            )

        print(
            "[DB] PostgreSQL 연결 완료"
        )

    except Exception as e:

        print(
            f"[DB ERROR] {e}"
        )


# =========================================================
# 회원 데이터 DB 불러오기
# =========================================================

async def load_members_from_db():

    global members

    if db_pool is None:

        print(
            "[DB] 회원 DB 연결 없음"
        )

        return

    try:

        async with db_pool.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT
                    user_id,
                    data::text AS data
                FROM members
                """
            )

        if rows:

            db_members = {}

            for row in rows:

                try:

                    db_members[
                        row["user_id"]
                    ] = json.loads(
                        row["data"]
                    )

                except Exception as e:

                    print(
                        f"[DB MEMBER LOAD ERROR] {e}"
                    )

            members = db_members

            print(
                f"[DB] 회원 데이터 "
                f"{len(members)}개 로드 완료"
            )

        else:

            print(
                f"[DB] 회원 DB가 비어있음 "
                f"- 기존 데이터 {len(members)}개 유지"
            )

            if members:

                print(
                    "[DB] 기존 회원 데이터를 "
                    "PostgreSQL로 이전합니다."
                )

                for user_id, data in members.items():

                    await save_member_to_db(
                        user_id,
                        data
                    )

                print(
                    f"[DB] 회원 데이터 "
                    f"{len(members)}개 이전 완료"
                )

    except Exception as e:

        print(
            f"[DB MEMBER LOAD ERROR] {e}"
        )


# =========================================================
# 회원 데이터 DB 저장
# =========================================================

async def save_member_to_db(
    user_id,
    data
):

    if db_pool is None:

        print(
            "[DB] 회원 DB 연결 없음"
        )

        return

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                INSERT INTO members (
                    user_id,
                    data
                )
                VALUES (
                    $1,
                    $2::jsonb
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    data = EXCLUDED.data
                """,

                str(user_id),

                json.dumps(
                    data,
                    ensure_ascii=False
                )

            )

        print(
            f"[DB] 회원 데이터 저장 완료: "
            f"{user_id}"
        )

    except Exception as e:

        print(
            f"[DB MEMBER SAVE ERROR] {e}"
        )


# =========================================================
# 회원 데이터 DB 삭제
# =========================================================

async def delete_member_from_db(
    user_id
):

    if db_pool is None:

        return

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                DELETE FROM members
                WHERE user_id = $1
                """,

                str(user_id)

            )

        print(
            f"[DB] 회원 데이터 삭제 완료: "
            f"{user_id}"
        )

    except Exception as e:

        print(
            f"[DB MEMBER DELETE ERROR] {e}"
        )


# =========================================================
# EXP 불러오기
# =========================================================

async def get_exp(user_id):

    if db_pool is None:

        return 0

    try:

        async with db_pool.acquire() as conn:

            value = await conn.fetchval(
                """
                SELECT exp
                FROM experience
                WHERE user_id = $1
                """,
                str(user_id)
            )

        if value is None:

            return 0

        return int(value)

    except Exception as e:

        print(
            f"[EXP LOAD ERROR] {e}"
        )

        return 0


# =========================================================
# EXP 저장
# =========================================================

async def set_exp(
    user_id,
    amount
):

    if db_pool is None:

        print(
            "[EXP] DB 연결 없음"
        )

        return

    amount = max(
        0,
        int(amount)
    )

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                INSERT INTO experience (
                    user_id,
                    exp
                )
                VALUES (
                    $1,
                    $2
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    exp = EXCLUDED.exp
                """,

                str(user_id),
                amount

            )

    except Exception as e:

        print(
            f"[EXP SAVE ERROR] {e}"
        )


# =========================================================
# EXP 추가
# =========================================================

async def add_exp(
    member,
    amount,
    reason="기타"
):

    if member.bot:

        return 0

    if member.guild.id != GUILD_ID:

        return 0

    current = await get_exp(
        member.id
    )

    new_exp = current + int(amount)

    await set_exp(
        member.id,
        new_exp
    )

    # 10만 EXP 달성
    if (
        current < EXP_TARGET
        and
        new_exp >= EXP_TARGET
    ):

        await give_exp_100k_role(
            member
        )

        print(
            f"[EXP] {member} "
            f"100,000 EXP 달성"
        )

    return new_exp


# =========================================================
# 10만 EXP 역할 지급
# =========================================================

async def give_exp_100k_role(
    member
):

    role = member.guild.get_role(
        ROLES["exp_100k"]
    )

    if not role:

        print(
            "[EXP ROLE ERROR] "
            "100,000 EXP 역할을 찾을 수 없습니다."
        )

        return

    try:

        if role not in member.roles:

            await member.add_roles(
                role,
                reason="100,000 EXP 달성"
            )

    except Exception as e:

        print(
            f"[EXP ROLE ERROR] {e}"
        )


# =========================================================
# 프로필 DB 불러오기
# =========================================================

async def load_profiles_from_db():

    global profiles

    if db_pool is None:

        print(
            "[DB] 프로필 DB 연결 없음"
        )

        return

    try:

        async with db_pool.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT
                    user_id,
                    data::text AS data
                FROM profiles
                """
            )

        profiles = {}

        for row in rows:

            try:

                profiles[row["user_id"]] = json.loads(
                    row["data"]
                )

            except Exception as e:

                print(
                    f"[DB PROFILE LOAD ERROR] {e}"
                )

        print(
            f"[DB] 프로필 "
            f"{len(profiles)}개 로드 완료"
        )

    except Exception as e:

        print(
            f"[DB PROFILE LOAD ERROR] {e}"
        )


# =========================================================
# 프로필 DB 저장
# =========================================================

async def save_profile_to_db(
    user_id,
    data
):

    if db_pool is None:

        print(
            "[DB] 프로필 DB 연결 없음"
        )

        return

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                INSERT INTO profiles (
                    user_id,
                    data
                )
                VALUES (
                    $1,
                    $2::jsonb
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    data = EXCLUDED.data
                """,

                str(user_id),

                json.dumps(
                    data,
                    ensure_ascii=False
                )

            )

        print(
            f"[DB] 프로필 저장 완료: "
            f"{user_id}"
        )

    except Exception as e:

        print(
            f"[DB PROFILE SAVE ERROR] {e}"
        )


# =========================================================
# 프로필 DB 삭제
# =========================================================

async def delete_profile_from_db(
    user_id
):

    if db_pool is None:

        return

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                DELETE FROM profiles
                WHERE user_id = $1
                """,

                str(user_id)

            )

        print(
            f"[DB] 프로필 삭제 완료: "
            f"{user_id}"
        )

    except Exception as e:

        print(
            f"[DB PROFILE DELETE ERROR] {e}"
        )


# =========================================================
# 데이터 로드
# =========================================================

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
        {
            "queue": [],
            "sessions": {}
        }
    )

    dating_queue = []

    for value in dating_data.get(
        "queue",
        []
    ):

        try:

            dating_queue.append(
                int(value)
            )

        except Exception:

            pass

    dating_sessions = dating_data.get(
        "sessions",
        {}
    )

    if not isinstance(
        dating_sessions,
        dict
    ):

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

    # 서버장은 항상 관리자 취급
    # 기존 관리자 권한도 그대로 인정
    return (
        member.id == member.guild.owner_id
        or member.guild_permissions.administrator
    )


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
