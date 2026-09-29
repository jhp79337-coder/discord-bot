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


# =========================================================
# 자기소개 파싱
#
# 1900~1999
# -> 1900 남
# -> 1999 여
#
# 2000년대
# -> 00 남
# -> 04 ㅇ
# -> 04 ㄴ
# -> 04 여
#
# 2012년생부터 추방
# =========================================================

def parse_intro(text):

    text = text.strip()

    # -----------------------------------------------------
    # 4자리 연도
    # -----------------------------------------------------

    match = re.search(

        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"\s*"
        r"(남|여|ㄴ|ㅇ)"
        r"(?!\S)",

        text

    )

    if match:

        raw_year = match.group(1)

        gender = match.group(2)

        year = int(
            raw_year
        )

    else:

        # -------------------------------------------------
        # 2자리 연도
        # 2000년대만 허용
        # -------------------------------------------------

        match = re.search(

            r"(?<!\d)"
            r"(\d{2})"
            r"\s*"
            r"(남|여|ㄴ|ㅇ)"
            r"(?!\S)",

            text

        )

        if not match:

            return None

        raw_year = match.group(1)

        gender = match.group(2)

        short_year = int(
            raw_year
        )

        current_year = datetime.now().year

        current_short = current_year % 100

        # 미래 연도 방지
        if short_year > current_short:

            return None

        year = 2000 + short_year


    # -----------------------------------------------------
    # 연도 검증
    # -----------------------------------------------------

    current_year = datetime.now().year

    if year < 1900:

        return None

    if year > current_year:

        return None


    # -----------------------------------------------------
    # 성별
    # -----------------------------------------------------

    if gender in (
        "남",
        "ㄴ"
    ):

        gender = "남"

    else:

        gender = "여"


    return (
        year,
        gender
    )


# =========================================================
# 자기소개 역할 적용
# =========================================================

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

        await manage_role(

            member,

            ROLES[key],

            False

        )


    # 성별

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


    # 나이

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


    # -----------------------------------------------------
    # 연령 제한
    # -----------------------------------------------------

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

                reason=
                "연령 제한"

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


    # -----------------------------------------------------
    # 회원 데이터
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # 역할
    # -----------------------------------------------------

    await apply_intro_roles(

        member,

        year,

        gender

    )


    # -----------------------------------------------------
    # 안내
    # -----------------------------------------------------

    await message.channel.send(

        f"🖤 {member.mention} "
        f"자기소개 확인했어요 ♡\n\n"

        f"`{year}년생` · "
        f"`{gender_text(gender)}` · "
        f"`{age_type(year)}`\n\n"

        f"🎀 <#{ROLE_CHANNEL_ID}> "
        f"에서 역할을 골라주세요.\n"

        f"💬 <#{MAIN_CHAT_ID}> "
        f"에서 편하게 놀아요!"

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

        style=
        discord.ButtonStyle.danger

    )
    async def confirm(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

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

                reason=
                "자기소개 미작성"

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

        style=
        discord.ButtonStyle.secondary

    )
    async def cancel(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

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
# 추방 확인
# =========================================================

async def send_kick_review(
    guild,
    member
):

    # 자기소개 제외 회원

    if member.id in intro_exceptions:

        return


    # 이미 대기 중

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

            f"입장 후 "
            f"`{INTRO_MINUTES}분` 경과\n\n"

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


        # 제외 회원

        if member.id in intro_exceptions:

            continue


        data = member_data(
            member
        )


        if data.get(
            "intro_completed",
            False
        ):

            continue


        # 기존 회원 제외

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
# 프로필
# =========================================================

def get_profile(
    user_id
):

    uid = str(
        user_id
    )


    if uid not in profiles:

        profiles[uid] = {

            "age":
                None,

            "location":
                None,

            "gender":
                None,

            "ideal_type":
                None,

            "likes":
                None

        }


    return profiles[uid]


# =========================================================
# 프로필 편집 Modal
# =========================================================

class ProfileModal(
    discord.ui.Modal,
    title="프로필 편집"
):

    age = discord.ui.TextInput(

        label="나이",

        placeholder="예: 04",

        required=False,

        max_length=10

    )


    location = discord.ui.TextInput(

        label="사는 곳",

        placeholder="예: 서울",

        required=False,

        max_length=50

    )


    gender = discord.ui.TextInput(

        label="성별",

        placeholder="예: 남 / 여",

        required=False,

        max_length=10

    )


    ideal_type = discord.ui.TextInput(

        label="이상형",

        placeholder="예: 웃는 게 예쁜 사람",

        required=False,

        max_length=200

    )


    likes = discord.ui.TextInput(

        label="좋아하는 것",

        placeholder="예: 게임, 음악, 영화",

        required=False,

        max_length=200

    )


    async def on_submit(
        self,
        interaction:
        discord.Interaction
    ):

        uid = str(
            interaction.user.id
        )


        profiles[uid] = {

            "age":
                self.age.value.strip()
                or None,

            "location":
                self.location.value.strip()
                or None,

            "gender":
                self.gender.value.strip()
                or None,

            "ideal_type":
                self.ideal_type.value.strip()
                or None,

            "likes":
                self.likes.value.strip()
                or None

        }


        save_json(

            FILES["profiles"],

            profiles

        )


        await interaction.response.send_message(

            "✅ 프로필을 저장했어요!\n"
            "이제 `!프로필`로 확인할 수 있어요.",

            ephemeral=True

        )


# =========================================================
# !프로필
# =========================================================

class ProfileCardView(discord.ui.View):

    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    @discord.ui.button(
        label="프로필 편집",
        emoji="✏️",
        style=discord.ButtonStyle.primary
    )
    async def edit_profile(self, interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ 본인 프로필만 수정할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(ProfileModal())

    @discord.ui.button(
        label="소개팅",
        emoji="💗",
        style=discord.ButtonStyle.success
    )
    async def dating(self, interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ 본인 프로필에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "`!소개팅` 명령어로 소개팅에 참가할 수 있어요.",
            ephemeral=True
        )


@bot.command(
    name="프로필"
)
async def profile_command(
    ctx
):

    profile = get_profile(
        ctx.author.id
    )

    member_info = members.get(
        str(ctx.author.id),
        {}
    )

    birth_year = profile.get("age") or member_info.get("birth_year")
    gender = profile.get("gender") or gender_text(member_info.get("gender"))
    location = profile.get("location") or "미설정"
    ideal_type = profile.get("ideal_type") or "미설정"
    likes = profile.get("likes") or "미설정"

    embed = discord.Embed(
        title=f"💗 {ctx.author.display_name}님의 프로필",
        description=(
            f"**{birth_year or '나이 미설정'}** · **{gender}**\n"
            f"📍 {location}"
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )

    embed.set_thumbnail(
        url=ctx.author.display_avatar.url
    )

    embed.add_field(
        name="♡ 이상형",
        value=ideal_type,
        inline=False
    )

    embed.add_field(
        name="🎮 좋아하는 것",
        value=likes,
        inline=False
    )

    embed.add_field(
        name="💬 소개팅",
        value="아래 버튼으로 프로필을 수정하거나 소개팅에 참가할 수 있어요.",
        inline=False
    )

    embed.set_footer(
        text="!프로필편집 으로도 수정할 수 있어요."
    )

    await ctx.send(
        embed=embed,
        view=ProfileCardView(ctx.author.id)
    )


# =========================================================
# !프로필편집
# =========================================================

@bot.command(
    name="프로필편집"
)
async def profile_edit_command(
    ctx
):

    await ctx.author.send(
        "프로필 편집창을 열어드릴게요."
    )

    try:

        await ctx.send(
            f"{ctx.author.mention} 📩 DM을 확인해주세요!",
            delete_after=5
        )

    except Exception:

        pass


    # -----------------------------------------------------
    # 주의:
    # prefix 명령어 자체는 interaction이 아니므로
    # Discord Modal을 직접 열 수 없습니다.
    #
    # 따라서 아래 버튼을 사용합니다.
    # -----------------------------------------------------

    view = ProfileEditView()


    try:

        await ctx.send(

            f"{ctx.author.mention}\n"
            f"아래 버튼을 눌러 프로필을 편집해주세요.",

            view=view

        )

    except Exception as e:

        print(
            f"[PROFILE VIEW ERROR] {e}"
        )


# =========================================================
# 프로필 편집 버튼
# =========================================================

class ProfileEditView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    @discord.ui.button(

        label="프로필 편집",

        emoji="✏️",

        style=
        discord.ButtonStyle.primary

    )
    async def edit(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

    ):

        await interaction.response.send_modal(
            ProfileModal()
        )


# =========================================================
# !프로필삭제
# =========================================================

@bot.command(
    name="프로필삭제"
)
async def profile_delete_command(
    ctx
):

    uid = str(
        ctx.author.id
    )


    if uid not in profiles:

        await ctx.send(
            "❌ 저장된 프로필이 없습니다."
        )

        return


    profiles.pop(
        uid,
        None
    )


    save_json(

        FILES["profiles"],

        profiles

    )


    await ctx.send(

        f"🗑️ {ctx.author.mention}님의 "
        f"프로필을 삭제했습니다."

    )


# =========================================================
# !자기소개제외
# =========================================================

@bot.command(
    name="자기소개제외"
)
async def intro_exception_add(
    ctx,
    member: discord.Member = None
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

            "❌ 사용법: "
            "`!자기소개제외 @회원`"

        )

        return


    intro_exceptions.add(
        member.id
    )


    save_json(

        FILES["exceptions"],

        list(intro_exceptions)

    )


    pending_kicks.discard(
        member.id
    )


    await ctx.send(

        f"✅ {member.mention}님을 "
        f"자기소개 검사에서 제외했습니다."

    )


# =========================================================
# !자기소개제외취소
# =========================================================

@bot.command(
    name="자기소개제외취소"
)
async def intro_exception_remove(
    ctx,
    member: discord.Member = None
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

            "❌ 사용법: "
            "`!자기소개제외 @회원`"

        )

        return


    intro_exceptions.discard(
        member.id
    )


    save_json(

        FILES["exceptions"],

        list(intro_exceptions)

    )


    await ctx.send(

        f"✅ {member.mention}님의 "
        f"자기소개 제외를 해제했습니다."

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

                    reason=
                    "경고 해제"

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

                    reason=
                    "경고 제한"

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

                now()
                +
                timedelta(
                    seconds=timeout
                ),

                reason=
                f"경고 {count}회"

            )

        except Exception as e:

            print(
                f"[TIMEOUT ERROR] {e}"
            )


    if count >= 5:

        try:

            await member.kick(

                reason=
                f"경고 {count}회 누적"

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

    member:
    discord.Member = None,

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

    member:
    discord.Member = None

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

            f"경고: "
            f"`{data.get('count', 0)}회`\n"

            f"사유: "
            f"`{data.get('last_reason', '없음')}`"

        )

        return


    if not warnings:

        await ctx.send(
            "📋 경고 기록 없음"
        )

        return


    result = []


    for uid, data in warnings.items():

        try:

            m = ctx.guild.get_member(
                int(uid)
            )

        except Exception:

            m = None


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

    member:
    discord.Member = None

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

                reason=
                "경고 취소"

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

    member:
    discord.Member = None

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

            reason=
            "경고 초기화"

        )

    except Exception:

        pass


    await ctx.send(

        f"✅ {member.mention} "
        f"경고 초기화 완료"

    )


# =========================================================
# 소개팅 콘텐츠
# =========================================================

DATING_CATEGORY_NAME = "💗・소개팅"
DATING_CHANNEL_PREFIX = "💞・소개팅"
DATING_TIMEOUT_MINUTES = 10

DATING_QUESTIONS = [
    "최근에 가장 재밌었던 일은?",
    "주말에 보통 뭐 하면서 보내요?",
    "요즘 가장 자주 듣는 노래는?",
    "같이 하루를 보낸다면 어디에 가고 싶어요?",
    "친해질 때 가장 중요하다고 생각하는 건?",
    "게임을 한다면 어떤 게임을 같이 하고 싶어요?",
    "여행을 간다면 바다와 산 중 어디가 좋아요?",
    "첫인상과 지금 느낌이 달라졌나요?"
]

DATING_GAMES = [
    "🎲 가위바위보 한 판 해보기",
    "🎯 서로에게 10초 안에 질문 하나씩 하기",
    "🧠 초성: ㅇㅅㅎ (상대가 맞혀보기)",
    "💭 서로의 첫인상 한 단어로 말하기",
    "⚖️ 밸런스: 바다 여행 vs 도시 여행"
]


def save_dating_data():
    save_json(
        FILES["dating"],
        {
            "queue": dating_queue,
            "sessions": dating_sessions
        }
    )


def dating_member_session(member_id):
    for session_id, session in dating_sessions.items():
        if session.get("status") != "active":
            continue
        if member_id in session.get("members", []):
            return session_id, session
    return None, None


def get_dating_group(member):
    """소개팅 연령 그룹: 성인 / 미성년자 / None."""
    if member.bot:
        return None

    data = members.get(str(member.id), {})

    if not data.get("intro_completed"):
        return None

    birth_year = data.get("birth_year")
    if not isinstance(birth_year, int):
        return None

    # 2007년생까지 성인, 2008~2011년생은 미성년자
    if birth_year <= ADULT_CUTOFF:
        return "adult"

    if MIN_ALLOWED_BIRTH_YEAR > birth_year > ADULT_CUTOFF:
        return "minor"

    return None


def get_dating_gender(member):
    """소개팅 성별: 남 / 여 / None."""
    data = members.get(str(member.id), {})
    gender = data.get("gender")

    if gender in ("남", "여"):
        return gender

    return None


def can_dating_match(member_a, member_b):
    """소개팅 매칭 조건을 한 곳에서 강제한다.

    1. 성인 ↔ 성인 / 미성년자 ↔ 미성년자
    2. 남자 ↔ 여자
    3. 둘 다 자기소개 완료 회원
    """
    group_a = get_dating_group(member_a)
    group_b = get_dating_group(member_b)
    gender_a = get_dating_gender(member_a)
    gender_b = get_dating_gender(member_b)

    if not group_a or not group_b:
        return False

    if group_a != group_b:
        return False

    if gender_a not in ("남", "여") or gender_b not in ("남", "여"):
        return False

    return gender_a != gender_b


async def get_dating_category(guild):
    category = discord.utils.get(
        guild.categories,
        name=DATING_CATEGORY_NAME
    )

    if category:
        return category

    try:
        return await guild.create_category(
            DATING_CATEGORY_NAME,
            reason="소개팅 콘텐츠 카테고리 생성"
        )
    except Exception as e:
        print(f"[DATING CATEGORY ERROR] {e}")
        return None


async def create_dating_channel(guild, member_a, member_b):
    category = await get_dating_category(guild)
    if not category:
        return None

    session_id = uuid.uuid4().hex[:6].upper()

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        member_a: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        member_b: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }

    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True
        )

    try:
        channel = await guild.create_text_channel(
            f"{DATING_CHANNEL_PREFIX}-{session_id}",
            category=category,
            overwrites=overwrites,
            reason="소개팅 매칭 전용 채널 생성"
        )
    except Exception as e:
        print(f"[DATING CHANNEL ERROR] {e}")
        return None

    session = {
        "channel_id": channel.id,
        "members": [member_a.id, member_b.id],
        "status": "active",
        "created_at": iso(now()),
        "likes": [],
        "session_id": session_id
    }

    dating_sessions[session_id] = session
    save_dating_data()

    return session_id, channel


def dating_embed_for_member(viewer, opponent, session):
    profile = get_profile(opponent.id)
    info = members.get(
        str(opponent.id),
        {}
    )

    birth_year = profile.get("age") or info.get("birth_year") or "미설정"
    gender = profile.get("gender") or gender_text(info.get("gender"))
    location = profile.get("location") or "미설정"
    ideal_type = profile.get("ideal_type") or "미설정"
    likes = profile.get("likes") or "미설정"

    embed = discord.Embed(
        title=f"💗 소개팅 · {opponent.display_name}",
        description=(
            f"**{birth_year}** · **{gender}**\n"
            f"📍 {location}\n\n"
            f"♡ **이상형**\n{ideal_type}\n\n"
            f"🎮 **좋아하는 것**\n{likes}"
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )
    embed.set_thumbnail(url=opponent.display_avatar.url)
    embed.set_footer(
        text=f"소개팅 세션 · {session.get('session_id', '')}"
    )
    return embed


async def finish_dating_session(session_id, reason="소개팅 종료"):
    session = dating_sessions.get(session_id)
    if not session:
        return

    session["status"] = "ended"
    session["ended_at"] = iso(now())
    save_dating_data()

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    channel = guild.get_channel(session.get("channel_id"))
    if channel:
        try:
            await channel.send(
                f"🚪 **소개팅이 종료되었습니다.**\n사유: `{reason}`\n\n"
                "이 채널은 잠시 후 정리됩니다."
            )
            await asyncio.sleep(5)
        except Exception:
            pass

        try:
            await channel.delete(
                reason=reason
            )
        except Exception as e:
            print(f"[DATING DELETE ERROR] {e}")


class DatingReportModal(discord.ui.Modal, title="소개팅 신고"):

    reason = discord.ui.TextInput(
        label="신고 사유",
        placeholder="신고할 내용을 적어주세요.",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction):
        session_id = getattr(self, "session_id", None)
        session = dating_sessions.get(session_id) if session_id else None

        log = get_log_channel(interaction.guild)
        if log:
            await log.send(
                f"🚨 **소개팅 신고**\n"
                f"신고자: {interaction.user.mention}\n"
                f"세션: `{session_id or '알 수 없음'}`\n"
                f"사유: `{self.reason.value}`"
            )

        await interaction.response.send_message(
            "✅ 신고가 접수되었습니다. 관리자에게 전달했어요.",
            ephemeral=True
        )


class DatingView(discord.ui.View):

    def __init__(self, session_id):
        super().__init__(timeout=None)
        self.session_id = session_id
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.custom_id = f"dating:{session_id}:{item.custom_id.split(':')[-1]}"

    def get_session(self):
        return dating_sessions.get(self.session_id)

    def get_opponent(self, user_id):
        session = self.get_session()
        if not session:
            return None
        opponent_id = next(
            (uid for uid in session.get("members", []) if uid != user_id),
            None
        )
        if opponent_id is None:
            return None
        guild = bot.get_guild(GUILD_ID)
        return guild.get_member(opponent_id) if guild else None

    async def interaction_check(self, interaction):
        session = self.get_session()
        if not session or session.get("status") != "active":
            await interaction.response.send_message(
                "❌ 이미 종료된 소개팅입니다.",
                ephemeral=True
            )
            return False

        if interaction.user.id not in session.get("members", []):
            await interaction.response.send_message(
                "❌ 이 소개팅의 참가자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="상대정보",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:info"
    )
    async def info(self, interaction, button):
        opponent = self.get_opponent(interaction.user.id)
        session = self.get_session()
        if not opponent:
            await interaction.response.send_message("❌ 상대를 찾을 수 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=dating_embed_for_member(interaction.user, opponent, session),
            ephemeral=True
        )

    @discord.ui.button(
        label="오늘의 질문",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:question"
    )
    async def question(self, interaction, button):
        await interaction.response.send_message(
            f"💭 **오늘의 질문**\n\n「{random.choice(DATING_QUESTIONS)}」",
            ephemeral=False
        )

    @discord.ui.button(
        label="💚 호감 보내기",
        style=discord.ButtonStyle.success,
        custom_id="dating:like"
    )
    async def like(self, interaction, button):
        session = self.get_session()
        likes = session.setdefault("likes", [])

        if interaction.user.id not in likes:
            likes.append(interaction.user.id)
            save_dating_data()

        opponent = self.get_opponent(interaction.user.id)

        if opponent and opponent.id in likes:
            await interaction.response.send_message(
                f"🎉 **서로 호감이 확인됐어요!**\n\n"
                f"💗 {interaction.user.mention} × {opponent.mention}\n"
                "두 분 모두 서로에게 호감을 보냈습니다!",
                ephemeral=False
            )

            try:
                await interaction.user.send(
                    f"💗 소개팅 결과\n{opponent.display_name}님과 서로 호감이 확인됐어요!"
                )
            except Exception:
                pass

            try:
                await opponent.send(
                    f"💗 소개팅 결과\n{interaction.user.display_name}님과 서로 호감이 확인됐어요!"
                )
            except Exception:
                pass
        else:
            await interaction.response.send_message(
                "💚 호감을 보냈어요. 상대방도 호감을 보내면 서로 매칭됩니다!",
                ephemeral=True
            )

    @discord.ui.button(
        label="🎮 미니게임",
        style=discord.ButtonStyle.primary,
        custom_id="dating:game"
    )
    async def game(self, interaction, button):
        await interaction.response.send_message(
            f"🎮 **미니게임**\n\n{random.choice(DATING_GAMES)}",
            ephemeral=False
        )

    @discord.ui.button(
        label="신고/차단",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:report"
    )
    async def report(self, interaction, button):
        modal = DatingReportModal()
        modal.session_id = self.session_id
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="즉시 종료",
        style=discord.ButtonStyle.danger,
        custom_id="dating:end"
    )
    async def end(self, interaction, button):
        await interaction.response.send_message(
            "🚪 소개팅을 종료할게요.",
            ephemeral=True
        )
        await finish_dating_session(
            self.session_id,
            "참가자에 의해 종료"
        )


class DatingLobbyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="💗 소개팅 참가",
        style=discord.ButtonStyle.success,
        custom_id="dating:lobby_join"
    )
    async def join(self, interaction, button):
        member = interaction.user

        member_group = get_dating_group(member)
        member_gender = get_dating_gender(member)

        if not member_group or not member_gender:
            await interaction.response.send_message(
                "❌ 자기소개를 완료하고 성별·출생년도가 정상적으로 등록된 회원만 소개팅에 참가할 수 있어요.",
                ephemeral=True
            )
            return

        active_id, _ = dating_member_session(member.id)
        if active_id:
            await interaction.response.send_message(
                "❌ 이미 진행 중인 소개팅이 있어요.",
                ephemeral=True
            )
            return

        if member.id in dating_queue:
            await interaction.response.send_message(
                "⏳ 이미 소개팅 대기열에 들어가 있어요.",
                ephemeral=True
            )
            return

        dating_queue.append(member.id)

        # 중요: 같은 연령대 + 이성인 회원만 후보로 선택
        candidates = []
        for uid in dating_queue:
            if uid == member.id:
                continue

            opponent = interaction.guild.get_member(uid)
            if not opponent:
                continue

            if can_dating_match(member, opponent):
                candidates.append(uid)

        opponent_id = random.choice(candidates) if candidates else None

        if opponent_id is None:
            save_dating_data()
            await interaction.response.send_message(
                f"💗 소개팅 대기열에 들어갔어요!\n"
                f"현재 대기자: `{len(dating_queue)}명`\n\n"
                "상대가 참가하면 자동으로 매칭됩니다.",
                ephemeral=True
            )
            return

        dating_queue.remove(member.id)
        dating_queue.remove(opponent_id)

        opponent = interaction.guild.get_member(opponent_id)
        if not opponent:
            if opponent_id not in dating_queue:
                dating_queue.append(opponent_id)
            save_dating_data()
            await interaction.response.send_message(
                "⏳ 상대를 찾지 못해서 다시 대기열로 돌렸어요.",
                ephemeral=True
            )
            return

        # 최종 안전 검사: 조건이 하나라도 다르면 절대 매칭하지 않음
        if not can_dating_match(member, opponent):
            if opponent_id not in dating_queue:
                dating_queue.append(opponent_id)
            if member.id not in dating_queue:
                dating_queue.append(member.id)
            save_dating_data()
            await interaction.response.send_message(
                "⏳ 현재 조건에 맞는 상대가 없어 대기열에 남아있어요.",
                ephemeral=True
            )
            return

        result = await create_dating_channel(
            interaction.guild,
            member,
            opponent
        )

        if not result:
            dating_queue.extend([member.id, opponent.id])
            save_dating_data()
            await interaction.response.send_message(
                "❌ 소개팅 채널을 만들지 못했습니다. 봇의 채널 관리 권한을 확인해주세요.",
                ephemeral=True
            )
            return

        session_id, channel = result

        await interaction.response.send_message(
            f"💗 **소개팅 매칭 완료!**\n{channel.mention} 으로 이동해주세요.",
            ephemeral=True
        )

        try:
            await opponent.send(
                f"💗 소개팅 매칭이 완료됐어요!\n{channel.mention} 에서 상대방과 대화해보세요."
            )
        except Exception:
            pass

        await channel.send(
            f"💗 **소개팅 매칭 완료!**\n\n"
            f"{member.mention} × {opponent.mention}\n\n"
            "이 채널은 두 분과 봇만 볼 수 있는 전용 채팅방입니다.\n"
            f"💭 **첫 질문:** 「{random.choice(DATING_QUESTIONS)}」",
            view=DatingView(session_id)
        )

    @discord.ui.button(
        label="❌ 대기 취소",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:lobby_leave"
    )
    async def leave(self, interaction, button):
        if interaction.user.id not in dating_queue:
            await interaction.response.send_message(
                "❌ 현재 소개팅 대기열에 들어가 있지 않아요.",
                ephemeral=True
            )
            return

        dating_queue.remove(interaction.user.id)
        save_dating_data()

        await interaction.response.send_message(
            "✅ 소개팅 대기열에서 나왔어요.",
            ephemeral=True
        )

    @discord.ui.button(
        label="👤 내 프로필",
        style=discord.ButtonStyle.primary,
        custom_id="dating:lobby_profile"
    )
    async def profile(self, interaction, button):
        profile = get_profile(interaction.user.id)
        info = members.get(str(interaction.user.id), {})

        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name}",
            description=(
                f"**{profile.get('age') or info.get('birth_year') or '미설정'}** · "
                f"**{profile.get('gender') or gender_text(info.get('gender'))}**\n"
                f"📍 {profile.get('location') or '미설정'}\n\n"
                f"♡ 이상형\n{profile.get('ideal_type') or '미설정'}\n\n"
                f"🎮 좋아하는 것\n{profile.get('likes') or '미설정'}"
            ),
            color=discord.Color.from_rgb(255, 82, 145)
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


@bot.command(
    name="소개팅"
)
async def dating_command(ctx):
    if not get_dating_group(ctx.author) or not get_dating_gender(ctx.author):
        await ctx.send(
            "❌ 자기소개를 완료하고 성별·출생년도가 정상적으로 등록된 회원만 `!소개팅`을 이용할 수 있어요."
        )
        return

    active_id, _ = dating_member_session(ctx.author.id)
    if active_id:
        await ctx.send(
            f"❌ 이미 소개팅을 진행 중이에요. 세션: `{active_id}`"
        )
        return

    queue_count = len(dating_queue)

    embed = discord.Embed(
        title="💗 소개팅",
        description=(
            "새로운 사람을 만나볼래요?\n\n"
            "버튼을 눌러 참가하면 다른 참가자와 랜덤으로 매칭됩니다.\n"
            "매칭되면 두 사람만 볼 수 있는 전용 채팅방이 자동으로 생성돼요.\n\n"
            f"💗 현재 대기자 **{queue_count}명**\n"
            "🔞 성인 회원 전용 콘텐츠"
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )
    embed.set_footer(
        text="상대방을 존중하면서 즐겨주세요."
    )

    await ctx.send(
        embed=embed,
        view=DatingLobbyView()
    )


# =========================================================
# 메시지 이벤트
# =========================================================

@bot.event
async def on_message(
    message
):

    # 봇 무시

    if message.author.bot:

        return


    # DM 무시

    if not message.guild:

        return


    # 지정 서버만

    if message.guild.id != GUILD_ID:

        return


    # 활동 기록

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

        message.channel.id
        ==
        INTRO_CHANNEL_ID

        and

        not data.get(
            "intro_completed",
            False
        )

        and

        message.author.id
        not in
        intro_exceptions

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


    # !명령어 처리

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

    global dating_views_registered
    if not dating_views_registered:
        bot.add_view(DatingLobbyView())
        dating_views_registered = True


    guild = bot.get_guild(
        GUILD_ID
    )


    if not guild:

        print(
            "❌ 서버를 찾을 수 없음"
        )

        return


    for session_id, session in dating_sessions.items():
        if session.get("status") == "active":
            bot.add_view(
                DatingView(session_id),
                message_id=None
            )


    print(
        f"[SERVER] {guild.name}"
    )


    # 자기소개 체크

    if not intro_check.is_running():

        intro_check.start()

        print(
            "[CHECK] 자기소개 감시 시작"
        )


# =========================================================
# 명령어 오류
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
        f"{type(error).__name__}: "
        f"{error}"

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
