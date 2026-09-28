# =========================================================
# Discord Server Management Bot
# bot.py
# =========================================================

import os
import json
import re

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
        "intro_exceptions.json"

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


    embed = discord.Embed(

        title="👤 프로필",

        color=
        discord.Color.blurple()

    )


    embed.set_thumbnail(

        url=
        ctx.author.display_avatar.url

    )


    embed.add_field(

        name="나이",

        value=(

            profile.get("age")

            or

            member_info.get(
                "birth_year"
            )

            or

            "미설정"

        ),

        inline=True

    )


    embed.add_field(

        name="사는 곳",

        value=

        profile.get(
            "location"
        )
        or
        "미설정",

        inline=True

    )


    embed.add_field(

        name="성별",

        value=(

            profile.get("gender")

            or

            gender_text(

                member_info.get(
                    "gender"
                )

            )

        ),

        inline=True

    )


    embed.add_field(

        name="이상형",

        value=

        profile.get(
            "ideal_type"
        )
        or
        "미설정",

        inline=False

    )


    embed.add_field(

        name="좋아하는 것",

        value=

        profile.get(
            "likes"
        )
        or
        "미설정",

        inline=False

    )


    embed.set_footer(

        text=
        "!프로필편집 으로 수정"

    )


    await ctx.send(
        embed=embed
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
