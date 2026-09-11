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
# 새벽에너를기다리는중 자동관리봇 + AI 수다
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------

INTRO_KEYWORD = "자기소개"
LOG_CHANNEL_NAME = "추방-로그"

GRACE_DAYS = 3
CHECK_MINUTES = 30

# 2026년 기준
# 00~07 = 성인
# 08~26 = 미자
ADULT_CUTOFF_YEAR = 2007

# ------------------------------------------------------------
# 기존 Discord 역할 ID
# ------------------------------------------------------------

ROLE_IDS = {
    "unverified": 1544031900295893112,
    "male": 1544031878812532858,
    "female": 1544031884227518525,
    "adult": 1544031894809616475,
    "minor": 1544031889533182043,
}

# ------------------------------------------------------------
# AI 수다
# ------------------------------------------------------------

# 채널 이름에 "메인채팅"이 들어가면 자동 대화
CHAT_CHANNEL_KEYWORD = "메인채팅"

MAX_HISTORY_MESSAGES = 12
MAX_AI_REPLY_LENGTH = 1900

DATA_FILE = Path(__file__).parent / "members.json"
CHAT_SETTINGS_FILE = Path(__file__).parent / "chat_settings.json"

# ------------------------------------------------------------
# Discord
# ------------------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# ------------------------------------------------------------
# OpenAI
# ------------------------------------------------------------

ai_client = (
    AsyncOpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY
    else None
)

AI_SYSTEM_PROMPT = """
너는 Discord 서버에서 사람들과 편하게 수다를 떠는 친근한 한국어 봇이야.

말투:
- 자연스러운 한국어
- 너무 길게 말하지 말 것
- 친구처럼 편하게 말하기
- 상황에 따라 ㅋㅋ, ㅇㅇ, ㄹㅇ, 오, 헐 등을 자연스럽게 사용
- 사용자가 진지하게 물으면 진지하게 답변
- 장난에는 가볍게 받아주기
- 억지로 질문을 계속하지 말 것
- AI라는 사실을 숨기지 말 것

안전:
- 미성년자와 관련된 성적/노골적인 내용에는 응하지 말 것.
- 미성년자의 성적 대상화, 성적 역할극 등을 하지 말 것.
- 나이 인증 우회나 서버 인증 규칙 회피를 도와주지 말 것.
- 불법 행위나 타인에게 피해를 주는 행동을 구체적으로 돕지 말 것.

Discord 대화에서는 짧고 자연스럽게 답하는 것을 우선한다.
"""

chat_history = defaultdict(
    lambda: deque(maxlen=MAX_HISTORY_MESSAGES)
)

# ------------------------------------------------------------
# 시간
# ------------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------
# JSON
# ------------------------------------------------------------

def load_json_file(path, default):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as e:
        print(
            f"[JSON 불러오기 오류] "
            f"{path.name}: {e}"
        )
        return default


def save_json_file(path, data):
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


members_data = load_json_file(
    DATA_FILE,
    {}
)

chat_settings = load_json_file(
    CHAT_SETTINGS_FILE,
    {}
)


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


# ------------------------------------------------------------
# 멤버 기록
# ------------------------------------------------------------

def ensure_member(member: discord.Member):

    key = str(member.id)

    if key not in members_data:

        members_data[key] = {
            "joined": utcnow().isoformat(),
            "last_activity": utcnow().isoformat(),
            "intro": False,
            "birth_year": None,
            "gender": None
        }

        save_data()

    members_data[key].setdefault(
        "birth_year",
        None
    )

    members_data[key].setdefault(
        "gender",
        None
    )

    return members_data[key]


# ------------------------------------------------------------
# 자동 추방 제외
# ------------------------------------------------------------

def is_exempt(member: discord.Member):

    if member.bot:
        return True

    if member.guild_permissions.administrator:
        return True

    return False


# ------------------------------------------------------------
# 채널 찾기
# ------------------------------------------------------------

def find_intro_channel(guild):

    for channel in guild.text_channels:

        if INTRO_KEYWORD in channel.name:
            return channel

    return None


def find_log_channel(guild):

    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )


# ------------------------------------------------------------
# 기존 역할 가져오기
# ------------------------------------------------------------

async def ensure_roles(guild):

    roles = {}

    for role_type, role_id in ROLE_IDS.items():

        role = guild.get_role(role_id)

        if role is not None:

            roles[role_type] = role

        else:

            print(
                f"[역할 없음] "
                f"{role_type} / ID: {role_id}"
            )

    return roles


# ------------------------------------------------------------
# 자기소개 파싱
# ------------------------------------------------------------

def convert_birth_year(two_digit):

    if 0 <= two_digit <= 26:
        return 2000 + two_digit

    return 1900 + two_digit


def is_adult_from_birth_year(birth_year):

    return birth_year <= ADULT_CUTOFF_YEAR


def parse_intro(text):

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


# ------------------------------------------------------------
# 자기소개 역할 적용
# ------------------------------------------------------------

async def apply_intro_roles(
    member,
    birth_year,
    gender
):

    roles = await ensure_roles(
        member.guild
    )

    unverified = roles.get("unverified")
    male = roles.get("male")
    female = roles.get("female")
    adult = roles.get("adult")
    minor = roles.get("minor")

    add_roles = []
    remove_roles = []

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

    if is_adult_from_birth_year(birth_year):

        if adult:
            add_roles.append(adult)

        if minor:
            remove_roles.append(minor)

    else:

        if minor:
            add_roles.append(minor)

        if adult:
            remove_roles.append(adult)

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
            f"[역할 적용 오류] {e}"
        )

        return False


# ------------------------------------------------------------
# 신규 멤버
# ------------------------------------------------------------

@bot.event
async def on_member_join(member):

    if member.bot:
        return

    members_data[str(member.id)] = {

        "joined": utcnow().isoformat(),

        "last_activity": utcnow().isoformat(),

        "intro": False,

        "birth_year": None,

        "gender": None
    }

    save_data()

    print(
        f"[입장] "
        f"{member} ({member.id})"
    )

    try:

        roles = await ensure_roles(
            member.guild
        )

        unverified = roles.get(
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

    intro_channel = find_intro_channel(
        member.guild
    )

    if intro_channel:

        try:

            await intro_channel.send(
                f"{member.mention} "
                f"환영합니다! 👋\n\n"
                f"**3일 이내에 자기소개를 작성해주세요.**\n"
                f"예시: `04남`, `04 여`, `04ㄴ`, `04 ㅇ`\n\n"
                f"채팅이나 음성채널 활동도 자유롭게 해주세요.\n\n"
                f"⚠️ 자기소개도 없고 "
                f"3일간 활동도 없으면 "
                f"자동 퇴장 처리됩니다."
            )

        except discord.Forbidden:

            print(
                "[환영 메시지 전송 실패]"
            )


# ------------------------------------------------------------
# AI 수다
# ------------------------------------------------------------

def chat_enabled(guild_id):

    return bool(
        chat_settings.get(
            str(guild_id),
            False
        )
    )


def should_ai_chat(message):

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

    if (
        bot.user
        and bot.user in message.mentions
    ):
        return True

    lowered = content.lower()

    if lowered.startswith("봇아"):
        return True

    if re.match(
        r"^봇[\s,!?]",
        content
    ):
        return True

    if chat_enabled(
        message.guild.id
    ):

        if CHAT_CHANNEL_KEYWORD in message.channel.name:
            return True

    return False


def clean_bot_mention(text):

    if bot.user:

        text = text.replace(
            f"<@{bot.user.id}>",
            ""
        )

        text = text.replace(
            f"<@!{bot.user.id}>",
            ""
        )

    return text.strip()


async def generate_ai_reply(message):

    if ai_client is None:

        print("[AI 오류] OPENAI_API_KEY가 없습니다.")

        return (
            "AI 수다 기능이 아직 설정 안 됐어 ㅋㅋ\n"
            "Railway Variables의 "
            "`OPENAI_API_KEY`를 확인해줘!"
        )

    user_text = clean_bot_mention(
        message.content
    )

    if not user_text:
        user_text = "안녕!"

    channel_key = (
        message.guild.id,
        message.channel.id
    )

    history = list(
        chat_history[channel_key]
    )

    input_messages = []

    for item in history:
        input_messages.append(item)

    input_messages.append({

        "role": "user",

        "content":
            f"{message.author.display_name}: "
            f"{user_text}"
    })

    try:

        print(
            f"[AI 요청] "
            f"모델={OPENAI_MODEL} "
            f"사용자={message.author} "
            f"내용={user_text[:100]}"
        )

        response = await ai_client.responses.create(

            model=OPENAI_MODEL,

            instructions=AI_SYSTEM_PROMPT,

            input=input_messages,

            max_output_tokens=500
        )

        answer = (
            response.output_text or ""
        ).strip()

        if not answer:

            print(
                "[AI 오류] 응답 내용이 비어 있습니다."
            )

            return (
                "어... 갑자기 할 말이 "
                "생각 안 났다 ㅋㅋ"
            )

        chat_history[channel_key].append({

            "role": "user",

            "content":
                f"{message.author.display_name}: "
                f"{user_text}"
        })

        chat_history[channel_key].append({

            "role": "assistant",

            "content": answer
        })

        if len(answer) > MAX_AI_REPLY_LENGTH:

            answer = (
                answer[
                    :MAX_AI_REPLY_LENGTH - 3
                ]
                + "..."
            )

        print("[AI 성공] 답변 생성 완료")

        return answer

    except Exception as e:

        # ----------------------------------------------------
        # 중요:
        # 기존처럼 오류를 숨기지 않고 Railway 로그에
        # 실제 오류 내용을 표시함
        # ----------------------------------------------------

        print("=" * 60)
        print("[AI 오류 발생]")
        print(f"오류 종류: {type(e).__name__}")
        print(f"오류 내용: {e}")
        print("=" * 60)

        return (
            "AI 연결 중 오류가 발생했어 ㅠㅠ\n"
            "잠시 후 다시 말해줘!"
        )


# ------------------------------------------------------------
# 메시지
# ------------------------------------------------------------

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if isinstance(
        message.author,
        discord.Member
    ):

        member = message.author

        data = ensure_member(
            member
        )

        data["last_activity"] = (
            utcnow().isoformat()
        )

        # ----------------------------------------------------
        # 자기소개
        # ----------------------------------------------------

        if isinstance(
            message.channel,
            discord.TextChannel
        ):

            if INTRO_KEYWORD in message.channel.name:

                intro_text = (
                    message.content.strip()
                )

                parsed = parse_intro(
                    intro_text
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

                    role_success = (
                        await apply_intro_roles(
                            member,
                            parsed["birth_year"],
                            parsed["gender"]
                        )
                    )

                    gender_text = (
                        "남자"
                        if parsed["gender"] == "male"
                        else "여자"
                    )

                    age_text = (
                        "성인"
                        if is_adult_from_birth_year(
                            parsed["birth_year"]
                        )
                        else "미자"
                    )

                    print(
                        f"[자기소개 완료] "
                        f"{member} -> "
                        f"{parsed['birth_year']} / "
                        f"{gender_text} / "
                        f"{age_text}"
                    )

                    try:

                        await message.add_reaction(
                            "✅"
                        )

                    except discord.HTTPException:

                        pass

                    if role_success:

                        roles = await ensure_roles(
                            member.guild
                        )

                        gender_role = (
                            roles.get("male")
                            if parsed["gender"] == "male"
                            else roles.get("female")
                        )

                        age_role = (
                            roles.get("adult")
                            if is_adult_from_birth_year(
                                parsed["birth_year"]
                            )
                            else roles.get("minor")
                        )

                        role_mentions = []

                        if gender_role:
                            role_mentions.append(
                                gender_role.mention
                            )

                        if age_role:
                            role_mentions.append(
                                age_role.mention
                            )

                        role_text = (
                            " / ".join(role_mentions)
                            if role_mentions
                            else "역할을 찾을 수 없음"
                        )

                        try:

                            await message.channel.send(
                                f"{member.mention} "
                                f"자기소개 확인했어! [✅]\n"
                                f"역할 지급 완료: "
                                f"{role_text}"
                            )

                        except discord.HTTPException:
                            pass

                save_data()

            else:

                save_data()

        # ----------------------------------------------------
        # AI 수다
        # ----------------------------------------------------

        if should_ai_chat(message):

            async with message.channel.typing():

                answer = (
                    await generate_ai_reply(
                        message
                    )
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


# ------------------------------------------------------------
# 음성 활동
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# 자동 추방
# ------------------------------------------------------------

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

            except (
                KeyError,
                ValueError,
                TypeError
            ):

                continue

            if (
                current - joined
                < timedelta(days=GRACE_DAYS)
            ):
                continue

            if data.get(
                "intro",
                False
            ):
                continue

            if (
                current - last_activity
                < timedelta(days=GRACE_DAYS)
            ):
                continue

            try:

                log_channel = (
                    find_log_channel(guild)
                )

                if log_channel:

                    embed = discord.Embed(

                        title="🚪 자동 추방",

                        description=(
                            f"{member.mention} 님이 "
                            f"**자기소개 미작성 + "
                            f"장기 미활동**으로 "
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

                    embed.add_field(

                        name="사유",

                        value=(
                            "가입 후 3일 경과 / "
                            "자기소개 없음 / "
                            "3일간 활동 없음"
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

                save_data()

            except discord.Forbidden:

                print(
                    f"[추방 권한 오류] "
                    f"{member}"
                )

            except Exception as e:

                print(
                    f"[추방 오류] "
                    f"{member}: {e}"
                )


# ------------------------------------------------------------
# 검사 시작
# ------------------------------------------------------------

@check_members.before_loop
async def before_check_members():

    await bot.wait_until_ready()


# ------------------------------------------------------------
# !상태
# ------------------------------------------------------------

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
            "📌 이 사용자의 기록이 없습니다."
        )

        return

    intro = (
        "✅ 작성 완료"
        if data.get("intro", False)
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
        f"연령 역할: {age_text}\n"
        f"최근 활동: {last_text}"
    )


# ------------------------------------------------------------
# !검사
# ------------------------------------------------------------

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

                last_activity = (
                    datetime.fromisoformat(
                        data["last_activity"]
                    )
                )

            except Exception:

                continue

            if (
                current - joined
                < timedelta(days=GRACE_DAYS)
            ):
                continue

            if data.get(
                "intro",
                False
            ):
                continue

            if (
                current - last_activity
                < timedelta(days=GRACE_DAYS)
            ):
                continue

            count += 1

    await ctx.send(
        f"🔍 현재 자동 추방 조건에 "
        f"해당하는 멤버: **{count}명**"
    )


# ------------------------------------------------------------
# !자기소개초기화
# ------------------------------------------------------------

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

        roles = await ensure_roles(
            member.guild
        )

        remove_roles = []

        for role_type in [
            "male",
            "female",
            "adult",
            "minor"
        ]:

            role = roles.get(
                role_type
            )

            if role and role in member.roles:

                remove_roles.append(
                    role
                )

        unverified = roles.get(
            "unverified"
        )

        if remove_roles:

            await member.remove_roles(
                *remove_roles,
                reason="자기소개 인증 초기화"
            )

        if (
            unverified
            and unverified not in member.roles
        ):

            await member.add_roles(
                unverified,
                reason="자기소개 인증 초기화"
            )

    except discord.Forbidden:

        await ctx.send(
            "⚠️ 상태는 초기화했지만 "
            "역할 변경 권한이 없어 "
            "역할은 바꾸지 못했어."
        )

        return

    await ctx.send(
        f"🔄 {member.mention}님의 "
        f"자기소개 상태와 인증 역할을 "
        f"초기화했습니다."
    )


# ------------------------------------------------------------
# !대화 켜기 / 끄기
# ------------------------------------------------------------

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
            if chat_enabled(ctx.guild.id)
            else "꺼짐"
        )

        await ctx.send(
            f"💬 메인채팅 자동 대화: **{state}**\n\n"
            f"`!대화 켜기`\n"
            f"`!대화 끄기`"
        )

        return

    setting = setting.lower()

    if setting == "켜기":

        chat_settings[
            str(ctx.guild.id)
        ] = True

        save_chat_settings()

        await ctx.send(
            "💬 **메인채팅 AI 자동 대화 ON!**\n"
            "이제 `＃↝・메인채팅`에서 "
            "사람들이 말하면 나도 대화할게 ㅋㅋ"
        )

    elif setting == "끄기":

        chat_settings[
            str(ctx.guild.id)
        ] = False

        save_chat_settings()

        await ctx.send(
            "💬 **메인채팅 AI 자동 대화 OFF!**\n"
            "`봇아`라고 부르거나 "
            "멘션하면 그래도 답변해."
        )

    else:

        await ctx.send(
            "❌ 사용법:\n"
            "`!대화 켜기`\n"
            "`!대화 끄기`"
        )


# ------------------------------------------------------------
# !대화초기화
# ------------------------------------------------------------

@bot.command(
    name="대화초기화"
)
@commands.has_permissions(
    administrator=True
)
async def reset_chat(ctx):

    channel_key = (
        ctx.guild.id,
        ctx.channel.id
    )

    chat_history.pop(
        channel_key,
        None
    )

    await ctx.send(
        "🧹 이 채널의 AI 대화 기억을 초기화했어."
    )


# ------------------------------------------------------------
# !대화도움
# ------------------------------------------------------------

@bot.command(
    name="대화도움"
)
async def chat_help(ctx):

    await ctx.send(
        "💬 **AI 수다 사용법**\n\n"
        "• `봇아 안녕` → 답변\n"
        "• 봇 멘션 → 답변\n"
        "• 관리자 `!대화 켜기` → 메인채팅 자동 대화\n"
        "• 관리자 `!대화 끄기` → 자동 대화 OFF\n"
        "• 관리자 `!대화초기화` → 현재 채널 기억 초기화"
    )


# ------------------------------------------------------------
# 명령어 오류
# ------------------------------------------------------------

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
            "❌ 이 명령어는 관리자만 사용할 수 있습니다."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 사용법을 확인해주세요."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 멤버를 찾지 못했습니다."
        )

        return

    print(
        f"[명령어 오류] {error}"
    )


# ------------------------------------------------------------
# 로그인
# ------------------------------------------------------------

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
        f"연결된 서버: "
        f"{len(bot.guilds)}개"
    )

    print(
        f"AI 모델: "
        f"{OPENAI_MODEL}"
    )

    if OPENAI_API_KEY:

        print(
            "OpenAI API Key: 확인됨"
        )

    else:

        print(
            "OpenAI API Key: 없음"
        )

    print("=" * 60)

    if not check_members.is_running():

        check_members.start()


# ------------------------------------------------------------
# 실행
# ------------------------------------------------------------

if not TOKEN:

    print(
        "❌ DISCORD_TOKEN을 설정해주세요."
    )

else:

    print(
        "✅ 디스코드 토큰 확인 완료"
    )

    print(
        "🤖 봇을 시작합니다..."
    )

    bot.run(TOKEN)
