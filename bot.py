import os
import json
import re
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv


# =========================================================
# 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

try:
    GUILD_ID = int(
        os.getenv(
            "GUILD_ID",
            "1542210983127425158"
        )
    )
except ValueError:
    GUILD_ID = 1542210983127425158


# 로그 채널
LOG_CHANNEL = "🚪・추방로그"

# 야차방
YACHA_CATEGORY = "[ 💬 ] ─ 채팅"
YACHA_NAME = "＃↝・야차"

# 메인 채팅 채널
MAIN_CHAT_ID = 1544032267855470644

# 자기소개 제한 시간
INTRO_MINUTES = 30

# 2007년생까지 성인
ADULT_CUTOFF = 2007

# 2012년생부터 입장 제한
MIN_ALLOWED_BIRTH_YEAR = 2011

# 역할 안내 채널
ROLE_CHANNEL_ID = 1549631714769244261

# 역할 ID
ROLES = {
    "unverified": 1544031900295893112,
    "male": 1544031878812532858,
    "female": 1544031884227518525,
    "adult": 1544031894809616475,
    "minor": 1544031889533182043,
}

# 몸공유방 ID
BODY_SHARE_ID = 1544276267522719794


# =========================================================
# 데이터 파일
# =========================================================

FILES = {
    "members": "members.json",
    "chat": "chat.json",
    "yacha": "yacha_data.json",
    "warnings": "warnings.json",
}


# 경고별 타임아웃
WARNING_TIMEOUT = {
    3: 60 * 60,
    4: 24 * 60 * 60,
}


# =========================================================
# Discord
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
# 데이터
# =========================================================

members = {}
chat_settings = {}
yacha = {}
warnings = {}

# 자기소개 미작성 추방 확인 대기
pending_kicks = set()


# =========================================================
# JSON
# =========================================================

def load_json(file, default):
    """
    JSON 파일을 읽습니다.
    파일이 없거나 손상된 경우 default를 반환합니다.
    """

    try:
        if not os.path.exists(file):
            return default

        with open(
            file,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except (
        json.JSONDecodeError,
        OSError,
        TypeError
    ) as e:

        print(
            f"[JSON 읽기 오류] {file}: {e}"
        )

        return default


def save_json(file, data):
    """
    임시 파일에 먼저 저장한 뒤
    정상적으로 저장되면 원본을 교체합니다.
    """

    try:
        tmp = file + ".tmp"

        with open(
            tmp,
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
            tmp,
            file
        )

    except Exception as e:

        print(
            f"[JSON 저장 오류] {file}: {e}"
        )


def load_data():
    global members
    global chat_settings
    global yacha
    global warnings

    members = load_json(
        FILES["members"],
        {}
    )

    chat_settings = load_json(
        FILES["chat"],
        {
            "enabled": True
        }
    )

    yacha = load_json(
        FILES["yacha"],
        {}
    )

    warnings = load_json(
        FILES["warnings"],
        {}
    )

    print("=" * 50)
    print(
        f"[DATA] 회원       : {len(members)}명"
    )
    print(
        f"[DATA] 경고       : {len(warnings)}명"
    )
    print(
        f"[DATA] 야차 데이터: {yacha}"
    )
    print(
        f"[DATA] 채팅 설정  : {chat_settings}"
    )
    print("=" * 50)


# =========================================================
# 공통
# =========================================================

def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def parse_dt(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)

    except (
        ValueError,
        TypeError
    ):
        return None


def member_data(member):
    """
    회원 데이터를 가져옵니다.
    없으면 기본 데이터를 생성합니다.
    """

    return members.setdefault(
        str(member.id),
        {
            "joined_at": iso(
                member.joined_at or now()
            ),
            "intro_completed": False,
            "birth_year": None,
            "gender": None,
            "last_activity": iso(now()),
            "is_existing_member": True,
            "kicked": False
        }
    )


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

    except (
        ValueError,
        TypeError
    ):
        return 0


def is_admin(member):
    return member.guild_permissions.administrator


def age_type(year):
    return (
        "성인"
        if year <= ADULT_CUTOFF
        else "미성년자"
    )


def gender_text(gender):
    return {
        "남": "남자",
        "여": "여자"
    }.get(
        gender,
        "미확인"
    )


# =========================================================
# 자기소개
# =========================================================

def parse_intro(text):
    """
    자기소개에서 출생년도와 성별을 찾습니다.

    예:
    07 남
    07남
    2007 남
    2007남
    07 ㄴ
    07 여
    """

    match = re.search(
        r"(?<!\d)((?:19|20)\d{2}|\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)",
        text.strip()
    )

    if not match:
        return None

    raw, gender = match.groups()

    current = datetime.now().year

    if len(raw) == 4:
        year = int(raw)

    else:
        n = int(raw)

        year = (
            2000 + n
            if n <= current % 100
            else 1900 + n
        )

    if not 1900 <= year <= current:
        return None

    return (
        year,
        "남"
        if gender in ("남", "ㄴ")
        else "여"
    )


async def role(
    member,
    role_id,
    add=True
):
    role_obj = member.guild.get_role(
        role_id
    )

    if not role_obj:

        print(
            f"[역할 오류] 역할 ID를 찾을 수 없음: "
            f"{role_id}"
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

    except discord.Forbidden:

        print(
            f"[역할 오류] "
            f"봇에게 역할 관리 권한이 없음: "
            f"{role_obj.name}"
        )

    except discord.HTTPException as e:

        print(
            f"[역할 오류] Discord API 오류: {e}"
        )

    except Exception as e:

        print(
            f"[역할 오류] {e}"
        )


async def apply_intro_roles(
    member,
    year,
    gender
):
    # 기존 역할 제거
    for key in (
        "unverified",
        "male",
        "female",
        "adult",
        "minor"
    ):

        await role(
            member,
            ROLES[key],
            False
        )

    # 성별 역할
    await role(
        member,
        ROLES["male"]
        if gender == "남"
        else ROLES["female"]
    )

    # 성인/미성년 역할
    await role(
        member,
        ROLES["adult"]
        if age_type(year) == "성인"
        else ROLES["minor"]
    )


async def intro_complete(
    message,
    year,
    gender
):
    """
    자기소개 완료 처리
    """

    # =====================================================
    # 연령 제한
    # =====================================================

    if year > MIN_ALLOWED_BIRTH_YEAR:

        try:

            log = discord.utils.get(
                message.guild.text_channels,
                name=LOG_CHANNEL
            )

            if log:

                await log.send(
                    f"🚫 **연령 제한 추방**\n"
                    f"대상: {message.author.mention}\n"
                    f"출생연도: `{year}년생`\n"
                    f"사유: `2012년생부터 서버 이용 제한`"
                )

            await message.author.kick(
                reason=(
                    "연령 제한 "
                    "(2012년생부터 이용 제한)"
                )
            )

            return

        except discord.Forbidden:

            print(
                "[연령 제한 추방 오류] "
                "봇에게 추방 권한이 없습니다."
            )

            return

        except discord.HTTPException as e:

            print(
                f"[연령 제한 추방 오류] "
                f"Discord API: {e}"
            )

            return

        except Exception as e:

            print(
                f"[연령 제한 추방 오류] {e}"
            )

            return

    # =====================================================
    # 회원 데이터 저장
    # =====================================================

    data = member_data(
        message.author
    )

    data.update({
        "intro_completed": True,
        "birth_year": year,
        "gender": gender,
        "intro_completed_at": iso(now())
    })

    data.pop(
        "kick_review_declined_until",
        None
    )

    save_json(
        FILES["members"],
        members
    )

    # =====================================================
    # 역할 적용
    # =====================================================

    await apply_intro_roles(
        message.author,
        year,
        gender
    )

    # =====================================================
    # 완료 메시지
    # =====================================================

    if MAIN_CHAT_ID:

        main_chat_text = (
            f"💬 <#{MAIN_CHAT_ID}>에서 "
            f"편하게 놀아요 ♡"
        )

    else:

        main_chat_text = (
            "💬 메인 채팅방에서 "
            "편하게 놀아요 ♡"
        )

    await message.channel.send(
        f"🖤 {message.author.mention} "
        f"자기소개 확인했어 ♡\n"
        f"`{year}년생` · "
        f"`{gender_text(gender)}` · "
        f"`{age_type(year)}`\n\n"
        f"🎀 <#{ROLE_CHANNEL_ID}>에서 "
        f"역할을 골라주세요.\n"
        f"{main_chat_text}"
    )


# =========================================================
# 야차방
# =========================================================

def yacha_channel(guild):
    cid = yacha.get(
        "channel_id"
    )

    if cid:

        try:

            channel = guild.get_channel(
                int(cid)
            )

            if isinstance(
                channel,
                discord.TextChannel
            ):
                return channel

        except (
            ValueError,
            TypeError
        ):
            pass

    return discord.utils.get(
        guild.text_channels,
        name=YACHA_NAME
    )


def yacha_members():
    raw_members = yacha.get(
        "members",
        []
    )

    result = set()

    for x in raw_members:

        try:
            result.add(
                int(x)
            )

        except (
            ValueError,
            TypeError
        ):
            continue

    return result


async def update_yacha(guild):
    channel = yacha_channel(
        guild
    )

    if not channel:
        return

    # 기본 권한
    try:

        await channel.set_permissions(
            guild.default_role,
            view_channel=True,
            send_messages=False,
            add_reactions=False
        )

    except discord.Forbidden:

        print(
            "[야차 권한 오류] "
            "봇 권한을 확인해주세요."
        )

    except Exception as e:

        print(
            f"[야차 기본 권한 오류] {e}"
        )

    # 참여자 권한
    for uid in yacha_members():

        member = guild.get_member(
            uid
        )

        if not member:
            continue

        try:

            count = warning_count(
                member
            )

            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=count < 2,
                add_reactions=count < 2
            )

        except Exception as e:

            print(
                f"[야차 회원 권한 오류] "
                f"{member}: {e}"
            )


async def create_yacha(guild):
    old = yacha_channel(
        guild
    )

    if old:
        return old, False

    category = discord.utils.get(
        guild.categories,
        name=YACHA_CATEGORY
    )

    if not category:
        return None, None

    try:

        channel = await guild.create_text_channel(
            YACHA_NAME,
            category=category,
            overwrites={
                guild.default_role:
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False
                    ),

                guild.me:
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        manage_channels=True
                    )
            }
        )

        return channel, True

    except discord.Forbidden:

        print(
            "[야차 생성 오류] "
            "채널 생성 권한이 없습니다."
        )

        return None, None

    except Exception as e:

        print(
            f"[야차 생성 오류] {e}"
        )

        return None, None


@bot.group(
    name="야차방",
    invoke_without_command=True
)
async def yacha_cmd(ctx):

    await ctx.send(
        "`!야차방 생성`\n"
        "`!야차방 추가 @회원`\n"
        "`!야차방 제거 @회원`\n"
        "`!야차방 목록`\n"
        "`!야차방 삭제`"
    )


@yacha_cmd.command(
    name="생성"
)
async def yacha_create(ctx):

    if not ctx.guild:
        return

    if ctx.guild.id != GUILD_ID:
        return

    if warning_count(ctx.author) >= 2:

        return await ctx.send(
            "🚫 경고 2회 이상이라 "
            "사용할 수 없어요."
        )

    channel, created = await create_yacha(
        ctx.guild
    )

    if created is None:

        return await ctx.send(
            "❌ 야차방 카테고리를 "
            "찾지 못했어요."
        )

    if not created:

        return await ctx.send(
            f"ℹ️ 이미 {channel.mention}이 있어요."
        )

    yacha.update({
        "channel_id": channel.id,
        "members": [
            ctx.author.id
        ],
        "created_by": ctx.author.id,
        "created_at": iso(now())
    })

    save_json(
        FILES["yacha"],
        yacha
    )

    await update_yacha(
        ctx.guild
    )

    await channel.send(
        f"🔥 **야차방 오픈**\n"
        f"👤 당사자: {ctx.author.mention}\n"
        f"👀 나머지는 구경만 가능해요."
    )

    await ctx.send(
        f"✅ {channel.mention} 생성 완료!"
    )


@yacha_cmd.command(
    name="추가"
)
async def yacha_add(
    ctx,
    member: discord.Member
):

    if not ctx.guild:
        return

    channel = yacha_channel(
        ctx.guild
    )

    if not channel:

        return await ctx.send(
            "❌ 먼저 야차방을 생성해주세요."
        )

    members_set = yacha_members()

    if (
        not is_admin(ctx.author)
        and ctx.author.id not in members_set
    ):

        return await ctx.send(
            "❌ 당사자 또는 관리자만 "
            "추가할 수 있어요."
        )

    if warning_count(member) >= 2:

        return await ctx.send(
            "🚫 경고 2회 이상인 회원은 "
            "추가할 수 없어요."
        )

    members_set.add(
        member.id
    )

    yacha["members"] = list(
        members_set
    )

    save_json(
        FILES["yacha"],
        yacha
    )

    await update_yacha(
        ctx.guild
    )

    await ctx.send(
        f"✅ {member.mention} 추가 완료!"
    )


@yacha_cmd.command(
    name="제거"
)
async def yacha_remove(
    ctx,
    member: discord.Member
):

    if not ctx.guild:
        return

    channel = yacha_channel(
        ctx.guild
    )

    if not channel:

        return await ctx.send(
            "❌ 야차방이 없어요."
        )

    members_set = yacha_members()

    if (
        not is_admin(ctx.author)
        and ctx.author.id not in members_set
    ):

        return await ctx.send(
            "❌ 당사자 또는 관리자만 "
            "제거할 수 있어요."
        )

    members_set.discard(
        member.id
    )

    yacha["members"] = list(
        members_set
    )

    save_json(
        FILES["yacha"],
        yacha
    )

    try:

        await channel.set_permissions(
            member,
            overwrite=None
        )

    except Exception:
        pass

    await ctx.send(
        f"✅ {member.mention} 제거 완료!"
    )


@yacha_cmd.command(
    name="목록"
)
async def yacha_list(ctx):

    if not ctx.guild:
        return

    channel = yacha_channel(
        ctx.guild
    )

    if not channel:

        return await ctx.send(
            "❌ 야차방이 없어요."
        )

    lines = []

    for uid in yacha_members():

        member = ctx.guild.get_member(
            uid
        )

        if member:

            status = (
                "🚫 제한"
                if warning_count(member) >= 2
                else "💬 가능"
            )

            lines.append(
                f"{member.mention} — {status}"
            )

    await ctx.send(
        "🔥 **야차방 참여자**\n"
        +
        (
            "\n".join(lines)
            if lines
            else "없음"
        )
    )


@yacha_cmd.command(
    name="삭제"
)
@commands.has_permissions(
    administrator=True
)
async def yacha_delete(ctx):

    if not ctx.guild:
        return

    channel = yacha_channel(
        ctx.guild
    )

    if not channel:

        return await ctx.send(
            "❌ 야차방이 없어요."
        )

    try:

        await channel.delete()

    except discord.Forbidden:

        return await ctx.send(
            "❌ 채널 삭제 권한이 없어요."
        )

    except Exception as e:

        return await ctx.send(
            f"❌ 야차방 삭제 실패: {e}"
        )

    yacha.clear()

    save_json(
        FILES["yacha"],
        yacha
    )

    await ctx.send(
        "🗑️ 야차방을 삭제했어요."
    )


# =========================================================
# 경고
# =========================================================

async def restricted_access(
    member,
    allow=False
):

    for channel in member.guild.channels:

        if (
            channel.name != "＃↝・19금"
            and channel.id != BODY_SHARE_ID
        ):
            continue

        try:

            if allow:

                await channel.set_permissions(
                    member,
                    overwrite=None
                )

            else:

                await channel.set_permissions(
                    member,
                    view_channel=False,
                    reason="경고 제한"
                )

        except Exception:
            pass


async def apply_warning(member):

    count = warning_count(
        member
    )

    # 경고 1회부터 19금/몸공유방 제한
    await restricted_access(
        member,
        count == 0
    )

    # 야차방 제한
    channel = yacha_channel(
        member.guild
    )

    if (
        channel
        and member.id in yacha_members()
    ):

        try:

            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=count < 2,
                add_reactions=count < 2
            )

        except Exception as e:

            print(
                f"[야차 경고 권한 오류] {e}"
            )

    # 5회 추방
    if count >= 5:

        try:

            await member.kick(
                reason="경고 5회"
            )

        except Exception as e:

            print(
                f"[경고 추방 오류] {e}"
            )

    # 3회 1시간
    elif count >= 3:

        try:

            timeout_seconds = (
                WARNING_TIMEOUT[4]
                if count >= 4
                else WARNING_TIMEOUT[3]
            )

            await member.timeout(
                discord.utils.utcnow()
                + timedelta(
                    seconds=timeout_seconds
                ),
                reason=f"경고 {count}회"
            )

        except Exception as e:

            print(
                f"[타임아웃 오류] {e}"
            )


async def add_warning(
    member,
    moderator,
    reason
):

    key = str(
        member.id
    )

    data = warnings.setdefault(
        key,
        {
            "count": 0,
            "reasons": []
        }
    )

    data["count"] += 1

    data["reasons"].append({
        "reason": reason,
        "moderator_id": moderator.id,
        "at": iso(now())
    })

    save_json(
        FILES["warnings"],
        warnings
    )

    await apply_warning(
        member
    )

    return data["count"]


@bot.command(
    name="경고"
)
@commands.has_permissions(
    administrator=True
)
async def warning(
    ctx,
    member: discord.Member,
    *,
    reason="규칙 위반"
):

    if member.bot:

        return await ctx.send(
            "❌ 봇에게는 경고할 수 없어요."
        )

    count = await add_warning(
        member,
        ctx.author,
        reason
    )

    log = discord.utils.get(
        ctx.guild.text_channels,
        name=LOG_CHANNEL
    )

    if log:

        await log.send(
            f"⚠️ **경고 기록**\n"
            f"대상: {member.mention}\n"
            f"처리자: {ctx.author.mention}\n"
            f"사유: {reason}\n"
            f"현재 경고: **{count}회**"
        )

    actions = {
        1: "19금/몸공유방 차단",
        2: "야차방 채팅 차단",
        3: "1시간 타임아웃",
        4: "24시간 타임아웃",
        5: "서버 추방"
    }

    await ctx.send(
        f"⚠️ {member.mention} "
        f"**{count}회 경고**\n"
        f"📝 {reason}\n"
        f"🔒 {actions[min(count, 5)]}"
    )


@bot.command(
    name="경고목록"
)
@commands.has_permissions(
    administrator=True
)
async def warning_list(
    ctx,
    member: discord.Member
):

    data = warnings.get(
        str(member.id),
        {}
    )

    reasons = data.get(
        "reasons",
        []
    )

    if not reasons:

        return await ctx.send(
            f"📋 {member.mention} 경고 0회"
        )

    text = "\n".join(
        f"`{i}.` "
        f"{x.get('reason', '사유 없음')}"
        for i, x in enumerate(
            reasons,
            1
        )
    )

    await ctx.send(
        f"⚠️ **{member.display_name} "
        f"경고 기록**\n"
        f"현재: **{warning_count(member)}회**\n"
        f"{text}"
    )


@bot.command(
    name="경고취소"
)
@commands.has_permissions(
    administrator=True
)
async def warning_remove(
    ctx,
    member: discord.Member
):

    key = str(
        member.id
    )

    if warning_count(member) <= 0:

        return await ctx.send(
            "ℹ️ 경고가 없어요."
        )

    data = warnings[key]

    data["count"] -= 1

    if data.get("reasons"):
        data["reasons"].pop()

    if data["count"] <= 0:
        warnings.pop(
            key,
            None
        )

    save_json(
        FILES["warnings"],
        warnings
    )

    await apply_warning(
        member
    )

    # 경고가 0회가 되면 제한 해제
    if warning_count(member) == 0:

        await restricted_access(
            member,
            True
        )

        # 야차방 권한도 기본값으로 복구
        channel = yacha_channel(
            ctx.guild
        )

        if channel:

            try:
                await channel.set_permissions(
                    member,
                    overwrite=None
                )

            except Exception:
                pass

    await ctx.send(
        f"↩️ {member.mention} "
        f"경고 1회 취소\n"
        f"현재: **{warning_count(member)}회**"
    )


@bot.command(
    name="경고초기화"
)
@commands.has_permissions(
    administrator=True
)
async def warning_clear(
    ctx,
    member: discord.Member
):

    warnings.pop(
        str(member.id),
        None
    )

    save_json(
        FILES["warnings"],
        warnings
    )

    # 19금 / 몸공유방 제한 해제
    await restricted_access(
        member,
        True
    )

    # 야차방 제한 해제
    channel = yacha_channel(
        ctx.guild
    )

    if channel:

        try:

            await channel.set_permissions(
                member,
                overwrite=None
            )

        except Exception:
            pass

    # 기존 타임아웃도 해제
    try:

        await member.timeout(
            None,
            reason="경고 초기화"
        )

    except Exception:
        pass

    await ctx.send(
        f"🧹 {member.mention} "
        f"경고 초기화 완료"
    )


# =========================================================
# 추방 확인
# =========================================================

class KickView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id,
        member_id
    ):
        super().__init__(
            timeout=None
        )

        self.guild_id = guild_id
        self.member_id = member_id

    async def interaction_check(
        self,
        interaction
    ):

        if not interaction.user.guild_permissions.kick_members:

            await interaction.response.send_message(
                "❌ 추방 권한이 필요해요.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="예, 추방하기",
        style=discord.ButtonStyle.danger,
        emoji="🚪"
    )
    async def kick(
        self,
        interaction,
        button
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        member = (
            guild.get_member(
                self.member_id
            )
            if guild
            else None
        )

        if not member:

            pending_kicks.discard(
                self.member_id
            )

            return await interaction.response.edit_message(
                content="ℹ️ 이미 서버에 없는 멤버예요.",
                view=None
            )

        data = members.get(
            str(member.id)
        )

        if not data:

            return await interaction.response.send_message(
                "⚠️ 회원 데이터를 찾지 못했어요.",
                ephemeral=True
            )

        # 버튼을 누르는 순간 자기소개를 완료했다면 추방하지 않음
        if data.get(
            "intro_completed"
        ):

            pending_kicks.discard(
                member.id
            )

            return await interaction.response.edit_message(
                content=(
                    "✅ 이미 자기소개를 완료해서 "
                    "추방하지 않았어요."
                ),
                view=None
            )

        try:

            await member.kick(
                reason="30분 이상 자기소개 미작성"
            )

            data["kicked"] = True
            data["kicked_at"] = iso(
                now()
            )

            save_json(
                FILES["members"],
                members
            )

            await interaction.response.edit_message(
                content=(
                    f"🚪 {member.mention} "
                    f"추방 완료"
                ),
                view=None
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ 봇에게 추방 권한이 없어요.",
                ephemeral=True
            )

        except discord.HTTPException as e:

            await interaction.response.send_message(
                f"❌ 추방 실패: {e}",
                ephemeral=True
            )

        except Exception as e:

            await interaction.response.send_message(
                f"❌ 추방 실패: {e}",
                ephemeral=True
            )

        finally:

            pending_kicks.discard(
                member.id
            )

    @discord.ui.button(
        label="취소",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        data = members.get(
            str(self.member_id)
        )

        if data:

            data[
                "kick_review_declined_until"
            ] = iso(
                now()
                + timedelta(
                    hours=24
                )
            )

            save_json(
                FILES["members"],
                members
            )

        pending_kicks.discard(
            self.member_id
        )

        await interaction.response.edit_message(
            content=(
                "❌ 추방을 취소했어요.\n"
                "24시간 동안 다시 요청하지 않아요."
            ),
            view=None
        )


async def send_kick_review(
    guild,
    member
):

    if member.id in pending_kicks:
        return

    channel = discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL
    )

    if not channel:
        return

    pending_kicks.add(
        member.id
    )

    embed = discord.Embed(
        title="🚨 자기소개 미작성",
        description=(
            f"👤 대상: {member.mention}\n"
            f"🆔 ID: `{member.id}`\n"
            f"⏰ 입장 후 30분 경과\n\n"
            "이 회원을 추방할까요?"
        ),
        color=discord.Color.red()
    )

    try:

        await channel.send(
            embed=embed,
            view=KickView(
                guild.id,
                member.id
            )
        )

    except Exception as e:

        pending_kicks.discard(
            member.id
        )

        print(
            f"[추방 확인 메시지 오류] {e}"
        )


# =========================================================
# 자기소개 미작성 확인
# =========================================================

@tasks.loop(
    minutes=1
)
async def intro_check():

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:
        return

    changed = False

    for uid, data in list(
        members.items()
    ):

        # 이미 완료했거나 추방된 회원
        if (
            data.get("intro_completed")
            or data.get("kicked")
            or data.get("is_existing_member")
        ):
            continue

        joined = parse_dt(
            data.get(
                "joined_at",
                ""
            )
        )

        if not joined:
            continue

        deadline = (
            joined
            + timedelta(
                minutes=INTRO_MINUTES
            )
        )

        if now() < deadline:
            continue

        try:

            member = guild.get_member(
                int(uid)
            )

        except (
            ValueError,
            TypeError
        ):

            continue

        if not member:
            continue

        if member.bot:
            continue

        if is_admin(member):
            continue

        declined = parse_dt(
            data.get(
                "kick_review_declined_until",
                ""
            )
        )

        # 추방 취소 후 24시간 대기
        if declined:

            if now() < declined:
                continue

            data.pop(
                "kick_review_declined_until",
                None
            )

            changed = True

        await send_kick_review(
            guild,
            member
        )

    if changed:

        save_json(
            FILES["members"],
            members
        )


# =========================================================
# 입장한 회원 처리
# =========================================================

@bot.event
async def on_member_join(
    member
):

    if member.guild.id != GUILD_ID:
        return

    if member.bot:
        return

    # 새로 들어온 회원은 30분 자기소개 확인 대상
    members[str(member.id)] = {
        "joined_at": iso(
            now()
        ),
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": iso(
            now()
        ),
        "is_existing_member": False,
        "kicked": False
    }

    save_json(
        FILES["members"],
        members
    )

    # 미인증 역할 부여
    await role(
        member,
        ROLES["unverified"],
        True
    )

    print(
        f"[입장] {member} "
        f"({member.id})"
    )


# =========================================================
# 메시지 이벤트
# =========================================================

@bot.event
async def on_message(
    message
):

    if message.author.bot:
        return

    if not message.guild:
        return

    if message.guild.id != GUILD_ID:
        return

    data = member_data(
        message.author
    )

    # 활동 시간 갱신
    data["last_activity"] = iso(
        now()
    )

    # 아직 자기소개를 하지 않은 경우
    if not data.get(
        "intro_completed"
    ):

        intro = parse_intro(
            message.content
        )

        if intro:

            year, gender = intro

            await intro_complete(
                message,
                year,
                gender
            )

    # 명령어 처리
    await bot.process_commands(
        message
    )


# =========================================================
# 봇 시작
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(
        f"🤖 로그인 완료: {bot.user}"
    )
    print(
        f"🆔 봇 ID: {bot.user.id}"
    )
    print(
        f"🏠 서버 ID: {GUILD_ID}"
    )
    print("=" * 50)

    # 데이터가 아직 로드되지 않았으면 로드
    if not members:
        load_data()

    # 야차방 권한 동기화
    guild = bot.get_guild(
        GUILD_ID
    )

    if guild:

        try:
            await update_yacha(
                guild
            )
        except Exception as e:
            print(
                f"[야차 동기화 오류] {e}"
            )

    # 자기소개 검사 시작
    if not intro_check.is_running():
        intro_check.start()


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

        return await ctx.send(
            "❌ 관리자 권한이 필요해요."
        )

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        return await ctx.send(
            "❌ 필요한 인자가 빠졌어요."
        )

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        return await ctx.send(
            "❌ 해당 회원을 찾지 못했어요."
        )

    print(
        f"[명령어 오류] {error}"
    )


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":

    load_data()

    if not TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN이 .env에 없습니다."
        )

    bot.run(
        TOKEN
    )
