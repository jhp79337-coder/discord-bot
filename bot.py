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

# 3일 미활동
INACTIVE_DAYS = 3

# 검사 주기
CHECK_MINUTES = 1

# 2007년생부터 성인
ADULT_CUTOFF_YEAR = 2007

# AI 채널
ADULT_CHAT_CHANNEL = "＃↝・성인채팅"
ADULT_19_CHANNEL = "＃↝・19금"

# 데이터 파일
MEMBERS_FILE = "members.json"
CHAT_SETTINGS_FILE = "chat_settings.json"


# =========================================================
# 역할 ID
# =========================================================

UNVERIFIED_ROLE_ID = 1544031900295893112
MALE_ROLE_ID = 1544031878812532858
FEMALE_ROLE_ID = 1544031884227518525
ADULT_ROLE_ID = 1544031894809616475
MINOR_ROLE_ID = 1544031889533182043


# =========================================================
# 채널
# =========================================================

ROLE_CHANNEL_ID = 1549631714769244261
MAIN_CHAT_CHANNEL_ID = 1544032267855470644


# =========================================================
# 봇 설정
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
# OpenAI 호환 Gemini
# =========================================================

gemini_client = None

if GEMINI_API_KEY:
    gemini_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


# =========================================================
# 데이터
# =========================================================

members_data = {}
chat_settings = {}
chat_history = {}
ai_cooldowns = {}

# 현재 확인창이 떠 있는 사용자
pending_kick_reviews = set()


# =========================================================
# 시간 함수
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def parse_time(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except Exception:
        return None


# =========================================================
# JSON 저장 / 불러오기
# =========================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[JSON 불러오기 오류] {filename}: {e}")
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
        print(f"[JSON 저장 오류] {filename}: {e}")


members_data = load_json(MEMBERS_FILE, {})
chat_settings = load_json(CHAT_SETTINGS_FILE, {})


# =========================================================
# 회원 데이터
# =========================================================

def get_member_data(member_id):
    member_id = str(member_id)

    if member_id not in members_data:
        members_data[member_id] = {
            "intro_completed": False,
            "birth_year": None,
            "gender": None,
            "last_activity": None,
            "joined_at": None,
            "is_existing_member": True,
            "kick_review_declined_until": None
        }

    return members_data[member_id]


# =========================================================
# 활동 기록
# =========================================================

def update_activity(member):
    if member.bot:
        return

    data = get_member_data(member.id)

    # 자기소개를 완료한 사람만 활동 기록
    if not data.get("intro_completed", False):
        return

    data["last_activity"] = iso_now()

    # 다시 활동하면 추방 확인 제한 초기화
    data["kick_review_declined_until"] = None

    save_json(MEMBERS_FILE, members_data)


# =========================================================
# 역할 적용
# =========================================================

async def apply_member_roles(member, birth_year, gender):
    guild = member.guild

    unverified = guild.get_role(UNVERIFIED_ROLE_ID)
    male = guild.get_role(MALE_ROLE_ID)
    female = guild.get_role(FEMALE_ROLE_ID)
    adult = guild.get_role(ADULT_ROLE_ID)
    minor = guild.get_role(MINOR_ROLE_ID)

    roles_to_add = []
    roles_to_remove = []

    # 인증 역할 제거
    if unverified and unverified in member.roles:
        roles_to_remove.append(unverified)

    # 성별
    if gender == "남":
        if male:
            roles_to_add.append(male)

        if female and female in member.roles:
            roles_to_remove.append(female)

    elif gender == "여":
        if female:
            roles_to_add.append(female)

        if male and male in member.roles:
            roles_to_remove.append(male)

    # 성인 / 미성년
    if birth_year >= ADULT_CUTOFF_YEAR:
        if adult:
            roles_to_add.append(adult)

        if minor and minor in member.roles:
            roles_to_remove.append(minor)

    else:
        if minor:
            roles_to_add.append(minor)

        if adult and adult in member.roles:
            roles_to_remove.append(adult)

    try:
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason="자기소개 인증 역할 정리"
            )

        if roles_to_add:
            await member.add_roles(
                *roles_to_add,
                reason="자기소개 인증"
            )

    except discord.Forbidden:
        print(f"[역할 오류] {member} 역할을 변경할 권한이 없습니다.")

    except Exception as e:
        print(f"[역할 오류] {e}")


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
        title="🚪・추방 로그",
        description="추방 처리가 완료되었습니다.",
        color=discord.Color.red(),
        timestamp=now_utc()
    )

    embed.add_field(
        name="👤 사용자",
        value=f"{member.mention}\n`{member}`\n`{member.id}`",
        inline=False
    )

    embed.add_field(
        name="📋 사유",
        value=reason,
        inline=False
    )

    embed.set_footer(text="JARVIS・추방 로그")

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[추방 로그 오류] {e}")


# =========================================================
# 추방 확인 View
# =========================================================

class KickConfirmView(discord.ui.View):

    def __init__(self, member_id, guild_id):
        super().__init__(timeout=600)

        self.member_id = member_id
        self.guild_id = guild_id
        self.finished = False

    async def interaction_check(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 관리자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="🚪 추방하기",
        style=discord.ButtonStyle.danger
    )
    async def kick_button(self, interaction, button):

        if self.finished:
            await interaction.response.send_message(
                "⚠️ 이미 처리된 요청입니다.",
                ephemeral=True
            )
            return

        guild = bot.get_guild(self.guild_id)

        if not guild:
            await interaction.response.send_message(
                "❌ 서버를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        member = guild.get_member(self.member_id)

        if not member:
            self.finished = True
            pending_kick_reviews.discard(self.member_id)

            await interaction.response.send_message(
                "❌ 해당 사용자가 이미 서버에 없습니다.",
                ephemeral=True
            )
            return

        # 관리자 보호
        if member.guild_permissions.administrator:
            self.finished = True
            pending_kick_reviews.discard(self.member_id)

            await interaction.response.send_message(
                "🛡️ 관리자 계정은 추방할 수 없습니다.",
                ephemeral=True
            )
            return

        # 봇 보호
        if member.bot:
            self.finished = True
            pending_kick_reviews.discard(self.member_id)

            await interaction.response.send_message(
                "🤖 봇 계정은 이 기능으로 추방할 수 없습니다.",
                ephemeral=True
            )
            return

        try:
            reason = "관리자 승인 - 자기소개 완료 후 3일 활동 없음"

            await send_kick_log(member, reason)

            await member.kick(reason=reason)

            self.finished = True
            pending_kick_reviews.discard(self.member_id)

            await interaction.response.edit_message(
                content=(
                    f"✅ **추방 처리 완료**\n\n"
                    f"👤 `{member}`\n"
                    f"관리자 `{interaction.user}`의 승인으로 추방되었습니다."
                ),
                embed=None,
                view=None
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 봇에게 추방 권한이 없거나 역할 순서가 낮습니다.",
                ephemeral=True
            )

        except Exception as e:
            print(f"[추방 오류] {e}")

            await interaction.response.send_message(
                "❌ 추방 처리 중 오류가 발생했습니다.",
                ephemeral=True
            )

    @discord.ui.button(
        label="❌ 취소하기",
        style=discord.ButtonStyle.secondary
    )
    async def cancel_button(self, interaction, button):

        if self.finished:
            await interaction.response.send_message(
                "⚠️ 이미 처리된 요청입니다.",
                ephemeral=True
            )
            return

        self.finished = True

        data = get_member_data(self.member_id)

        # 취소하면 24시간 동안 같은 사람에게 다시 확인창을 띄우지 않음
        data["kick_review_declined_until"] = (
            now_utc() + timedelta(hours=24)
        ).isoformat()

        save_json(MEMBERS_FILE, members_data)

        pending_kick_reviews.discard(self.member_id)

        await interaction.response.edit_message(
            content=(
                "❌ **추방이 취소되었습니다.**\n\n"
                f"관리자 `{interaction.user}`가 추방 요청을 취소했습니다.\n"
                "24시간 동안 같은 추방 확인창이 다시 표시되지 않습니다."
            ),
            embed=None,
            view=None
        )

    async def on_timeout(self):
        pending_kick_reviews.discard(self.member_id)


# =========================================================
# 추방 확인 요청
# =========================================================

async def request_kick_confirmation(member, force=False):

    if member.bot:
        return

    if member.guild_permissions.administrator:
        return

    # 이미 확인창이 떠 있으면 중복 생성하지 않음
    if member.id in pending_kick_reviews:
        return

    data = get_member_data(member.id)

    # 일반 자동 검사에서는 24시간 취소 제한 적용
    if not force:
        declined_until = parse_time(
            data.get("kick_review_declined_until")
        )

        if declined_until:
            if now_utc() < declined_until:
                return

            data["kick_review_declined_until"] = None
            save_json(MEMBERS_FILE, members_data)

    channel = discord.utils.get(
        member.guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if not channel:
        print(f"[오류] {LOG_CHANNEL_NAME} 채널을 찾을 수 없습니다.")
        return

    last_activity = parse_time(
        data.get("last_activity")
    )

    if last_activity:
        last_activity_text = discord.utils.format_dt(
            last_activity,
            style="R"
        )
    else:
        last_activity_text = "기록 없음"

    pending_kick_reviews.add(member.id)

    embed = discord.Embed(
        title="⚠️・추방 확인 필요",
        description=(
            "해당 사용자가 자기소개를 완료한 뒤 "
            f"**{INACTIVE_DAYS}일 동안 활동 기록이 없습니다.**\n\n"
            "⚠️ **JARVIS는 관리자 승인 없이는 절대로 추방하지 않습니다.**\n"
            "아래 버튼을 눌러 처리해주세요."
        ),
        color=discord.Color.orange(),
        timestamp=now_utc()
    )

    embed.add_field(
        name="👤 사용자",
        value=f"{member.mention}\n`{member}`\n`{member.id}`",
        inline=False
    )

    embed.add_field(
        name="🕐 마지막 활동",
        value=last_activity_text,
        inline=True
    )

    embed.add_field(
        name="📅 기준",
        value=f"{INACTIVE_DAYS}일 미활동",
        inline=True
    )

    embed.set_footer(
        text="JARVIS・관리자 확인 필요"
    )

    try:
        await channel.send(
            embed=embed,
            view=KickConfirmView(
                member.id,
                member.guild.id
            )
        )

    except Exception as e:
        pending_kick_reviews.discard(member.id)
        print(f"[추방 확인창 오류] {e}")


# =========================================================
# 3일 미활동 검사
# =========================================================

@tasks.loop(minutes=CHECK_MINUTES)
async def check_members():

    for guild in bot.guilds:

        for member in guild.members:

            if member.bot:
                continue

            # 관리자 제외
            if member.guild_permissions.administrator:
                continue

            member_id = str(member.id)

            # 데이터가 없는 기존 회원은 절대 건드리지 않음
            if member_id not in members_data:
                continue

            data = members_data[member_id]

            # 자기소개 완료자만 검사
            if not data.get("intro_completed", False):
                continue

            last_activity = parse_time(
                data.get("last_activity")
            )

            if not last_activity:
                continue

            inactive_time = now_utc() - last_activity

            if inactive_time >= timedelta(days=INACTIVE_DAYS):

                # 실제 추방은 절대 하지 않음
                # 관리자 확인창만 띄움
                await request_kick_confirmation(member)


@check_members.before_loop
async def before_check_members():
    await bot.wait_until_ready()


# =========================================================
# 봇 준비
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"JARVIS 로그인 완료: {bot.user}")
    print(f"서버 수: {len(bot.guilds)}")
    print("=" * 50)

    if not check_members.is_running():
        check_members.start()


# =========================================================
# 새 멤버 입장
# =========================================================

@bot.event
async def on_member_join(member):

    if member.bot:
        return

    members_data[str(member.id)] = {
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": None,
        "joined_at": iso_now(),
        "is_existing_member": False,
        "kick_review_declined_until": None
    }

    save_json(MEMBERS_FILE, members_data)

    unverified = member.guild.get_role(
        UNVERIFIED_ROLE_ID
    )

    if unverified:

        try:
            await member.add_roles(
                unverified,
                reason="신규 입장 미인증 역할"
            )
        except Exception as e:
            print(f"[신규 역할 오류] {e}")

    try:

        await member.send(
            "👋 서버에 오신 것을 환영합니다!\n\n"
            f"먼저 <#{ROLE_CHANNEL_ID}>에서 "
            "자기소개를 해주세요.\n\n"
            "예시:\n"
            "`04 남`\n"
            "`04 ㅇ`\n\n"
            f"자기소개 후 <#{MAIN_CHAT_CHANNEL_ID}>에서 활동할 수 있습니다."
        )

    except Exception:
        pass


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(content):

    text = content.strip()

    # 00~99 + 남/여/ㄴ/ㅇ
    pattern = r"(?<!\d)(\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)"

    match = re.search(
        pattern,
        text
    )

    if not match:
        return None

    birth_year = int(match.group(1))
    gender_raw = match.group(2)

    if gender_raw in ["남", "ㄴ"]:
        gender = "남"
    else:
        gender = "여"

    # 2자리 연도 -> 2000년대
    birth_year += 2000

    return birth_year, gender


# =========================================================
# 메시지
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    member = message.author

    data = get_member_data(member.id)

    # -----------------------------------------------------
    # 자기소개 처리
    # -----------------------------------------------------

    if INTRO_KEYWORD in message.content:

        parsed = parse_intro(message.content)

        if parsed:

            birth_year, gender = parsed

            data["intro_completed"] = True
            data["birth_year"] = birth_year
            data["gender"] = gender
            data["last_activity"] = iso_now()
            data["kick_review_declined_until"] = None

            save_json(
                MEMBERS_FILE,
                members_data
            )

            await apply_member_roles(
                member,
                birth_year,
                gender
            )

            await message.reply(
                "✅ 자기소개가 완료되었습니다!\n\n"
                f"🎂 출생년도: `{birth_year}`\n"
                f"👤 성별: `{gender}`\n\n"
                "이제 서버 활동 기록이 시작됩니다."
            )

            return

    # -----------------------------------------------------
    # 활동 기록
    # -----------------------------------------------------

    if data.get("intro_completed", False):

        data["last_activity"] = iso_now()

        # 활동하면 추방 확인 취소 상태 초기화
        data["kick_review_declined_until"] = None

        save_json(
            MEMBERS_FILE,
            members_data
        )

    # -----------------------------------------------------
    # AI 채팅
    # -----------------------------------------------------

    await handle_ai_chat(message)

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

    data = get_member_data(member.id)

    if not data.get("intro_completed", False):
        return

    # 음성채널 입장/퇴장/이동
    if before.channel != after.channel:

        data["last_activity"] = iso_now()
        data["kick_review_declined_until"] = None

        save_json(
            MEMBERS_FILE,
            members_data
        )


# =========================================================
# AI 채팅
# =========================================================

async def handle_ai_chat(message):

    if gemini_client is None:
        return

    channel_name = message.channel.name

    is_adult_channel = (
        channel_name == ADULT_CHAT_CHANNEL
        or channel_name == ADULT_19_CHANNEL
    )

    is_main_chat = (
        "메인채팅" in channel_name
        or message.channel.id == MAIN_CHAT_CHANNEL_ID
    )

    # AI 사용 조건
    mentioned = bot.user in message.mentions

    trigger_words = [
        "봇아",
        "자비스야",
        "자비스"
    ]

    triggered_by_word = any(
        word in message.content
        for word in trigger_words
    )

    setting = chat_settings.get(
        str(message.guild.id),
        True
    )

    if not setting:
        return

    if not (
        mentioned
        or triggered_by_word
        or is_adult_channel
        or is_main_chat
    ):
        return

    # 너무 빠른 연속 요청 방지
    cooldown_key = str(message.author.id)

    current_time = datetime.now().timestamp()

    if cooldown_key in ai_cooldowns:

        if current_time - ai_cooldowns[cooldown_key] < 2:
            return

    ai_cooldowns[cooldown_key] = current_time

    content = message.content

    content = content.replace(
        f"<@{bot.user.id}>",
        ""
    )

    for word in trigger_words:
        content = content.replace(word, "")

    content = content.strip()

    if not content:
        content = "안녕"

    # -----------------------------------------------------
    # 성인 채널 AI 안전 규칙
    # -----------------------------------------------------

    if is_adult_channel:

        system_prompt = (
            "너는 디스코드 서버 JARVIS다. "
            "성인 채팅방에서 대화하지만 노골적인 성적 행위 묘사, "
            "포르노식 묘사, 성적 역할극은 하지 않는다. "
            "가벼운 성인 농담과 연애 이야기는 가능하지만 "
            "항상 비노골적으로 답한다. "
            "미성년자와 관련된 성적 내용은 절대 다루지 않는다. "
            "한국어로 자연스럽고 친근하게 대화한다."
        )

    else:

        system_prompt = (
            "너는 디스코드 서버 JARVIS다. "
            "사용자들과 자연스럽고 친근하게 대화한다. "
            "너무 딱딱하지 않게 한국어 반말 위주로 대화한다. "
            "사용자가 질문하면 최대한 도움이 되게 답한다."
        )

    # -----------------------------------------------------
    # 대화 기록
    # -----------------------------------------------------

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)

    history_key = f"{guild_id}:{user_id}"

    if history_key not in chat_history:
        chat_history[history_key] = []

    history = chat_history[history_key]

    history.append({
        "role": "user",
        "content": content
    })

    # 최근 12개만 유지
    history = history[-12:]

    chat_history[history_key] = history

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    messages.extend(history)

    try:

        async with message.channel.typing():

            response = await asyncio.to_thread(
                gemini_client.chat.completions.create,
                model=GEMINI_MODEL,
                messages=messages,
                max_tokens=700
            )

        answer = response.choices[0].message.content

        if not answer:
            return

        answer = answer[:1900]

        history.append({
            "role": "assistant",
            "content": answer
        })

        chat_history[history_key] = history[-12:]

        await message.reply(
            answer,
            mention_author=False
        )

    except Exception as e:

        print(f"[Gemini 오류] {type(e).__name__}: {e}")

        try:
            await message.reply(
                "잠깐 오류났어 😵 조금 있다가 다시 말 걸어줘!",
                mention_author=False
            )
        except:
            pass


# =========================================================
# !상태
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 상태(ctx):

    total = len(ctx.guild.members)

    completed = 0

    for member in ctx.guild.members:

        data = members_data.get(str(member.id))

        if data and data.get("intro_completed"):
            completed += 1

    embed = discord.Embed(
        title="🤖・JARVIS 상태",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👥 서버 인원",
        value=str(total),
        inline=True
    )

    embed.add_field(
        name="✅ 자기소개 완료",
        value=str(completed),
        inline=True
    )

    embed.add_field(
        name="⏱️ 미활동 기준",
        value=f"{INACTIVE_DAYS}일",
        inline=True
    )

    embed.add_field(
        name="🚪 자동 추방",
        value="❌ 없음",
        inline=True
    )

    embed.add_field(
        name="🛡️ 관리자 승인",
        value="필수",
        inline=True
    )

    await ctx.send(embed=embed)


# =========================================================
# !대화 on/off
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 대화(ctx, option=None):

    guild_id = str(ctx.guild.id)

    if option == "on":

        chat_settings[guild_id] = True

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🟢 JARVIS 대화를 켰습니다."
        )

    elif option == "off":

        chat_settings[guild_id] = False

        save_json(
            CHAT_SETTINGS_FILE,
            chat_settings
        )

        await ctx.send(
            "🔴 JARVIS 대화를 껐습니다."
        )

    else:

        current = chat_settings.get(
            guild_id,
            True
        )

        await ctx.send(
            f"현재 JARVIS 대화 기능: "
            f"{'🟢 ON' if current else '🔴 OFF'}\n\n"
            "`!대화 on`\n"
            "`!대화 off`"
        )


# =========================================================
# !기억초기화
# =========================================================

@bot.command()
async def 기억초기화(ctx):

    key = f"{ctx.guild.id}:{ctx.author.id}"

    chat_history.pop(
        key,
        None
    )

    await ctx.send(
        f"🧹 {ctx.author.mention}의 JARVIS 대화 기억을 초기화했어."
    )


# =========================================================
# !검사
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 검사(ctx, member: discord.Member):

    data = get_member_data(member.id)

    intro = data.get(
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

    embed = discord.Embed(
        title="🔎・회원 검사",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👤 사용자",
        value=f"{member.mention}\n`{member}`",
        inline=False
    )

    embed.add_field(
        name="📝 자기소개",
        value="완료" if intro else "미완료",
        inline=True
    )

    embed.add_field(
        name="🎂 출생년도",
        value=str(birth_year) if birth_year else "-",
        inline=True
    )

    embed.add_field(
        name="👤 성별",
        value=gender or "-",
        inline=True
    )

    if last_activity:

        dt = parse_time(last_activity)

        activity_text = (
            discord.utils.format_dt(
                dt,
                style="R"
            )
            if dt
            else "-"
        )

    else:
        activity_text = "기록 없음"

    embed.add_field(
        name="🕐 최근 활동",
        value=activity_text,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# !자기소개초기화
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 자기소개초기화(
    ctx,
    member: discord.Member
):

    data = get_member_data(member.id)

    data["intro_completed"] = False
    data["birth_year"] = None
    data["gender"] = None
    data["last_activity"] = None
    data["kick_review_declined_until"] = None

    save_json(
        MEMBERS_FILE,
        members_data
    )

    await ctx.send(
        f"🔄 {member.mention}의 자기소개 정보를 초기화했습니다."
    )


# =========================================================
# !추방로그테스트
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 추방로그테스트(ctx):

    channel = discord.utils.get(
        ctx.guild.text_channels,
        name=LOG_CHANNEL_NAME
    )

    if not channel:

        await ctx.send(
            f"❌ `{LOG_CHANNEL_NAME}` 채널을 찾을 수 없습니다."
        )

        return

    embed = discord.Embed(
        title="🧪・추방 로그 테스트",
        description="추방 없이 로그 표시만 테스트했습니다.",
        color=discord.Color.blurple(),
        timestamp=now_utc()
    )

    embed.add_field(
        name="👤 테스트 관리자",
        value=(
            f"{ctx.author.mention}\n"
            f"`{ctx.author}`\n"
            f"`{ctx.author.id}`"
        ),
        inline=False
    )

    embed.set_footer(
        text="JARVIS・로그 테스트"
    )

    await channel.send(
        embed=embed
    )

    try:
        await ctx.message.delete()
    except:
        pass


# =========================================================
# !추방확인테스트
#
# 사용법:
# !추방확인테스트 @사용자
#
# 실제 3일을 기다리지 않고
# 추방 확인창을 띄움.
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 추방확인테스트(
    ctx,
    member: discord.Member
):

    if member.bot:

        await ctx.send(
            "❌ 봇 계정은 테스트할 수 없습니다."
        )

        return

    if member.guild_permissions.administrator:

        await ctx.send(
            "🛡️ 관리자 계정은 테스트 대상으로 지정할 수 없습니다."
        )

        return

    # 중요:
    # force=True라서 기존 24시간 취소 제한을 무시함.
    await request_kick_confirmation(
        member,
        force=True
    )

    try:
        await ctx.message.delete()
    except:
        pass


# =========================================================
# 오류 처리
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            "❌ 관리자만 사용할 수 있는 명령어입니다."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        if ctx.command:

            if ctx.command.name == "추방확인테스트":

                await ctx.send(
                    "사용법:\n"
                    "`!추방확인테스트 @사용자`"
                )

                return

            if ctx.command.name == "검사":

                await ctx.send(
                    "사용법:\n"
                    "`!검사 @사용자`"
                )

                return

            if ctx.command.name == "자기소개초기화":

                await ctx.send(
                    "사용법:\n"
                    "`!자기소개초기화 @사용자`"
                )

                return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 사용자를 찾을 수 없습니다."
        )

        return

    if isinstance(
        error,
        commands.CommandNotFound
    ):

        return

    print(
        f"[명령어 오류] {type(error).__name__}: {error}"
    )


# =========================================================
# 봇 실행
# =========================================================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN을 설정해주세요."
    )

bot.run(DISCORD_TOKEN)
