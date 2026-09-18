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
# 환경설정
# =========================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# 추방 로그 채널
LOG_CHANNEL_NAME = "🚪・추방로그"

# 자기소개 미작성 기준
INTRO_DEADLINE_DAYS = 30

# 추방 검사 주기
CHECK_MINUTES = 1

# 2007년생까지 성인
ADULT_CUTOFF_YEAR = 2007


# =========================================================
# 채널
# =========================================================

ADULT_CHAT_CHANNEL = "＃↝・성인채팅"
ADULT_19_CHANNEL = "＃↝・19금"

# 역할선택
ROLE_CHANNEL_ID = 1549631714769244261

# 메인채팅
MAIN_CHAT_CHANNEL_ID = 1544032267855470644

# 자기소개 채널
INTRO_CHANNEL_ID = 1547582628369276938

# 서버 ID
GUILD_ID = 1542210983127425158


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
# Discord
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
# Gemini
# =========================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        print("[Gemini] API 연결 준비 완료")
    except Exception as e:
        print(f"[Gemini 연결 오류] {e}")
else:
    print("[Gemini] GEMINI_API_KEY가 없습니다.")


# =========================================================
# 데이터
# =========================================================

members_data = {}
chat_settings = {}
chat_history = {}
ai_cooldowns = {}

# 현재 추방 확인창이 떠 있는 유저
pending_kick_reviews = set()


# =========================================================
# 시간
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
# JSON
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
# 멤버 데이터
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

    match = re.search(pattern, text)

    if not match:
        return None

    birth_year = int(match.group(1))

    gender_raw = match.group(2)

    if gender_raw in ["남", "ㄴ"]:
        gender = "남"
    else:
        gender = "여"

    birth_year += 2000

    return birth_year, gender


# =========================================================
# 나이 구분
# =========================================================

def get_age_type(birth_year):

    if birth_year <= ADULT_CUTOFF_YEAR:
        return "성인"

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
# 역할 지급
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


    # -----------------------------------------------------
    # 역할 존재 확인
    # -----------------------------------------------------

    print(
        f"[ROLE CHECK] "
        f"성인={adult.name if adult else '없음'} "
        f"({ADULT_ROLE_ID}) / "
        f"미성년자={minor.name if minor else '없음'} "
        f"({MINOR_ROLE_ID})"
    )


    # -----------------------------------------------------
    # 미인증 역할 제거
    # -----------------------------------------------------

    if unverified and unverified in member.roles:
        roles_to_remove.append(unverified)


    # -----------------------------------------------------
    # 성별 역할
    # -----------------------------------------------------

    if gender == "남":

        if male and male not in member.roles:
            roles_to_add.append(male)

        if female and female in member.roles:
            roles_to_remove.append(female)

    elif gender == "여":

        if female and female not in member.roles:
            roles_to_add.append(female)

        if male and male in member.roles:
            roles_to_remove.append(male)


    # -----------------------------------------------------
    # 나이 역할
    #
    # 2007년생까지 = 성인
    # 2008년생부터 = 미성년자
    # -----------------------------------------------------

    if birth_year <= ADULT_CUTOFF_YEAR:

        print(
            f"[ROLE] {member} -> 성인 "
            f"({birth_year}년생)"
        )

        if adult and adult not in member.roles:
            roles_to_add.append(adult)

        if minor and minor in member.roles:
            roles_to_remove.append(minor)

    else:

        print(
            f"[ROLE] {member} -> 미성년자 "
            f"({birth_year}년생)"
        )

        if minor and minor not in member.roles:
            roles_to_add.append(minor)

        if adult and adult in member.roles:
            roles_to_remove.append(adult)


    # -----------------------------------------------------
    # 역할 변경
    # -----------------------------------------------------

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

        print(
            f"[ROLE SUCCESS] "
            f"{member} / "
            f"추가={[r.name for r in roles_to_add]} / "
            f"제거={[r.name for r in roles_to_remove]}"
        )

        return True

    except discord.Forbidden:

        print(
            f"[역할 오류] {member} 역할 변경 권한 없음"
        )

        return False

    except Exception as e:

        print(f"[역할 오류] {e}")

        return False


# =========================================================
# 활동 기록
# =========================================================

def update_activity(member):

    data = get_member_data(member.id)

    data["last_activity"] = iso_now()

    save_json(
        MEMBERS_FILE,
        members_data
    )


# =========================================================
# 자기소개 완료 메시지
# =========================================================

async def send_intro_success_message(
    message,
    birth_year,
    gender
):

    age_type = get_age_type(birth_year)
    gender_text = get_gender_text(gender)

    await message.channel.send(

        f"[🖤]・♡・어서 와요 ♡ "
        f"**{message.author.mention}** 님, "
        f"자기소개 확인했어 ♡\n\n"

        f"`{birth_year}년생` · "
        f"`{gender_text}` · "
        f"`{age_type}`\n\n"

        f"[🎀・역할선택]"
        f"(https://discord.com/channels/"
        f"{GUILD_ID}/"
        f"{ROLE_CHANNEL_ID}) "
        f"에서 역할을 골라주세요.\n"

        f"[💬・메인채팅]"
        f"(https://discord.com/channels/"
        f"{GUILD_ID}/"
        f"{MAIN_CHAT_CHANNEL_ID}) "
        f"에서 편하게 놀아요 ♡\n\n"

        f"╭・────────────・╮\n"
        f"　　♡ 자기소개 인증 완료 ♡\n"
        f"　　역할 지급까지 완료됐어요 🎀\n"
        f"╰・────────────・╯"
    )


# =========================================================
# 추방 로그 채널
# =========================================================

def get_log_channel(guild):

    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )


# =========================================================
# 추방 확인 View
# =========================================================

class KickConfirmView(discord.ui.View):

    def __init__(self, member):

        super().__init__(
            timeout=86400
        )

        self.member = member


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
                "❌ 추방 권한이 없습니다.",
                ephemeral=True
            )

            return


        member = self.member

        if member.id not in pending_kick_reviews:

            await interaction.response.send_message(
                "이미 처리된 사용자입니다.",
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

            await interaction.response.send_message(
                f"🚪 **{member}** 님을 추방했습니다."
            )

            print(
                f"[KICK] {member} / "
                f"{member.id}"
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ 봇에게 추방 권한이 없거나 역할 순위가 낮습니다.",
                ephemeral=True
            )

        except Exception as e:

            await interaction.response.send_message(
                f"❌ 추방 중 오류가 발생했습니다.\n`{e}`",
                ephemeral=True
            )


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
                "❌ 관리자 권한이 없습니다.",
                ephemeral=True
            )

            return


        member = self.member

        data = get_member_data(
            member.id
        )

        data[
            "kick_review_declined_until"
        ] = (
            now_utc() + timedelta(hours=24)
        ).isoformat()

        save_json(
            MEMBERS_FILE,
            members_data
        )

        pending_kick_reviews.discard(
            member.id
        )

        await interaction.response.send_message(
            f"❌ **{member}** 님의 추방 확인을 취소했습니다.\n"
            f"24시간 동안 다시 확인창이 뜨지 않습니다."
        )


# =========================================================
# 추방 확인창 생성
# =========================================================

async def send_kick_review(member):

    guild = member.guild

    if member.bot:
        return

    if member.guild_permissions.administrator:
        return

    data = get_member_data(member.id)

    if data.get("intro_completed"):
        return

    if member.id in pending_kick_reviews:
        return

    declined_until = parse_time(
        data.get(
            "kick_review_declined_until"
        )
    )

    if declined_until and now_utc() < declined_until:
        return

    joined_at = parse_time(
        data.get("joined_at")
    )

    if not joined_at:
        return

    deadline = joined_at + timedelta(
        days=INTRO_DEADLINE_DAYS
    )

    if now_utc() < deadline:
        return

    channel = get_log_channel(guild)

    if not channel:
        print(
            f"[추방로그 오류] "
            f"{LOG_CHANNEL_NAME} 채널을 찾을 수 없습니다."
        )
        return

    pending_kick_reviews.add(
        member.id
    )

    embed = discord.Embed(
        title="🚪 자기소개 미작성 사용자 확인",
        description=(
            f"**{member.mention}** 님이 "
            f"가입 후 **{INTRO_DEADLINE_DAYS}일**이 지났지만 "
            f"자기소개를 작성하지 않았습니다.\n\n"
            f"관리자가 확인 후 추방 여부를 결정해주세요."
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
        name="📅 가입일",
        value=f"<t:{int(joined_at.timestamp())}:F>",
        inline=False
    )

    await channel.send(
        embed=embed,
        view=KickConfirmView(member)
    )


# =========================================================
# 30일 검사
# =========================================================

@tasks.loop(minutes=CHECK_MINUTES)
async def check_members():

    for guild in bot.guilds:

        for member in guild.members:

            if member.bot:
                continue

            if member.guild_permissions.administrator:
                continue

            data = members_data.get(
                str(member.id)
            )

            # 기존에 기록되지 않은 사람은
            # 자동 추방 대상으로 만들지 않음
            if not data:
                continue

            if data.get("intro_completed"):
                continue

            try:
                await send_kick_review(member)

            except Exception as e:

                print(
                    f"[추방 검사 오류] "
                    f"{member}: {e}"
                )


# =========================================================
# 봇 준비
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)

    print(
        f"[JARVIS] 로그인 완료: "
        f"{bot.user}"
    )

    print(
        f"[JARVIS] 서버 수: "
        f"{len(bot.guilds)}"
    )

    print(
        f"[JARVIS] 성인 기준: "
        f"{ADULT_CUTOFF_YEAR}년생까지"
    )

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

    data = get_member_data(
        member.id
    )

    data["joined_at"] = iso_now()
    data["intro_completed"] = False
    data["is_existing_member"] = False
    data["last_activity"] = iso_now()

    save_json(
        MEMBERS_FILE,
        members_data
    )

    role = member.guild.get_role(
        UNVERIFIED_ROLE_ID
    )

    if role:

        try:

            await member.add_roles(
                role,
                reason="신규 입장 미인증 역할"
            )

        except Exception as e:

            print(
                f"[입장 역할 오류] {e}"
            )


    # DM
    try:

        await member.send(
            "🖤・♡・어서 와요!\n\n"
            "서버 이용을 위해 자기소개를 작성해주세요.\n\n"
            "**예시**\n"
            "`04 남`\n"
            "`04 여`\n"
            "`04 ㄴ`\n"
            "`04 ㅇ`\n\n"
            "자기소개가 완료되면 자동으로 역할이 지급됩니다 ♡"
        )

    except Exception as e:

        print(
            f"[DM 실패] {member}: {e}"
        )


# =========================================================
# 메시지
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return


    member = message.author

    # 활동 기록
    update_activity(member)


    # =====================================================
    # 자기소개 확인
    # =====================================================

    parsed = parse_intro(
        message.content
    )

    if parsed:

        birth_year, gender = parsed

        data = get_member_data(
            member.id
        )

        data["intro_completed"] = True
        data["birth_year"] = birth_year
        data["gender"] = gender
        data["last_activity"] = iso_now()
        data["kick_review_declined_until"] = None

        save_json(
            MEMBERS_FILE,
            members_data
        )


        # 역할 지급
        role_success = await apply_member_roles(
            member,
            birth_year,
            gender
        )


        # 성공 메시지
        await send_intro_success_message(
            message,
            birth_year,
            gender
        )

        return


    # =====================================================
    # AI 대화
    # =====================================================

    await handle_ai_chat(message)


    # =====================================================
    # 명령어
    # =====================================================

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
# AI 채팅 활성화 확인
# =========================================================

def is_chat_enabled(guild_id):

    return chat_settings.get(
        str(guild_id),
        True
    )


# =========================================================
# AI 채팅
# =========================================================

async def handle_ai_chat(message):

    if not gemini_client:
        return

    if not is_chat_enabled(
        message.guild.id
    ):
        return

    content = message.content.strip()

    # 봇 멘션
    mentioned = bot.user in message.mentions

    # 봇아
    called = (
        "봇아" in content
        or "자비스" in content.lower()
    )

    # 메인채팅
    main_channel = (
        message.channel.id
        == MAIN_CHAT_CHANNEL_ID
    )

    # 성인채팅 / 19금
    adult_channel = (
        message.channel.name
        in [
            ADULT_CHAT_CHANNEL,
            ADULT_19_CHANNEL
        ]
    )

    if not (
        mentioned
        or called
        or main_channel
        or adult_channel
    ):
        return


    # -----------------------------------------------------
    # 멘션 제거
    # -----------------------------------------------------

    prompt = content

    if bot.user:

        prompt = prompt.replace(
            bot.user.mention,
            ""
        ).strip()


    if not prompt:
        prompt = "안녕"


    # -----------------------------------------------------
    # 쿨다운
    # -----------------------------------------------------

    user_key = (
        message.guild.id,
        message.author.id
    )

    last_time = ai_cooldowns.get(
        user_key
    )

    if last_time:

        diff = (
            now_utc() - last_time
        ).total_seconds()

        if diff < 2:
            return

    ai_cooldowns[user_key] = now_utc()


    # -----------------------------------------------------
    # 대화 기록
    # -----------------------------------------------------

    history_key = (
        message.guild.id,
        message.channel.id,
        message.author.id
    )

    if history_key not in chat_history:

        chat_history[history_key] = []


    history = chat_history[
        history_key
    ]

    history.append(
        {
            "role": "user",
            "content": prompt
        }
    )

    # 최대 12개
    history = history[-12:]

    chat_history[
        history_key
    ] = history


    # -----------------------------------------------------
    # 시스템 프롬프트
    # -----------------------------------------------------

    system_prompt = """
너는 디스코드 서버의 AI 봇 JARVIS다.

말투:
- 한국어
- 친근하고 자연스럽게
- 너무 길게 답하지 않는다
- 디스코드에서 실제 사람이 대화하는 것처럼 답한다
- 상황에 따라 ♡, ㅋㅋ, ㅎㅎ 같은 표현을 적당히 사용할 수 있다.

중요:
- 사용자가 질문하면 최대한 직접 답한다.
- 모르는 내용은 아는 척하지 않는다.
- 개인정보를 요구하거나 노출하지 않는다.
- 불법행위를 구체적으로 돕지 않는다.
- 성적인 대화가 나오더라도 노골적인 성행위 묘사나 음란물을 생성하지 않는다.
- 미성년자와 관련된 성적 내용은 절대 생성하지 않는다.
- 사용자가 장난스럽게 말하면 적당히 장난스럽게 답한다.
"""


    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    messages.extend(
        history
    )


    # -----------------------------------------------------
    # Gemini 호출
    # -----------------------------------------------------

    try:

        response = await asyncio.to_thread(
            gemini_client.chat.completions.create,
            model=GEMINI_MODEL,
            messages=messages,
            temperature=0.8,
            max_tokens=500
        )

        reply = response.choices[0].message.content

        if not reply:
            return

        reply = reply.strip()

        # Discord 최대 길이
        if len(reply) > 1900:

            reply = (
                reply[:1890]
                + "..."
            )

        await message.channel.send(
            reply
        )


    except Exception as e:

        print(
            f"[Gemini 오류] {type(e).__name__}: {e}"
        )


# =========================================================
# !상태
# =========================================================

@bot.command(name="상태")
async def status_command(ctx):

    data = get_member_data(
        ctx.author.id
    )

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

    last_activity = parse_time(
        data.get(
            "last_activity"
        )
    )


    if birth_year:

        age_type = get_age_type(
            birth_year
        )

        birth_text = (
            f"{birth_year}년생"
        )

    else:

        age_type = "미인증"
        birth_text = "미작성"


    if gender:

        gender_text = get_gender_text(
            gender
        )

    else:

        gender_text = "미작성"


    if last_activity:

        activity_text = (
            f"<t:{int(last_activity.timestamp())}:R>"
        )

    else:

        activity_text = "기록 없음"


    embed = discord.Embed(
        title="🖤 JARVIS 상태",
        color=discord.Color.dark_purple()
    )

    embed.add_field(
        name="🔐 자기소개",
        value=(
            "완료" if intro_completed
            else "미작성"
        ),
        inline=True
    )

    embed.add_field(
        name="🎂 출생년도",
        value=birth_text,
        inline=True
    )

    embed.add_field(
        name="👤 성별",
        value=gender_text,
        inline=True
    )

    embed.add_field(
        name="🔐 구분",
        value=age_type,
        inline=True
    )

    embed.add_field(
        name="💬 최근 활동",
        value=activity_text,
        inline=True
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# !검사
# =========================================================

@bot.command(name="검사")
async def inspect_member(
    ctx,
    member: discord.Member = None
):

    if not (
        ctx.author.guild_permissions.manage_guild
        or ctx.author.guild_permissions.kick_members
    ):

        await ctx.send(
            "❌ 관리자 권한이 필요합니다."
        )

        return


    if member is None:

        member = ctx.author


    data = get_member_data(
        member.id
    )

    birth_year = data.get(
        "birth_year"
    )

    gender = data.get(
        "gender"
    )

    intro_completed = data.get(
        "intro_completed",
        False
    )


    if birth_year:

        age_type = get_age_type(
            birth_year
        )

    else:

        age_type = "미인증"


    embed = discord.Embed(
        title="🔎 사용자 검사",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👤 사용자",
        value=f"{member.mention}",
        inline=False
    )

    embed.add_field(
        name="📝 자기소개",
        value=(
            "완료" if intro_completed
            else "미작성"
        ),
        inline=True
    )

    embed.add_field(
        name="🎂 출생년도",
        value=(
            str(birth_year)
            if birth_year
            else "미작성"
        ),
        inline=True
    )

    embed.add_field(
        name="👤 성별",
        value=(
            get_gender_text(gender)
            if gender
            else "미작성"
        ),
        inline=True
    )

    embed.add_field(
        name="🔐 구분",
        value=age_type,
        inline=True
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# !자기소개초기화
# =========================================================

@bot.command(name="자기소개초기화")
async def reset_intro(
    ctx,
    member: discord.Member = None
):

    if not ctx.author.guild_permissions.administrator:

        await ctx.send(
            "❌ 서버 관리자만 사용할 수 있습니다."
        )

        return


    if member is None:

        member = ctx.author


    data = get_member_data(
        member.id
    )

    data["intro_completed"] = False
    data["birth_year"] = None
    data["gender"] = None
    data["kick_review_declined_until"] = None

    save_json(
        MEMBERS_FILE,
        members_data
    )


    # 인증 역할 제거
    roles = []

    for role_id in [
        MALE_ROLE_ID,
        FEMALE_ROLE_ID,
        ADULT_ROLE_ID,
        MINOR_ROLE_ID
    ]:

        role = ctx.guild.get_role(
            role_id
        )

        if role and role in member.roles:

            roles.append(role)


    if roles:

        try:

            await member.remove_roles(
                *roles,
                reason="자기소개 초기화"
            )

        except Exception as e:

            print(
                f"[초기화 역할 제거 오류] {e}"
            )


    # 미인증 역할 추가
    unverified = ctx.guild.get_role(
        UNVERIFIED_ROLE_ID
    )

    if unverified:

        try:

            await member.add_roles(
                unverified,
                reason="자기소개 초기화"
            )

        except Exception as e:

            print(
                f"[미인증 역할 추가 오류] {e}"
            )


    await ctx.send(
        f"🔄 {member.mention} 님의 자기소개 정보를 초기화했습니다."
    )


# =========================================================
# !대화 on/off
# =========================================================

@bot.command(name="대화")
async def chat_toggle(
    ctx,
    option: str = None
):

    if not ctx.author.guild_permissions.administrator:

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    guild_id = str(
        ctx.guild.id
    )


    if option not in [
        "on",
        "off"
    ]:

        current = is_chat_enabled(
            ctx.guild.id
        )

        await ctx.send(
            f"현재 AI 대화 상태: "
            f"`{'ON' if current else 'OFF'}`\n\n"
            f"`!대화 on`\n"
            f"`!대화 off`"
        )

        return


    chat_settings[
        guild_id
    ] = option == "on"

    save_json(
        CHAT_SETTINGS_FILE,
        chat_settings
    )


    if option == "on":

        await ctx.send(
            "🤖・JARVIS AI 대화를 **ON** 했습니다."
        )

    else:

        await ctx.send(
            "🤖・JARVIS AI 대화를 **OFF** 했습니다."
        )


# =========================================================
# !기억초기화
# =========================================================

@bot.command(name="기억초기화")
async def reset_memory(ctx):

    removed = 0

    keys = list(
        chat_history.keys()
    )

    for key in keys:

        if (
            key[0] == ctx.guild.id
            and key[2] == ctx.author.id
        ):

            del chat_history[key]
            removed += 1


    await ctx.send(
        f"🧠・대화 기억을 초기화했습니다.\n"
        f"삭제된 기록: `{removed}`개"
    )


# =========================================================
# !추방로그테스트
# =========================================================

@bot.command(name="추방로그테스트")
async def kick_log_test(ctx):

    if not ctx.author.guild_permissions.administrator:

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    channel = get_log_channel(
        ctx.guild
    )

    if not channel:

        await ctx.send(
            f"❌ `{LOG_CHANNEL_NAME}` 채널을 찾을 수 없습니다."
        )

        return


    embed = discord.Embed(
        title="🚪 추방 로그 테스트",
        description=(
            "JARVIS 추방 로그 채널이 정상적으로 연결되어 있습니다."
        ),
        color=discord.Color.orange()
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

@bot.command(name="추방확인테스트")
async def kick_confirm_test(
    ctx,
    member: discord.Member = None
):

    if not ctx.author.guild_permissions.administrator:

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    if member is None:

        await ctx.send(
            "사용법: `!추방확인테스트 @사용자`"
        )

        return


    channel = get_log_channel(
        ctx.guild
    )

    if not channel:

        await ctx.send(
            f"❌ `{LOG_CHANNEL_NAME}` 채널을 찾을 수 없습니다."
        )

        return


    pending_kick_reviews.add(
        member.id
    )


    embed = discord.Embed(
        title="🚪 추방 확인 테스트",
        description=(
            f"**{member.mention}** 님을 "
            f"추방할지 확인해주세요."
        ),
        color=discord.Color.red()
    )


    await channel.send(
        embed=embed,
        view=KickConfirmView(member)
    )


    await ctx.send(
        "✅ 추방 확인 테스트를 보냈습니다."
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
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 해당 사용자를 찾을 수 없습니다."
        )

        return


    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 필요한 인수가 빠졌습니다."
        )

        return


    print(
        f"[명령어 오류] {type(error).__name__}: {error}"
    )


# =========================================================
# 실행
# =========================================================

if not DISCORD_TOKEN:

    print(
        "[ERROR] DISCORD_TOKEN이 설정되지 않았습니다."
    )

else:

    bot.run(
        DISCORD_TOKEN
    )
