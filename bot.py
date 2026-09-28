# =========================================================
# Discord Server Management Bot
# Profile + Matching Version
# =========================================================

import os
import json
import re
import random

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

    "unverified": 1553440335751938118,

    "male": 1553434350916206592,

    "female": 1553434497213538304,

    "adult": 1553440075830919238,

    "minor": 1553438682298589284

}


# =========================================================
# 데이터 파일
# =========================================================

FILES = {

    "members": "members.json",

    "warnings": "warnings.json",

    "chat": "chat.json",

    "profiles": "profiles.json",

    "matches": "matches.json"

}


# =========================================================
# 경고 설정
# =========================================================

WARNING_TIMEOUT = {

    3: 60 * 60,

    4: 24 * 60 * 60

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

chat_settings = {}

profiles = {}

matches = {}


pending_kicks = set()


# =========================================================
# JSON 관리
# =========================================================

def load_json(
    filename,
    default
):

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
            f"[JSON LOAD ERROR] {filename}: {e}"
        )

        return default


def save_json(
    filename,
    data
):

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

            f"[JSON SAVE ERROR] {filename}: {e}"

        )


def load_data():

    global members
    global warnings
    global chat_settings
    global profiles
    global matches


    members = load_json(

        FILES["members"],

        {}

    )


    warnings = load_json(

        FILES["warnings"],

        {}

    )


    chat_settings = load_json(

        FILES["chat"],

        {
            "enabled": True
        }

    )


    profiles = load_json(

        FILES["profiles"],

        {}

    )


    matches = load_json(

        FILES["matches"],

        {}


    )


    print("=" * 50)

    print(
        f"[DATA] members  : {len(members)}"
    )

    print(
        f"[DATA] warnings : {len(warnings)}"
    )

    print(
        f"[DATA] profiles : {len(profiles)}"
    )

    print(
        f"[DATA] matches  : {len(matches)}"
    )

    print("=" * 50)


# =========================================================
# 공통 함수
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

        "남": "남자",

        "여": "여자"

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
                    member.joined_at or now()
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

            f"[ROLE ERROR] 역할 없음: {role_id}"

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


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(text):

    text = text.strip()


    match = re.search(

        r"(?<!\d)"
        r"(19\d{2}|20\d{2}|\d{2})"
        r"\s*(?:년생|년)?"
        r"\s*"
        r"(남자|여자|남|여|ㄴ|ㅇ)"
        r"(?!\S)",

        text

    )


    if not match:

        return None


    raw_year, raw_gender = match.groups()

    current_year = datetime.now().year


    # 4자리

    if len(raw_year) == 4:

        year = int(raw_year)


    # 2자리
    # 무조건 2000년대로 처리

    else:

        year = 2000 + int(raw_year)


    if year < 1900:

        return None


    if year > current_year:

        return None


    if raw_gender in (

        "남자",

        "남",

        "ㄴ"

    ):

        gender = "남"

    else:

        gender = "여"


    return year, gender


# =========================================================
# 자기소개 역할 적용
# =========================================================

async def apply_intro_roles(

    member,

    year,

    gender

):

    for key in (

        "unverified",

        "male",

        "female",

        "adult",

        "minor"

    ):

        await manage_role(

            member,

            ROLES[key],

            False

        )


    if gender == "남":

        await manage_role(

            member,

            ROLES["male"],

            True

        )

    else:

        await manage_role(

            member,

            ROLES["female"],

            True

        )


    if age_type(year) == "성인":

        await manage_role(

            member,

            ROLES["adult"],

            True

        )

    else:

        await manage_role(

            member,

            ROLES["minor"],

            True

        )


# =========================================================
# 자기소개 완료
# =========================================================

async def intro_complete(

    message,

    year,

    gender

):

    member = message.author


    # =====================================================
    # 연령 제한
    # =====================================================

    if year >= MIN_ALLOWED_BIRTH_YEAR:

        try:

            log = get_log_channel(

                message.guild

            )


            if log:

                await log.send(

                    f"🚫 **연령 제한 추방**\n"
                    f"대상: {member.mention}\n"
                    f"출생년도: `{year}`\n"
                    f"사유: `2012년생부터 이용 제한`"

                )


            await member.kick(

                reason="연령 제한"

            )


            data = member_data(

                member

            )

            data["kicked"] = True


            save_json(

                FILES["members"],

                members

            )


            return


        except Exception as e:

            print(

                f"[AGE KICK ERROR] {e}"

            )

            return


    # =====================================================
    # 데이터 저장
    # =====================================================

    data = member_data(

        member

    )


    data.update({

        "intro_completed":
            True,

        "birth_year":
            year,

        "gender":
            gender,

        "intro_completed_at":
            iso(now()),

        "kicked":
            False

    })


    save_json(

        FILES["members"],

        members

    )


    pending_kicks.discard(

        member.id

    )


    await apply_intro_roles(

        member,

        year,

        gender

    )


    await message.channel.send(

        f"🖤 {member.mention} "
        f"자기소개 확인했어요 ♡\n\n"

        f"`{year}년생` · "
        f"`{gender_text(gender)}` · "
        f"`{age_type(year)}`\n\n"

        f"🎀 <#{ROLE_CHANNEL_ID}> "
        f"에서 역할을 골라주세요.\n"

        f"💬 <#{MAIN_CHAT_ID}> "
        f"에서 편하게 놀아요!\n\n"

        f"💗 프로필은 `/프로필 편집`으로 "
        f"설정할 수 있어요."

    )


# =========================================================
# 추방 확인 버튼
# =========================================================

class KickView(
    discord.ui.View
):

    def __init__(

        self,

        member

    ):

        super().__init__(

            timeout=300

        )

        self.member = member


    async def on_timeout(

        self

    ):

        pending_kicks.discard(

            self.member.id

        )


    @discord.ui.button(

        label="예, 추방하기",

        style=discord.ButtonStyle.danger

    )

    async def confirm(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        if not interaction.user.guild_permissions.administrator:

            await interaction.response.send_message(

                "❌ 관리자만 사용할 수 있습니다.",

                ephemeral=True

            )

            return


        member = interaction.guild.get_member(

            self.member.id

        )


        if not member:

            await interaction.response.edit_message(

                content=
                "❌ 회원을 찾을 수 없습니다.",

                view=None

            )

            return


        data = member_data(

            member

        )


        if data.get(

            "intro_completed",

            False

        ):

            pending_kicks.discard(

                member.id

            )


            await interaction.response.edit_message(

                content=
                f"✅ {member.mention}님은 "
                f"이미 자기소개를 완료했습니다.",

                view=None

            )

            return


        try:

            await member.kick(

                reason="자기소개 미작성"

            )


            data["kicked"] = True


            save_json(

                FILES["members"],

                members

            )


            pending_kicks.discard(

                member.id

            )


            await interaction.response.edit_message(

                content=
                f"🚪 {member.mention}님을 "
                f"자기소개 미작성으로 추방했습니다.",

                view=None

            )


        except Exception as e:

            print(

                f"[KICK ERROR] {e}"

            )


            await interaction.response.send_message(

                "❌ 추방 처리 실패",

                ephemeral=True

            )


    @discord.ui.button(

        label="취소",

        style=discord.ButtonStyle.secondary

    )

    async def cancel(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        if not interaction.user.guild_permissions.administrator:

            await interaction.response.send_message(

                "❌ 관리자만 사용할 수 있습니다.",

                ephemeral=True

            )

            return


        pending_kicks.discard(

            self.member.id

        )


        await interaction.response.edit_message(

            content=
            f"❎ {self.member.mention}님의 "
            f"추방 처리를 취소했습니다.",

            view=None

        )


# =========================================================
# 추방 확인 메시지
# =========================================================

async def send_kick_review(

    guild,

    member

):

    if member.id in pending_kicks:

        return


    data = member_data(

        member

    )


    if data.get(

        "intro_completed",

        False

    ):

        return


    log = get_log_channel(

        guild

    )


    if not log:

        return


    pending_kicks.add(

        member.id

    )


    try:

        await log.send(

            f"⚠️ **자기소개 미작성 확인**\n\n"

            f"회원: {member.mention}\n"
            f"입장 후 `{INTRO_MINUTES}분` 경과\n\n"

            f"추방 여부를 선택해주세요.",

            view=KickView(member)

        )


    except Exception as e:

        pending_kicks.discard(

            member.id

        )

        print(

            f"[KICK REVIEW ERROR] {e}"

        )


# =========================================================
# 자기소개 시간 체크
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


    current = now()


    for member in guild.members:

        if member.bot:

            continue


        data = member_data(

            member

        )


        if data.get(

            "intro_completed",

            False

        ):

            continue


        if data.get(

            "is_existing_member",

            True

        ):

            continue


        joined = parse_dt(

            data.get(

                "joined_at"

            )

        )


        if not joined:

            continue


        elapsed = (

            current - joined

        ).total_seconds()


        if elapsed < INTRO_MINUTES * 60:

            continue


        await send_kick_review(

            guild,

            member

        )


# =========================================================
# 멤버 입장
# =========================================================

@bot.event

async def on_member_join(

    member

):

    if member.guild.id != GUILD_ID:

        return


    if member.bot:

        return


    members[str(member.id)] = {

        "joined_at":

            iso(now()),

        "intro_completed":

            False,

        "birth_year":

            None,

        "gender":

            None,

        "last_activity":

            iso(now()),

        "is_existing_member":

            False,

        "kicked":

            False

    }


    save_json(

        FILES["members"],

        members

    )


    await manage_role(

        member,

        ROLES["unverified"],

        True

    )


    print(

        f"[JOIN] {member}"

    )


# =========================================================
# 제한 채널
# =========================================================

async def restricted_access(

    member,

    allow=False

):

    channels = []


    adult_channel = discord.utils.get(

        member.guild.text_channels,

        name="＃↝・19금"

    )


    if adult_channel:

        channels.append(

            adult_channel

        )


    body_channel = member.guild.get_channel(

        BODY_SHARE_ID

    )


    if isinstance(

        body_channel,

        discord.TextChannel

    ):

        channels.append(

            body_channel

        )


    for channel in channels:

        try:

            if allow:

                await channel.set_permissions(

                    member,

                    overwrite=None,

                    reason="경고 해제"

                )

            else:

                overwrite = channel.overwrites_for(

                    member

                )


                overwrite.view_channel = False

                overwrite.send_messages = False

                overwrite.read_message_history = False


                await channel.set_permissions(

                    member,

                    overwrite=overwrite,

                    reason="경고 제한"

                )


        except Exception as e:

            print(

                f"[제한 채널 오류] {e}"

            )


# =========================================================
# 경고 적용
# =========================================================

async def apply_warning(

    member,

    reason="사유 없음"

):

    member_id = str(

        member.id

    )


    count = warning_count(

        member

    ) + 1


    warnings[member_id] = {

        "count":
            count,

        "last_reason":
            reason,

        "updated_at":
            iso(now())

    }


    save_json(

        FILES["warnings"],

        warnings

    )


    await restricted_access(

        member,

        False

    )


    timeout = WARNING_TIMEOUT.get(

        count

    )


    if timeout:

        try:

            await member.timeout(

                now() + timedelta(

                    seconds=timeout

                ),

                reason=f"경고 {count}회"

            )

        except Exception as e:

            print(

                f"[TIMEOUT ERROR] {e}"

            )


    if count >= 5:

        try:

            await member.kick(

                reason=f"경고 {count}회 누적"

            )

        except Exception as e:

            print(

                f"[KICK ERROR] {e}"

            )


    return count


# =========================================================
# 경고 로그
# =========================================================

async def send_warning_log(

    guild,

    member,

    count,

    reason

):

    log = get_log_channel(

        guild

    )


    if not log:

        return


    if count >= 5:

        action = "🚪 추방"

    elif count == 4:

        action = "⏰ 24시간 타임아웃"

    elif count == 3:

        action = "⏰ 1시간 타임아웃"

    else:

        action = "🔒 제한 채널 차단"


    await log.send(

        f"⚠️ **경고 처리**\n\n"

        f"대상: {member.mention}\n"
        f"경고: `{count}회`\n"
        f"사유: `{reason}`\n"
        f"조치: {action}"

    )


# =========================================================
# !경고
# =========================================================

@bot.command(

    name="경고"

)

async def warning_command(

    ctx,

    member: discord.Member = None,

    *,

    reason="사유 없음"

):

    if not is_admin(

        ctx.author

    ):

        await ctx.send(

            "❌ 관리자만 사용할 수 있습니다."

        )

        return


    if member is None:

        await ctx.send(

            "❌ 회원을 멘션해주세요."

        )

        return


    if member.bot:

        await ctx.send(

            "❌ 봇에게 경고 불가"

        )

        return


    count = await apply_warning(

        member,

        reason

    )


    await send_warning_log(

        ctx.guild,

        member,

        count,

        reason

    )


    if count >= 5:

        text = (

            f"🚪 {member.mention}님 "
            f"경고 {count}회 누적으로 추방"

        )

    elif count == 4:

        text = (

            f"⚠️ {member.mention}님\n"
            f"경고 {count}회\n"
            f"24시간 타임아웃"

        )

    elif count == 3:

        text = (

            f"⚠️ {member.mention}님\n"
            f"경고 {count}회\n"
            f"1시간 타임아웃"

        )

    else:

        text = (

            f"⚠️ {member.mention}님\n"
            f"경고 {count}회 누적\n"
            f"제한 채널 차단"

        )


    await ctx.send(

        text

    )


# =========================================================
# !경고목록
# =========================================================

@bot.command(

    name="경고목록"

)

async def warning_list(

    ctx,

    member: discord.Member = None

):

    if not is_admin(

        ctx.author

    ):

        await ctx.send(

            "❌ 관리자만 사용 가능"

        )

        return


    if member:

        data = warnings.get(

            str(member.id),

            {}

        )


        await ctx.send(

            f"⚠️ {member.mention}\n"
            f"경고: `{data.get('count', 0)}회`\n"
            f"사유: `{data.get('last_reason', '없음')}`"

        )

        return


    if not warnings:

        await ctx.send(

            "📋 경고 기록 없음"

        )

        return


    result = []


    for uid, data in warnings.items():

        m = ctx.guild.get_member(

            int(uid)

        )


        name = (

            m.mention

            if m

            else uid

        )


        result.append(

            f"• {name} : "
            f"`{data.get('count', 0)}회`"

        )


    await ctx.send(

        "⚠️ **전체 경고 목록**\n\n"
        +
        "\n".join(result)

    )


# =========================================================
# !경고취소
# =========================================================

@bot.command(

    name="경고취소"

)

async def warning_remove(

    ctx,

    member: discord.Member = None

):

    if not is_admin(

        ctx.author

    ):

        return


    if member is None:

        return


    uid = str(

        member.id

    )


    count = warning_count(

        member

    )


    if count <= 0:

        await ctx.send(

            "❌ 경고 없음"

        )

        return


    count -= 1


    if count <= 0:

        warnings.pop(

            uid,

            None

        )


        await restricted_access(

            member,

            True

        )


        try:

            await member.timeout(

                None,

                reason="경고 취소"

            )

        except Exception:

            pass

    else:

        warnings[uid] = {

            "count":
                count,

            "last_reason":
                warnings[uid].get(

                    "last_reason",

                    "없음"

                ),

            "updated_at":
                iso(now())

        }


    save_json(

        FILES["warnings"],

        warnings

    )


    await ctx.send(

        f"✅ {member.mention} "
        f"경고 취소\n"
        f"현재 `{count}회`"

    )


# =========================================================
# !경고초기화
# =========================================================

@bot.command(

    name="경고초기화"

)

async def warning_reset(

    ctx,

    member: discord.Member = None

):

    if not is_admin(

        ctx.author

    ):

        return


    if member is None:

        return


    warnings.pop(

        str(member.id),

        None

    )


    save_json(

        FILES["warnings"],

        warnings

    )


    await restricted_access(

        member,

        True

    )


    try:

        await member.timeout(

            None,

            reason="경고 초기화"

        )

    except Exception:

        pass


    await ctx.send(

        f"✅ {member.mention} "
        f"경고 초기화 완료"

    )


# =========================================================
# 프로필 기본값
# =========================================================

def get_profile(user_id):

    user_id = str(user_id)


    if user_id not in profiles:

        profiles[user_id] = {

            "birth_year": None,

            "gender": None,

            "location": None,

            "ideal_type": None,

            "likes": None,

            "updated_at": None

        }


    return profiles[user_id]


# =========================================================
# 프로필 완료 여부
# =========================================================

def profile_complete(user_id):

    profile = profiles.get(

        str(user_id)

    )


    if not profile:

        return False


    required = [

        "birth_year",

        "gender",

        "location",

        "ideal_type",

        "likes"

    ]


    return all(

        profile.get(field)

        for field in required

    )


# =========================================================
# 프로필 Embed
# =========================================================

def profile_embed(

    member,

    profile=None

):

    if profile is None:

        profile = profiles.get(

            str(member.id),

            {}

        )


    birth_year = profile.get(

        "birth_year"

    )


    if birth_year:

        try:

            age_text = f"{datetime.now().year - int(birth_year) + 1}세"

        except Exception:

            age_text = "미입력"

    else:

        age_text = "미입력"


    gender = gender_text(

        profile.get(

            "gender"

        )

    )


    embed = discord.Embed(

        title="💗 프로필",

        description=
        f"**{member.display_name}**님의 프로필",

        color=discord.Color.from_rgb(

            255,

            120,

            170

        )

    )


    embed.add_field(

        name="🎂 나이",

        value=age_text,

        inline=True

    )


    embed.add_field(

        name="⚧ 성별",

        value=gender,

        inline=True

    )


    embed.add_field(

        name="📍 사는 곳",

        value=profile.get(

            "location",

            "미입력"

        ),

        inline=False

    )


    embed.add_field(

        name="💘 이상형",

        value=profile.get(

            "ideal_type",

            "미입력"

        ),

        inline=False

    )


    embed.add_field(

        name="🎀 좋아하는 것",

        value=profile.get(

            "likes",

            "미입력"

        ),

        inline=False

    )


    embed.set_thumbnail(

        url=member.display_avatar.url

    )


    return embed


# =========================================================
# 프로필 편집 Modal
# =========================================================

class ProfileModal(

    discord.ui.Modal,

    title="💗 프로필 편집"

):

    birth_year = discord.ui.TextInput(

        label="출생년도",

        placeholder="예: 2004 또는 04",

        required=True,

        max_length=4

    )


    location = discord.ui.TextInput(

        label="사는 곳",

        placeholder="예: 서울",

        required=True,

        max_length=50

    )


    gender = discord.ui.TextInput(

        label="성별",

        placeholder="남 / 여",

        required=True,

        max_length=10

    )


    ideal_type = discord.ui.TextInput(

        label="이상형",

        placeholder="어떤 사람을 좋아하나요?",

        required=True,

        max_length=200,

        style=discord.TextStyle.paragraph

    )


    likes = discord.ui.TextInput(

        label="좋아하는 것",

        placeholder="예: 게임, 음악, 카페",

        required=True,

        max_length=200,

        style=discord.TextStyle.paragraph

    )


    async def on_submit(

        self,

        interaction: discord.Interaction

    ):

        member = interaction.user


        # ---------------------------------------------
        # 출생년도 처리
        # ---------------------------------------------

        raw_year = self.birth_year.value.strip()


        if not raw_year.isdigit():

            await interaction.response.send_message(

                "❌ 출생년도는 숫자로 입력해주세요.",

                ephemeral=True

            )

            return


        if len(raw_year) == 2:

            year = 2000 + int(raw_year)

        elif len(raw_year) == 4:

            year = int(raw_year)

        else:

            await interaction.response.send_message(

                "❌ 출생년도는 `04` 또는 `2004`처럼 입력해주세요.",

                ephemeral=True

            )

            return


        current_year = datetime.now().year


        if year < 1900 or year > current_year:

            await interaction.response.send_message(

                "❌ 올바른 출생년도를 입력해주세요.",

                ephemeral=True

            )

            return


        # ---------------------------------------------
        # 서버 자기소개 정보와 비교
        # ---------------------------------------------

        member_info = member_data(member)

        intro_year = member_info.get(

            "birth_year"

        )


        if intro_year and int(intro_year) != year:

            await interaction.response.send_message(

                f"❌ 자기소개에서 등록한 출생년도 "
                f"`{intro_year}`와 다릅니다.",

                ephemeral=True

            )

            return


        # ---------------------------------------------
        # 성별
        # ---------------------------------------------

        gender_raw = self.gender.value.strip().lower()


        if gender_raw in (

            "남",

            "남자",

            "ㄴ",

            "m",

            "male"

        ):

            gender = "남"

        elif gender_raw in (

            "여",

            "여자",

            "ㅇ",

            "f",

            "female"

        ):

            gender = "여"

        else:

            await interaction.response.send_message(

                "❌ 성별은 `남` 또는 `여`로 입력해주세요.",

                ephemeral=True

            )

            return


        # ---------------------------------------------
        # 자기소개 성별과 비교
        # ---------------------------------------------

        intro_gender = member_info.get(

            "gender"

        )


        if intro_gender and intro_gender != gender:

            await interaction.response.send_message(

                f"❌ 자기소개에서 등록한 성별 "
                f"`{gender_text(intro_gender)}`와 다릅니다.",

                ephemeral=True

            )

            return


        # ---------------------------------------------
        # 연령 제한
        # ---------------------------------------------

        if year >= MIN_ALLOWED_BIRTH_YEAR:

            await interaction.response.send_message(

                "❌ 현재 서버 이용 연령 제한에 해당합니다.",

                ephemeral=True

            )

            return


        # ---------------------------------------------
        # 프로필 저장
        # ---------------------------------------------

        profiles[str(member.id)] = {

            "birth_year":
                year,

            "gender":
                gender,

            "location":
                self.location.value.strip(),

            "ideal_type":
                self.ideal_type.value.strip(),

            "likes":
                self.likes.value.strip(),

            "updated_at":
                iso(now())

        }


        save_json(

            FILES["profiles"],

            profiles

        )


        await interaction.response.send_message(

            "💗 프로필 저장 완료!\n"
            "`/프로필` 명령어로 확인할 수 있어요.",

            ephemeral=True

        )


# =========================================================
# 프로필 편집 버튼
# =========================================================

class ProfileEditView(

    discord.ui.View

):

    def __init__(self):

        super().__init__(

            timeout=180

        )


    @discord.ui.button(

        label="프로필 작성 / 수정",

        emoji="💗",

        style=discord.ButtonStyle.primary

    )

    async def edit(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        await interaction.response.send_modal(

            ProfileModal()

        )


# =========================================================
# /프로필 편집
# =========================================================

@bot.tree.command(

    name="프로필_편집",

    description="내 프로필을 작성하거나 수정합니다."

)

async def profile_edit(

    interaction: discord.Interaction

):

    embed = discord.Embed(

        title="💗 프로필 편집",

        description=(

            "아래 버튼을 눌러 프로필을 작성해주세요.\n\n"

            "🎂 출생년도\n"
            "📍 사는 곳\n"
            "⚧ 성별\n"
            "💘 이상형\n"
            "🎀 좋아하는 것"

        ),

        color=discord.Color.from_rgb(

            255,

            120,

            170

        )

    )


    await interaction.response.send_message(

        embed=embed,

        view=ProfileEditView(),

        ephemeral=True

    )


# =========================================================
# /프로필
# =========================================================

@bot.tree.command(

    name="프로필",

    description="프로필을 확인합니다."

)

async def profile_command(

    interaction: discord.Interaction,

    member: discord.Member = None

):

    target = member or interaction.user


    profile = profiles.get(

        str(target.id)

    )


    if not profile:

        await interaction.response.send_message(

            "❌ 아직 작성된 프로필이 없습니다.",

            ephemeral=True

        )

        return


    embed = profile_embed(

        target,

        profile

    )


    await interaction.response.send_message(

        embed=embed

    )


# =========================================================
# 매칭 데이터 함수
# =========================================================

def get_match_data(user_id):

    uid = str(user_id)


    if uid not in matches:

        matches[uid] = {

            "yes": [],

            "no": [],

            "matched": []

        }


    return matches[uid]


def already_decided(

    user_id,

    target_id

):

    data = get_match_data(

        user_id

    )


    target_id = str(target_id)


    return (

        target_id in data["yes"]

        or

        target_id in data["no"]

    )


def already_matched(

    user_id,

    target_id

):

    data = get_match_data(

        user_id

    )


    return str(target_id) in data["matched"]


def add_unique(

    array,

    value

):

    value = str(value)


    if value not in array:

        array.append(value)


# =========================================================
# 매칭 가능한지 확인
# =========================================================

def can_match(

    member_a,

    member_b

):

    if member_a.id == member_b.id:

        return False


    data_a = member_data(

        member_a

    )

    data_b = member_data(

        member_b

    )


    # 자기소개 완료 필요

    if not data_a.get(

        "intro_completed",

        False

    ):

        return False


    if not data_b.get(

        "intro_completed",

        False

    ):

        return False


    # 프로필 작성 필요

    if not profile_complete(

        member_a.id

    ):

        return False


    if not profile_complete(

        member_b.id

    ):

        return False


    year_a = data_a.get(

        "birth_year"

    )

    year_b = data_b.get(

        "birth_year"

    )


    if not year_a or not year_b:

        return False


    # 성인 / 미성년자 간 매칭 방지

    if age_type(

        int(year_a)

    ) != age_type(

        int(year_b)

    ):

        return False


    return True


# =========================================================
# 매칭 후보 찾기
# =========================================================

def find_candidate(

    guild,

    user

):

    candidates = []


    user_data = get_match_data(

        user.id

    )


    for member in guild.members:

        if member.bot:

            continue


        if member.id == user.id:

            continue


        if not can_match(

            user,

            member

        ):

            continue


        if already_decided(

            user.id,

            member.id

        ):

            continue


        if already_matched(

            user.id,

            member.id

        ):

            continue


        candidates.append(

            member

        )


    if not candidates:

        return None


    return random.choice(

        candidates

    )


# =========================================================
# 매칭 Embed
# =========================================================

def matching_embed(

    member

):

    profile = profiles.get(

        str(member.id),

        {}

    )


    embed = profile_embed(

        member,

        profile

    )


    embed.title = "💗 새로운 프로필"

    embed.set_footer(

        text="이 프로필을 보고 선택해주세요."

    )


    return embed


# =========================================================
# YES / NO 버튼
# =========================================================

class MatchingView(

    discord.ui.View

):

    def __init__(

        self,

        owner_id,

        target_id

    ):

        super().__init__(

            timeout=300

        )

        self.owner_id = owner_id

        self.target_id = target_id


    async def interaction_check(

        self,

        interaction: discord.Interaction

    ):

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(

                "❌ 이 매칭 카드는 본인만 사용할 수 있어요.",

                ephemeral=True

            )

            return False


        return True


    async def on_timeout(

        self

    ):

        for item in self.children:

            item.disabled = True


    @discord.ui.button(

        label="YES",

        emoji="💗",

        style=discord.ButtonStyle.success

    )

    async def yes_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        user = interaction.user


        target = interaction.guild.get_member(

            self.target_id

        )


        if not target:

            await interaction.response.edit_message(

                content="❌ 상대방을 찾을 수 없습니다.",

                embed=None,

                view=None

            )

            return


        data = get_match_data(

            user.id

        )


        target_id = str(

            target.id

        )


        if target_id in data["no"]:

            data["no"].remove(

                target_id

            )


        add_unique(

            data["yes"],

            target_id

        )


        # 상대가 나에게 YES를 했는지 확인

        target_data = get_match_data(

            target.id

        )


        mutual = str(

            user.id

        ) in target_data["yes"]


        if mutual:

            add_unique(

                data["matched"],

                target_id

            )

            add_unique(

                target_data["matched"],

                str(user.id)

            )


            save_json(

                FILES["matches"],

                matches


            )

            await interaction.response.edit_message(

                content=(

                    "💗 **매칭됐어요!**\n\n"

                    f"{target.mention}님과 서로 YES를 눌렀어요.\n"

                    "서로의 프로필을 확인하고 대화를 시작해보세요!"

                ),

                embed=None,

                view=None

            )


            try:

                await target.send(

                    f"💗 **매칭됐어요!**\n\n"
                    f"{user.display_name}님과 "
                    f"서로 YES를 눌렀어요!\n\n"
                    f"상대 프로필:\n"
                    f"{target.guild.name}"

                )

            except Exception:

                pass


        else:

            save_json(

                FILES["matches"],

                matches


            )

            await interaction.response.edit_message(

                content=(

                    "💗 YES를 선택했어요.\n\n"
                    "상대방도 YES를 선택하면 매칭됩니다."

                ),

                embed=None,

                view=None

            )


    @discord.ui.button(

        label="NO",

        emoji="❌",

        style=discord.ButtonStyle.secondary

    )

    async def no_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        user = interaction.user


        target_id = str(

            self.target_id

        )


        data = get_match_data(

            user.id

        )


        if target_id in data["yes"]:

            data["yes"].remove(

                target_id

            )


        add_unique(

            data["no"],

            target_id


        )


        save_json(

            FILES["matches"],

            matches


        )


        await interaction.response.edit_message(

            content=(

                "❌ NO를 선택했어요.\n\n"

                "다음 프로필을 보려면 `/매칭`을 사용해주세요."

            ),

            embed=None,

            view=None

        )


# =========================================================
# /매칭
# =========================================================

@bot.tree.command(

    name="매칭",

    description="새로운 프로필을 확인합니다."

)

async def matching_command(

    interaction: discord.Interaction

):

    user = interaction.user


    # ---------------------------------------------
    # 자기소개 확인
    # ---------------------------------------------

    data = member_data(

        user

    )


    if not data.get(

        "intro_completed",

        False

    ):

        await interaction.response.send_message(

            "❌ 먼저 서버 자기소개를 완료해주세요.",

            ephemeral=True

        )

        return


    # ---------------------------------------------
    # 프로필 확인
    # ---------------------------------------------

    if not profile_complete(

        user.id

    ):

        await interaction.response.send_message(

            "❌ 먼저 `/프로필_편집`에서 "
            "프로필을 작성해주세요.",

            ephemeral=True

        )

        return


    # ---------------------------------------------
    # 후보 찾기
    # ---------------------------------------------

    target = find_candidate(

        interaction.guild,

        user

    )


    if not target:

        await interaction.response.send_message(

            "💭 지금 보여드릴 수 있는 "
            "새로운 프로필이 없어요.",

            ephemeral=True

        )

        return


    # ---------------------------------------------
    # 프로필 표시
    # ---------------------------------------------

    embed = matching_embed(

        target

    )


    view = MatchingView(

        user.id,

        target.id

    )


    await interaction.response.send_message(

        embed=embed,

        view=view

    )


# =========================================================
# /매칭목록
# =========================================================

@bot.tree.command(

    name="매칭목록",

    description="내가 매칭된 사람을 확인합니다."

)

async def match_list(

    interaction: discord.Interaction

):

    data = get_match_data(

        interaction.user.id

    )


    matched = data.get(

        "matched",

        []

    )


    if not matched:

        await interaction.response.send_message(

            "💭 아직 매칭된 사람이 없어요.",

            ephemeral=True

        )

        return


    result = []


    for uid in matched:

        member = interaction.guild.get_member(

            int(uid)

        )


        if member:

            result.append(

                f"💗 {member.mention}"

            )


    if not result:

        await interaction.response.send_message(

            "💭 아직 매칭된 사람이 없어요.",

            ephemeral=True

        )

        return


    await interaction.response.send_message(

        "💗 **내 매칭 목록**\n\n"
        +
        "\n".join(result),

        ephemeral=True

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


    data["last_activity"] = iso(

        now()

    )


    # =====================================================
    # 자기소개 감지
    # =====================================================

    if (

        message.channel.id == INTRO_CHANNEL_ID

        and not data.get(

            "intro_completed",

            False

        )

    ):

        result = parse_intro(

            message.content

        )


        if result:

            year, gender = result


            await intro_complete(

                message,

                year,

                gender

            )


    save_json(

        FILES["members"],

        members

    )


    await bot.process_commands(

        message

    )


# =========================================================
# 봇 준비 완료
# =========================================================

@bot.event

async def on_ready():

    print("=" * 50)

    print(

        f"로그인 완료 : {bot.user}"

    )

    print(

        f"서버 수 : {len(bot.guilds)}"

    )

    print("=" * 50)


    load_data()


    guild = bot.get_guild(

        GUILD_ID

    )


    if not guild:

        print(

            "❌ 서버를 찾을 수 없음"

        )

        return


    print(

        f"[SERVER] {guild.name}"

    )


    # =====================================================
    # 슬래시 명령어 동기화
    # =====================================================

    try:

        synced = await bot.tree.sync(

            guild=discord.Object(

                id=GUILD_ID

            )

        )


        print(

            f"[SLASH] "
            f"{len(synced)}개 명령어 동기화 완료"

        )

    except Exception as e:

        print(

            f"[SLASH ERROR] {e}"

        )


    # =====================================================
    # 자기소개 체크
    # =====================================================

    if not intro_check.is_running():

        intro_check.start()

        print(

            "[CHECK] 자기소개 감시 시작"

        )


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

        commands.MemberNotFound

    ):

        await ctx.send(

            "❌ 회원을 찾을 수 없습니다."

        )

        return


    if isinstance(

        error,

        commands.MissingRequiredArgument

    ):

        await ctx.send(

            "❌ 필요한 값이 없습니다."

        )

        return


    print(

        f"[ERROR] "
        f"{type(error).__name__}: {error}"

    )


# =========================================================
# 데이터 최초 로드
# =========================================================

load_data()


# =========================================================
# 토큰 확인
# =========================================================

if not TOKEN:

    raise RuntimeError(

        "DISCORD_TOKEN이 없습니다."

    )


# =========================================================
# 실행
# =========================================================

print(

    "[BOT] Discord 연결 중..."

)


bot.run(

    TOKEN

)
