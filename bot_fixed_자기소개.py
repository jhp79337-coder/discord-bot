import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, deque
import json
import os
import re
import random
from difflib import SequenceMatcher
from dotenv import load_dotenv

# ============================================================
# 새벽에너를기다리는중 자동관리봇
#
# 기능
# ------------------------------------------------------------
# 1. 신규 멤버 미인증 역할 지급
# 2. 자기소개 자동 인식
# 3. 남자 / 여자 역할 자동 지급
# 4. 성인 / 미자 역할 자동 지급
# 5. 자기소개 미작성 + 장기 미활동 자동 추방
# 6. 로컬 학습형 자동 대화
# 7. 자동학습
#
# Gemini / OpenAI 등 외부 AI API 사용 안 함
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# ============================================================
# 기본 설정
# ============================================================

INTRO_KEYWORD = "자기소개"
LOG_CHANNEL_NAME = "추방-로그"

GRACE_DAYS = 3
CHECK_MINUTES = 30

# 2007년생까지 성인 처리
ADULT_CUTOFF_YEAR = 2007

# 자동 대화 채널 이름
CHAT_CHANNEL_KEYWORD = "메인채팅"

# 최근 대화 기억
MAX_HISTORY_MESSAGES = 30

# 자동학습 파일
AUTO_LEARNING_FILE = Path(__file__).parent / "auto_learning.json"

# 관리자 학습 파일
LEARNING_FILE = Path(__file__).parent / "learning_data.json"

# 회원 데이터
DATA_FILE = Path(__file__).parent / "members.json"

# 대화 설정
CHAT_SETTINGS_FILE = Path(__file__).parent / "chat_settings.json"

# 학습 매칭 최소 유사도
MATCH_THRESHOLD = 0.55

# ============================================================
# Discord 역할 ID
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
# 데이터
# ============================================================

members_data = {}
chat_settings = {}
learning_data = []
auto_learning_data = {}
auto_learning_settings = {}

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

learning_data = load_json_file(
    LEARNING_FILE,
    []
)

auto_learning_data = load_json_file(
    AUTO_LEARNING_FILE,
    {}
)

# ============================================================
# 데이터 안전 처리
# ============================================================

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

if not isinstance(
    learning_data,
    list
):
    learning_data = {}

if not isinstance(
    learning_data,
    list
):
    learning_data = []

if not isinstance(
    auto_learning_data,
    dict
):
    auto_learning_data = {}

# ============================================================
# 저장 함수
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


def save_learning_data():

    save_json_file(
        LEARNING_FILE,
        learning_data
    )


def save_auto_learning_data():

    save_json_file(
        AUTO_LEARNING_FILE,
        auto_learning_data
    )


# ============================================================
# 멤버 기록
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
# 채널
# ============================================================

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


# ============================================================
# 역할
# ============================================================

async def ensure_roles(guild):

    roles = {}

    for role_type, role_id in ROLE_IDS.items():

        role = guild.get_role(
            role_id
        )

        if role:

            roles[role_type] = role

        else:

            print(
                f"[역할 없음] "
                f"{role_type} / {role_id}"
            )

    return roles


# ============================================================
# 자기소개
# ============================================================

def convert_birth_year(two_digit):

    if 0 <= two_digit <= 26:

        return 2000 + two_digit

    return 1900 + two_digit


def is_adult_from_birth_year(
    birth_year
):

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


# ============================================================
# 역할 적용
# ============================================================

async def apply_intro_roles(
    member,
    birth_year,
    gender
):

    roles = await ensure_roles(
        member.guild
    )

    unverified = roles.get(
        "unverified"
    )

    male = roles.get(
        "male"
    )

    female = roles.get(
        "female"
    )

    adult = roles.get(
        "adult"
    )

    minor = roles.get(
        "minor"
    )

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


# ============================================================
# 텍스트 정리
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r"<@!?\d+>",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def similarity(a, b):

    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if a in b or b in a:
        return 0.85

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# 관리자 학습
# ============================================================

def learn_response(
    question,
    answer,
    guild_id,
    author_id,
    automatic=False
):

    question = question.strip()
    answer = answer.strip()

    if not question or not answer:
        return False

    best_index = None
    best_score = 0.0

    for index, item in enumerate(
        learning_data
    ):

        if item.get("guild_id") != guild_id:
            continue

        score = similarity(
            question,
            item.get(
                "question",
                ""
            )
        )

        if score > best_score:

            best_score = score
            best_index = index

    if (
        best_index is not None
        and best_score >= 0.90
    ):

        learning_data[
            best_index
        ]["answer"] = answer

        learning_data[
            best_index
        ]["updated_at"] = utcnow().isoformat()

        learning_data[
            best_index
        ]["automatic"] = automatic

        save_learning_data()

        return True

    learning_data.append({

        "question":
            question,

        "answer":
            answer,

        "guild_id":
            guild_id,

        "author_id":
            author_id,

        "automatic":
            automatic,

        "created_at":
            utcnow().isoformat(),

        "updated_at":
            utcnow().isoformat()
    })

    save_learning_data()

    return True


def find_learned_answer(
    question,
    guild_id
):

    best_item = None
    best_score = 0.0

    for item in learning_data:

        if item.get("guild_id") != guild_id:
            continue

        score = similarity(
            question,
            item.get(
                "question",
                ""
            )
        )

        if score > best_score:

            best_score = score
            best_item = item

    if (
        best_item
        and best_score >= MATCH_THRESHOLD
    ):

        return (
            best_item.get(
                "answer",
                ""
            ),
            best_score
        )

    return None, best_score


# ============================================================
# 자동학습
# ============================================================

def auto_learning_enabled(
    guild_id
):

    return bool(
        auto_learning_settings.get(
            str(guild_id),
            False
        )
    )


def chat_enabled(
    guild_id
):

    return bool(
        chat_settings.get(
            str(guild_id),
            False
        )
    )


def get_guild_auto_data(
    guild_id
):

    key = str(guild_id)

    if key not in auto_learning_data:

        auto_learning_data[key] = {
            "phrases": {},
            "topics": {},
            "users": {}
        }

    data = auto_learning_data[key]

    data.setdefault(
        "phrases",
        {}
    )

    data.setdefault(
        "topics",
        {}
    )

    data.setdefault(
        "users",
        {}
    )

    return data


def save_auto_guild_data(
    guild_id
):

    save_auto_learning_data()


# ============================================================
# 자동학습 - 문장 분류
# ============================================================

def detect_topic(text):

    text = normalize_text(
        text
    )

    topic_words = {

        "food": [
            "밥",
            "먹었",
            "먹어",
            "음식",
            "치킨",
            "피자",
            "햄버거",
            "라면",
            "떡볶이",
            "김치",
            "고기",
            "국밥",
            "초밥",
            "파스타"
        ],

        "sleep": [
            "잤",
            "잠",
            "자고",
            "졸려",
            "졸리",
            "수면"
        ],

        "game": [
            "게임",
            "롤",
            "배그",
            "발로",
            "마크",
            "오버워치",
            "게임함"
        ],

        "school": [
            "학교",
            "수업",
            "시험",
            "숙제",
            "공부"
        ],

        "work": [
            "회사",
            "출근",
            "퇴근",
            "일하",
            "업무"
        ],

        "weather": [
            "날씨",
            "비온",
            "비가",
            "눈온",
            "더워",
            "추워"
        ],

        "mood": [
            "행복",
            "행복해",
            "기분",
            "우울",
            "슬퍼",
            "화나",
            "짜증",
            "좋다",
            "좋아"
        ]
    }

    for topic, words in topic_words.items():

        for word in words:

            if word in text:
                return topic

    return None


def looks_like_statement(
    text
):

    text = normalize_text(
        text
    )

    if not text:
        return False

    if len(text) < 3:
        return False

    if "?" in text:
        return False

    question_words = [
        "뭐야",
        "뭐임",
        "뭔데",
        "어떻게",
        "어디",
        "언제",
        "누구",
        "왜",
        "몇",
        "알려줘",
        "알려 줘",
        "뜻",
        "의미",
        "뭐 먹",
        "뭐했"
    ]

    for word in question_words:

        if word in text:
            return False

    return True


# ============================================================
# 자동학습 데이터 기록
# ============================================================

def learn_auto_message(
    message
):

    if not auto_learning_enabled(
        message.guild.id
    ):
        return

    text = normalize_text(
        message.content
    )

    if not looks_like_statement(
        text
    ):
        return

    data = get_guild_auto_data(
        message.guild.id
    )

    phrases = data["phrases"]

    if text not in phrases:

        phrases[text] = {
            "count": 1,
            "last_user":
                message.author.id,
            "last_seen":
                utcnow().isoformat()
        }

    else:

        phrases[text]["count"] = (
            phrases[text].get(
                "count",
                0
            ) + 1
        )

        phrases[text]["last_seen"] = (
            utcnow().isoformat()
        )

    topic = detect_topic(
        text
    )

    if topic:

        topics = data["topics"]

        if topic not in topics:

            topics[topic] = {
                "count": 0,
                "examples": []
            }

        topics[topic]["count"] = (
            topics[topic].get(
                "count",
                0
            ) + 1
        )

        examples = topics[
            topic
        ].setdefault(
            "examples",
            []
        )

        if text not in examples:

            examples.append(text)

        if len(examples) > 20:

            del examples[:-20]

    users = data["users"]

    user_key = str(
        message.author.id
    )

    if user_key not in users:

        users[user_key] = {
            "name":
                message.author.display_name,
            "messages": 0,
            "topics": {}
        }

    users[user_key][
        "name"
    ] = message.author.display_name

    users[user_key][
        "messages"
    ] = (
        users[user_key].get(
            "messages",
            0
        ) + 1
    )

    if topic:

        user_topics = users[
            user_key
        ].setdefault(
            "topics",
            {}
        )

        user_topics[topic] = (
            user_topics.get(
                topic,
                0
            ) + 1
        )

    save_auto_guild_data(
        message.guild.id
    )


# ============================================================
# 자동학습 반응
# ============================================================

def get_auto_reply(
    message
):

    if not auto_learning_enabled(
        message.guild.id
    ):
        return None

    text = normalize_text(
        message.content
    )

    topic = detect_topic(
        text
    )

    if not topic:
        return None

    data = get_guild_auto_data(
        message.guild.id
    )

    # --------------------------------------------------------
    # 사용자가 반복적으로 이야기한 주제
    # --------------------------------------------------------

    user_key = str(
        message.author.id
    )

    user_data = data[
        "users"
    ].get(
        user_key,
        {}
    )

    user_topics = user_data.get(
        "topics",
        {}
    )

    # --------------------------------------------------------
    # 음식
    # --------------------------------------------------------

    if topic == "food":

        if "뭐 먹었" in text:
            return random.choice([
                "맛있었어? ㅋㅋ",
                "오 뭐 먹었는데?",
                "뭐 먹었어?",
                "오 맛있는 거 먹었나 보네 ㅋㅋ"
            ])

        return random.choice([
            "오 맛있었어? 뭐 먹었어?",
            "뭐 먹었어 ㅋㅋ",
            "오 밥 먹었구나 뭐 먹었는데?",
            "맛있는 거 먹었나 보네 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 수면
    # --------------------------------------------------------

    if topic == "sleep":

        return random.choice([
            "많이 잤어?",
            "어제 늦게 잤어? ㅋㅋ",
            "잠은 좀 잤어?",
            "졸리겠다 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 게임
    # --------------------------------------------------------

    if topic == "game":

        return random.choice([
            "오 무슨 게임 했어?",
            "게임 재밌었어? ㅋㅋ",
            "뭐 하고 있었어?",
            "오 게임 중이었구나 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 학교
    # --------------------------------------------------------

    if topic == "school":

        return random.choice([
            "오늘 학교 어땠어?",
            "시험이나 숙제 있었어?",
            "학교 갔다 왔어?",
            "공부하느라 힘들었겠다 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 회사
    # --------------------------------------------------------

    if topic == "work":

        return random.choice([
            "오늘 일 힘들었어?",
            "퇴근했어?",
            "오늘은 좀 괜찮았어?",
            "고생했네 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 날씨
    # --------------------------------------------------------

    if topic == "weather":

        return random.choice([
            "그러게 오늘 날씨 이상하더라 ㅋㅋ",
            "밖에 많이 추워?",
            "비 많이 와?",
            "날씨 때문에 힘들겠다 ㅋㅋ"
        ])

    # --------------------------------------------------------
    # 기분
    # --------------------------------------------------------

    if topic == "mood":

        if any(
            word in text
            for word in [
                "슬퍼",
                "우울",
                "짜증",
                "화나"
            ]
        ):

            return random.choice([
                "무슨 일 있었어?",
                "왜 무슨 일인데?",
                "괜찮아?",
                "오늘 무슨 일 있었나 보네."
            ])

        return random.choice([
            "오 오늘 기분 좋은가 보네 ㅋㅋ",
            "왜? 좋은 일 있었어?",
            "오 좋네 ㅋㅋ 무슨 일 있어?"
        ])

    return None


# ============================================================
# 최근 대화
# ============================================================

chat_history = defaultdict(
    lambda: deque(
        maxlen=MAX_HISTORY_MESSAGES
    )
)


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
# 질문 판별
# ============================================================

def looks_like_question(
    text
):

    text = text.strip()

    if not text:
        return False

    if len(text) < 2:
        return False

    question_words = [
        "?",
        "뭐야",
        "뭐임",
        "뭔데",
        "어떻게",
        "어디",
        "언제",
        "누구",
        "왜",
        "몇",
        "알려줘",
        "알려 줘",
        "뜻",
        "의미"
    ]

    return any(
        word in text
        for word in question_words
    )


# ============================================================
# 봇 호출 여부
# ============================================================

def should_local_chat(
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

    # 봇 멘션
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

    return text.strip()


# ============================================================
# 로컬 답변
# ============================================================

async def generate_local_reply(
    message
):

    user_text = clean_bot_mention(
        message.content
    )

    if not user_text:
        user_text = "안녕"

    # ========================================================
    # 1. 관리자 학습 데이터
    # ========================================================

    answer, score = find_learned_answer(
        user_text,
        message.guild.id
    )

    if answer:

        print(
            f"[학습 답변] "
            f"유사도={score:.2f}"
        )

        return answer

    # ========================================================
    # 2. 자동학습 반응
    # ========================================================

    auto_reply = get_auto_reply(
        message
    )

    if auto_reply:

        return auto_reply

    # ========================================================
    # 3. 기본 반응
    # ========================================================

    normalized = normalize_text(
        user_text
    )

    if normalized in [
        "안녕",
        "하이",
        "ㅎㅇ",
        "ㅎㅇㅇ"
    ]:

        return random.choice([
            "오 ㅋㅋ 안녕!",
            "안녕 ㅋㅋ",
            "오 왔어? ㅋㅋ",
            "ㅎㅇㅎㅇ ㅋㅋ"
        ])

    if "뭐해" in normalized:

        return "나? 여기서 대기 중이지 ㅋㅋ"

    if "잘자" in normalized:

        return "웅 잘자 ㅋㅋ 좋은 꿈 꿔!"

    if "고마워" in normalized:

        return random.choice([
            "ㅋㅋ 별거 아니지",
            "아냐아냐 ㅋㅋ",
            "웅웅 ㅋㅋ"
        ])

    if "ㅋㅋ" in normalized:

        return random.choice([
            "ㅋㅋㅋㅋ",
            "왜 웃어 ㅋㅋ",
            "ㅋㅋㅋㅋㅋ"
        ])

    if "안녕하세요" in normalized:

        return "안녕하세요 ㅋㅋ"

    if (
        "봇" in normalized
        and (
            "이름" in normalized
            or "누구" in normalized
        )
    ):

        return (
            "내 이름은 아직 정해진 게 없는데 "
            "그냥 봇이라고 불러줘 ㅋㅋ"
        )

    if looks_like_question(
        user_text
    ):

        return (
            "음... 그건 아직 내가 "
            "배운 내용이 없어 ㅋㅋ"
        )

    return random.choice([
        "오 ㅋㅋ",
        "그래서 어떻게 됐어?",
        "오오 ㅋㅋ 계속 말해봐",
        "ㅋㅋ 그렇구나",
        "진짜? ㅋㅋ"
    ])


# ============================================================
# 신규 멤버
# ============================================================

@bot.event
async def on_member_join(
    member
):

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

    save_data()

    print(
        f"[입장] "
        f"{member} ({member.id})"
    )

    # --------------------------------------------------------
    # 미인증 역할만 지급
    #
    # 환영 메시지는 삭제됨
    # --------------------------------------------------------

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
    # 멤버 활동 기록
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

                        if parsed["gender"]
                        == "male"

                        else roles.get(
                            "female"
                        )
                    )

                    age_role = (

                        roles.get("adult")

                        if is_adult_from_birth_year(
                            parsed["birth_year"]
                        )

                        else roles.get(
                            "minor"
                        )
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

                        " / ".join(
                            role_mentions
                        )

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

    # ========================================================
    # 자동학습
    # ========================================================

    if (
        isinstance(
            message.channel,
            discord.TextChannel
        )
        and auto_learning_enabled(
            message.guild.id
        )
        and CHAT_CHANNEL_KEYWORD
        in message.channel.name
    ):

        learn_auto_message(
            message
        )

    # ========================================================
    # 로컬 수다
    # ========================================================

    if should_local_chat(
        message
    ):

        async with message.channel.typing():

            answer = (
                await generate_local_reply(
                    message
                )
            )

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
                f"[답변 전송 오류] {e}"
            )

    await bot.process_commands(
        message
    )


# ============================================================
# !학습시키기
# ============================================================

@bot.command(
    name="학습시키기"
)
@commands.has_permissions(
    administrator=True
)
async def teach(
    ctx,
    *,
    content: str = None
):

    if not content:

        await ctx.send(
            "❌ 사용법:\n"
            "`!학습시키기 질문 | 답변`\n\n"
            "예시:\n"
            "`!학습시키기 봇 이름이 뭐야? | 새벽봇이야!`"
        )

        return

    if "|" not in content:

        await ctx.send(
            "❌ 질문과 답변 사이에 `|`를 넣어줘."
        )

        return

    question, answer = content.split(
        "|",
        1
    )

    question = question.strip()
    answer = answer.strip()

    if not question or not answer:

        await ctx.send(
            "❌ 질문과 답변을 모두 입력해줘."
        )

        return

    if len(question) > 500:

        await ctx.send(
            "❌ 질문이 너무 길어."
        )

        return

    if len(answer) > 1500:

        await ctx.send(
            "❌ 답변이 너무 길어."
        )

        return

    learn_response(
        question,
        answer,
        ctx.guild.id,
        ctx.author.id,
        automatic=False
    )

    await ctx.send(
        "🧠 **학습 완료!**\n"
        f"질문: `{question}`\n"
        f"답변: `{answer}`"
    )


# ============================================================
# !학습목록
# ============================================================

@bot.command(
    name="학습목록"
)
@commands.has_permissions(
    administrator=True
)
async def learning_list(
    ctx
):

    guild_items = [

        item

        for item in learning_data

        if item.get(
            "guild_id"
        ) == ctx.guild.id
    ]

    if not guild_items:

        await ctx.send(
            "🧠 아직 배운 내용이 없어."
        )

        return

    guild_items = guild_items[-20:]

    lines = []

    for index, item in enumerate(
        guild_items,
        start=1
    ):

        question = item.get(
            "question",
            ""
        )

        answer = item.get(
            "answer",
            ""
        )

        lines.append(
            f"**{index}.** "
            f"Q: {question}\n"
            f"A: {answer}"
        )

    text = (
        "🧠 **최근 학습 목록**\n\n"
        + "\n\n".join(lines)
    )

    if len(text) > 1900:

        text = text[:1890] + "..."

    await ctx.send(
        text
    )


# ============================================================
# !학습검색
# ============================================================

@bot.command(
    name="학습검색"
)
@commands.has_permissions(
    administrator=True
)
async def learning_search(
    ctx,
    *,
    question: str = None
):

    if not question:

        await ctx.send(
            "❌ 사용법:\n"
            "`!학습검색 질문`"
        )

        return

    answer, score = find_learned_answer(
        question,
        ctx.guild.id
    )

    if not answer:

        await ctx.send(
            "🔎 비슷한 학습 내용을 찾지 못했어."
        )

        return

    await ctx.send(
        f"🔎 **검색 결과**\n\n"
        f"유사도: `{score:.2f}`\n"
        f"답변: {answer}"
    )


# ============================================================
# !학습삭제
# ============================================================

@bot.command(
    name="학습삭제"
)
@commands.has_permissions(
    administrator=True
)
async def learning_delete(
    ctx,
    number: int = None
):

    if number is None:

        await ctx.send(
            "❌ 사용법:\n"
            "`!학습삭제 번호`"
        )

        return

    guild_items = [

        (
            real_index,
            item
        )

        for real_index, item
        in enumerate(learning_data)

        if item.get(
            "guild_id"
        ) == ctx.guild.id
    ]

    if (
        number < 1
        or number > len(guild_items)
    ):

        await ctx.send(
            "❌ 존재하지 않는 학습 번호야."
        )

        return

    real_index, item = guild_items[
        number - 1
    ]

    removed = learning_data.pop(
        real_index
    )

    save_learning_data()

    await ctx.send(
        "🗑️ **학습 삭제 완료**\n"
        f"질문: `{removed.get('question', '')}`"
    )


# ============================================================
# !학습초기화
# ============================================================

@bot.command(
    name="학습초기화"
)
@commands.has_permissions(
    administrator=True
)
async def learning_reset(
    ctx
):

    global learning_data

    before = len(
        learning_data
    )

    learning_data = [

        item

        for item in learning_data

        if item.get(
            "guild_id"
        ) != ctx.guild.id
    ]

    save_learning_data()

    removed = (
        before
        - len(learning_data)
    )

    await ctx.send(
        f"🧹 이 서버의 학습 내용을 "
        f"**{removed}개** 삭제했어."
    )


# ============================================================
# !자동학습
# ============================================================

@bot.command(
    name="자동학습"
)
@commands.has_permissions(
    administrator=True
)
async def auto_learning(
    ctx,
    setting: str = None
):

    if setting is None:

        state = (

            "켜짐"

            if auto_learning_enabled(
                ctx.guild.id
            )

            else "꺼짐"
        )

        await ctx.send(
            f"🧠 자동학습: **{state}**\n\n"
            "`!자동학습 켜기`\n"
            "`!자동학습 끄기`"
        )

        return

    setting = setting.lower()

    if setting == "켜기":

        auto_learning_settings[
            str(ctx.guild.id)
        ] = True

        save_auto_learning_data()

        # 데이터 구조도 미리 생성
        get_guild_auto_data(
            ctx.guild.id
        )

        save_auto_learning_data()

        await ctx.send(
            "🧠 **자동학습 ON!**\n"
            "이제 메인채팅에서 대화하면서 "
            "자주 나오는 말과 주제를 기억하고 "
            "상황에 맞게 반응할게."
        )

    elif setting == "끄기":

        auto_learning_settings[
            str(ctx.guild.id)
        ] = False

        save_auto_learning_data()

        await ctx.send(
            "🧠 **자동학습 OFF!**"
        )

    else:

        await ctx.send(
            "❌ 사용법:\n"
            "`!자동학습 켜기`\n"
            "`!자동학습 끄기`"
        )


# ============================================================
# !자동학습목록
# ============================================================

@bot.command(
    name="자동학습목록"
)
@commands.has_permissions(
    administrator=True
)
async def auto_learning_list(
    ctx
):

    data = get_guild_auto_data(
        ctx.guild.id
    )

    phrases = data.get(
        "phrases",
        {}
    )

    topics = data.get(
        "topics",
        {}
    )

    lines = []

    lines.append(
        f"🧠 **자동학습 문장:** "
        f"{len(phrases)}개"
    )

    lines.append(
        f"📚 **학습 주제:** "
        f"{len(topics)}개"
    )

    if topics:

        lines.append(
            "\n**주제별 학습량**"
        )

        sorted_topics = sorted(
            topics.items(),
            key=lambda x:
                x[1].get(
                    "count",
                    0
                ),
            reverse=True
        )

        for topic, info in sorted_topics:

            lines.append(
                f"• `{topic}` "
                f"{info.get('count', 0)}회"
            )

    if phrases:

        lines.append(
            "\n**최근 자동학습 문장**"
        )

        recent = list(
            phrases.items()
        )[-15:]

        for phrase, info in recent:

            count = info.get(
                "count",
                0
            )

            lines.append(
                f"• {phrase} "
                f"({count}회)"
            )

    text = "\n".join(
        lines
    )

    if len(text) > 1900:

        text = text[:1890] + "..."

    await ctx.send(
        text
    )


# ============================================================
# !자동학습초기화
# ============================================================

@bot.command(
    name="자동학습초기화"
)
@commands.has_permissions(
    administrator=True
)
async def auto_learning_reset(
    ctx
):

    key = str(
        ctx.guild.id
    )

    auto_learning_data[
        key
    ] = {
        "phrases": {},
        "topics": {},
        "users": {}
    }

    save_auto_learning_data()

    await ctx.send(
        "🧹 **자동학습 데이터를 초기화했어.**"
    )


# ============================================================
# !대화 켜기 / 끄기
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
            "💬 **메인채팅 자동 대화 ON!**\n"
            "이제 메인채팅에서 자연스럽게 "
            "대화에 반응할게 ㅋㅋ"
        )

    elif setting == "끄기":

        chat_settings[
            str(ctx.guild.id)
        ] = False

        save_chat_settings()

        await ctx.send(
            "💬 **메인채팅 자동 대화 OFF!**\n"
            "`봇아`라고 부르거나 "
            "멘션하면 그래도 답변해."
        )

    else:

        await ctx.send(
            "❌ 사용법:\n"
            "`!대화 켜기`\n"
            "`!대화 끄기`"
        )


# ============================================================
# !대화초기화
# ============================================================

@bot.command(
    name="대화초기화"
)
@commands.has_permissions(
    administrator=True
)
async def reset_chat(
    ctx
):

    channel_key = (
        ctx.guild.id,
        ctx.channel.id
    )

    chat_history.pop(
        channel_key,
        None
    )

    await ctx.send(
        "🧹 이 채널의 대화 기억을 초기화했어."
    )


# ============================================================
# !대화도움
# ============================================================

@bot.command(
    name="대화도움"
)
async def chat_help(
    ctx
):

    await ctx.send(

        "💬 **로컬 학습형 봇 사용법**\n\n"

        "• `봇아 안녕` → 봇 호출\n"
        "• 봇 멘션 → 봇 호출\n"
        "• 관리자 `!대화 켜기` → 메인채팅 자동 대화\n"
        "• 관리자 `!대화 끄기` → 자동 대화 OFF\n\n"

        "🧠 **수동 학습**\n"
        "• `!학습시키기 질문 | 답변`\n"
        "• `!학습목록`\n"
        "• `!학습검색 질문`\n"
        "• `!학습삭제 번호`\n"
        "• `!학습초기화`\n\n"

        "🤖 **자동학습**\n"
        "• `!자동학습 켜기`\n"
        "• `!자동학습 끄기`\n"
        "• `!자동학습목록`\n"
        "• `!자동학습초기화`"
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
            "📌 이 사용자의 기록이 없습니다."
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
        f"연령 역할: {age_text}\n"
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
        f"🔍 현재 자동 추방 조건에 "
        f"해당하는 멤버: **{count}명**"
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

            if (
                role
                and role in member.roles
            ):

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

            except (
                KeyError,
                ValueError,
                TypeError
            ):

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

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "❌ 명령어의 값을 확인해주세요."
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
        f"연결된 서버: "
        f"{len(bot.guilds)}개"
    )

    print(
        "AI API: 사용하지 않음"
    )

    print(
        f"수동 학습 데이터: "
        f"{len(learning_data)}개"
    )

    print(
        "자동학습 시스템: 준비됨"
    )

    print("=" * 60)

    if not check_members.is_running():

        check_members.start()


# ============================================================
# 실행
# ============================================================

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
