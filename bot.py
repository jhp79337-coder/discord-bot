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

INTRO_KEYWORD = "자기소개"
LOG_CHANNEL_NAME = "🚪・추방로그"

GRACE_DAYS = 3
CHECK_MINUTES = 1
INTRO_GRACE_MINUTES = 10

# 2007년생까지 성인 역할
ADULT_CUTOFF_YEAR = 2007

# =========================================================
# 역할 ID
# =========================================================

UNVERIFIED_ROLE_ID = 1544031900295893112
MALE_ROLE_ID = 1544031878812532858
FEMALE_ROLE_ID = 1544031884227518525
ADULT_ROLE_ID = 1544031894809616475
MINOR_ROLE_ID = 1544031889533182043


# =========================================================
# 파일
# =========================================================

MEMBERS_FILE = "members.json"
CHAT_SETTINGS_FILE = "chat_settings.json"


# =========================================================
# Discord 설정
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================================
# Gemini 설정
# =========================================================

gemini_ready = bool(GEMINI_API_KEY)

if gemini_ready:
    gemini_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
else:
    gemini_client = None


# =========================================================
# 데이터
# =========================================================

members_data = {}
chat_settings = {}
chat_history = {}
ai_cooldowns = {}


def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"[파일 불러오기 오류] {filename}: {e}")
        return default


def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print(f"[파일 저장 오류] {filename}: {e}")


members_data = load_json(MEMBERS_FILE, {})
chat_settings = load_json(CHAT_SETTINGS_FILE, {})


# =========================================================
# 유틸
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def parse_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return now_utc()


def get_member_data(member_id):
    key = str(member_id)

    if key not in members_data:
        members_data[key] = {
            "intro_completed": False,
            "birth_year": None,
            "gender": None,
            "last_activity": iso_now(),
            "joined_at": iso_now()
        }

    return members_data[key]


def update_activity(member):
    key = str(member.id)

    # 새로 가입해서 기록이 만들어진 멤버만 활동을 추적합니다.
    # 기존 멤버에게는 자동 추방용 타이머가 새로 생기지 않습니다.
    if key not in members_data:
        return

    data = members_data[key]
    data["last_activity"] = iso_now()
    save_json(MEMBERS_FILE, members_data)


# =========================================================
# 자기소개 분석
# =========================================================

def parse_intro(content):
    """
    예:
    04 남
    04 여
    04 ㄴ
    04 ㅇ

    2000~2026 → 2000~2026
    그 외 2자리 → 1900 + 숫자
    """

    text = content.strip()

    pattern = re.search(
        r"(?<!\d)(\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)",
        text,
        re.IGNORECASE
    )

    if not pattern:
        return None

    year_number = int(pattern.group(1))
    gender_code = pattern.group(2)

    if year_number <= 26:
        birth_year = 2000 + year_number
    else:
        birth_year = 1900 + year_number

    if gender_code in ["남", "ㄴ"]:
        gender = "male"
    else:
        gender = "female"

    return birth_year, gender


# =========================================================
# 역할 처리
# =========================================================

async def apply_intro_roles(member, birth_year, gender):
    guild = member.guild

    role_ids = [
        UNVERIFIED_ROLE_ID,
        MALE_ROLE_ID,
        FEMALE_ROLE_ID,
        ADULT_ROLE_ID,
        MINOR_ROLE_ID
    ]

    roles = {}

    for role_id in role_ids:
        role = guild.get_role(role_id)

        if role:
            roles[role_id] = role

    remove_roles = []

    for role_id, role in roles.items():
        if role_id != UNVERIFIED_ROLE_ID:
            remove_roles.append(role)

    if remove_roles:
        try:
            await member.remove_roles(*remove_roles)
        except Exception as e:
            print(f"[역할 제거 오류] {member}: {e}")

    # 미인증 역할 제거
    if UNVERIFIED_ROLE_ID in roles:
        try:
            await member.remove_roles(
                roles[UNVERIFIED_ROLE_ID]
            )
        except Exception as e:
            print(f"[미인증 역할 제거 오류] {member}: {e}")

    # 성별 역할
    if gender == "male":
        role = roles.get(MALE_ROLE_ID)

        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"[남자 역할 오류] {e}")

    elif gender == "female":
        role = roles.get(FEMALE_ROLE_ID)

        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"[여자 역할 오류] {e}")

    # 성인 / 미성년
    if birth_year <= ADULT_CUTOFF_YEAR:
        role = roles.get(ADULT_ROLE_ID)

        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"[성인 역할 오류] {e}")
    else:
        role = roles.get(MINOR_ROLE_ID)

        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"[미성년 역할 오류] {e}")


# =========================================================
# 추방 로그
# =========================================================

async def send_kick_log(member, reason):
    channel = discord.utils.get(
        member.guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if not channel:
        return

    embed = discord.Embed(
        title="🚪・멤버 자동 추방",
        description=(
            f"{member.mention} 님이 서버에서 추방되었습니다.\n\n"
            "자기소개 미작성 및 장기간 활동 없음으로 "
            "자동 처리되었습니다."
        ),
        color=discord.Color.red(),
        timestamp=now_utc()
    )

    embed.add_field(
        name="👤 사용자",
        value=f"{member} (`{member.id}`)",
        inline=False
    )

    embed.add_field(
        name="📋 처리 사유",
        value=reason,
        inline=False
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.set_footer(
        text="JARVIS・자동 관리 시스템"
    )

    try:
        await channel.send(embed=embed)

    except Exception as e:
        print(f"[추방 로그 오류] {e}")


# =========================================================
# AI 응답
# =========================================================

SYSTEM_PROMPT = """
너는 디스코드 서버의 AI 비서 '자비스'야.
어벤져스의 JARVIS 같은 분위기의 말투를 사용해.

[말투]
- 차분하고 정중한 존댓말을 사용해.
- 짧고 간결하게 답해. 기본적으로 1~2문장만 말해.
- 똑똑하고 침착한 비서처럼 말하되 너무 딱딱하지 않게 해.
- 필요할 때만 가벼운 위트나 농담을 섞어.
- 'ㅋㅋㅋ', 이모지, 감탄사를 매번 사용하지 마.
- 사용자가 장난을 치면 자연스럽게 받아주되 과하게 수다 떨지 마.
- 사용자가 인사를 하면 짧게 인사해.
- 사용자가 칭찬하면 간단히 감사하고 끝내.
- 사용자가 질문하면 핵심 답부터 말해.

[절대 하지 말 것]
- 한 번의 답변에 여러 질문을 던지지 마.
- 대화가 끝날 만한 상황에서 억지로 새로운 질문을 붙이지 마.
- 저녁 메뉴, 날씨, 기분 등을 이유 없이 먼저 묻지 마.
- 같은 내용을 반복하거나 장황하게 설명하지 마.
- 스스로 '제가 AI라서' 같은 말을 불필요하게 하지 마.

[대화 예시]
사용자: 자비스 안녕
자비스: 안녕하세요. 오늘도 잘 지내고 계시는군요.

사용자: 청설님이 나 환영해줬어
자비스: 청설님께서 따뜻하게 환영해주셨군요. 좋은 시작입니다.

사용자: 나 배고파
자비스: 식사 시간이군요. 무리하지 마시고 챙겨 드세요.

사용자: 자비스 뭐해?
자비스: 대기 중입니다. 필요하신 일이 있다면 말씀하시죠.

사용자: 자비스 나 천재지?
자비스: 판단을 보류하겠습니다. 아직 데이터가 부족하군요.

항상 자연스러운 한국어로 대화하고, 서버의 분위기에 맞춰 행동해.
"""


async def generate_ai_reply(guild_id, channel_id, user_name, content):

    if not gemini_ready or gemini_client is None:
        return "⚠️ 아직 Gemini API 키가 설정되지 않았어요."

    history_key = f"{guild_id}:{channel_id}"

    if history_key not in chat_history:
        chat_history[history_key] = []

    history = chat_history[history_key]

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    for item in history[-20:]:
        messages.append(item)

    messages.append({
        "role": "user",
        "content": f"{user_name}: {content}"
    })

    for attempt in range(3):

        try:
            response = await asyncio.to_thread(
                gemini_client.chat.completions.create,
                model=GEMINI_MODEL,
                messages=messages,
                max_tokens=250,
                temperature=0.7
            )

            reply = response.choices[0].message.content

            if not reply:
                return "음... 지금은 뭐라고 답해야 할지 모르겠어요 😅"

            reply = reply.strip()

            history.append({
                "role": "user",
                "content": f"{user_name}: {content}"
            })

            history.append({
                "role": "assistant",
                "content": reply
            })

            if len(history) > 40:
                chat_history[history_key] = history[-40:]

            return reply[:1900]

        except Exception as e:

            error_text = str(e)

            print(f"[Gemini 오류] {error_text}")

            if (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "high demand" in error_text.lower()
            ):
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue

            return "⚠️ 지금 AI 서버가 잠시 바쁜 것 같아요. 조금 있다가 다시 말해주세요."

    return "⚠️ AI 응답에 실패했어요."


# =========================================================
# AI 대화 여부
# =========================================================

def should_ai_chat(message):

    if not message.guild:
        return False

    content = message.content.strip()

    if bot.user and bot.user.mentioned_in(message):
        return True

    if content.startswith("자비스"):
        return True

    if content.startswith("봇 "):
        return True

    enabled = chat_settings.get(
        str(message.guild.id),
        False
    )

    if enabled and "메인채팅" in message.channel.name:
        return True

    return False


# =========================================================
# 멤버 검사
# =========================================================

@tasks.loop(minutes=CHECK_MINUTES)
async def check_members():

    current_time = now_utc()

    for guild in bot.guilds:

        for member in guild.members:

            if member.bot:
                continue

            # 봇이 기록한 가입 데이터가 없는 기존 멤버는 제외합니다.
            key = str(member.id)
            if key not in members_data:
                continue

            data = members_data[key]

            # 자기소개를 완료한 멤버는 3일 활동 기준으로 검사합니다.
            if data.get("intro_completed"):
                last_activity = parse_datetime(
                    data.get("last_activity", iso_now())
                )

                inactive = (
                    current_time - last_activity
                ) >= timedelta(days=GRACE_DAYS)

                if inactive:
                    try:
                        await send_kick_log(
                            member,
                            "자기소개 완료 후 3일 동안 활동이 없습니다."
                        )

                        await member.kick(
                            reason="자기소개 완료 후 3일 활동 없음"
                        )

                        print(
                            f"[자동 추방] {member} ({member.id})"
                        )

                    except Exception as e:
                        print(
                            f"[자동 추방 실패] {member}: {e}"
                        )

                continue

            # 새로 가입한 멤버는 10분 안에 자기소개를 작성해야 합니다.
            joined_at = parse_datetime(
                data.get("joined_at", iso_now())
            )

            intro_expired = (
                current_time - joined_at
            ) >= timedelta(minutes=INTRO_GRACE_MINUTES)

            if intro_expired:
                try:
                    await send_kick_log(
                        member,
                        "가입 후 10분 동안 자기소개를 작성하지 않았습니다."
                    )

                    await member.kick(
                        reason="가입 후 10분 자기소개 미작성"
                    )

                    print(
                        f"[자동 추방] {member} ({member.id})"
                    )

                except Exception as e:
                    print(
                        f"[자동 추방 실패] {member}: {e}"
                    )


@check_members.before_loop
async def before_check_members():
    await bot.wait_until_ready()


# =========================================================
# 봇 시작
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print("JARVIS ONLINE")
    print(f"봇 이름 : {bot.user}")
    print(f"봇 ID : {bot.user.id}")
    print(f"서버 수 : {len(bot.guilds)}")
    print(f"Gemini 모델 : {GEMINI_MODEL}")

    if gemini_ready:
        print("Gemini AI : ONLINE")
    else:
        print("Gemini AI : API KEY 없음")

    print("=" * 50)

    if not check_members.is_running():
        check_members.start()


# =========================================================
# 서버 입장
# =========================================================

@bot.event
async def on_member_join(member):

    if member.bot:
        return

    data = get_member_data(member.id)

    data["joined_at"] = iso_now()
    data["last_activity"] = iso_now()
    data["intro_completed"] = False

    save_json(MEMBERS_FILE, members_data)

    role = member.guild.get_role(
        UNVERIFIED_ROLE_ID
    )

    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"[미인증 역할 지급 오류] {e}")


# =========================================================
# 메시지
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        await bot.process_commands(message)
        return

    # 활동 기록
    update_activity(message.author)

    # 자기소개 채널 검사
    if INTRO_KEYWORD in message.channel.name:

        parsed = parse_intro(message.content)

        if parsed:

            birth_year, gender = parsed

            data = get_member_data(message.author.id)

            data["intro_completed"] = True
            data["birth_year"] = birth_year
            data["gender"] = gender
            data["last_activity"] = iso_now()

            save_json(
                MEMBERS_FILE,
                members_data
            )

            await apply_intro_roles(
                message.author,
                birth_year,
                gender
            )

            gender_text = (
                "남자"
                if gender == "male"
                else "여자"
            )

            age_type = (
                "성인"
                if birth_year <= ADULT_CUTOFF_YEAR
                else "미성년"
            )

            try:
                embed = discord.Embed(
                    title="🖤・♡・어서 와요",
                    description=(
                        f"♡ {message.author.mention} 님, 자기소개 확인했어 ♡\n\n"
                        f"`{birth_year}년생` · `{gender_text}` · `{age_type}`\n\n"
                        "🎀 <#1549631714769244261> 에서 역할을 골라주세요.\n"
                        "💬 <#1544032267855470644> 에서 편하게 놀아요 ♡"
                    ),
                    color=discord.Color.from_rgb(45, 20, 45),
                    timestamp=now_utc()
                )

                embed.set_thumbnail(
                    url=message.author.display_avatar.url
                )

                embed.set_footer(
                    text="새벽에 너를 기다리는 중 ・ WELCOME"
                )

                await message.reply(embed=embed)

            except Exception as e:
                print(f"[자기소개 답장 오류] {e}")

    # AI 대화
    if should_ai_chat(message):

        now = now_utc()

        last_time = ai_cooldowns.get(
            message.author.id
        )

        if last_time:

            elapsed = (
                now - last_time
            ).total_seconds()

            if elapsed < 3:
                await bot.process_commands(message)
                return

        ai_cooldowns[message.author.id] = now

        content = message.content

        if bot.user:
            content = content.replace(
                f"<@{bot.user.id}>",
                ""
            )

        content = content.strip()

        if content.startswith("자비스"):
            content = content[3:].strip()

        if content.startswith("봇 "):
            content = content[2:].strip()

        if not content:
            content = "안녕"

        async with message.channel.typing():

            reply = await generate_ai_reply(
                message.guild.id,
                message.channel.id,
                message.author.display_name,
                content
            )

        try:
            await message.reply(reply)
        except Exception as e:
            print(f"[AI 답장 오류] {e}")

    await bot.process_commands(message)


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

    if before.channel != after.channel:

        update_activity(member)


# =========================================================
# !상태
# =========================================================

@bot.command(name="상태")
@commands.has_permissions(administrator=True)
async def status_command(ctx):

    data = get_member_data(ctx.author.id)

    intro = (
        "완료"
        if data.get("intro_completed")
        else "미작성"
    )

    last_activity = data.get(
        "last_activity",
        "없음"
    )

    embed = discord.Embed(
        title="🤖 자비스 상태",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="자기소개",
        value=intro,
        inline=True
    )

    embed.add_field(
        name="최근 활동",
        value=last_activity,
        inline=False
    )

    embed.add_field(
        name="Gemini",
        value=(
            "🟢 ONLINE"
            if gemini_ready
            else "🔴 API KEY 없음"
        ),
        inline=True
    )

    await ctx.send(embed=embed)


# =========================================================
# !대화
# =========================================================

@bot.command(name="대화")
@commands.has_permissions(administrator=True)
async def chat_toggle(ctx, value=None):

    guild_id = str(ctx.guild.id)

    if value is None:

        current = chat_settings.get(
            guild_id,
            False
        )

        await ctx.send(
            f"현재 메인채팅 AI 대화: "
            f"{'ON 🟢' if current else 'OFF 🔴'}"
        )

        return

    value = value.lower()

    if value in ["on", "켜", "켜기", "활성화"]:

        chat_settings[guild_id] = True

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🟢 메인채팅 AI 대화를 켰어요."
        )

    elif value in ["off", "꺼", "끄기", "비활성화"]:

        chat_settings[guild_id] = False

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🔴 메인채팅 AI 대화를 껐어요."
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
async def clear_memory(ctx):

    guild_id = str(ctx.guild.id)

    keys = [
        key
        for key in chat_history
        if key.startswith(f"{guild_id}:")
    ]

    for key in keys:
        del chat_history[key]

    await ctx.send(
        "🧹 이 서버의 자비스 대화 기억을 초기화했어요."
    )


# =========================================================
# !검사
# =========================================================

@bot.command(name="검사")
@commands.has_permissions(administrator=True)
async def check_user(ctx, member: discord.Member = None):

    if member is None:
        member = ctx.author

    data = get_member_data(member.id)

    intro = (
        "완료"
        if data.get("intro_completed")
        else "미작성"
    )

    birth_year = data.get(
        "birth_year",
        "없음"
    )

    gender = data.get(
        "gender",
        "없음"
    )

    last_activity = data.get(
        "last_activity",
        "없음"
    )

    embed = discord.Embed(
        title=f"🔎 {member.display_name} 검사",
        color=discord.Color.green()
    )

    embed.add_field(
        name="자기소개",
        value=intro,
        inline=True
    )

    embed.add_field(
        name="출생년도",
        value=str(birth_year),
        inline=True
    )

    embed.add_field(
        name="성별",
        value=str(gender),
        inline=True
    )

    embed.add_field(
        name="최근 활동",
        value=last_activity,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# !자기소개초기화
# =========================================================

@bot.command(name="자기소개초기화")
@commands.has_permissions(administrator=True)
async def reset_intro(
    ctx,
    member: discord.Member = None
):

    if member is None:
        member = ctx.author

    data = get_member_data(member.id)

    data["intro_completed"] = False
    data["birth_year"] = None
    data["gender"] = None
    data["last_activity"] = iso_now()

    save_json(
        MEMBERS_FILE,
        members_data
    )

    await ctx.send(
        f"🔄 {member.mention}님의 자기소개 기록을 초기화했어요."
    )


# =========================================================
# !추방로그테스트
# =========================================================

@bot.command(name="추방로그테스트")
@commands.has_permissions(administrator=True)
async def kick_log_test(ctx):

    await send_kick_log(
        ctx.author,
        "테스트용 추방 로그입니다."
    )

    await ctx.send(
        "✅ 추방 로그 테스트를 보냈어요."
    )


# =========================================================
# 오류 처리
# =========================================================

@bot.event
async def on_command_error(ctx, error):

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
        commands.MemberNotFound
    ):
        await ctx.send(
            "❌ 해당 멤버를 찾을 수 없어요."
        )
        return

    print(f"[명령어 오류] {error}")


# =========================================================
# 토큰 확인
# =========================================================

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN이 설정되지 않았습니다.")
    raise SystemExit(1)


# =========================================================
# 실행
# =========================================================

bot.run(DISCORD_TOKEN)
