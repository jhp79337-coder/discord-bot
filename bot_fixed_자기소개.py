import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, deque
import json
import os
import re
import asyncio

from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# 설정
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 모델
# 실제 사용 가능한 모델은 Google AI Studio/API 계정의 무료 티어
# 지원 여부를 확인해서 필요하면 변경
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

INTRO_KEYWORD = "자기소개"
LOG_CHANNEL_NAME = "추방-로그"

GRACE_DAYS = 3
CHECK_MINUTES = 30

# 2007년생까지 성인 처리
ADULT_CUTOFF_YEAR = 2007

CHAT_CHANNEL_KEYWORD = "메인채팅"

# 채널별 최근 대화 기억
MAX_HISTORY_MESSAGES = 30

# Gemini에 한 번에 보내는 최대 메시지 수
MAX_AI_HISTORY = 20

# 한 사용자가 너무 빠르게 AI를 호출하는 것 방지
AI_COOLDOWN_SECONDS = 3


# ============================================================
# 파일
# ============================================================

BASE_DIR = Path(__file__).parent

DATA_FILE = BASE_DIR / "members.json"
CHAT_SETTINGS_FILE = BASE_DIR / "chat_settings.json"


# ============================================================
# 역할 ID
# ============================================================

ROLE_IDS = {
    "unverified": 1544031900295893112,
    "male": 1544031878812532858,
    "female": 1544031884227518525,
    "adult": 1544031894809616475,
    "minor": 1544031889533182043,
}


# ============================================================
# Discord Intents
# ============================================================

intents = discord.Intents.default()

intents.members = True
intents.message_content = True
intents.voice_states = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# Gemini
# ============================================================

gemini_client = None

if GEMINI_API_KEY:

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("✅ Gemini API 연결 준비 완료")

    except Exception as e:

        print(
            f"❌ Gemini 초기화 오류: {e}"
        )

else:

    print(
        "⚠️ GEMINI_API_KEY가 없습니다."
    )


# ============================================================
# 데이터
# ============================================================

members_data = {}
chat_settings = {}

chat_history = defaultdict(
    lambda: deque(
        maxlen=MAX_HISTORY_MESSAGES
    )
)

ai_cooldowns = {}


# ============================================================
# 시간
# ============================================================

def utcnow():

    return datetime.now(
        timezone.utc
    )


# ============================================================
# JSON
# ============================================================

def load_json_file(
    path,
    default
):

    if not path.exists():

        return default

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as e:

        print(
            f"[JSON 오류] "
            f"{path.name}: {e}"
        )

        return default


def save_json_file(
    path,
    data
):

    try:

        path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

    except Exception as e:

        print(
            f"[JSON 저장 오류] "
            f"{path.name}: {e}"
        )


# ============================================================
# 데이터 불러오기
# ============================================================

members_data = load_json_file(
    DATA_FILE,
    {}
)

chat_settings = load_json_file(
    CHAT_SETTINGS_FILE,
    {}
)


if not isinstance(
    members_data,
    dict
):

    members_data = {}


if not isinstance(
    chat_settings,
    dict
):

    chat_settings = {}


# ============================================================
# 저장
# ============================================================

def save_data():

    save_json_file(
        DATA_FILE,
        members_data
    )


def save_chat_settings():

    save_json_file(
        CHAT_SETTINGS_FILE,
        chat_settings
    )


# ============================================================
# 멤버 기록
# ============================================================

def ensure_member(
    member
):

    key = str(
        member.id
    )

    if key not in members_data:

        now = utcnow().isoformat()

        members_data[key] = {

            "joined":
                now,

            "last_activity":
                now,

            "intro":
                False,

            "birth_year":
                None,

            "gender":
                None
        }

        save_data()

    data = members_data[key]

    data.setdefault(
        "birth_year",
        None
    )

    data.setdefault(
        "gender",
        None
    )

    data.setdefault(
        "intro",
        False
    )

    data.setdefault(
        "joined",
        utcnow().isoformat()
    )

    data.setdefault(
        "last_activity",
        utcnow().isoformat()
    )

    return data


# ============================================================
# 자동 추방 제외
# ============================================================

def is_exempt(
    member
):

    if member.bot:

        return True

    if member.guild_permissions.administrator:

        return True

    return False


# ============================================================
# 채널
# ============================================================

def find_log_channel(
    guild
):

    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )


# ============================================================
# 역할
# ============================================================

def get_role(
    guild,
    role_type
):

    role_id = ROLE_IDS.get(
        role_type
    )

    if not role_id:

        return None

    return guild.get_role(
        role_id
    )


# ============================================================
# 자기소개 파싱
# ============================================================

def convert_birth_year(
    two_digit
):

    if 0 <= two_digit <= 26:

        return 2000 + two_digit

    return 1900 + two_digit


def is_adult_from_birth_year(
    birth_year
):

    return birth_year <= ADULT_CUTOFF_YEAR


def parse_intro(
    text
):

    match = re.fullmatch(
        r"(\d{2})\s*(ㄴ|ㅇ|남|여)",
        text.strip()
    )

    if not match:

        return None

    two_digit = int(
        match.group(1)
    )

    gender_code = match.group(2)

    birth_year = convert_birth_year(
        two_digit
    )

    if gender_code in (
        "ㄴ",
        "남"
    ):

        gender = "male"

    else:

        gender = "female"

    return {
        "birth_year": birth_year,
        "gender": gender
    }


# ============================================================
# 역할 적용
# ============================================================

async def apply_intro_roles(
    member,
    birth_year,
    gender
):

    unverified = get_role(
        member.guild,
        "unverified"
    )

    male = get_role(
        member.guild,
        "male"
    )

    female = get_role(
        member.guild,
        "female"
    )

    adult = get_role(
        member.guild,
        "adult"
    )

    minor = get_role(
        member.guild,
        "minor"
    )

    add_roles = []
    remove_roles = []

    # 성별
    if gender == "male":

        if male:

            add_roles.append(
                male
            )

        if female:

            remove_roles.append(
                female
            )

    else:

        if female:

            add_roles.append(
                female
            )

        if male:

            remove_roles.append(
                male
            )

    # 나이
    if is_adult_from_birth_year(
        birth_year
    ):

        if adult:

            add_roles.append(
                adult
            )

        if minor:

            remove_roles.append(
                minor
            )

    else:

        if minor:

            add_roles.append(
                minor
            )

        if adult:

            remove_roles.append(
                adult
            )

    # 미인증 제거
    if unverified:

        remove_roles.append(
            unverified
        )

    try:

        if remove_roles:

            await member.remove_roles(
                *remove_roles,
                reason="자기소개 인증 역할 정리"
            )

        if add_roles:

            await member.add_roles(
                *add_roles,
                reason="자기소개 인증 완료"
            )

        return True

    except discord.Forbidden:

        print(
            f"[역할 권한 오류] {member}"
        )

        return False

    except discord.HTTPException as e:

        print(
            f"[역할 적용 오류] {e}"
        )

        return False


# ============================================================
# 채팅 설정
# ============================================================

def chat_enabled(
    guild_id
):

    return bool(
        chat_settings.get(
            str(guild_id),
            False
        )
    )


# ============================================================
# 봇 호출 여부
# ============================================================

def should_ai_chat(
    message
):

    if not isinstance(
        message.channel,
        discord.TextChannel
    ):

        return False

    content = message.content.strip()

    if not content:

        return False

    if content.startswith("!"):

        return False

    # 멘션
    if (
        bot.user
        and bot.user in message.mentions
    ):

        return True

    lowered = content.lower()

    # 봇아
    if lowered.startswith(
        "봇아"
    ):

        return True

    # 봇,
    if re.match(
        r"^봇[\s,!?]",
        content
    ):

        return True

    # 메인채팅 자동 대화
    if chat_enabled(
        message.guild.id
    ):

        if (
            CHAT_CHANNEL_KEYWORD
            in message.channel.name
        ):

            return True

    return False


# ============================================================
# 멘션 제거
# ============================================================

def clean_bot_mention(
    text
):

    if bot.user:

        text = text.replace(
            f"<@{bot.user.id}>",
            ""
        )

        text = text.replace(
            f"<@!{bot.user.id}>",
            ""
        )

    text = re.sub(
        r"^봇아[\s,!?]*",
        "",
        text,
        flags=re.IGNORECASE
    )

    return text.strip()


# ============================================================
# AI 말투
# ============================================================

SYSTEM_PROMPT = """
너는 한국어 Discord 서버에서 활동하는 친근한 채팅 봇이다.

너의 말투:
- 한국 인터넷 커뮤니티에서 친구끼리 대화하는 것처럼 자연스럽게 말한다.
- 너무 정중하거나 딱딱하게 말하지 않는다.
- 짧고 자연스럽게 답한다.
- 필요하면 ㅋㅋ, ㅎㅎ, ㄹㅇ, 인정, ㄷㄷ 같은 표현을 적당히 사용한다.
- 상대방의 말에 맞춰서 반응한다.
- 똑같은 문장을 반복하지 않는다.
- 대화의 앞뒤 문맥을 기억하고 이어서 답한다.
- 사용자가 농담하면 농담으로 받아친다.
- 살짝 장난스럽고 능글맞은 분위기는 가능하다.
- 상대가 불편해할 정도로 공격적으로 굴지는 않는다.
- 성적인 농담을 요청받더라도 노골적인 성적 묘사나 미성년자 관련 성적 내용은 만들지 않는다.
- 사용자가 미성년자임을 밝힌 경우 성적인 방향으로 대화를 유도하지 않는다.
- 실제 사람인 척하거나 사용자의 개인정보를 안다고 주장하지 않는다.

답변은 Discord 채팅에 바로 보낼 수 있는 자연스러운 문장으로 작성한다.
쓸데없는 설명이나 'AI로서' 같은 말은 하지 않는다.
"""


# ============================================================
# 대화 기억 추가
# ============================================================

def add_chat_history(
    message,
    answer=None
):

    key = (
        message.guild.id,
        message.channel.id
    )

    chat_history[key].append({

        "user":
            message.author.display_name,

        "content":
            message.content.strip(),

        "answer":
            answer
    })


# ============================================================
# Gemini용 대화 내용
# ============================================================

def build_ai_prompt(
    message
):

    key = (
        message.guild.id,
        message.channel.id
    )

    history = chat_history.get(
        key,
        []
    )

    lines = []

    for item in list(history)[
        -MAX_AI_HISTORY:
    ]:

        user = item.get(
            "user",
            "사용자"
        )

        content = item.get(
            "content",
            ""
        )

        answer = item.get(
            "answer"
        )

        if content:

            lines.append(
                f"{user}: {content}"
            )

        if answer:

            lines.append(
                f"봇: {answer}"
            )

    current_text = clean_bot_mention(
        message.content
    )

    lines.append(
        f"{message.author.display_name}: "
        f"{current_text}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# Gemini 답변
# ============================================================

async def generate_ai_reply(
    message
):

    if not gemini_client:

        return (
            "⚠️ Gemini API 키가 아직 설정되지 않았어."
        )

    user_id = message.author.id

    now = asyncio.get_running_loop().time()

    last_time = ai_cooldowns.get(
        user_id,
        0
    )

    if (
        now - last_time
        < AI_COOLDOWN_SECONDS
    ):

        return None

    ai_cooldowns[user_id] = now

    prompt = build_ai_prompt(
        message
    )

    try:

        response = await asyncio.to_thread(

            gemini_client.models.generate_content,

            model=GEMINI_MODEL,

            contents=prompt,

            config=types.GenerateContentConfig(

                system_instruction=SYSTEM_PROMPT,

                temperature=0.9,

                max_output_tokens=300
            )
        )

        answer = response.text

        if not answer:

            return (
                "음... 잠깐 머리 좀 굴려볼게 ㅋㅋ"
            )

        answer = answer.strip()

        # Discord 메시지 최대 길이 보호
        if len(answer) > 1900:

            answer = answer[:1900] + "..."

        return answer

    except Exception as e:

        print(
            f"[Gemini 오류] {type(e).__name__}: {e}"
        )

        return (
            "잠깐 오류났네 ㅋㅋ 조금 있다가 다시 불러봐."
        )


# ============================================================
# 신규 멤버
# ============================================================

@bot.event
async def on_member_join(
    member
):

    if member.bot:

        return

    now = utcnow().isoformat()

    members_data[
        str(member.id)
    ] = {

        "joined":
            now,

        "last_activity":
            now,

        "intro":
            False,

        "birth_year":
            None,

        "gender":
            None
    }

    save_data()

    print(
        f"[입장] {member} ({member.id})"
    )

    try:

        unverified = get_role(
            member.guild,
            "unverified"
        )

        if unverified:

            await member.add_roles(
                unverified,
                reason="신규 입장 미인증 역할"
            )

    except discord.Forbidden:

        print(
            "[미인증 역할 실패] "
            "Manage Roles 권한 확인"
        )


# ============================================================
# 메시지
# ============================================================

@bot.event
async def on_message(
    message
):

    if message.author.bot:

        return

    if not isinstance(
        message.author,
        discord.Member
    ):

        await bot.process_commands(
            message
        )

        return

    member = message.author

    # ========================================================
    # 활동 기록
    # ========================================================

    data = ensure_member(
        member
    )

    data["last_activity"] = (
        utcnow().isoformat()
    )

    save_data()

    # ========================================================
    # 자기소개
    # ========================================================

    if isinstance(
        message.channel,
        discord.TextChannel
    ):

        if (
            INTRO_KEYWORD
            in message.channel.name
        ):

            parsed = parse_intro(
                message.content
            )

            if parsed:

                data["intro"] = True

                data["birth_year"] = (
                    parsed["birth_year"]
                )

                data["gender"] = (
                    parsed["gender"]
                )

                save_data()

                success = (
                    await apply_intro_roles(
                        member,
                        parsed["birth_year"],
                        parsed["gender"]
                    )
                )

                gender_text = (

                    "남자"

                    if parsed["gender"]
                    == "male"

                    else "여자"
                )

                age_text = (

                    "성인"

                    if is_adult_from_birth_year(
                        parsed["birth_year"]
                    )

                    else "미자"
                )

                try:

                    await message.add_reaction(
                        "✅"
                    )

                except Exception:

                    pass

                if success:

                    await message.channel.send(

                        f"{member.mention} "
                        f"자기소개 확인했어! ✅\n"
                        f"출생연도: "
                        f"{parsed['birth_year']}\n"
                        f"성별: {gender_text}\n"
                        f"연령: {age_text}"
                    )

                else:

                    await message.channel.send(
                        f"{member.mention} "
                        f"자기소개는 확인했는데 "
                        f"역할 지급에 실패했어."
                    )

    # ========================================================
    # AI 대화
    # ========================================================

    if should_ai_chat(
        message
    ):

        async with message.channel.typing():

            answer = await generate_ai_reply(
                message
            )

        if answer:

            add_chat_history(
                message,
                answer
            )

            try:

                await message.reply(
                    answer,
                    mention_author=False
                )

            except discord.HTTPException as e:

                print(
                    f"[AI 답변 전송 오류] {e}"
                )

    await bot.process_commands(
        message
    )


# ============================================================
# !대화
# ============================================================

@bot.command(
    name="대화"
)
@commands.has_permissions(
    administrator=True
)
async def chat_toggle(
    ctx,
    setting: str = None
):

    if setting is None:

        state = (

            "켜짐"

            if chat_enabled(
                ctx.guild.id
            )

            else "꺼짐"
        )

        await ctx.send(

            f"💬 메인채팅 자동 대화: "
            f"**{state}**\n\n"
            "`!대화 켜기`\n"
            "`!대화 끄기`"
        )

        return

    setting = setting.lower()

    if setting == "켜기":

        chat_settings[
            str(ctx.guild.id)
        ] = True

        save_chat_settings()

        await ctx.send(
            "💬 메인채팅 AI 대화 **ON**"
        )

    elif setting == "끄기":

        chat_settings[
            str(ctx.guild.id)
        ] = False

        save_chat_settings()

        await ctx.send(
            "💬 메인채팅 AI 대화 **OFF**\n"
            "그래도 `봇아` 또는 멘션하면 답해."
        )

    else:

        await ctx.send(
            "사용법: `!대화 켜기` / `!대화 끄기`"
        )


# ============================================================
# !기억초기화
# ============================================================

@bot.command(
    name="기억초기화"
)
@commands.has_permissions(
    administrator=True
)
async def reset_memory(
    ctx
):

    key = (
        ctx.guild.id,
        ctx.channel.id
    )

    chat_history.pop(
        key,
        None
    )

    await ctx.send(
        "🧹 이 채널의 AI 대화 기억을 초기화했어."
    )


# ============================================================
# !상태
# ============================================================

@bot.command(
    name="상태"
)
@commands.has_permissions(
    administrator=True
)
async def status(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author

    data = members_data.get(
        str(member.id)
    )

    if not data:

        await ctx.send(
            "📌 이 사용자의 기록이 없어."
        )

        return

    intro = (

        "✅ 작성 완료"

        if data.get(
            "intro",
            False
        )

        else "❌ 미작성"
    )

    try:

        last = datetime.fromisoformat(
            data["last_activity"]
        )

        last_text = (
            f"<t:{int(last.timestamp())}:R>"
        )

    except Exception:

        last_text = "알 수 없음"

    birth_year = data.get(
        "birth_year"
    )

    gender = data.get(
        "gender"
    )

    gender_text = {

        "male":
            "남자",

        "female":
            "여자"

    }.get(
        gender,
        "미설정"
    )

    age_text = "미설정"

    if birth_year:

        age_text = (

            "성인"

            if is_adult_from_birth_year(
                int(birth_year)
            )

            else "미자"
        )

    await ctx.send(

        f"**{member.display_name} 상태**\n"
        f"자기소개: {intro}\n"
        f"출생연도: "
        f"{birth_year or '미설정'}\n"
        f"성별: {gender_text}\n"
        f"연령: {age_text}\n"
        f"최근 활동: {last_text}"
    )


# ============================================================
# !검사
# ============================================================

@bot.command(
    name="검사"
)
@commands.has_permissions(
    administrator=True
)
async def manual_check(
    ctx
):

    count = 0

    current = utcnow()

    for guild in bot.guilds:

        for member in guild.members:

            if is_exempt(member):

                continue

            data = members_data.get(
                str(member.id)
            )

            if not data:

                continue

            try:

                joined = datetime.fromisoformat(
                    data["joined"]
                )

                last_activity = (
                    datetime.fromisoformat(
                        data["last_activity"]
                    )
                )

            except Exception:

                continue

            if (
                current - joined
                < timedelta(
                    days=GRACE_DAYS
                )
            ):

                continue

            if data.get(
                "intro",
                False
            ):

                continue

            if (
                current - last_activity
                < timedelta(
                    days=GRACE_DAYS
                )
            ):

                continue

            count += 1

    await ctx.send(
        f"🔍 자동 추방 조건 해당 멤버: "
        f"**{count}명**"
    )


# ============================================================
# !자기소개초기화
# ============================================================

@bot.command(
    name="자기소개초기화"
)
@commands.has_permissions(
    administrator=True
)
async def reset_intro(
    ctx,
    member: discord.Member
):

    data = ensure_member(
        member
    )

    data["intro"] = False
    data["birth_year"] = None
    data["gender"] = None

    save_data()

    try:

        remove_roles = []

        for role_type in [
            "male",
            "female",
            "adult",
            "minor"
        ]:

            role = get_role(
                member.guild,
                role_type
            )

            if (
                role
                and role in member.roles
            ):

                remove_roles.append(
                    role
                )

        unverified = get_role(
            member.guild,
            "unverified"
        )

        if remove_roles:

            await member.remove_roles(
                *remove_roles,
                reason="자기소개 초기화"
            )

        if (
            unverified
            and unverified not in member.roles
        ):

            await member.add_roles(
                unverified,
                reason="자기소개 초기화"
            )

    except discord.Forbidden:

        await ctx.send(
            "⚠️ 데이터는 초기화했지만 "
            "역할 변경 권한이 없어."
        )

        return

    await ctx.send(
        f"🔄 {member.mention}님의 "
        f"자기소개 상태를 초기화했어."
    )


# ============================================================
# 음성 활동
# ============================================================

@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if member.bot:

        return

    if (
        before.channel is None
        and after.channel is not None
    ):

        data = ensure_member(
            member
        )

        data["last_activity"] = (
            utcnow().isoformat()
        )

        save_data()


# ============================================================
# 자동 추방
# ============================================================

@tasks.loop(
    minutes=CHECK_MINUTES
)
async def check_members():

    current = utcnow()

    print(
        f"[자동 검사] "
        f"{current.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    for guild in bot.guilds:

        for member in guild.members:

            if is_exempt(member):

                continue

            data = members_data.get(
                str(member.id)
            )

            if not data:

                continue

            try:

                joined = datetime.fromisoformat(
                    data["joined"]
                )

                last_activity = (
                    datetime.fromisoformat(
                        data["last_activity"]
                    )
                )

            except Exception:

                continue

            if (
                current - joined
                < timedelta(
                    days=GRACE_DAYS
                )
            ):

                continue

            if data.get(
                "intro",
                False
            ):

                continue

            if (
                current - last_activity
                < timedelta(
                    days=GRACE_DAYS
                )
            ):

                continue

            try:

                log_channel = (
                    find_log_channel(
                        guild
                    )
                )

                if log_channel:

                    embed = discord.Embed(

                        title="🚪 자동 추방",

                        description=(
                            f"{member.mention} 님이 "
                            f"자기소개 미작성 및 "
                            f"장기 미활동으로 "
                            f"자동 추방되었습니다."
                        ),

                        timestamp=current
                    )

                    embed.add_field(
                        name="사용자",
                        value=(
                            f"{member} "
                            f"({member.id})"
                        ),
                        inline=False
                    )

                    await log_channel.send(
                        embed=embed
                    )

                await member.kick(
                    reason=(
                        "자기소개 미작성 + "
                        "장기 미활동"
                    )
                )

                members_data.pop(
                    str(member.id),
                    None
                )

                save_data()

            except discord.Forbidden:

                print(
                    f"[추방 권한 오류] {member}"
                )

            except Exception as e:

                print(
                    f"[추방 오류] "
                    f"{member}: {e}"
                )


# ============================================================
# 자동 검사 시작
# ============================================================

@check_members.before_loop
async def before_check_members():

    await bot.wait_until_ready()


# ============================================================
# 명령어 오류
# ============================================================

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
            "❌ 관리자만 사용할 수 있어."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 필요한 값을 입력해줘."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 멤버를 찾지 못했어."
        )

        return

    print(
        f"[명령어 오류] {error}"
    )


# ============================================================
# 봇 준비
# ============================================================

@bot.event
async def on_ready():

    print("=" * 60)

    print(
        f"로그인 완료: {bot.user}"
    )

    print(
        f"봇 ID: {bot.user.id}"
    )

    print(
        f"연결된 서버: {len(bot.guilds)}개"
    )

    print(
        f"Gemini 모델: {GEMINI_MODEL}"
    )

    print(
        "AI 대화: "
        + (
            "사용 가능"
            if gemini_client
            else "API 키 없음"
        )
    )

    print("=" * 60)

    if not check_members.is_running():

        check_members.start()


# ============================================================
# 실행
# ============================================================

if not DISCORD_TOKEN:

    print(
        "❌ DISCORD_TOKEN을 설정해주세요."
    )

else:

    print(
        "🤖 디스코드 봇 시작"
    )

    bot.run(
        DISCORD_TOKEN
    )
