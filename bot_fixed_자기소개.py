import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, deque
import json
import os
import re
from difflib import SequenceMatcher

from dotenv import load_dotenv


# ============================================================
# 새벽에너를기다리는중 자동관리봇
#
# 기능
# ------------------------------------------------------------
# 1. 자기소개 자동 인증
# 2. 성별 / 성인 / 미자 역할 자동 지급
# 3. 신규 멤버 관리
# 4. 자기소개 미작성 + 장기 미활동 자동 추방
# 5. 로컬 대화형 봇
# 6. 대화 자동학습
#
# 외부 AI API 사용 안 함
# Gemini 사용 안 함
# OpenAI 사용 안 함
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

ADULT_CUTOFF_YEAR = 2007

CHAT_CHANNEL_KEYWORD = "메인채팅"

MAX_HISTORY_MESSAGES = 20

MATCH_THRESHOLD = 0.55

# 자동학습 최소 길이
MIN_LEARNING_TEXT_LENGTH = 3

# 자동학습 최대 길이
MAX_LEARNING_TEXT_LENGTH = 300

# 같은 사람이 연속으로 말한 경우는 학습하지 않음
LEARNING_MAX_TIME_GAP = 180


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
# 파일
# ============================================================

BASE_DIR = Path(__file__).parent

DATA_FILE = BASE_DIR / "members.json"
CHAT_SETTINGS_FILE = BASE_DIR / "chat_settings.json"

LEARNING_FILE = BASE_DIR / "learning_data.json"

AUTO_LEARNING_FILE = BASE_DIR / "auto_learning.json"

AUTO_CONVERSATION_FILE = BASE_DIR / "auto_conversations.json"


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

auto_learning_settings = {}

auto_conversations = {}


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

auto_learning_settings = load_json_file(
    AUTO_LEARNING_FILE,
    {}
)

auto_conversations = load_json_file(
    AUTO_CONVERSATION_FILE,
    {}
)


if not isinstance(
    learning_data,
    list
):

    learning_data = []


if not isinstance(
    auto_learning_settings,
    dict
):

    auto_learning_settings = {}


if not isinstance(
    auto_conversations,
    dict
):

    auto_conversations = {}


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


def save_learning_data():

    save_json_file(
        LEARNING_FILE,
        learning_data
    )


def save_auto_learning_settings():

    save_json_file(
        AUTO_LEARNING_FILE,
        auto_learning_settings
    )


def save_auto_conversations():

    save_json_file(
        AUTO_CONVERSATION_FILE,
        auto_conversations
    )


# ============================================================
# 멤버
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
# 제외 멤버
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

        role = guild.get_role(role_id)

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


def clean_message_for_learning(
    text
):

    text = text.strip()

    text = re.sub(
        r"<@!?\d+>",
        "",
        text
    )

    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# 유사도
# ============================================================

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
# 수동 학습
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

        if item.get(
            "guild_id"
        ) != guild_id:

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

        old = learning_data[
            best_index
        ]

        old["answer"] = answer

        old["updated_at"] = (
            utcnow().isoformat()
        )

        old["automatic"] = automatic

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


# ============================================================
# 학습 답변 검색
# ============================================================

def find_learned_answer(
    question,
    guild_id
):

    best_item = None
    best_score = 0.0

    for item in learning_data:

        if item.get(
            "guild_id"
        ) != guild_id:

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
# 설정
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


# ============================================================
# 대화 기록
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

        "user_id":
            message.author.id,

        "content":
            message.content.strip(),

        "answer":
            answer,

        "time":
            utcnow().isoformat()
    })


# ============================================================
# 자동학습
# ============================================================

def learning_key(
    guild_id,
    channel_id
):

    return f"{guild_id}:{channel_id}"


def get_previous_message(
    guild_id,
    channel_id
):

    key = learning_key(
        guild_id,
        channel_id
    )

    return auto_conversations.get(
        key
    )


def update_previous_message(
    message
):

    key = learning_key(
        message.guild.id,
        message.channel.id
    )

    auto_conversations[key] = {

        "author_id":
            message.author.id,

        "content":
            clean_message_for_learning(
                message.content
            ),

        "timestamp":
            utcnow().isoformat()
    }

    save_auto_conversations()


def valid_learning_text(
    text
):

    text = clean_message_for_learning(
        text
    )

    if len(text) < MIN_LEARNING_TEXT_LENGTH:

        return False

    if len(text) > MAX_LEARNING_TEXT_LENGTH:

        return False

    if text.startswith("!"):

        return False

    return True


def looks_like_bot_trigger(
    text
):

    lowered = text.lower().strip()

    if lowered.startswith("봇아"):

        return True

    return False


def should_learn_pair(
    previous,
    current
):

    if not previous:

        return False

    previous_text = previous.get(
        "content",
        ""
    )

    current_text = clean_message_for_learning(
        current.content
    )

    if not valid_learning_text(
        previous_text
    ):

        return False

    if not valid_learning_text(
        current_text
    ):

        return False

    # 같은 사람이 연속으로 말한 경우
    if (
        previous.get("author_id")
        == current.author.id
    ):

        return False

    # 봇 호출 문장은 학습에서 제외
    if looks_like_bot_trigger(
        previous_text
    ):

        return False

    if looks_like_bot_trigger(
        current_text
    ):

        return False

    try:

        previous_time = datetime.fromisoformat(
            previous["timestamp"]
        )

        if (
            utcnow() - previous_time
            > timedelta(
                seconds=LEARNING_MAX_TIME_GAP
            )
        ):

            return False

    except Exception:

        return False

    return True


def automatic_learn_pair(
    message
):

    if not auto_learning_enabled(
        message.guild.id
    ):

        update_previous_message(
            message
        )

        return False

    if not isinstance(
        message.channel,
        discord.TextChannel
    ):

        return False

    previous = get_previous_message(
        message.guild.id,
        message.channel.id
    )

    learned = False

    if should_learn_pair(
        previous,
        message
    ):

        question = clean_message_for_learning(
            previous["content"]
        )

        answer = clean_message_for_learning(
            message.content
        )

        # 지나치게 짧거나 긴 대화 제외
        if (
            question
            and answer
        ):

            learned = learn_response(
                question,
                answer,
                message.guild.id,
                message.author.id,
                automatic=True
            )

            if learned:

                print(
                    "[자동학습] "
                    f"{question} -> {answer}"
                )

    update_previous_message(
        message
    )

    return learned


# ============================================================
# 질문 판별
# ============================================================

def looks_like_question(
    text
):

    text = text.strip()

    if len(text) < 3:

        return False

    words = [

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
        for word in words
    )


# ============================================================
# 봇 호출
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

    if (
        bot.user
        and bot.user in message.mentions
    ):

        return True

    lowered = content.lower()

    if lowered.startswith(
        "봇아"
    ):

        return True

    if re.match(
        r"^봇[\s,!?]",
        content
    ):

        return True

    if chat_enabled(
        message.guild.id
    ):

        if (
            CHAT_CHANNEL_KEYWORD
            in message.channel.name
        ):

            return True

    return False


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
# 기본 응답
# ============================================================

async def generate_local_reply(
    message
):

    user_text = clean_bot_mention(
        message.content
    )

    if not user_text:

        user_text = "안녕"

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

    normalized = normalize_text(
        user_text
    )

    if normalized in [
        "안녕",
        "하이",
        "ㅎㅇ",
        "ㅎㅇㅇ"
    ]:

        return "오 ㅋㅋ 안녕!"

    if "뭐해" in normalized:

        return "나? 여기서 대기 중이지 ㅋㅋ"

    if "잘자" in normalized:

        return "웅 잘자 ㅋㅋ 좋은 꿈 꿔!"

    if "고마워" in normalized:

        return "ㅋㅋ 별거 아니지"

    if "ㅋㅋ" in normalized:

        return "ㅋㅋㅋㅋ"

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
            "서버에서는 그냥 봇이라고 불러줘 ㅋㅋ"
        )

    if looks_like_question(
        user_text
    ):

        return (
            "음... 그건 아직 내가 "
            "배운 내용이 없어 ㅋㅋ"
        )

    return (
        "오 ㅋㅋ "
        "그건 아직 내가 배운 내용이 없어!"
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

                f"예시: `04남`, `04 여`, "
                f"`04ㄴ`, `04 ㅇ`\n\n"

                f"채팅이나 음성채널 활동도 "
                f"자유롭게 해주세요.\n\n"

                f"⚠️ 자기소개도 없고 "
                f"3일간 활동도 없으면 "
                f"자동 퇴장 처리됩니다."
            )

        except discord.Forbidden:

            print(
                "[환영 메시지 전송 실패]"
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

    data = ensure_member(
        member
    )

    data["last_activity"] = (
        utcnow().isoformat()
    )

    save_data()

    # ========================================================
    # 자동학습
    # ========================================================

    if (
        isinstance(
            message.channel,
            discord.TextChannel
        )
        and CHAT_CHANNEL_KEYWORD
        in message.channel.name
    ):

        automatic_learn_pair(
            message
        )

    # ========================================================
    # 자기소개
    # ========================================================

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

            save_data()

    # ========================================================
    # 로컬 대화
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
            "`!학습시키기 질문 | 답변`"
        )

        return

    if "|" not in content:

        await ctx.send(
            "❌ 질문과 답변 사이에 "
            "`|`를 넣어줘."
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
        )
        == ctx.guild.id
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

        automatic = item.get(
            "automatic",
            False
        )

        mode = (
            "자동"
            if automatic
            else "수동"
        )

        lines.append(
            f"**{index}. [{mode}]**\n"
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
        )
        == ctx.guild.id
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
        )
        != ctx.guild.id
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
            "`!자동학습 끄기`\n\n"

            "자동학습은 메인채팅에서 "
            "사람과 사람의 대화 흐름을 보고 "
            "이전 메시지 → 다음 답변 패턴을 "
            "자동으로 저장해."
        )

        return

    setting = setting.lower()

    if setting == "켜기":

        auto_learning_settings[
            str(ctx.guild.id)
        ] = True

        save_auto_learning_settings()

        await ctx.send(

            "🧠 **자동학습 ON!**\n\n"

            "이제 메인채팅의 대화 흐름을 "
            "보고 자동으로 학습할게.\n\n"

            "예:\n"
            "`오늘 밥 맛있었다`\n"
            "→ `뭐 먹었어?`\n\n"

            "다음에 비슷한 말이 나오면 "
            "배운 답변을 사용할 수 있어."
        )

    elif setting == "끄기":

        auto_learning_settings[
            str(ctx.guild.id)
        ] = False

        save_auto_learning_settings()

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
            "💬 **메인채팅 자동 대화 ON!**\n"
            "이제 메인채팅에서 대화하면 "
            "배운 내용을 찾아서 반응할게 ㅋㅋ"
        )

    elif setting == "끄기":

        chat_settings[
            str(ctx.guild.id)
        ] = False

        save_chat_settings()

        await ctx.send(
            "💬 **메인채팅 자동 대화 OFF!**\n"
            "단, `봇아`라고 부르거나 "
            "멘션하면 답변할 수 있어."
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

        "💬 **로컬 학습형 봇**\n\n"

        "🗣️ **대화**\n"
        "• `봇아 안녕`\n"
        "• 봇 멘션\n"
        "• 관리자 `!대화 켜기`\n"
        "• 관리자 `!대화 끄기`\n\n"

        "🧠 **자동학습**\n"
        "• 관리자 `!자동학습 켜기`\n"
        "• 관리자 `!자동학습 끄기`\n\n"

        "✏️ **수동학습**\n"
        "• `!학습시키기 질문 | 답변`\n"
        "• `!학습목록`\n"
        "• `!학습검색 질문`\n"
        "• `!학습삭제 번호`\n"
        "• `!학습초기화`"
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
# 검사 시작 전
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
# 로그인
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
        f"학습 데이터: "
        f"{len(learning_data)}개"
    )

    print(
        f"자동학습: "
        f"{len(auto_conversations)}개 대화 기록"
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
