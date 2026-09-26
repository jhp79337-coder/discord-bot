# =========================================================
# Discord Server Management Bot
# bot.py PART 1/5
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


YACHA_CATEGORY = "[ 💬 ] ─ 채팅"

YACHA_NAME = "＃↝・야차"


# =========================================================
# 자기소개 설정
# =========================================================

INTRO_MINUTES = 30

# 2007년생까지 성인
ADULT_CUTOFF = 2007

# 2012년생부터 제한
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

    "yacha": "yacha_data.json",

    "chat": "chat.json"

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

yacha = {}

chat_settings = {}


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

            data = json.load(f)


        return data


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

    global yacha

    global chat_settings


    members = load_json(

        FILES["members"],

        {}

    )


    warnings = load_json(

        FILES["warnings"],

        {}

    )


    yacha = load_json(

        FILES["yacha"],

        {}

    )


    chat_settings = load_json(

        FILES["chat"],

        {
            "enabled": True
        }

    )


    print("=" * 50)

    print(
        f"[DATA] members : {len(members)}"
    )

    print(
        f"[DATA] warnings : {len(warnings)}"
    )

    print(
        f"[DATA] yacha : {yacha}"
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

            f"[ROLE ERROR] {role_id}"

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

        year = 2000 + n


    if not 1900 <= year <= current:

        return None


    return (

        year,

        "남"

        if gender in ("남", "ㄴ")

        else "여"

    )
# =========================================================
# bot.py PART 2/5
# 자기소개 / 입장 / 추방 확인 시스템
# =========================================================


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


    # 성별 역할

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


    # 연령 역할

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

    if year > MIN_ALLOWED_BIRTH_YEAR:

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


    # =====================================================
    # 역할 적용
    # =====================================================

    await apply_intro_roles(
        member,
        year,
        gender
    )


    # =====================================================
    # 안내
    # =====================================================

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


        # 이미 작성했으면 보호

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
# bot.py PART 3/5
# 야차방 시스템
# =========================================================


# =========================================================
# 야차방 찾기
# =========================================================

def get_yacha_channel(
    guild
):

    saved_id = yacha.get(
        str(guild.id)
    )


    if saved_id:

        try:

            channel = guild.get_channel(
                int(saved_id)
            )


            if isinstance(
                channel,
                discord.TextChannel
            ):

                return channel


        except Exception:

            pass



    channel = discord.utils.get(

        guild.text_channels,

        name=YACHA_NAME

    )


    if channel:

        yacha[str(guild.id)] = channel.id

        save_json(

            FILES["yacha"],

            yacha

        )


        return channel



    return None



# =========================================================
# 야차방 생성
# =========================================================

async def create_yacha(

    guild

):


    existing = get_yacha_channel(

        guild

    )


    if existing:

        return existing



    category = discord.utils.get(

        guild.categories,

        name=YACHA_CATEGORY

    )


    if not category:

        print(

            "[야차방] 카테고리 없음"

        )

        return None



    try:


        channel = await guild.create_text_channel(

            YACHA_NAME,

            category=category,

            reason="야차방 생성"

        )


        yacha[str(guild.id)] = channel.id


        save_json(

            FILES["yacha"],

            yacha

        )


        return channel



    except Exception as e:


        print(

            f"[야차방 생성 오류] {e}"

        )


        return None



# =========================================================
# 야차방 명령어
# =========================================================

@bot.command(
    name="야차방"
)

async def yacha_command(

    ctx,

    action=None,

    member: discord.Member = None

):


    # -----------------------------------------------------
    # 현재 야차방 확인
    # -----------------------------------------------------

    if action is None:


        channel = get_yacha_channel(

            ctx.guild

        )


        if channel:

            await ctx.send(

                f"💬 야차방: {channel.mention}"

            )


        else:

            await ctx.send(

                "❌ 야차방이 없습니다."

            )


        return



    # -----------------------------------------------------
    # 생성
    # -----------------------------------------------------

    if action in (

        "생성",

        "만들기",

        "create"

    ):


        if not is_admin(
            ctx.author
        ):

            await ctx.send(

                "❌ 관리자만 사용할 수 있습니다."

            )

            return



        channel = await create_yacha(

            ctx.guild

        )


        if channel:


            await ctx.send(

                f"✅ 야차방 생성 완료\n"
                f"{channel.mention}"

            )


        else:


            await ctx.send(

                "❌ 야차방 생성 실패\n"
                "카테고리를 확인해주세요."

            )


        return



    # -----------------------------------------------------
    # 회원 추가
    # -----------------------------------------------------

    if action in (

        "추가",

        "add"

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

                "❌ 추가할 회원을 멘션해주세요."

            )

            return



        channel = get_yacha_channel(

            ctx.guild

        )


        if not channel:


            await ctx.send(

                "❌ 야차방이 없습니다."

            )

            return



        try:


            overwrite = channel.overwrites_for(

                member

            )


            overwrite.view_channel = True

            overwrite.send_messages = True

            overwrite.read_message_history = True



            await channel.set_permissions(

                member,

                overwrite=overwrite,

                reason="야차방 추가"

            )



            await ctx.send(

                f"✅ {member.mention}님 "
                f"야차방 추가 완료"

            )



        except Exception as e:


            print(

                f"[야차방 추가 오류] {e}"

            )


            await ctx.send(

                "❌ 권한 변경 실패"

            )


        return



    # -----------------------------------------------------
    # 회원 제거
    # -----------------------------------------------------

    if action in (

        "제거",

        "삭제",

        "remove"

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

                "❌ 제거할 회원을 멘션해주세요."

            )

            return



        channel = get_yacha_channel(

            ctx.guild

        )


        if not channel:


            await ctx.send(

                "❌ 야차방이 없습니다."

            )

            return



        try:


            await channel.set_permissions(

                member,

                overwrite=None,

                reason="야차방 제거"

            )


            await ctx.send(

                f"✅ {member.mention}님 "
                f"야차방 제거 완료"

            )


        except Exception as e:


            print(

                f"[야차방 제거 오류] {e}"

            )



        return



    # -----------------------------------------------------
    # 목록
    # -----------------------------------------------------

    if action in (

        "목록",

        "list"

    ):


        if not is_admin(
            ctx.author
        ):


            await ctx.send(

                "❌ 관리자만 사용할 수 있습니다."

            )

            return



        channel = get_yacha_channel(

            ctx.guild

        )


        if not channel:


            await ctx.send(

                "❌ 야차방이 없습니다."

            )

            return



        result = []



        for m in ctx.guild.members:


            overwrite = channel.overwrites_for(

                m

            )


            if overwrite.view_channel is True:


                result.append(

                    f"• {m.mention}"

                )



        if not result:


            await ctx.send(

                "📋 추가된 회원 없음"

            )

            return



        await ctx.send(

            "📋 **야차방 이용자 목록**\n\n"

            +

            "\n".join(result)

        )


        return



    # -----------------------------------------------------
    # 방 삭제
    # -----------------------------------------------------

    if action in (

        "삭제방",

        "방삭제",

        "delete"

    ):


        if not is_admin(
            ctx.author
        ):


            await ctx.send(

                "❌ 관리자만 사용할 수 있습니다."

            )

            return



        channel = get_yacha_channel(

            ctx.guild

        )


        if not channel:


            await ctx.send(

                "❌ 야차방이 없습니다."

            )

            return



        try:


            await channel.delete(

                reason="야차방 삭제"

            )


            yacha.pop(

                str(ctx.guild.id),

                None

            )


            save_json(

                FILES["yacha"],

                yacha

            )


            await ctx.send(

                "✅ 야차방 삭제 완료"

            )



        except Exception as e:


            print(

                f"[야차방 삭제 오류] {e}"

            )


        return



    await ctx.send(

        "❌ 사용법 오류\n\n"

        "`!야차방`\n"

        "`!야차방 생성`\n"

        "`!야차방 추가 @회원`\n"

        "`!야차방 제거 @회원`\n"

        "`!야차방 목록`\n"

        "`!야차방 삭제방`"

    )
# =========================================================
# bot.py PART 4/5
# 경고 / 제재 시스템
# =========================================================


# =========================================================
# 제한 채널 관리
# =========================================================

async def restricted_access(

    member,

    allow=False

):


    channels = []


    # 19금 채널

    adult_channel = discord.utils.get(

        member.guild.text_channels,

        name="＃↝・19금"

    )


    if adult_channel:

        channels.append(

            adult_channel

        )


    # 몸공유방

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



    # 경고 1회 이상 제한

    await restricted_access(

        member,

        False

    )



    # 3회 / 4회 타임아웃

    timeout = WARNING_TIMEOUT.get(

        count

    )


    if timeout:


        try:


            await member.timeout(

                now() + timedelta(

                    seconds=timeout

                ),

                reason=

                f"경고 {count}회"

            )


        except Exception as e:


            print(

                f"[TIMEOUT ERROR] {e}"

            )



    # 5회 이상 추방

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

    member: discord.Member=None,

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

    member: discord.Member=None

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

            f"경고: `{data.get('count',0)}회`\n"

            f"사유: `{data.get('last_reason','없음')}`"

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

            f"• {name} : `{data.get('count',0)}회`"

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

    member: discord.Member=None

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

    member: discord.Member=None

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
# bot.py PART 5/5
# 이벤트 / 실행부
# =========================================================


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



    # 야차방 확인

    yacha_channel = get_yacha_channel(

        guild

    )


    if yacha_channel:


        print(

            f"[야차방] {yacha_channel.name}"

        )



    else:


        print(

            "[야차방] 없음"

        )



    # 자기소개 체크 시작

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

        f"[ERROR] {type(error).__name__}: {error}"

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
