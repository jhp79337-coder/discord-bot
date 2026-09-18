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
# 환경변수
# =========================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)


# =========================================================
# 기본 설정
# =========================================================

LOG_CHANNEL_NAME = "🚪・추방로그"

INTRO_DEADLINE_DAYS = 30
CHECK_MINUTES = 1

# 2007년생까지 성인
# 2008년생부터 미성년자
ADULT_CUTOFF_YEAR = 2007


# =========================================================
# 서버 / 채널 ID
# =========================================================

GUILD_ID = 1542210983127425158

# 역할선택 채널
ROLE_CHANNEL_ID = 1549631714769244261

# 메인채팅 채널
MAIN_CHAT_CHANNEL_ID = 1544032267855470644

# AI 대화 채널
ADULT_CHAT_CHANNEL = "＃↝・성인채팅"
ADULT_19_CHANNEL = "＃↝・19금"


# =========================================================
# 역할 ID
# =========================================================

UNVERIFIED_ROLE_ID = 1544031900295893112
MALE_ROLE_ID = 1544031878812532858
FEMALE_ROLE_ID = 1544031884227518525

ADULT_ROLE_ID = 1544031894809616475
MINOR_ROLE_ID = 1544031889533182043


# =========================================================
# 데이터 파일
# =========================================================

MEMBERS_FILE = "members.json"
CHAT_SETTINGS_FILE = "chat_settings.json"


# =========================================================
# Discord Intents
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.voice_states = True


# =========================================================
# Bot
# =========================================================

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================================
# Gemini / OpenAI 호환 API
# =========================================================

gemini_client = None

if GEMINI_API_KEY:
    gemini_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


# =========================================================
# 메모리 데이터
# =========================================================

members_data = {}
chat_settings = {}

chat_history = {}
ai_cooldowns = {}

pending_kick_reviews = set()


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
# JSON 불러오기
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
            f"[JSON 불러오기 오류] {filename}: {e}"
        )

        return default


# =========================================================
# JSON 저장
# =========================================================

def save_json(filename, data):

    try:

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"[JSON 저장 오류] {filename}: {e}"
        )


members_data = load_json(
    MEMBERS_FILE,
    {}
)

chat_settings = load_json(
    CHAT_SETTINGS_FILE,
    {}
)


# =========================================================
# 시간
# =========================================================

def now_utc():

    return datetime.now(
        timezone.utc
    )


def iso_now():

    return now_utc().isoformat()


def parse_datetime(value):

    if not value:
        return None

    try:

        return datetime.fromisoformat(
            value
        )

    except Exception:

        return None


# =========================================================
# 사용자 데이터 키
# =========================================================

def member_key(
    guild_id,
    user_id
):

    return f"{guild_id}:{user_id}"


# =========================================================
# 나이 구분
# =========================================================

def get_age_type(birth_year):

    # 2007년생까지 성인
    if birth_year <= ADULT_CUTOFF_YEAR:
        return "성인"

    # 2008년생부터 미성년자
    return "미성년자"


# =========================================================
# 성별 표시
# =========================================================

def get_gender_text(gender):

    if gender == "남":
        return "남자"

    if gender == "여":
        return "여자"

    return "미확인"


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(content):

    text = content.strip()

    pattern = (
        r"(?<!\d)"
        r"(\d{2})"
        r"\s*"
        r"(남|여|ㄴ|ㅇ)"
        r"(?!\S)"
    )

    match = re.search(
        pattern,
        text
    )

    if not match:
        return None

    birth_year = int(
        match.group(1)
    )

    gender_raw = match.group(2)

    if gender_raw in [
        "남",
        "ㄴ"
    ]:

        gender = "남"

    else:

        gender = "여"

    birth_year += 2000

    return birth_year, gender


# =========================================================
# 역할 적용
# =========================================================

async def apply_member_roles(
    member,
    birth_year,
    gender
):

    guild = member.guild

    unverified = guild.get_role(
        UNVERIFIED_ROLE_ID
    )

    male = guild.get_role(
        MALE_ROLE_ID
    )

    female = guild.get_role(
        FEMALE_ROLE_ID
    )

    adult = guild.get_role(
        ADULT_ROLE_ID
    )

    minor = guild.get_role(
        MINOR_ROLE_ID
    )

    roles_to_add = []
    roles_to_remove = []


    # -----------------------------------------------------
    # 미인증 역할 제거
    # -----------------------------------------------------

    if (
        unverified
        and unverified in member.roles
    ):

        roles_to_remove.append(
            unverified
        )


    # -----------------------------------------------------
    # 남자 / 여자 역할
    # -----------------------------------------------------

    if gender == "남":

        if (
            male
            and male not in member.roles
        ):

            roles_to_add.append(
                male
            )

        if (
            female
            and female in member.roles
        ):

            roles_to_remove.append(
                female
            )


    elif gender == "여":

        if (
            female
            and female not in member.roles
        ):

            roles_to_add.append(
                female
            )

        if (
            male
            and male in member.roles
        ):

            roles_to_remove.append(
                male
            )


    # -----------------------------------------------------
    # 성인 / 미성년자
    # -----------------------------------------------------

    if birth_year <= ADULT_CUTOFF_YEAR:

        # 2007년생까지 성인

        if (
            adult
            and adult not in member.roles
        ):

            roles_to_add.append(
                adult
            )

        if (
            minor
            and minor in member.roles
        ):

            roles_to_remove.append(
                minor
            )

    else:

        # 2008년생부터 미성년자

        if (
            minor
            and minor not in member.roles
        ):

            roles_to_add.append(
                minor
            )

        if (
            adult
            and adult in member.roles
        ):

            roles_to_remove.append(
                adult
            )


    # -----------------------------------------------------
    # 로그
    # -----------------------------------------------------

    print(
        f"[역할 처리] "
        f"{member} / "
        f"{birth_year}년생 / "
        f"{gender} / "
        f"{get_age_type(birth_year)}"
    )


    try:

        # 기존 역할 제거
        if roles_to_remove:

            await member.remove_roles(
                *roles_to_remove,
                reason="자기소개 인증 역할 정리"
            )


        # 새로운 역할 추가
        if roles_to_add:

            await member.add_roles(
                *roles_to_add,
                reason="자기소개 인증"
            )


        return True


    except discord.Forbidden:

        print(
            f"[역할 오류] {member} 역할 변경 권한 없음"
        )

        return False


    except Exception as e:

        print(
            f"[역할 오류] {e}"
        )

        return False


# =========================================================
# 활동 기록
# =========================================================

def update_activity(member):

    key = member_key(
        member.guild.id,
        member.id
    )


    if key not in members_data:

        members_data[key] = {

            "guild_id": member.guild.id,

            "user_id": member.id,

            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at
                else iso_now()
            ),

            "intro_completed": False,

            "birth_year": None,

            "gender": None,

            "last_activity": iso_now(),

            "is_existing_member": False
        }


    else:

        members_data[key][
            "last_activity"
        ] = iso_now()


    save_json(
        MEMBERS_FILE,
        members_data
    )


# =========================================================
# 자기소개 성공 메시지
# =========================================================

async def send_intro_success_message(
    message,
    birth_year,
    gender
):

    age_type = get_age_type(
        birth_year
    )

    gender_text = get_gender_text(
        gender
    )


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
# AI 활성화 여부
# =========================================================

def is_ai_enabled(guild_id):

    return chat_settings.get(
        str(guild_id),
        True
    )


# =========================================================
# AI 응답 여부
# =========================================================

def should_ai_reply(message):

    if message.author.bot:
        return False

    if not message.guild:
        return False

    if not gemini_client:
        return False

    if not is_ai_enabled(
        message.guild.id
    ):
        return False


    # 봇 멘션
    if (
        bot.user
        and bot.user in message.mentions
    ):

        return True


    # 봇아
    if "봇아" in message.content:
        return True


    # 자비스
    if "자비스" in message.content.lower():
        return True


    # 메인채팅
    if (
        message.channel.id
        == MAIN_CHAT_CHANNEL_ID
    ):

        return True


    # 성인채팅 / 19금
    if message.channel.name in [
        ADULT_CHAT_CHANNEL,
        ADULT_19_CHANNEL
    ]:

        return True


    return False


# =========================================================
# AI 처리
# =========================================================

async def handle_ai_chat(message):

    if not should_ai_reply(
        message
    ):

        return


    user_id = message.author.id


    # -----------------------------------------------------
    # 2초 쿨다운
    # -----------------------------------------------------

    current_time = (
        asyncio.get_event_loop().time()
    )

    last_time = ai_cooldowns.get(
        user_id,
        0
    )


    if current_time - last_time < 2:

        return


    ai_cooldowns[user_id] = (
        current_time
    )


    # -----------------------------------------------------
    # 사용자별 기록
    # -----------------------------------------------------

    key = member_key(
        message.guild.id,
        user_id
    )


    if key not in chat_history:

        chat_history[key] = []


    # -----------------------------------------------------
    # 봇 멘션 제거
    # -----------------------------------------------------

    content = message.content


    if bot.user:

        content = content.replace(
            bot.user.mention,
            ""
        )


    content = content.strip()


    if not content:

        return


    chat_history[key].append({

        "role": "user",

        "content": content
    })


    # 최근 12개
    chat_history[key] = (
        chat_history[key][-12:]
    )


    # -----------------------------------------------------
    # Gemini 요청
    # -----------------------------------------------------

    try:

        messages = [

            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }

        ]

        messages.extend(
            chat_history[key]
        )


        response = await asyncio.to_thread(

            gemini_client.chat.completions.create,

            model=GEMINI_MODEL,

            messages=messages,

            max_tokens=700
        )


        reply = (
            response
            .choices[0]
            .message
            .content
        )


        if not reply:

            return


        # Discord 메시지 제한
        if len(reply) > 1900:

            reply = (
                reply[:1900]
                + "..."
            )


        chat_history[key].append({

            "role": "assistant",

            "content": reply
        })


        chat_history[key] = (
            chat_history[key][-12:]
        )


        await message.channel.send(

            reply,

            allowed_mentions=(
                discord.AllowedMentions.none()
            )
        )


    except Exception as e:

        print(
            f"[Gemini 오류] "
            f"{type(e).__name__}: {e}"
        )

        try:

            await message.channel.send(
                "잠깐 오류가 났어 ㅠㅠ "
                "조금 있다가 다시 말 걸어줘!"
            )

        except Exception:

            pass


# =========================================================
# 추방 확인 버튼
# =========================================================

class KickConfirmView(
    discord.ui.View
):

    def __init__(self, member):

        super().__init__(
            timeout=86400
        )

        self.member = member


    # -----------------------------------------------------
    # 추방
    # -----------------------------------------------------

    @discord.ui.button(
        label="🚪 추방하기",
        style=discord.ButtonStyle.danger
    )
    async def kick_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.kick_members:

            await interaction.response.send_message(
                "추방 권한이 필요해요.",
                ephemeral=True
            )

            return


        member = interaction.guild.get_member(
            self.member.id
        )


        if not member:

            await interaction.response.send_message(
                "이미 서버에 없는 멤버예요.",
                ephemeral=True
            )

            return


        try:

            await member.kick(
                reason="30일 이상 자기소개 미작성"
            )


            pending_kick_reviews.discard(
                member.id
            )


            await interaction.response.edit_message(

                content=(
                    f"🚪 **{member}** 님을 추방했습니다."
                ),

                embed=None,

                view=None
            )


        except discord.Forbidden:

            await interaction.response.send_message(

                "봇의 역할이 대상 멤버보다 낮아서 "
                "추방할 수 없어요.",

                ephemeral=True
            )


        except Exception as e:

            print(
                f"[추방 오류] {e}"
            )

            await interaction.response.send_message(

                "추방 중 오류가 발생했어요.",

                ephemeral=True
            )


    # -----------------------------------------------------
    # 취소
    # -----------------------------------------------------

    @discord.ui.button(
        label="❌ 취소하기",
        style=discord.ButtonStyle.secondary
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.kick_members:

            await interaction.response.send_message(

                "관리자/추방 권한이 필요해요.",

                ephemeral=True
            )

            return


        key = member_key(
            interaction.guild.id,
            self.member.id
        )


        if key in members_data:

            members_data[key][
                "kick_review_declined_until"
            ] = (

                now_utc()
                + timedelta(hours=24)
            ).isoformat()


            save_json(
                MEMBERS_FILE,
                members_data
            )


        pending_kick_reviews.discard(
            self.member.id
        )


        await interaction.response.edit_message(

            content=(

                f"❌ **{self.member}** 님의 "
                f"추방 검토를 취소했습니다.\n"
                f"24시간 동안 같은 추방 확인이 "
                f"다시 뜨지 않습니다."
            ),

            embed=None,

            view=None
        )


# =========================================================
# 추방 검토 메시지
# =========================================================

async def send_kick_review(member):

    if member.id in pending_kick_reviews:

        return


    pending_kick_reviews.add(
        member.id
    )


    channel = discord.utils.get(

        member.guild.text_channels,

        name=LOG_CHANNEL_NAME
    )


    if not channel:

        print(
            f"[추방 로그 오류] "
            f"{LOG_CHANNEL_NAME} 채널을 찾을 수 없음"
        )

        pending_kick_reviews.discard(
            member.id
        )

        return


    embed = discord.Embed(

        title="🚪 자기소개 미작성 멤버 추방 확인",

        description=(

            f"**대상:** {member.mention}\n"

            f"**닉네임:** `{member}`\n\n"

            f"가입 후 **{INTRO_DEADLINE_DAYS}일**이 지났지만 "
            f"자기소개가 확인되지 않았습니다.\n\n"

            f"추방하려면 아래 버튼을 눌러주세요."
        ),

        color=discord.Color.red()
    )


    embed.set_thumbnail(
        url=member.display_avatar.url
    )


    embed.timestamp = now_utc()


    await channel.send(

        embed=embed,

        view=KickConfirmView(
            member
        )
    )


# =========================================================
# 30일 자기소개 검사
# =========================================================

@tasks.loop(
    minutes=CHECK_MINUTES
)
async def check_members():

    await bot.wait_until_ready()


    guild = bot.get_guild(
        GUILD_ID
    )


    if not guild:

        return


    for member in guild.members:

        # 봇 제외
        if member.bot:
            continue


        # 관리자 제외
        if member.guild_permissions.administrator:
            continue


        key = member_key(
            guild.id,
            member.id
        )


        # 기존 데이터 없는 멤버는 제외
        if key not in members_data:
            continue


        data = members_data[key]


        # 자기소개 완료
        if data.get(
            "intro_completed",
            False
        ):

            continue


        # 이미 추방 검토 중
        if member.id in pending_kick_reviews:

            continue


        joined_at = parse_datetime(
            data.get("joined_at")
        )


        if not joined_at:

            continue


        deadline = (
            joined_at
            + timedelta(
                days=INTRO_DEADLINE_DAYS
            )
        )


        # 아직 30일 안 됨
        if now_utc() < deadline:

            continue


        # 24시간 취소 상태
        declined_until = parse_datetime(

            data.get(
                "kick_review_declined_until"
            )
        )


        if declined_until:

            if now_utc() < declined_until:

                continue


        try:

            await send_kick_review(
                member
            )

        except Exception as e:

            print(
                f"[30일 검사 오류] "
                f"{member}: {e}"
            )


# =========================================================
# Bot Ready
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)

    print(
        f"JARVIS 로그인 완료: {bot.user}"
    )

    print(
        f"서버 수: {len(bot.guilds)}"
    )

    print(
        f"Gemini 모델: {GEMINI_MODEL}"
    )

    print(
        f"성인 기준: {ADULT_CUTOFF_YEAR}년생까지"
    )

    print(
        f"자기소개 제한: "
        f"{INTRO_DEADLINE_DAYS}일"
    )

    print("=" * 50)


    if not check_members.is_running():

        check_members.start()


# =========================================================
# 서버 입장
# =========================================================

@bot.event
async def on_member_join(member):

    if member.guild.id != GUILD_ID:

        return


    key = member_key(
        member.guild.id,
        member.id
    )


    members_data[key] = {

        "guild_id": member.guild.id,

        "user_id": member.id,

        "joined_at": (

            member.joined_at.isoformat()

            if member.joined_at

            else iso_now()
        ),

        "intro_completed": False,

        "birth_year": None,

        "gender": None,

        "last_activity": iso_now(),

        "is_existing_member": False
    }


    save_json(
        MEMBERS_FILE,
        members_data
    )


    # -----------------------------------------------------
    # 미인증 역할
    # -----------------------------------------------------

    unverified = member.guild.get_role(
        UNVERIFIED_ROLE_ID
    )


    if unverified:

        try:

            await member.add_roles(

                unverified,

                reason="신규 가입 미인증 역할"
            )

        except Exception as e:

            print(
                f"[입장 역할 오류] {e}"
            )


    # -----------------------------------------------------
    # DM
    # -----------------------------------------------------

    try:

        await member.send(

            "🖤 어서 와요!\n\n"

            "서버 이용을 위해 자기소개를 해주세요.\n\n"

            "**예시**\n"

            "`04 남`\n"
            "`04 여`\n"
            "`04 ㄴ`\n"
            "`04 ㅇ`\n\n"

            "2007년생까지 성인,\n"
            "2008년생부터 미성년자로 구분됩니다."
        )

    except Exception:

        pass


# =========================================================
# 메시지 이벤트
# =========================================================

@bot.event
async def on_message(message):

    # 봇 제외
    if message.author.bot:

        return


    # DM
    if not message.guild:

        await bot.process_commands(
            message
        )

        return


    # -----------------------------------------------------
    # 활동 기록
    # -----------------------------------------------------

    update_activity(
        message.author
    )


    # -----------------------------------------------------
    # 자기소개 검사
    # -----------------------------------------------------

    intro = parse_intro(
        message.content
    )


    if intro:

        birth_year, gender = intro


        key = member_key(
            message.guild.id,
            message.author.id
        )


        if key not in members_data:

            members_data[key] = {

                "guild_id": message.guild.id,

                "user_id": message.author.id,

                "joined_at": (

                    message.author.joined_at.isoformat()

                    if message.author.joined_at

                    else iso_now()
                ),

                "intro_completed": False,

                "birth_year": None,

                "gender": None,

                "last_activity": iso_now(),

                "is_existing_member": True
            }


        # -------------------------------------------------
        # 자기소개 저장
        # -------------------------------------------------

        members_data[key][
            "intro_completed"
        ] = True


        members_data[key][
            "birth_year"
        ] = birth_year


        members_data[key][
            "gender"
        ] = gender


        members_data[key][
            "last_activity"
        ] = iso_now()


        members_data[key].pop(
            "kick_review_declined_until",
            None
        )


        save_json(
            MEMBERS_FILE,
            members_data
        )


        # -------------------------------------------------
        # 역할 적용
        # -------------------------------------------------

        role_success = await apply_member_roles(

            message.author,

            birth_year,

            gender
        )


        if not role_success:

            await message.channel.send(

                "자기소개는 확인했는데 "
                "역할을 바꾸는 중 문제가 발생했어요. "
                "관리자에게 알려주세요."
            )


        # -------------------------------------------------
        # 성공 메시지
        # -------------------------------------------------

        await send_intro_success_message(

            message,

            birth_year,

            gender
        )


        # 자기소개 메시지는 AI로 보내지 않음
        await bot.process_commands(
            message
        )

        return


    # -----------------------------------------------------
    # AI
    # -----------------------------------------------------

    await handle_ai_chat(
        message
    )


    # -----------------------------------------------------
    # 명령어
    # -----------------------------------------------------

    await bot.process_commands(
        message
    )


# =========================================================
# 음성 채널 활동
# =========================================================

@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if member.bot:

        return


    if before.channel == after.channel:

        return


    update_activity(
        member
    )


# =========================================================
# !상태
# =========================================================

@bot.command(
    name="상태"
)
async def status_command(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author


    key = member_key(
        ctx.guild.id,
        member.id
    )


    data = members_data.get(
        key
    )


    if not data:

        await ctx.send(

            f"❌ **{member}** 님의 "
            f"기록이 없습니다."
        )

        return


    intro_completed = data.get(
        "intro_completed",
        False
    )


    birth_year = data.get(
        "birth_year"
    )


    gender = data.get(
        "gender"
    )


    last_activity = data.get(
        "last_activity"
    )


    if birth_year:

        age_type = get_age_type(
            birth_year
        )

    else:

        age_type = "미확인"


    embed = discord.Embed(

        title="📋 JARVIS 상태",

        color=discord.Color.blurple()
    )


    embed.add_field(

        name="사용자",

        value=member.mention,

        inline=False
    )


    embed.add_field(

        name="자기소개",

        value=(

            "✅ 완료"

            if intro_completed

            else "❌ 미작성"
        ),

        inline=True
    )


    embed.add_field(

        name="출생년도",

        value=(

            f"{birth_year}년생"

            if birth_year

            else "미확인"
        ),

        inline=True
    )


    embed.add_field(

        name="성별",

        value=(

            get_gender_text(gender)

            if gender

            else "미확인"
        ),

        inline=True
    )


    embed.add_field(

        name="연령 구분",

        value=age_type,

        inline=True
    )


    embed.add_field(

        name="최근 활동",

        value=(

            last_activity

            if last_activity

            else "기록 없음"
        ),

        inline=False
    )


    await ctx.send(
        embed=embed
    )


# =========================================================
# !대화 on / off
# =========================================================

@bot.command(
    name="대화"
)
@commands.has_permissions(
    administrator=True
)
async def toggle_chat(
    ctx,
    option: str = None
):

    if option not in [
        "on",
        "off"
    ]:

        current = is_ai_enabled(
            ctx.guild.id
        )


        await ctx.send(

            f"현재 AI 대화 상태: "
            f"`{'ON' if current else 'OFF'}`\n"

            f"`!대화 on` 또는 "
            f"`!대화 off`"
        )

        return


    enabled = option == "on"


    chat_settings[
        str(ctx.guild.id)
    ] = enabled


    save_json(
        CHAT_SETTINGS_FILE,
        chat_settings
    )


    await ctx.send(

        f"🤖 AI 대화를 "
        f"**{'ON' if enabled else 'OFF'}** 했어요."
    )


# =========================================================
# !기억초기화
# =========================================================

@bot.command(
    name="기억초기화"
)
async def clear_memory(
    ctx
):

    key = member_key(
        ctx.guild.id,
        ctx.author.id
    )


    chat_history.pop(
        key,
        None
    )


    await ctx.send(

        f"🧹 {ctx.author.mention} 님과의 "
        f"AI 대화 기억을 초기화했어요."
    )


# =========================================================
# !검사
# =========================================================

@bot.command(
    name="검사"
)
@commands.has_permissions(
    administrator=True
)
async def inspect_member(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author


    key = member_key(
        ctx.guild.id,
        member.id
    )


    data = members_data.get(
        key
    )


    if not data:

        await ctx.send(
            "❌ 해당 멤버의 데이터가 없습니다."
        )

        return


    birth_year = data.get(
        "birth_year"
    )


    gender = data.get(
        "gender"
    )


    age_type = (

        get_age_type(
            birth_year
        )

        if birth_year

        else "미확인"
    )


    role_names = [

        role.name

        for role in member.roles

        if role.name != "@everyone"
    ]


    embed = discord.Embed(

        title="🔎 멤버 검사",

        color=discord.Color.orange()
    )


    embed.add_field(

        name="멤버",

        value=member.mention,

        inline=False
    )


    embed.add_field(

        name="자기소개",

        value=(

            "완료"

            if data.get(
                "intro_completed"
            )

            else "미작성"
        ),

        inline=True
    )


    embed.add_field(

        name="출생년도",

        value=(

            f"{birth_year}년생"

            if birth_year

            else "미확인"
        ),

        inline=True
    )


    embed.add_field(

        name="성별",

        value=(

            get_gender_text(
                gender
            )

            if gender

            else "미확인"
        ),

        inline=True
    )


    embed.add_field(

        name="연령",

        value=age_type,

        inline=True
    )


    embed.add_field(

        name="역할",

        value=(

            ", ".join(role_names)

            if role_names

            else "없음"
        ),

        inline=False
    )


    await ctx.send(
        embed=embed
    )


# =========================================================
# !자기소개초기화
# =========================================================

@bot.command(
    name="자기소개초기화"
)
@commands.has_permissions(
    administrator=True
)
async def reset_intro(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author


    key = member_key(
        ctx.guild.id,
        member.id
    )


    if key not in members_data:

        members_data[key] = {

            "guild_id": ctx.guild.id,

            "user_id": member.id,

            "joined_at": iso_now(),

            "intro_completed": False,

            "birth_year": None,

            "gender": None,

            "last_activity": iso_now(),

            "is_existing_member": True
        }


    else:

        members_data[key][
            "intro_completed"
        ] = False

        members_data[key][
            "birth_year"
        ] = None

        members_data[key][
            "gender"
        ] = None

        members_data[key][
            "last_activity"
        ] = iso_now()


    save_json(
        MEMBERS_FILE,
        members_data
    )


    # -----------------------------------------------------
    # 기존 역할 제거
    # -----------------------------------------------------

    roles_to_remove = []


    for role_id in [

        MALE_ROLE_ID,

        FEMALE_ROLE_ID,

        ADULT_ROLE_ID,

        MINOR_ROLE_ID

    ]:

        role = ctx.guild.get_role(
            role_id
        )


        if (
            role
            and role in member.roles
        ):

            roles_to_remove.append(
                role
            )


    if roles_to_remove:

        try:

            await member.remove_roles(

                *roles_to_remove,

                reason="관리자 자기소개 초기화"
            )

        except Exception as e:

            print(
                f"[초기화 역할 제거 오류] {e}"
            )


    # -----------------------------------------------------
    # 미인증 역할 추가
    # -----------------------------------------------------

    unverified = ctx.guild.get_role(
        UNVERIFIED_ROLE_ID
    )


    if unverified:

        try:

            await member.add_roles(

                unverified,

                reason="관리자 자기소개 초기화"
            )

        except Exception as e:

            print(
                f"[미인증 역할 추가 오류] {e}"
            )


    await ctx.send(

        f"♻️ {member.mention} 님의 "
        f"자기소개 정보를 초기화했습니다."
    )


# =========================================================
# !추방로그테스트
# =========================================================

@bot.command(
    name="추방로그테스트"
)
@commands.has_permissions(
    administrator=True
)
async def kick_log_test(
    ctx
):

    channel = discord.utils.get(

        ctx.guild.text_channels,

        name=LOG_CHANNEL_NAME
    )


    if not channel:

        await ctx.send(

            f"❌ `{LOG_CHANNEL_NAME}` "
            f"채널을 찾을 수 없습니다."
        )

        return


    embed = discord.Embed(

        title="🚪 추방 로그 테스트",

        description=(
            "추방 로그 채널이 "
            "정상적으로 연결되었습니다."
        ),

        color=discord.Color.red()
    )


    await channel.send(
        embed=embed
    )


    await ctx.send(
        "✅ 추방 로그 테스트를 보냈습니다."
    )


# =========================================================
# !추방확인테스트
# =========================================================

@bot.command(
    name="추방확인테스트"
)
@commands.has_permissions(
    administrator=True
)
async def kick_review_test(
    ctx,
    member: discord.Member = None
):

    if not member:

        await ctx.send(

            "사용법: "
            "`!추방확인테스트 @멤버`"
        )

        return


    await send_kick_review(
        member
    )


    await ctx.send(

        f"✅ {member.mention} "
        f"추방 확인 메시지를 보냈습니다."
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
        commands.MissingPermissions
    ):

        await ctx.send(
            "❌ 이 명령어를 사용할 권한이 없습니다."
        )

        return


    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 필요한 인자가 빠졌어요."
        )

        return


    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 멤버를 찾을 수 없습니다."
        )

        return


    print(
        f"[명령어 오류] "
        f"{type(error).__name__}: {error}"
    )


# =========================================================
# 시작
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
