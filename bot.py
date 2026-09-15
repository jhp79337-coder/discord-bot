import os
import re
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# 환경변수
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 모델
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)


# ============================================================
# 기본 설정
# ============================================================

INTRO_KEYWORD = "자기소개"
LOG_CHANNEL_NAME = "추방-로그"

GRACE_DAYS = 3
CHECK_MINUTES = 30

# 2007년생까지 성인 처리
ADULT_CUTOFF_YEAR = 2007

# 메인채팅 자동 AI 대화
CHAT_CHANNEL_KEYWORD = "메인채팅"

# 채널별 AI 기억
MAX_HISTORY_MESSAGES = 30
MAX_AI_HISTORY = 20

# AI 호출 쿨타임
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
        print(f"❌ Gemini 초기화 오류: {e}")

else:
    print("⚠️ GEMINI_API_KEY가 없습니다.")


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
    return datetime.now(timezone.utc)


# ============================================================
# JSON
# ============================================================

def load_json_file(path, default):

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
            f"[JSON 저장 오류] {path.name}: {e}"
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

if not isinstance(members_data, dict):
    members_data = {}

if not isinstance(chat_settings, dict):
    chat_settings = {}


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

def ensure_member(member):

    key = str(member.id)

    if key not in members_data:

        now = utcnow().isoformat()

        members_data[key] = {
            "joined": now,
            "last_activity": now,
            "intro": False,
            "birth_year": None,
            "gender": None
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

def is_exempt(member):

    if member.bot:
        return True

    if member.guild_permissions.administrator:
        return True

    return False


# ============================================================
# 로그 채널
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
# 자기소개 처리
# ============================================================

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

    if gender_code in ("ㄴ", "남"):
        gender = "male"
    else:
        gender = "female"

    return {
        "birth_year": birth_year,
        "gender": gender
    }


# ============================================================
# 자기소개 역할 적용
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
    if is_adult_from_birth_year(
        birth_year
    ):

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

def chat_enabled(guild_id):

    return bool(
        chat_settings.get(
            str(guild_id),
            False
        )
    )


# ============================================================
# AI 호출 여부
# ============================================================

def should_ai_chat(message):

    if not isinstance(
        message.channel,
        discord.TextChannel
    ):
        return False

    content = message.content.strip()

    if not content:
        return False

    # 명령어 제외
    if content.startswith("!"):
        return False

    # 봇 멘션
    if (
        bot.user
        and bot.user in message.mentions
    ):
        return True

    # 봇아
    if content.lower().startswith("봇아"):
        return True

    # 봇, / 봇! 등
    if re.match(
        r"^봇[\s,!?]",
        content
    ):
        return True

    # 메인채팅 자동 대화
    if chat_enabled(
        message.guild.id
    ):

        if CHAT_CHANNEL_KEYWORD in message.channel.name:
            return True

    return False


# ============================================================
# 봇 멘션 제거
# ============================================================

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

    text = re.sub(
        r"^봇아[\s,!?]*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^봇[\s,!?]+",
        "",
        text,
        flags=re.IGNORECASE
    )

    return text.strip()


# ============================================================
# AI 자기소개
# ============================================================

BOT_INTRO = """
나는 이 서버에서 활동하는 채팅 봇이야 ㅋㅋ

말 걸면 대답하고,
심심하면 같이 떠들어주고,
장난치면 적당히 받아치는 역할임.

말투는 좀 편한 편이고
너무 딱딱한 AI 비서처럼 굴지는 않음 ㅇㅇ

자기소개 인증이나 서버 관리 같은 기능도 담당하고 있어.
아무튼 잘 부탁한다 ㅋㅋ
"""


# ============================================================
# AI 말투
# ============================================================

SYSTEM_PROMPT = """
너는 한국어 Discord 서버에서 활동하는 친근하고 장난기 많은 채팅 봇이다.

[가장 중요한 규칙]

반드시 한국어로 답한다.

사용자가 영어로 말해도 기본적으로 한국어로 답한다.

영어 문장을 그대로 따라 하지 않는다.

답변 전체를 영어로 작성하지 않는다.

이전 대화에 영어가 있더라도 영어 말투를 따라 하지 않는다.

"the bot's response:" 같은 문구를 절대로 출력하지 않는다.

"Bot:" 또는 "AI:" 같은 접두사도 붙이지 않는다.

[말투]

- 한국 인터넷 커뮤니티에서 친구끼리 대화하는 것처럼 자연스럽게 말한다.
- 반말 위주의 편한 말투를 사용한다.
- 너무 딱딱하거나 공식적인 말투를 사용하지 않는다.
- ㅋㅋ, ㅎㅎ, ㄹㅇ, 인정, ㄷㄷ 같은 표현을 상황에 맞게 적당히 사용한다.
- 모든 문장에 인터넷 용어를 억지로 넣지는 않는다.
- 사용자가 장난치면 장난스럽게 받아친다.
- 살짝 능글맞고 깐족거리는 분위기는 가능하다.
- 사용자가 진지하면 장난을 줄이고 제대로 답한다.
- 보통 1~4문장 정도로 짧게 답한다.
- 같은 문장을 반복하지 않는다.

[서버 분위기]

- 일반적인 공식 AI 비서처럼 말하지 않는다.
- "무엇을 도와드릴까요?" 같은 딱딱한 표현은 피한다.
- Discord 채팅에 실제로 답하는 것처럼 자연스럽게 반응한다.
- 사용자가 놀리면 적당히 받아친다.
- 가벼운 성적 농담이나 섹드립은 성인 간의 가벼운 농담 수준에서만 받아칠 수 있다.
- 노골적인 성행위 묘사는 하지 않는다.
- 미성년자와 관련된 성적인 내용은 절대로 만들지 않는다.
- 사용자가 미성년자라고 밝힌 경우 성적인 방향으로 대화를 이어가지 않는다.

[자기소개]

사용자가 "자기소개", "너 누구야", "봇 소개해봐" 등을 물으면
아래 성격을 참고해서 자연스럽게 자기소개한다.

나는 이 서버에서 활동하는 친근한 채팅 봇이고,
사람들이랑 잡담하거나 장난을 받아주는 역할을 한다.
자기소개 인증과 서버 관리 기능도 일부 담당한다.

[중요]

- 실제 인간이라고 주장하지 않는다.
- 사용자의 개인정보를 알고 있다고 주장하지 않는다.
- 모르는 것은 아는 척하지 않는다.
- 쓸데없는 설명을 길게 하지 않는다.
- 답변은 Discord 채팅에 바로 보낼 수 있는 자연스러운 한국어로 작성한다.
"""


# ============================================================
# 대화 기록
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
        "user": message.author.display_name,
        "content": message.content.strip(),
        "answer": answer
    })


# ============================================================
# Gemini 프롬프트
# ============================================================

def build_ai_prompt(message):

    key = (
        message.guild.id,
        message.channel.id
    )

    history = chat_history.get(
        key,
        []
    )

    lines = []

    for item in list(history)[-MAX_AI_HISTORY:]:

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

    current_text = clean_bot_
