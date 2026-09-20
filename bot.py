import os
import json
import re
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import OpenAI


# =========================================================
# 기본 설정
# =========================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# 추방 로그 채널
LOG_CHANNEL_NAME = "🚪・추방로그"

# 자기소개 제한 시간
INTRO_DEADLINE_MINUTES = 30

# 검사 주기
CHECK_MINUTES = 1

# 성인 기준
# 2007년생까지 성인
# 2008년생부터 미성년자
ADULT_CUTOFF_YEAR = 2007

# 서버
GUILD_ID = 1542210983127425158

# 역할 선택 채널
ROLE_CHANNEL_ID = 1549631714769244261

# 메인 채팅
MAIN_CHAT_CHANNEL_ID = 1544032267855470644

# AI 채팅 채널
ADULT_CHAT_CHANNEL = "＃↝・성인채팅"
ADULT_19_CHANNEL = "＃↝・19금"

# 역할 ID
UNVERIFIED_ROLE_ID = 1544031900295893112
MALE_ROLE_ID = 1544031878812532858
FEMALE_ROLE_ID = 1544031884227518525
ADULT_ROLE_ID = 1544031894809616475
MINOR_ROLE_ID = 1544031889533182043

# 데이터 파일
MEMBERS_FILE = "members.json"
CHAT_SETTINGS_FILE = "chat_settings.json"

# 야차방
YACHA_CATEGORY_NAME = "【💬】- 채팅"
YACHA_CHANNEL_NAME = "＃↝・야차"
YACHA_FILE = "yacha_data.json"

# 경고 시스템
WARNINGS_FILE = "warnings.json"

# 경고 1회부터 접근 제한할 채널
# 서버에서 실제 채널명이 다르면 이 목록만 바꾸면 됩니다.
RESTRICTED_CHANNEL_NAMES = [
    "＃↝・19금",
]

# 경고 1회 이상 시 숨길 몸공유방 채널 ID
BODY_SHARE_CHANNEL_ID = 1544276267522719794

# 경고 단계
# 1회: 19금/몸공유방 숨김
# 2회: 야차방 채팅 제한
# 3회: 1시간 타임아웃
# 4회: 24시간 타임아웃
# 5회: 서버 추방
WARNING_TIMEOUT_SECONDS = 60 * 60
WARNING_TIMEOUT_4_SECONDS = 24 * 60 * 60


# =========================================================
# Discord Intent
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
# Gemini
# =========================================================

gemini_client = None

if GEMINI_API_KEY:
    gemini_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


# =========================================================
# 데이터
# =========================================================

members_data = {}
chat_settings = {}
chat_history = {}

# AI 쿨다운
ai_cooldowns = {}

# 현재 관리자 확인 대기 중인 멤버
pending_kick_reviews = set()

# 야차방 데이터
# {
#   "channel_id": 123,
#   "members": [유저ID, ...]
# }
yacha_data = {}

# 경고 데이터
# {
#   "유저ID": {
#       "count": 1,
#       "reasons": [{"reason": "...", "moderator_id": 123, "at": "..."}]
#   }
# }
warnings_data = {}


# =========================================================
# AI 시스템 프롬프트
# =========================================================

SYSTEM_PROMPT = """
너는 디스코드 서버의 AI 봇 JARVIS다.

말투:
- 한국어
- 친근하고 자연스럽게
- 너무 길게 답하지 않는다.
- 실제 디스코드에서 대화하는 것처럼 답한다.
- 상황에 따라 ㅋㅋ, ㅎㅎ, ♡ 등을 적당히 사용할 수 있다.

원칙:
- 질문에는 직접적으로 답한다.
- 모르는 것은 아는 척하지 않는다.
- 개인정보를 요구하거나 노출하지 않는다.
- 불법행위를 구체적으로 돕지 않는다.
- 노골적인 성적 콘텐츠를 생성하지 않는다.
- 미성년자와 관련된 성적 콘텐츠는 절대 생성하지 않는다.
"""


# =========================================================
# JSON 저장 / 불러오기
# =========================================================

def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"[JSON 불러오기 오류] {filename}: {e}")
        return default


def save_json(filename, data):
    try:
        temp_file = filename + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, filename)

    except Exception as e:
        print(f"[JSON 저장 오류] {filename}: {e}")


def load_data():
    global members_data
    global chat_settings
    global yacha_data
    global warnings_data

    members_data = load_json(
        MEMBERS_FILE,
        {}
    )

    chat_settings = load_json(
        CHAT_SETTINGS_FILE,
        {
            "enabled": True
        }
    )

    yacha_data = load_json(
        YACHA_FILE,
        {}
    )

    warnings_data = load_json(
        WARNINGS_FILE,
        {}
    )

    print(
        f"[데이터] 멤버 {len(members_data)}명 / "
        f"AI {'ON' if chat_settings.get('enabled', True) else 'OFF'}"
    )


# =========================================================
# 시간 관련
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def utc_string(dt):
    return dt.isoformat()


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(content):
    """
    지원 형식

    04 남
    04남
    04 ㄴ
    04ㄴ

    08 여
    08여
    08 ㅇ
    08ㅇ

    1999 남
    2004 여

    두 자리 연도는 현재 연도를 기준으로 판단.

    2026년 기준:
    00~26 -> 2000~2026
    27~99 -> 1900~1999
    """

    text = content.strip()

    pattern = (
        r"(?<!\d)"
        r"((?:19|20)\d{2}|\d{2})"
        r"\s*"
        r"(남|여|ㄴ|ㅇ)"
        r"(?!\S)"
    )

    match = re.search(pattern, text)

    if not match:
        return None

    year_raw = match.group(1)
    gender_raw = match.group(2)

    # -------------------------
    # 연도 처리
    # -------------------------

    if len(year_raw) == 4:
        birth_year = int(year_raw)

    else:
        year = int(year_raw)

        current_year = datetime.now().year
        current_2digit = current_year % 100

        if year <= current_2digit:
            birth_year = 2000 + year
        else:
            birth_year = 1900 + year

    # 너무 이상한 연도 방지
    current_year = datetime.now().year

    if birth_year < 1900 or birth_year > current_year:
        return None

    # -------------------------
    # 성별
    # -------------------------

    if gender_raw in ["남", "ㄴ"]:
        gender = "남"
    else:
        gender = "여"

    return birth_year, gender


# =========================================================
# 성별 / 나이 표시
# =========================================================

def get_gender_text(gender):
    if gender == "남":
        return "남자"

    if gender == "여":
        return "여자"

    return "미확인"


def get_age_type(birth_year):
    if birth_year <= ADULT_CUTOFF_YEAR:
        return "성인"

    return "미성년자"


# =========================================================
# 활동 기록
# =========================================================

def update_activity(member_id):
    member_id = str(member_id)

    if member_id not in members_data:
        return

    members_data[member_id]["last_activity"] = utc_string(now_utc())

    save_json(
        MEMBERS_FILE,
        members_data
    )



# =========================================================
# 야차방 / 경고 시스템
# =========================================================

def is_admin(member):
    return member.guild_permissions.administrator


def get_warning_count(member_id):
    data = warnings_data.get(str(member_id), {})
    try:
        return int(data.get("count", 0))
    except Exception:
        return 0


def get_yacha_channel(guild):
    channel_id = yacha_data.get("channel_id")
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel

    channel = discord.utils.get(
        guild.text_channels,
        name=YACHA_CHANNEL_NAME
    )
    if channel:
        return channel

    return None


def get_yacha_members():
    raw = yacha_data.get("members", [])
    result = set()
    for value in raw:
        try:
            result.add(int(value))
        except Exception:
            pass
    return result


def save_yacha_data():
    save_json(YACHA_FILE, yacha_data)


def save_warnings_data():
    save_json(WARNINGS_FILE, warnings_data)


async def set_restricted_channel_access(member, can_view):
    """경고 대상의 19금/몸공유방 접근을 숨기거나 복구."""
    changed = 0

    for channel in member.guild.text_channels:
        if (
            channel.name not in RESTRICTED_CHANNEL_NAMES
            and channel.id != BODY_SHARE_CHANNEL_ID
        ):
            continue

        try:
            if can_view:
                await channel.set_permissions(
                    member,
                    overwrite=None,
                    reason="경고 해제/초기화 - 제한 채널 접근 복구"
                )
            else:
                await channel.set_permissions(
                    member,
                    view_channel=False,
                    reason="경고 1회 이상 - 제한 채널 접근 차단"
                )
            changed += 1
        except discord.Forbidden:
            print(f"[채널 권한 실패] {channel.name} / {member}")
        except Exception as e:
            print(f"[채널 권한 오류] {channel.name} / {member}: {e}")

    return changed


async def apply_warning_restrictions(member):
    """
    경고 단계 적용:
    1회 이상: 19금/몸공유방 숨김
    2회 이상: 야차방 채팅 금지
    3회 이상: 1시간 타임아웃
    4회 이상: 24시간 타임아웃
    5회 이상: 서버 추방
    """
    count = get_warning_count(member.id)

    if count >= 1:
        await set_restricted_channel_access(member, False)
    else:
        await set_restricted_channel_access(member, True)

    yacha = get_yacha_channel(member.guild)
    if yacha:
        try:
            if count >= 2:
                await yacha.set_permissions(
                    member,
                    send_messages=False,
                    reason="경고 2회 이상 - 야차방 채팅 제한"
                )
            else:
                # 야차방 참여자로 등록되어 있을 때만 명시적으로 복구
                if member.id in get_yacha_members():
                    await yacha.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        reason="경고 단계 복구 - 야차방 채팅 허용"
                    )
        except discord.Forbidden:
            print(f"[야차 권한 실패] {member}")
        except Exception as e:
            print(f"[야차 권한 오류] {member}: {e}")

    if count >= 5:
        # 5회: 서버 추방
        try:
            await member.kick(reason="경고 5회 누적 - 자동 서버 추방")
        except discord.Forbidden:
            print(f"[추방 권한 실패] {member}")
        except Exception as e:
            print(f"[추방 오류] {member}: {e}")

    elif count >= 4:
        # 4회: 24시간 타임아웃
        try:
            until = discord.utils.utcnow() + timedelta(
                seconds=WARNING_TIMEOUT_4_SECONDS
            )
            await member.timeout(
                until,
                reason="경고 4회 - 자동 24시간 타임아웃"
            )
        except discord.Forbidden:
            print(f"[타임아웃 권한 실패] {member}")
        except Exception as e:
            print(f"[타임아웃 오류] {member}: {e}")

    elif count >= 3:
        # 3회: 1시간 타임아웃
        try:
            until = discord.utils.utcnow() + timedelta(
                seconds=WARNING_TIMEOUT_SECONDS
            )
            await member.timeout(
                until,
                reason="경고 3회 - 자동 1시간 타임아웃"
            )
        except discord.Forbidden:
            print(f"[타임아웃 권한 실패] {member}")
        except Exception as e:
            print(f"[타임아웃 오류] {member}: {e}")


async def restore_yacha_member_permission(member):
    yacha = get_yacha_channel(member.guild)
    if not yacha:
        return

    try:
        if member.id in get_yacha_members() and get_warning_count(member.id) < 2:
            await yacha.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                reason="야차방 참여 권한 복구"
            )
        else:
            await yacha.set_permissions(
                member,
                overwrite=None,
                reason="야차방 권한 초기화"
            )
    except Exception as e:
        print(f"[야차 권한 복구 오류] {member}: {e}")


async def update_yacha_permissions(guild):
    """야차방의 현재 등록 멤버 권한을 전체적으로 다시 적용."""
    channel = get_yacha_channel(guild)
    if not channel:
        return

    members = get_yacha_members()

    # @everyone: 보기 가능, 채팅 불가
    try:
        await channel.set_permissions(
            guild.default_role,
            view_channel=True,
            send_messages=False,
            add_reactions=False,
            reason="야차방 기본 관람 권한"
        )
    except Exception as e:
        print(f"[야차 @everyone 권한 오류] {e}")

    # 등록된 멤버만 채팅 허용
    for member_id in members:
        member = guild.get_member(member_id)
        if member is None:
            continue

        if get_warning_count(member.id) >= 2:
            send_allowed = False
        else:
            send_allowed = True

        try:
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=send_allowed,
                add_reactions=send_allowed,
                reason="야차방 참여자 권한 적용"
            )
        except Exception as e:
            print(f"[야차 참여자 권한 오류] {member}: {e}")


async def create_yacha_channel(guild):
    existing = get_yacha_channel(guild)
    if existing:
        return existing, False

    category = discord.utils.find(
        lambda c: isinstance(c, discord.CategoryChannel)
        and c.name == YACHA_CATEGORY_NAME,
        guild.categories
    )

    if category is None:
        return None, None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            add_reactions=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            manage_channels=True
        )
    }

    try:
        channel = await guild.create_text_channel(
            YACHA_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            reason="JARVIS 야차방 생성"
        )
        return channel, True
    except discord.Forbidden:
        return None, None
    except Exception as e:
        print(f"[야차방 생성 오류] {e}")
        return None, None


async def delete_yacha_channel(guild):
    channel = get_yacha_channel(guild)
    if channel:
        try:
            await channel.delete(reason="JARVIS 야차방 삭제")
        except Exception as e:
            print(f"[야차방 삭제 오류] {e}")

    yacha_data.clear()
    save_yacha_data()


# =========================================================
# 경고 처리
# =========================================================

async def add_warning(member, moderator, reason):
    key = str(member.id)

    if key not in warnings_data:
        warnings_data[key] = {
            "count": 0,
            "reasons": []
        }

    warnings_data[key]["count"] = int(
        warnings_data[key].get("count", 0)
    ) + 1

    warnings_data[key].setdefault("reasons", []).append({
        "reason": reason,
        "moderator_id": moderator.id,
        "at": utc_string(now_utc())
    })

    save_warnings_data()
    await apply_warning_restrictions(member)

    return warnings_data[key]["count"]


async def remove_one_warning(member):
    key = str(member.id)
    data = warnings_data.get(key)

    if not data:
        return 0

    count = max(0, int(data.get("count", 0)) - 1)
    data["count"] = count

    reasons = data.get("reasons", [])
    if reasons:
        reasons.pop()

    if count == 0:
        warnings_data.pop(key, None)

    save_warnings_data()

    await apply_warning_restrictions(member)
    await restore_yacha_member_permission(member)

    return count


async def clear_all_warnings(member):
    warnings_data.pop(str(member.id), None)
    save_warnings_data()

    await set_restricted_channel_access(member, True)
    await restore_yacha_member_permission(member)


async def send_warning_log(guild, member, moderator, count, reason):
    channel = discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if channel is None:
        return

    embed = discord.Embed(
        title="⚠️ 경고 기록",
        description=(
            f"👤 **대상:** {member.mention}\n"
            f"🛡️ **처리자:** {moderator.mention}\n"
            f"📌 **사유:** {reason}\n"
            f"⚠️ **현재 경고:** `{count}회`\n\n"
            f"1회 이상 → 19금/몸공유방 숨김\n"
            f"2회 이상 → 야차방 채팅 제한\n"
            f"3회 → 1시간 타임아웃\n"
            f"4회 → 24시간 타임아웃\n"
            f"5회 → 서버 추방"
        ),
        color=discord.Color.orange()
    )

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[경고 로그 오류] {e}")


# =========================================================
# 야차방 명령어
# =========================================================

@bot.group(name="야차방", invoke_without_command=True)
async def yacha_group(ctx):
    await ctx.send(
        "🔥 **야차방 사용법**\n"
        "`!야차방 생성` - 야차방 생성 및 본인을 당사자로 등록\n"
        "`!야차방 추가 @회원` - 채팅 가능 인원 추가\n"
        "`!야차방 제거 @회원` - 채팅 가능 인원 제거\n"
        "`!야차방 목록` - 현재 채팅 가능 인원 확인\n"
        "`!야차방 삭제` - 야차방 삭제"
    )


@yacha_group.command(name="생성")
async def yacha_create(ctx):
    global yacha_data

    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    if get_warning_count(ctx.author.id) >= 2:
        await ctx.send(
            "🚫 경고 2회 이상이라 야차방을 사용할 수 없어요."
        )
        return

    channel, created = await create_yacha_channel(ctx.guild)

    if created is None:
        await ctx.send(
            f"❌ `{YACHA_CATEGORY_NAME}` 카테고리를 찾지 못했거나 "
            "봇에게 채널 관리 권한이 없어요."
        )
        return

    if not created:
        await ctx.send(
            f"ℹ️ 이미 {channel.mention} 야차방이 있어요."
        )
        return

    yacha_data = {
        "channel_id": channel.id,
        "members": [ctx.author.id],
        "created_by": ctx.author.id,
        "created_at": utc_string(now_utc())
    }
    save_yacha_data()

    await update_yacha_permissions(ctx.guild)

    await channel.send(
        "🔥 **야차방이 열렸어요.**\n"
        f"👤 현재 당사자: {ctx.author.mention}\n"
        "👀 다른 사람은 구경만 할 수 있어요.\n\n"
        "`!야차방 추가 @회원`으로 중간에 채팅 가능한 사람을 추가할 수 있어요."
    )

    await ctx.send(
        f"✅ {channel.mention} 생성 완료!\n"
        f"👤 당사자: {ctx.author.mention}"
    )


@yacha_group.command(name="추가")
async def yacha_add(ctx, member: discord.Member):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    if get_warning_count(ctx.author.id) >= 2:
        await ctx.send("🚫 경고 2회 이상이라 야차방 관리를 할 수 없어요.")
        return

    channel = get_yacha_channel(ctx.guild)
    if channel is None:
        await ctx.send("❌ 먼저 `!야차방 생성`을 해주세요.")
        return

    members = get_yacha_members()

    if not is_admin(ctx.author) and ctx.author.id not in members:
        await ctx.send("❌ 야차방 당사자 또는 관리자만 사람을 추가할 수 있어요.")
        return

    if get_warning_count(member.id) >= 2:
        await ctx.send("🚫 경고 2회 이상인 회원은 야차방 채팅에 추가할 수 없어요.")
        return

    if member.bot:
        await ctx.send("❌ 봇은 야차방 참여자로 추가할 수 없어요.")
        return

    if member.id in members:
        await ctx.send(f"ℹ️ {member.mention} 님은 이미 채팅 가능 상태예요.")
        return

    members.add(member.id)
    yacha_data["members"] = list(members)
    save_yacha_data()

    await update_yacha_permissions(ctx.guild)

    await ctx.send(
        f"✅ {member.mention} 님을 야차방 채팅 가능 인원에 추가했어요."
    )


@yacha_group.command(name="제거")
async def yacha_remove(ctx, member: discord.Member):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    channel = get_yacha_channel(ctx.guild)
    if channel is None:
        await ctx.send("❌ 야차방이 없어요.")
        return

    members = get_yacha_members()

    if not is_admin(ctx.author) and ctx.author.id not in members:
        await ctx.send("❌ 야차방 당사자 또는 관리자만 사람을 제거할 수 있어요.")
        return

    if member.id not in members:
        await ctx.send(f"ℹ️ {member.mention} 님은 현재 채팅 가능 인원이 아니에요.")
        return

    members.discard(member.id)
    yacha_data["members"] = list(members)
    save_yacha_data()

    await channel.set_permissions(
        member,
        overwrite=None,
        reason="야차방 채팅 가능 인원에서 제거"
    )

    await ctx.send(
        f"✅ {member.mention} 님을 야차방 채팅 가능 인원에서 제거했어요.\n"
        "👀 이제 구경만 할 수 있어요."
    )


@yacha_group.command(name="목록")
async def yacha_list(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    channel = get_yacha_channel(ctx.guild)
    if channel is None:
        await ctx.send("❌ 야차방이 없어요.")
        return

    members = get_yacha_members()

    if not members:
        text = "현재 채팅 가능한 사람이 없어요."
    else:
        lines = []
        for member_id in members:
            member = ctx.guild.get_member(member_id)
            if member:
                status = "🚫 경고 제한" if get_warning_count(member.id) >= 2 else "💬 채팅 가능"
                lines.append(f"• {member.mention} — {status}")
        text = "\n".join(lines) if lines else "현재 채팅 가능한 사람이 없어요."

    await ctx.send(
        f"🔥 **야차방 참여자 목록**\n{text}\n\n"
        f"📍 {channel.mention}"
    )


@yacha_group.command(name="삭제")
@commands.has_permissions(administrator=True)
async def yacha_delete(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    channel = get_yacha_channel(ctx.guild)
    if channel is None:
        await ctx.send("❌ 삭제할 야차방이 없어요.")
        return

    await delete_yacha_channel(ctx.guild)
    await ctx.send("🗑️ 야차방을 삭제했어요.")


# =========================================================
# 경고 명령어
# =========================================================

@bot.command(name="경고")
@commands.has_permissions(administrator=True)
async def warning_add_command(ctx, member: discord.Member, *, reason: str = "규칙 위반"):
    if member.bot:
        await ctx.send("❌ 봇에게는 경고를 줄 수 없어요.")
        return

    count = await add_warning(
        member,
        ctx.author,
        reason
    )

    await send_warning_log(
        ctx.guild,
        member,
        ctx.author,
        count,
        reason
    )

    if count == 1:
        action = "🔒 19금/몸공유방 접근을 차단했어요."
    elif count == 2:
        action = "🔒 19금/몸공유방 + 야차방 채팅을 제한했어요."
    elif count == 3:
        action = "🔒 제한 유지 + 1시간 타임아웃을 적용했어요."
    elif count == 4:
        action = "🔒 제한 유지 + 24시간 타임아웃을 적용했어요."
    else:
        action = "🚪 경고 5회 누적으로 서버에서 추방했어요."

    await ctx.send(
        f"⚠️ {member.mention} 님에게 **{count}회 경고**를 부여했어요.\n"
        f"📝 사유: `{reason}`\n"
        f"{action}"
    )


@bot.command(name="경고목록")
@commands.has_permissions(administrator=True)
async def warning_list_command(ctx, member: discord.Member):
    count = get_warning_count(member.id)
    data = warnings_data.get(str(member.id), {})
    reasons = data.get("reasons", [])

    if not reasons:
        await ctx.send(f"📋 {member.mention} 님의 경고는 **0회**예요.")
        return

    lines = []
    for index, item in enumerate(reasons, start=1):
        reason = item.get("reason", "사유 없음")
        moderator_id = item.get("moderator_id")
        moderator = ctx.guild.get_member(int(moderator_id)) if moderator_id else None
        moderator_text = moderator.mention if moderator else "알 수 없음"
        lines.append(f"`{index}.` {reason} — {moderator_text}")

    await ctx.send(
        f"⚠️ **{member.display_name} 경고 기록**\n"
        f"현재 경고: **{count}회**\n\n"
        + "\n".join(lines)
    )


@bot.command(name="경고취소")
@commands.has_permissions(administrator=True)
async def warning_remove_command(ctx, member: discord.Member):
    old_count = get_warning_count(member.id)

    if old_count <= 0:
        await ctx.send(f"ℹ️ {member.mention} 님은 경고가 없어요.")
        return

    new_count = await remove_one_warning(member)

    await ctx.send(
        f"↩️ {member.mention} 님의 경고 1회를 취소했어요.\n"
        f"현재 경고: **{new_count}회**"
    )


@bot.command(name="경고초기화")
@commands.has_permissions(administrator=True)
async def warning_clear_command(ctx, member: discord.Member):
    old_count = get_warning_count(member.id)

    await clear_all_warnings(member)

    await ctx.send(
        f"🧹 {member.mention} 님의 경고를 전부 초기화했어요.\n"
        f"기존 경고: **{old_count}회 → 0회**"
    )


# =========================================================
# 역할 관련
# =========================================================

async def remove_role_if_exists(member, role_id):
    role = member.guild.get_role(role_id)

    if role and role in member.roles:
        try:
            await member.remove_roles(role)
        except Exception as e:
            print(
                f"[역할 제거 실패] "
                f"{member} / {role.name}: {e}"
            )


async def add_role_if_exists(member, role_id):
    role = member.guild.get_role(role_id)

    if role and role not in member.roles:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(
                f"[역할 지급 실패] "
                f"{member} / {role.name}: {e}"
            )


async def apply_intro_roles(member, birth_year, gender):

    # 미인증 제거
    await remove_role_if_exists(
        member,
        UNVERIFIED_ROLE_ID
    )

    # 기존 성별 제거
    await remove_role_if_exists(
        member,
        MALE_ROLE_ID
    )

    await remove_role_if_exists(
        member,
        FEMALE_ROLE_ID
    )

    # 기존 나이 역할 제거
    await remove_role_if_exists(
        member,
        ADULT_ROLE_ID
    )

    await remove_role_if_exists(
        member,
        MINOR_ROLE_ID
    )

    # 성별 지급
    if gender == "남":
        await add_role_if_exists(
            member,
            MALE_ROLE_ID
        )

    elif gender == "여":
        await add_role_if_exists(
            member,
            FEMALE_ROLE_ID
        )

    # 나이 지급
    age_type = get_age_type(birth_year)

    if age_type == "성인":
        await add_role_if_exists(
            member,
            ADULT_ROLE_ID
        )

    else:
        await add_role_if_exists(
            member,
            MINOR_ROLE_ID
        )


# =========================================================
# 자기소개 완료 메시지
# =========================================================

async def send_intro_success_message(
    message,
    birth_year,
    gender
):

    age_type = get_age_type(birth_year)
    gender_text = get_gender_text(gender)

    await message.channel.send(
        f"🖤・♡・어서 와요  ♡ "
        f"**{message.author.mention}** 님, "
        f"자기소개 확인했어 ♡\n"
        f"`{birth_year}년생` · "
        f"`{gender_text}` · "
        f"`{age_type}`\n\n"
        f"🎀 <#{ROLE_CHANNEL_ID}>에서 "
        f"역할을 골라주세요.\n"
        f"💬 <#{MAIN_CHAT_CHANNEL_ID}>에서 "
        f"편하게 놀아요 ♡"
    )


# =========================================================
# 입장 시 DM
# =========================================================

async def send_welcome_dm(member):

    try:
        await member.send(
            f"🖤 **{member.guild.name}에 오신 걸 환영해요 ♡**\n\n"
            f"입장 후 **30분 이내에 자기소개**를 작성해주세요.\n\n"
            f"예시:\n"
            f"`04 남`\n"
            f"`04 여`\n"
            f"`08 ㄴ`\n"
            f"`08 ㅇ`\n\n"
            f"또는\n"
            f"`1999 남`\n"
            f"`2004 여`\n\n"
            f"30분 동안 자기소개가 없으면 "
            f"관리자에게 추방 확인 요청이 전달됩니다."
        )

    except Exception as e:
        print(
            f"[DM 전송 실패] {member}: {e}"
        )


# =========================================================
# 추방 확인 버튼
# =========================================================

class KickConfirmView(discord.ui.View):

    def __init__(self, guild_id, member_id):
        super().__init__(timeout=None)

        self.guild_id = guild_id
        self.member_id = member_id

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(
                "❌ 이 버튼은 추방 권한이 있는 관리자만 사용할 수 있어요.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="예, 추방하기",
        style=discord.ButtonStyle.danger,
        emoji="🚪"
    )
    async def confirm_kick(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = bot.get_guild(self.guild_id)

        if guild is None:
            await interaction.response.send_message(
                "❌ 서버를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        member = guild.get_member(self.member_id)

        if member is None:
            await interaction.response.edit_message(
                content="ℹ️ 이미 서버에 없는 멤버입니다.",
                view=None
            )

            pending_kick_reviews.discard(
                self.member_id
            )

            return

        # =================================================
        # 핵심 안전장치
        # 버튼을 누르는 순간 자기소개 여부를 다시 확인
        # =================================================

        member_key = str(member.id)
        data = members_data.get(member_key)

        if not data:
            await interaction.response.send_message(
                "⚠️ 이 멤버의 등록 정보를 찾을 수 없어 추방하지 않았어요.",
                ephemeral=True
            )
            return

        if data.get("intro_completed", False):

            await interaction.response.edit_message(
                content=(
                    f"✅ **추방 취소**\n"
                    f"{member.mention} 님이 이미 자기소개를 완료했어요."
                ),
                view=None
            )

            pending_kick_reviews.discard(
                self.member_id
            )

            return

        # 관리자에게 최종 확인 후 추방
        try:
            await member.kick(
                reason="30분 이상 자기소개 미작성 - 관리자 확인"
            )

            await interaction.response.edit_message(
                content=(
                    f"🚪 **추방 완료**\n"
                    f"{member.mention} 님을 추방했어요."
                ),
                view=None
            )

            pending_kick_reviews.discard(
                self.member_id
            )

            # 데이터에도 기록
            data["kicked"] = True
            data["kick_reason"] = "30분 이상 자기소개 미작성"
            data["kicked_at"] = utc_string(now_utc())

            save_json(
                MEMBERS_FILE,
                members_data
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ 봇에게 멤버 추방 권한이 없거나 역할 순서가 잘못되어 있어요.",
                ephemeral=True
            )

        except Exception as e:

            print(
                f"[추방 오류] {member}: {e}"
            )

            await interaction.response.send_message(
                "❌ 추방 중 오류가 발생했어요.",
                ephemeral=True
            )

    @discord.ui.button(
        label="아니오, 취소",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel_kick(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        member_key = str(self.member_id)

        data = members_data.get(member_key)

        if data:
            data["kick_review_declined_until"] = utc_string(
                now_utc() + timedelta(hours=24)
            )

            save_json(
                MEMBERS_FILE,
                members_data
            )

        pending_kick_reviews.discard(
            self.member_id
        )

        await interaction.response.edit_message(
            content=(
                "❌ **추방 취소**\n"
                "관리자가 추방을 취소했어요.\n"
                "앞으로 24시간 동안 같은 확인 요청을 다시 보내지 않아요."
            ),
            view=None
        )


# =========================================================
# 추방 확인 요청
# =========================================================

async def send_kick_review(guild, member):

    if member.id in pending_kick_reviews:
        return

    channel = discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if channel is None:
        print(
            f"[오류] {LOG_CHANNEL_NAME} 채널을 찾을 수 없습니다."
        )
        return

    pending_kick_reviews.add(
        member.id
    )

    embed = discord.Embed(
        title="🚨 자기소개 미작성 확인",
        description=(
            f"👤 **대상:** {member.mention}\n"
            f"🆔 **ID:** `{member.id}`\n"
            f"⏰ **입장 후 30분 경과**\n"
            f"📝 **자기소개:** 작성하지 않음\n\n"
            f"이 회원을 추방할까요?"
        ),
        color=discord.Color.red()
    )

    embed.set_footer(
        text="관리자만 버튼을 사용할 수 있습니다."
    )

    view = KickConfirmView(
        guild.id,
        member.id
    )

    try:
        await channel.send(
            embed=embed,
            view=view
        )

    except Exception as e:
        pending_kick_reviews.discard(
            member.id
        )

        print(
            f"[추방 확인 메시지 오류] {e}"
        )


# =========================================================
# 자기소개 30분 검사
# =========================================================

@tasks.loop(minutes=CHECK_MINUTES)
async def intro_check_loop():

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        return

    current_time = now_utc()

    changed = False

    for member_id, data in list(members_data.items()):

        # -------------------------
        # 이미 자기소개 완료
        # -------------------------

        if data.get("intro_completed", False):
            continue

        # -------------------------
        # 이미 추방 처리된 데이터
        # -------------------------

        if data.get("kicked", False):
            continue

        # -------------------------
        # 기존 멤버 보호
        # -------------------------

        if data.get("is_existing_member", False):
            continue

        # -------------------------
        # 입장 시간 확인
        # -------------------------

        joined_at_raw = data.get("joined_at")

        if not joined_at_raw:
            continue

        joined_at = parse_datetime(
            joined_at_raw
        )

        if joined_at is None:
            continue

        # -------------------------
        # 30분 경과 여부
        # -------------------------

        deadline = joined_at + timedelta(
            minutes=INTRO_DEADLINE_MINUTES
        )

        if current_time < deadline:
            continue

        # -------------------------
        # 실제 서버 멤버 확인
        # -------------------------

        try:
            member_id_int = int(member_id)

        except Exception:
            continue

        member = guild.get_member(
            member_id_int
        )

        # 이미 나간 사람
        if member is None:
            continue

        # -------------------------
        # 관리자 보호
        # -------------------------

        if member.guild_permissions.administrator:
            continue

        # 봇 보호
        if member.bot:
            continue

        # -------------------------
        # 24시간 취소 여부
        # -------------------------

        declined_raw = data.get(
            "kick_review_declined_until"
        )

        if declined_raw:

            declined_until = parse_datetime(
                declined_raw
            )

            if declined_until:

                if current_time < declined_until:
                    continue

                # 기간이 끝났으므로 삭제
                data.pop(
                    "kick_review_declined_until",
                    None
                )

                changed = True

        # -------------------------
        # 다시 한번 자기소개 여부 확인
        # -------------------------

        if data.get("intro_completed", False):
            continue

        # -------------------------
        # 관리자 확인 요청
        # -------------------------

        await send_kick_review(
            guild,
            member
        )

    if changed:
        save_json(
            MEMBERS_FILE,
            members_data
        )


# =========================================================
# 봇 준비
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"JARVIS 로그인 완료: {bot.user}")
    print(f"서버 수: {len(bot.guilds)}")
    print("=" * 50)

    load_data()

    # 기존 야차방이 있으면 권한 상태 복구
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await update_yacha_permissions(guild)
        except Exception as e:
            print(f"[야차방 복구 오류] {e}")

    if not intro_check_loop.is_running():
        intro_check_loop.start()


# =========================================================
# 신규 멤버 입장
# =========================================================

@bot.event
async def on_member_join(member):

    if member.guild.id != GUILD_ID:
        return

    # 봇은 기록하지 않음
    if member.bot:
        return

    member_key = str(member.id)

    # 신규 가입자 데이터
    members_data[member_key] = {
        "joined_at": utc_string(now_utc()),
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": utc_string(now_utc()),

        # 신규 가입자
        "is_existing_member": False,

        # 추방 여부
        "kicked": False
    }

    save_json(
        MEMBERS_FILE,
        members_data
    )

    # 미인증 역할
    await add_role_if_exists(
        member,
        UNVERIFIED_ROLE_ID
    )

    # DM 안내
    await send_welcome_dm(
        member
    )

    print(
        f"[입장] {member} / "
        f"30분 자기소개 타이머 시작"
    )


# =========================================================
# 메시지 처리
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    if message.guild.id != GUILD_ID:
        await bot.process_commands(message)
        return

    member = message.author

    member_key = str(member.id)

    # =====================================================
    # 데이터가 없는 기존 멤버
    # =====================================================

    if member_key not in members_data:

        members_data[member_key] = {
            "joined_at": utc_string(
                member.joined_at or now_utc()
            ),
            "intro_completed": False,
            "birth_year": None,
            "gender": None,
            "last_activity": utc_string(now_utc()),

            # 중요:
            # 이미 서버에 있던 멤버이므로
            # 30분 추방 대상이 아님
            "is_existing_member": True,

            "kicked": False
        }

        save_json(
            MEMBERS_FILE,
            members_data
        )

    # =====================================================
    # 활동 기록
    # =====================================================

    update_activity(
        member.id
    )

    # =====================================================
    # 자기소개 검사
    # =====================================================

    parsed = parse_intro(
        message.content
    )

    if parsed:

        birth_year, gender = parsed

        # 데이터 저장
        members_data[member_key][
            "intro_completed"
        ] = True

        members_data[member_key][
            "birth_year"
        ] = birth_year

        members_data[member_key][
            "gender"
        ] = gender

        members_data[member_key][
            "intro_completed_at"
        ] = utc_string(
            now_utc()
        )

        # 기존 취소 기록 삭제
        members_data[member_key].pop(
            "kick_review_declined_until",
            None
        )

        save_json(
            MEMBERS_FILE,
            members_data
        )

        # 역할 적용
        await apply_intro_roles(
            member,
            birth_year,
            gender
        )

        # 성공 메시지
        await send_intro_success_message(
            message,
            birth_year,
            gender
        )

        # 자기소개 처리했으므로 여기서 종료
        await bot.process_commands(message)
        return

    # =====================================================
    # AI
    # =====================================================

    await handle_ai_message(
        message
    )

    # =====================================================
    # 명령어
    # =====================================================

    await bot.process_commands(message)



# =========================================================
# 자기소개 수정 감지
# =========================================================

@bot.event
async def on_message_edit(before, after):
    if after.author.bot:
        return

    if after.guild is None:
        return

    if after.guild.id != GUILD_ID:
        return

    # 내용이 실제로 바뀌지 않았으면 무시
    if before.content == after.content:
        return

    member = after.author
    member_key = str(member.id)

    # 데이터가 없으면 기존 멤버로 등록
    if member_key not in members_data:
        members_data[member_key] = {
            "joined_at": utc_string(
                member.joined_at or now_utc()
            ),
            "intro_completed": False,
            "birth_year": None,
            "gender": None,
            "last_activity": utc_string(now_utc()),
            "is_existing_member": True,
            "kicked": False
        }

    update_activity(member.id)

    parsed = parse_intro(after.content)

    if not parsed:
        # 잘못 수정한 경우 기존 정상 자기소개 정보는 유지
        # 즉, 실수로 메시지를 수정했다고 바로 미작성 처리하지 않음.
        return

    birth_year, gender = parsed

    members_data[member_key]["intro_completed"] = True
    members_data[member_key]["birth_year"] = birth_year
    members_data[member_key]["gender"] = gender
    members_data[member_key]["intro_completed_at"] = utc_string(now_utc())
    members_data[member_key].pop(
        "kick_review_declined_until",
        None
    )

    save_json(MEMBERS_FILE, members_data)

    await apply_intro_roles(
        member,
        birth_year,
        gender
    )

    age_type = get_age_type(birth_year)
    gender_text = get_gender_text(gender)

    try:
        await after.channel.send(
            f"✏️ **자기소개 수정 확인**\n"
            f"{member.mention} 님의 수정된 자기소개를 다시 확인했어요.\n"
            f"`{birth_year}년생` · `{gender_text}` · `{age_type}`"
        )
    except Exception as e:
        print(f"[수정 감지 메시지 오류] {e}")


# =========================================================
# 음성 활동
# =========================================================

@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if member.bot:
        return

    if member.guild.id != GUILD_ID:
        return

    update_activity(
        member.id
    )


# =========================================================
# AI 메시지 처리
# =========================================================

async def handle_ai_message(message):

    if gemini_client is None:
        return

    if not chat_settings.get(
        "enabled",
        True
    ):
        return

    content = message.content.strip()

    if not content:
        return

    channel_name = message.channel.name

    is_ai_channel = (
        message.channel.id == MAIN_CHAT_CHANNEL_ID
        or channel_name == ADULT_CHAT_CHANNEL
        or channel_name == ADULT_19_CHANNEL
    )

    is_mention = bot.user in message.mentions

    trigger_words = [
        "봇아",
        "자비스"
    ]

    has_trigger = any(
        word in content.lower()
        for word in trigger_words
    )

    if not (
        is_ai_channel
        or is_mention
        or has_trigger
    ):
        return

    # =====================================================
    # 미성년자 성인채팅 보호
    # =====================================================

    member_data = members_data.get(
        str(message.author.id),
        {}
    )

    birth_year = member_data.get(
        "birth_year"
    )

    if channel_name in [
        ADULT_CHAT_CHANNEL,
        ADULT_19_CHANNEL
    ]:

        if not member_data.get(
            "intro_completed",
            False
        ):

            await message.reply(
                "🖤 먼저 자기소개를 완료해주세요."
            )

            return

        if not birth_year:
            await message.reply(
                "🖤 나이 확인이 되지 않았어요."
            )

            return

        if get_age_type(
            birth_year
        ) != "성인":

            await message.reply(
                "🔒 이 채널은 성인만 이용할 수 있어요."
            )

            return

    # =====================================================
    # AI 쿨다운
    # =====================================================

    user_id = message.author.id

    current_time = now_utc()

    last_time = ai_cooldowns.get(
        user_id
    )

    if last_time:

        if (
            current_time - last_time
        ).total_seconds() < 2:

            return

    ai_cooldowns[user_id] = current_time

    # =====================================================
    # 메시지 정리
    # =====================================================

    clean_content = content

    if bot.user:
        clean_content = clean_content.replace(
            f"<@{bot.user.id}>",
            ""
        )

        clean_content = clean_content.replace(
            f"<@!{bot.user.id}>",
            ""
        )

    clean_content = clean_content.strip()

    if not clean_content:
        clean_content = "안녕"

    # =====================================================
    # 대화 기록
    # =====================================================

    channel_id = str(
        message.channel.id
    )

    if channel_id not in chat_history:
        chat_history[channel_id] = []

    history = chat_history[channel_id]

    history.append({
        "role": "user",
        "content": clean_content
    })

    # 최근 12개
    history = history[-12:]

    chat_history[channel_id] = history

    # =====================================================
    # AI 요청
    # =====================================================

    try:

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

        messages.extend(
            history
        )

        response = await asyncio.to_thread(
            gemini_client.chat.completions.create,
            model=GEMINI_MODEL,
            messages=messages,
            max_tokens=700,
            temperature=0.8
        )

        reply = response.choices[0].message.content

        if not reply:
            return

        reply = reply.strip()

        # Discord 메시지 최대 길이
        if len(reply) > 1900:
            reply = reply[:1900] + "..."

        history.append({
            "role": "assistant",
            "content": reply
        })

        chat_history[channel_id] = history[-12:]

        await message.reply(
            reply,
            mention_author=False
        )

    except Exception as e:

        print(
            f"[Gemini 오류] {type(e).__name__}: {e}"
        )

        await message.reply(
            "🖤 지금은 머리가 잠깐 꼬였어 ㅋㅋ 조금 있다가 다시 말 걸어줘!"
        )


# =========================================================
# !대화
# =========================================================

@bot.command(name="대화")
@commands.has_permissions(administrator=True)
async def chat_toggle(
    ctx,
    mode: str = None
):

    global chat_settings

    if mode is None:
        status = (
            "켜짐"
            if chat_settings.get("enabled", True)
            else "꺼짐"
        )

        await ctx.send(
            f"🤖 AI 대화 상태: **{status}**"
        )

        return

    mode = mode.lower()

    if mode in ["on", "켜", "켜기"]:

        chat_settings["enabled"] = True

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🤖 AI 대화를 **켜졌어.**"
        )

    elif mode in ["off", "꺼", "끄기"]:

        chat_settings["enabled"] = False

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🤖 AI 대화를 **꺼졌어.**"
        )

    else:

        await ctx.send(
            "사용법: `!대화 on` 또는 `!대화 off`"
        )


# =========================================================
# !기억초기화
# =========================================================

@bot.command(name="기억초기화")
@commands.has_permissions(administrator=True)
async def clear_ai_memory(ctx):

    chat_history.clear()

    await ctx.send(
        "🧠 JARVIS의 현재 대화 기억을 초기화했어."
    )


# =========================================================
# !상태
# =========================================================

@bot.command(name="상태")
async def status_command(ctx):

    data = members_data.get(
        str(ctx.author.id)
    )

    if not data:

        await ctx.send(
            "📋 아직 내 데이터에 등록되지 않았어."
        )

        return

    intro = (
        "완료"
        if data.get("intro_completed", False)
        else "미작성"
    )

    birth_year = data.get(
        "birth_year"
    )

    gender = data.get(
        "gender"
    )

    age_text = "-"

    if birth_year:
        age_text = (
            f"{birth_year}년생 / "
            f"{get_gender_text(gender)} / "
            f"{get_age_type(birth_year)}"
        )

    joined_at = parse_datetime(
        data.get("joined_at", "")
    )

    timer_text = "-"

    if joined_at:

        deadline = joined_at + timedelta(
            minutes=INTRO_DEADLINE_MINUTES
        )

        remaining = deadline - now_utc()

        if remaining.total_seconds() > 0:

            total_seconds = int(
                remaining.total_seconds()
            )

            minutes = total_seconds // 60
            seconds = total_seconds % 60

            timer_text = (
                f"{minutes}분 {seconds}초 남음"
            )

        else:

            timer_text = "30분 경과"

    await ctx.send(
        f"📋 **JARVIS 상태**\n\n"
        f"👤 자기소개: **{intro}**\n"
        f"🎂 정보: **{age_text}**\n"
        f"⏰ 자기소개 타이머: **{timer_text}**"
    )


# =========================================================
# !검사
# =========================================================

@bot.command(name="검사")
@commands.has_permissions(administrator=True)
async def check_member(
    ctx,
    member: discord.Member = None
):

    if member is None:
        member = ctx.author

    data = members_data.get(
        str(member.id)
    )

    if not data:

        await ctx.send(
            f"❌ {member.mention}의 데이터를 찾을 수 없어요."
        )

        return

    intro = data.get(
        "intro_completed",
        False
    )

    birth_year = data.get(
        "birth_year"
    )

    gender = data.get(
        "gender"
    )

    result = (
        "완료"
        if intro
        else "미작성"
    )

    info = "없음"

    if birth_year:
        info = (
            f"{birth_year}년생 / "
            f"{get_gender_text(gender)} / "
            f"{get_age_type(birth_year)}"
        )

    await ctx.send(
        f"🔎 **회원 검사**\n"
        f"👤 {member.mention}\n"
        f"📝 자기소개: **{result}**\n"
        f"🎂 정보: **{info}**"
    )


# =========================================================
# !자기소개초기화
# =========================================================

@bot.command(name="자기소개초기화")
@commands.has_permissions(administrator=True)
async def reset_intro(
    ctx,
    member: discord.Member
):

    member_key = str(member.id)

    if member_key not in members_data:

        await ctx.send(
            "❌ 이 멤버의 데이터를 찾을 수 없어요."
        )

        return

    members_data[member_key][
        "intro_completed"
    ] = False

    members_data[member_key][
        "birth_year"
    ] = None

    members_data[member_key][
        "gender"
    ] = None

    members_data[member_key].pop(
        "intro_completed_at",
        None
    )

    members_data[member_key].pop(
        "kick_review_declined_until",
        None
    )

    members_data[member_key][
        "is_existing_member"
    ] = True

    save_json(
        MEMBERS_FILE,
        members_data
    )

    # 미인증 역할 다시 지급
    await add_role_if_exists(
        member,
        UNVERIFIED_ROLE_ID
    )

    # 성별 / 나이 역할 제거
    await remove_role_if_exists(
        member,
        MALE_ROLE_ID
    )

    await remove_role_if_exists(
        member,
        FEMALE_ROLE_ID
    )

    await remove_role_if_exists(
        member,
        ADULT_ROLE_ID
    )

    await remove_role_if_exists(
        member,
        MINOR_ROLE_ID
    )

    await ctx.send(
        f"🔄 {member.mention}의 자기소개 정보를 초기화했어요."
    )


# =========================================================
# !추방로그테스트
# =========================================================

@bot.command(name="추방로그테스트")
@commands.has_permissions(administrator=True)
async def kick_log_test(ctx):

    channel = discord.utils.get(
        ctx.guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if channel is None:

        await ctx.send(
            f"❌ `{LOG_CHANNEL_NAME}` 채널을 찾지 못했어요."
        )

        return

    await channel.send(
        "🧪 **추방 로그 테스트 성공**\n"
        "이 채널에 정상적으로 메시지를 보낼 수 있어요."
    )

    await ctx.send(
        "✅ 추방로그 테스트 완료."
    )


# =========================================================
# !추방확인테스트
# =========================================================

@bot.command(name="추방확인테스트")
@commands.has_permissions(administrator=True)
async def kick_confirm_test(
    ctx,
    member: discord.Member
):

    await send_kick_review(
        ctx.guild,
        member
    )

    await ctx.send(
        f"✅ {member.mention}에 대한 추방 확인창을 보냈어요."
    )



# =========================================================
# !도움말
# =========================================================

@bot.command(name="도움말", aliases=["도움"])
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 JARVIS 명령어",
        description="현재 사용할 수 있는 명령어를 정리했어요.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👤 일반",
        value=(
            "`!상태` — 내 자기소개/타이머 확인\n"
            "`!도움말` — 명령어 확인"
        ),
        inline=False
    )

    embed.add_field(
        name="🔥 야차방",
        value=(
            "`!야차방 생성` — 야차방 생성\n"
            "`!야차방 추가 @회원` — 채팅 가능 인원 추가\n"
            "`!야차방 제거 @회원` — 채팅 가능 인원 제거\n"
            "`!야차방 목록` — 참여자 확인\n"
            "`!야차방 삭제` — 야차방 삭제 (관리자)"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ 경고 (관리자)",
        value=(
            "`!경고 @회원 사유`\n"
            "`!경고목록 @회원`\n"
            "`!경고취소 @회원`\n"
            "`!경고초기화 @회원`"
        ),
        inline=False
    )

    embed.add_field(
        name="🛡️ 관리 (관리자)",
        value=(
            "`!검사 @회원`\n"
            "`!자기소개초기화 @회원`\n"
            "`!추방로그테스트`\n"
            "`!추방확인테스트 @회원`\n"
            "`!대화 on/off`\n"
            "`!기억초기화`"
        ),
        inline=False
    )

    embed.set_footer(
        text="경고 단계: 1회=19금/몸공유방 차단 · 2회=야차 채팅 차단 · 3회=1시간 타임아웃"
    )

    await ctx.send(embed=embed)


# =========================================================
# 명령어 오류 처리
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            "❌ 이 명령어를 사용할 권한이 없어요."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 필요한 값을 빠뜨렸어요."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 멤버를 찾지 못했어요."
        )

        return

    print(
        f"[명령어 오류] {type(error).__name__}: {error}"
    )


# =========================================================
# 실행
# =========================================================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN을 설정해주세요."
    )

if not GEMINI_API_KEY:
    print(
        "[경고] GEMINI_API_KEY가 없습니다. "
        "AI 기능은 사용할 수 없습니다."
    )


bot.run(
    DISCORD_TOKEN
)
