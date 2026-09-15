# ============================================================
# Discord GPT 자동관리봇
#
# 기능
# ------------------------------------------------------------
# 1. 신규 멤버 미인증 역할
# 2. 자기소개 자동 인식
# 3. 남자 / 여자 역할 자동 지급
# 4. 성인 / 미자 역할 자동 지급
# 5. 자기소개 + 장기 미활동 자동 추방
# 6. GPT 기반 자연스러운 대화
# 7. 최근 대화 기억
# 8. 서버별 대화 ON/OFF
# 9. 관리자용 AI 성격 변경
# 10. 관리자용 대화 초기화
# 11. 관리자용 멤버 상태 확인
# 12. 입장/추방 로그
# 13. 기본 관리 명령어
#
# 필요 패키지:
# pip install discord.py openai python-dotenv
#
# .env:
# DISCORD_TOKEN=디스코드_봇_토큰
# OPENAI_API_KEY=OpenAI_API키
# ============================================================

import discord
from discord.ext import commands, tasks

from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, deque

import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI


# ============================================================
# 환경설정
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN이 없습니다.")

if not OPENAI_API_KEY:
    print("❌ OPENAI_API_KEY가 없습니다.")


# ============================================================
# OpenAI
# ============================================================

ai = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)

# 비용을 아끼고 일반 채팅용으로 사용하는 모델
OPENAI_MODEL = "gpt-5.6-luna"


# ============================================================
# 기본 설정
# ============================================================

INTRO_KEYWORD = "자기소개"

LOG_CHANNEL_NAME = "추방-로그"

CHAT_CHANNEL_KEYWORD = "메인채팅"

GRACE_DAYS = 3

CHECK_MINUTES = 30

MAX_HISTORY_MESSAGES = 30

ADULT_CUTOFF_YEAR = 2007


# ============================================================
# 파일
# ============================================================

BASE_DIR = Path(__file__).parent

MEMBERS_FILE = BASE_DIR / "members.json"

SETTINGS_FILE = BASE_DIR / "chat_settings.json"

PERSONALITY_FILE = BASE_DIR / "bot_personality.json"


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
# 기본 AI 성격
# ============================================================

DEFAULT_PERSONALITY = """
너는 이 디스코드 서버에서 활동하는 친근한 채팅봇이다.

말투 규칙:

- 한국어 반말을 기본으로 한다.
- 너무 정중하거나 딱딱하게 말하지 않는다.
- 디스코드에서 실제 사람이 대화하는 것처럼 자연스럽게 말한다.
- 짧고 자연스럽게 답한다.
- 상황에 따라 ㅋㅋ, ㅇㅇ, ㄹㅇ, ㄱㄱ 등의 표현을 사용할 수 있다.
- 매번 ㅋㅋ을 붙이지 않는다.
- 같은 문장을 반복하지 않는다.
- 사용자가 진지한 이야기를 하면 장난스럽게 답하지 않는다.
- 사용자가 농담하면 같이 농담한다.
- 약간 거친 인터넷 커뮤니티 느낌은 가능하지만 억지로 욕하지 않는다.
- 가벼운 성인 농담이나 야한 뉘앙스의 농담은 성인 간 농담 수준에서만 한다.
- 노골적인 성적 묘사는 하지 않는다.
- 미성년자를 성적으로 다루는 대화에는 절대 응하지 않는다.
- 사용자가 이전에 말한 내용을 대화 맥락에 맞게 기억해서 이어간다.
- 모르는 사실은 아는 척하지 않는다.
- 자신이 디스코드 봇이라는 사실을 숨기지 않는다.

대화 스타일 예시:

사용자: 오늘 학교 개힘들었다
봇: 또 무슨 일 있었냐 ㅋㅋ

사용자: 시험 조짐
봇: 몇 점 나왔는데 ㅋㅋ

사용자: 42점
봇: 아 ㅋㅋ 그건 좀 아프네

사용자: 너 왜 이렇게 말함
봇: 너희 서버 분위기에 맞추는 중이지 ㅋㅋ

절대 모든 답변을 이런 식으로 똑같이 만들지 말고
대화 상황에 맞춰 자연스럽게 답한다.
"""


# ============================================================
# JSON
# ============================================================

def load_json(path, default):

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
            f"[JSON 오류] {path.name}: {e}"
        )

        return default


def save_json(path, data):

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
            f"[저장 오류] {path.name}: {e}"
        )


# ============================================================
# 데이터
# ============================================================

members_data = load_json(
    MEMBERS_FILE,
    {}
)

chat_settings = load_json(
    SETTINGS_FILE,
    {}
)

personality_data = load_json(
    PERSONALITY_FILE,
    {}
)


if not isinstance(members_data, dict):
    members_data = {}

if not isinstance(chat_settings, dict):
    chat_settings = {}

if not isinstance(personality_data, dict):
    personality_data = {}


# ============================================================
# 시간
# ============================================================

def utcnow():

    return datetime.now(timezone.utc)


# ============================================================
# Discord
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
# 대화 기억
#
# guild_id + channel_id 기준
# ============================================================

chat_history = defaultdict(
    lambda: deque(
        maxlen=MAX_HISTORY_MESSAGES
    )
)


# ============================================================
# 서버별 설정
# ============================================================

def is_chat_enabled(guild_id):

    return bool(
        chat_settings.get(
            str(guild_id),
            False
        )
    )


def set_chat_enabled(guild_id, value):

    chat_settings[
        str(guild_id)
    ] = value

    save_json(
        SETTINGS_FILE,
        chat_settings
    )


def get_personality(guild_id):

    return personality_data.get(
        str(guild_id),
        DEFAULT_PERSONALITY
    )


def set_personality(guild_id, text):

    personality_data[
        str(guild_id)
    ] = text

    save_json(
        PERSONALITY_FILE,
        personality_data
    )


# ============================================================
# 멤버 데이터
# ============================================================

def ensure_member(member):

    key = str(member.id)

    if key not in members_data:

        members_data[key] = {

            "joined":
                utcnow().isoformat(),

            "last_activity":
                utcnow().isoformat(),

            "intro":
                False,

            "birth_year":
                None,

            "gender":
                None
        }

        save_json(
            MEMBERS_FILE,
            members_data
        )

    data = members_data[key]

    data.setdefault(
        "joined",
        utcnow().isoformat()
    )

    data.setdefault(
        "last_activity",
        utcnow().isoformat()
    )

    data.setdefault(
        "intro",
        False
    )

    data.setdefault(
        "birth_year",
        None
    )

    data.setdefault(
        "gender",
        None
    )

    return data


# ============================================================
# 자동추방 제외
# ============================================================

def is_exempt(member):

    if member.bot:
        return True

    if member.guild_permissions.administrator:
        return True

    return False


# ============================================================
# 채널
# ============================================================

def find_log_channel(guild):

    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )


# ============================================================
# 역할
# ============================================================

def get_role(guild, role_type):

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
#
# 예:
# 07남
# 07남자
# 07ㄴ
# 08여
# 08여자
# 08ㅇ
# ============================================================

def convert_birth_year(two_digit):

    if 0 <= two_digit <= 26:

        return 2000 + two_digit

    return 1900 + two_digit


def is_adult(year):

    return year <= ADULT_CUTOFF_YEAR


def parse_intro(text):

    match = re.fullmatch(
        r"(\d{2})\s*(ㄴ|ㅇ|남|남자|여|여자)",
        text.strip()
    )

    if not match:
        return None

    year = convert_birth_year(
        int(match.group(1))
    )

    gender_code = match.group(2)

    if gender_code in (
        "ㄴ",
        "남",
        "남자"
    ):

        gender = "male"

    else:

        gender = "female"

    return {
        "birth_year": year,
        "gender": gender
    }


# ============================================================
# 자기소개 역할 지급
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
            add_roles.append(male)

        if female:
            remove_roles.append(female)

    else:

        if female:
            add_roles.append(female)

        if male:
            remove_roles.append(male)


    # 나이

    if is_adult(birth_year):

        if adult:
            add_roles.append(adult)

        if minor:
            remove_roles.append(minor)

    else:

        if minor:
            add_roles.append(minor)

        if adult:
            remove_roles.append(adult)


    # 미인증 제거

    if unverified:
        remove_roles.append(unverified)


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
            f"[역할 오류] {e}"
        )

        return False


# ============================================================
# AI에게 보낼 대화 기록
# ============================================================

def build_history(
    guild_id,
    channel_id
):

    key = (
        guild_id,
        channel_id
    )

    history = chat_history[key]

    result = []

    for item in history:

        result.append({

            "role": "user",

            "content":
                f"{item['user']}: "
                f"{item['content']}"
        })

        if item.get("answer"):

            result.append({

                "role": "assistant",

                "content":
                    item["answer"]
            })

    return result


# ============================================================
# AI 대화
# ============================================================

async def generate_ai_reply(message):

    guild_id = message.guild.id

    channel_id = message.channel.id

    personality = get_personality(
        guild_id
    )

    history = build_history(
        guild_id,
        channel_id
    )


    # 현재 질문

    user_text = message.content.strip()

    # 봇 멘션 제거

    if bot.user:

        user_text = user_text.replace(
            f"<@{bot.user.id}>",
            ""
        )

        user_text = user_text.replace(
            f"<@!{bot.user.id}>",
            ""
        )

    user_text = user_text.strip()

    if not user_text:

        user_text = "안녕"


    # ========================================================
    # 미성년자 관련 안전 처리
    # ========================================================

    safety_note = """
중요:
사용자가 미성년자라고 밝히거나 미성년자와 관련된
성적인 대화를 요구하면 성적인 내용으로 답하지 말고
일반적인 대화로 전환한다.
"""


    instructions = (
        personality
        + "\n"
        + safety_note
    )


    # 최근 대화 + 현재 질문

    input_messages = []

    input_messages.extend(
        history
    )

    input_messages.append({

        "role": "user",

        "content":
            f"{message.author.display_name}: "
            f"{user_text}"
    })


    try:

        response = await ai.responses.create(

            model=OPENAI_MODEL,

            instructions=instructions,

            input=input_messages,

            max_output_tokens=300
        )


        answer = response.output_text.strip()


        if not answer:

            return "잠깐 머리가 멈췄다 ㅋㅋ"


        # Discord 메시지 제한

        if len(answer) > 1900:

            answer = answer[:1890] + "..."


        return answer


    except Exception as e:

        print(
            f"[OpenAI 오류] {type(e).__name__}: {e}"
        )

        return (
            "잠깐 오류 났다 ㅋㅋ "
            "조금 있다가 다시 말 걸어봐."
        )


# ============================================================
# 대화 기억 저장
# ============================================================

def save_chat_memory(
    message,
    answer
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
# 신규 멤버
# ============================================================

@bot.event
async def on_member_join(member):

    if member.bot:
        return


    members_data[
        str(member.id)
    ] = {

        "joined":
            utcnow().isoformat(),

        "last_activity":
            utcnow().isoformat(),

        "intro":
            False,

        "birth_year":
            None,

        "gender":
            None
    }

    save_json(
        MEMBERS_FILE,
        members_data
    )


    # 미인증 역할

    try:

        role = get_role(
            member.guild,
            "unverified"
        )

        if role:

            await member.add_roles(
                role,
                reason="신규 멤버 미인증 역할"
            )

    except discord.Forbidden:

        print(
            "[역할 지급 실패] "
            "봇의 역할 순서를 확인하세요."
        )


    print(
        f"[입장] {member} ({member.id})"
    )


# ============================================================
# 메시지
# ============================================================

@bot.event
async def on_message(message):

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

    save_json(
        MEMBERS_FILE,
        members_data
    )


    # ========================================================
    # 자기소개
    # ========================================================

    if isinstance(
        message.channel,
        discord.TextChannel
    ):

        if INTRO_KEYWORD in message.channel.name:

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

                save_json(
                    MEMBERS_FILE,
                    members_data
                )


                success = await apply_intro_roles(
                    member,
                    parsed["birth_year"],
                    parsed["gender"]
                )


                if success:

                    gender_text = (
                        "남자"
                        if parsed["gender"] == "male"
                        else "여자"
                    )

                    age_text = (
                        "성인"
                        if is_adult(
                            parsed["birth_year"]
                        )
                        else "미자"
                    )


                    try:

                        await message.add_reaction(
                            "✅"
                        )

                    except discord.HTTPException:

                        pass


                    await message.channel.send(

                        f"{member.mention} "
                        f"자기소개 확인했어! ✅\n"
                        f"{parsed['birth_year']}년생 / "
                        f"{gender_text} / "
                        f"{age_text}"
                    )


    # ========================================================
    # GPT 자동대화
    # ========================================================

    should_chat = False


    # 멘션

    if bot.user and bot.user in message.mentions:

        should_chat = True


    content = message.content.strip()

    # 봇아

    if content.startswith("봇아"):

        should_chat = True


    # 메인채팅

    if isinstance(
        message.channel,
        discord.TextChannel
    ):

        if is_chat_enabled(
            message.guild.id
        ):

            if CHAT_CHANNEL_KEYWORD in message.channel.name:

                should_chat = True


    # 명령어는 AI가 가로채지 않음

    if content.startswith("!"):

        should_chat = False


    if should_chat:

        async with message.channel.typing():

            answer = await generate_ai_reply(
                message
            )


        save_chat_memory(
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

@bot.command(name="대화")
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
            if is_chat_enabled(
                ctx.guild.id
            )
            else "꺼짐"
        )

        await ctx.send(
            f"💬 메인채팅 AI 자동대화: **{state}**\n"
            f"`!대화 켜기`\n"
            f"`!대화 끄기`"
        )

        return


    setting = setting.lower()


    if setting == "켜기":

        set_chat_enabled(
            ctx.guild.id,
            True
        )

        await ctx.send(
            "💬 **GPT 자동대화 ON**\n"
            "메인채팅에서 자연스럽게 대화할게 ㅋㅋ"
        )


    elif setting == "끄기":

        set_chat_enabled(
            ctx.guild.id,
            False
        )

        await ctx.send(
            "💬 **GPT 자동대화 OFF**\n"
            "그래도 `봇아`라고 부르거나 멘션하면 답해."
        )


    else:

        await ctx.send(
            "`!대화 켜기` 또는 `!대화 끄기`"
        )


# ============================================================
# !대화초기화
# ============================================================

@bot.command(name="대화초기화")
@commands.has_permissions(
    administrator=True
)
async def reset_chat(ctx):

    key = (
        ctx.guild.id,
        ctx.channel.id
    )

    chat_history.pop(
        key,
        None
    )

    await ctx.send(
        "🧹 이 채널의 GPT 대화 기억을 초기화했어."
    )


# ============================================================
# !성격
# ============================================================

@bot.command(name="성격")
@commands.has_permissions(
    administrator=True
)
async def personality(
    ctx,
    *,
    text: str = None
):

    if not text:

        await ctx.send(
            "현재 설정된 성격:\n\n"
            f"```text\n"
            f"{get_personality(ctx.guild.id)[:1800]}"
            f"\n```"
        )

        return


    if len(text) > 3000:

        await ctx.send(
            "❌ 성격 설정은 3000자 이하로 해줘."
        )

        return


    set_personality(
        ctx.guild.id,
        text
    )


    await ctx.send(
        "🧠 **봇 성격 변경 완료!**"
    )


# ============================================================
# !성격초기화
# ============================================================

@bot.command(name="성격초기화")
@commands.has_permissions(
    administrator=True
)
async def personality_reset(ctx):

    personality_data.pop(
        str(ctx.guild.id),
        None
    )

    save_json(
        PERSONALITY_FILE,
        personality_data
    )

    await ctx.send(
        "🧠 기본 성격으로 되돌렸어."
    )


# ============================================================
# !상태
# ============================================================

@bot.command(name="상태")
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
            "📌 기록이 없는 멤버야."
        )

        return


    intro = (
        "✅ 작성 완료"
        if data.get("intro")
        else "❌ 미작성"
    )


    birth_year = data.get(
        "birth_year"
    )


    gender = data.get(
        "gender"
    )


    gender_text = {

        "male": "남자",

        "female": "여자"

    }.get(
        gender,
        "미설정"
    )


    age_text = "미설정"

    if birth_year:

        age_text = (
            "성인"
            if is_adult(
                int(birth_year)
            )
            else "미자"
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


    await ctx.send(

        f"**{member.display_name} 상태**\n"
        f"자기소개: {intro}\n"
        f"출생연도: {birth_year or '미설정'}\n"
        f"성별: {gender_text}\n"
        f"연령: {age_text}\n"
        f"최근 활동: {last_text}"
    )


# ============================================================
# !검사
# ============================================================

@bot.command(name="검사")
@commands.has_permissions(
    administrator=True
)
async def manual_check(ctx):

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

                last_activity = datetime.fromisoformat(
                    data["last_activity"]
                )

            except Exception:

                continue


            if (
                current - joined
                < timedelta(days=GRACE_DAYS)
            ):

                continue


            if data.get("intro"):

                continue


            if (
                current - last_activity
                < timedelta(days=GRACE_DAYS)
            ):

                continue


            count += 1


    await ctx.send(
        f"🔍 자동 추방 조건 해당 멤버: **{count}명**"
    )


# ============================================================
# !자기소개초기화
# ============================================================

@bot.command(name="자기소개초기화")
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


    save_json(
        MEMBERS_FILE,
        members_data
    )


    try:

        remove_roles = []

        for role_type in (
            "male",
            "female",
            "adult",
            "minor"
        ):

            role = get_role(
                member.guild,
                role_type
            )

            if role and role in member.roles:

                remove_roles.append(
                    role
                )


        if remove_roles:

            await member.remove_roles(
                *remove_roles,
                reason="자기소개 초기화"
            )


        unverified = get_role(
            member.guild,
            "unverified"
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
            "⚠️ 데이터는 초기화했지만 역할 변경 권한이 없어."
        )

        return


    await ctx.send(
        f"🔄 {member.mention} 자기소개 상태 초기화 완료."
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

        save_json(
            MEMBERS_FILE,
            members_data
        )


# ============================================================
# 자동추방
# ============================================================

@tasks.loop(minutes=CHECK_MINUTES)
async def check_members():

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

                last_activity = datetime.fromisoformat(
                    data["last_activity"]
                )

            except Exception:

                continue


            # 가입 후 3일 이내

            if (
                current - joined
                < timedelta(days=GRACE_DAYS)
            ):

                continue


            # 자기소개 완료

            if data.get("intro"):

                continue


            # 최근 활동 있음

            if (
                current - last_activity
                < timedelta(days=GRACE_DAYS)
            ):

                continue


            # =================================================
            # 추방
            # =================================================

            try:

                log_channel = find_log_channel(
                    guild
                )


                if log_channel:

                    embed = discord.Embed(

                        title="🚪 자동 추방",

                        description=(
                            f"{member.mention} 님이 "
                            f"자기소개 미작성 및 "
                            f"장기 미활동으로 추방됨."
                        ),

                        timestamp=current,

                        color=discord.Color.red()
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
                        "3일간 활동 없음"
                    )
                )


                members_data.pop(
                    str(member.id),
                    None
                )


                save_json(
                    MEMBERS_FILE,
                    members_data
                )


            except discord.Forbidden:

                print(
                    f"[추방 권한 없음] {member}"
                )

            except Exception as e:

                print(
                    f"[추방 오류] {member}: {e}"
                )


# ============================================================
# 검사 시작
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
# 준비
# ============================================================

@bot.event
async def on_ready():

    print("=" * 60)

    print(
        f"🤖 로그인: {bot.user}"
    )

    print(
        f"🆔 ID: {bot.user.id}"
    )

    print(
        f"🌐 서버: {len(bot.guilds)}개"
    )

    print(
        f"🧠 AI 모델: {OPENAI_MODEL}"
    )

    print(
        "💬 GPT 대화 시스템: 준비 완료"
    )

    print("=" * 60)


    if not check_members.is_running():

        check_members.start()


# ============================================================
# 실행
# ============================================================

if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN을 .env에 설정하세요."
    )


if not OPENAI_API_KEY:

    raise RuntimeError(
        "OPENAI_API_KEY를 .env에 설정하세요."
    )


print("🚀 봇 시작")

bot.run(
    DISCORD_TOKEN
)
