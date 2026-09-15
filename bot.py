import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from google import genai

# ============================================================
# 환경변수
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 없습니다.")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY가 없습니다.")

# ============================================================
# Gemini
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """
너는 디스코드 서버에서 활동하는 친근한 한국어 봇이다.

말투:
- 한국 인터넷 커뮤니티에서 자연스럽게 대화하는 느낌
- 너무 딱딱하거나 공식적인 말투를 사용하지 않는다.
- 짧고 자연스럽게 답한다.
- 상황에 따라 ㅋㅋ, ㅎㅎ 등을 적당히 사용한다.
- 사용자가 장난을 치면 장난스럽게 받아준다.
- 사용자가 진지하면 진지하게 답한다.
- 같은 말을 반복하지 않는다.

중요:
- 너 자신을 AI라고 굳이 강조하지 않는다.
- 모르는 내용은 아는 척하지 않는다.
- 답변은 기본적으로 1~4문장 정도로 한다.
- 성적인 주제가 나오더라도 노골적인 성적 행위 묘사나 미성년자 관련 성적 내용은 하지 않는다.
"""

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

# 채널별 최근 대화
conversation_history = {}

MAX_HISTORY = 12


# ============================================================
# Gemini 답변
# ============================================================

async def ask_gemini(
    guild_id: int,
    channel_id: int,
    user_name: str,
    user_message: str
):

    key = (guild_id, channel_id)

    if key not in conversation_history:
        conversation_history[key] = []

    history = conversation_history[key]

    history.append(
        f"{user_name}: {user_message}"
    )

    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]

    conversation = "\n".join(history)

    prompt = f"""
{SYSTEM_PROMPT}

최근 디스코드 대화:
{conversation}

위 대화의 흐름을 기억하면서 마지막 사용자의 말에 자연스럽게 답해라.

답변만 출력해라.
"the bot's response:" 같은 접두사는 절대 붙이지 마.
"""

    try:

        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=prompt
        )

        answer = response.text.strip()

        if not answer:
            answer = "잠깐 생각이 안 나네 ㅋㅋ"

        history.append(
            f"봇: {answer}"
        )

        if len(history) > MAX_HISTORY:
            del history[:-MAX_HISTORY]

        return answer

    except Exception as e:

        print(
            f"[Gemini 오류] {type(e).__name__}: {e}"
        )

        return "잠깐 오류 났다 ㅋㅋ 다시 말해봐."


# ============================================================
# 봇 준비
# ============================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"로그인 완료: {bot.user}")
    print(f"서버 수: {len(bot.guilds)}")
    print("Gemini 대화 시스템: ON")
    print("=" * 50)


# ============================================================
# 메시지
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # 명령어는 일반 대화로 처리하지 않음
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    # 봇 멘션 또는 "봇아"로 시작할 때만 대답
    content = message.content.strip()

    mentioned = (
        bot.user is not None
        and bot.user in message.mentions
    )

    called = content.startswith("봇아")

    if mentioned or called:

        text = content

        if bot.user:
            text = text.replace(
                f"<@{bot.user.id}>",
                ""
            )
            text = text.replace(
                f"<@!{bot.user.id}>",
                ""
            )

        if text.startswith("봇아"):
            text = text[2:].strip()

        if not text:
            text = "안녕"

        async with message.channel.typing():

            answer = await ask_gemini(
                message.guild.id,
                message.channel.id,
                message.author.display_name,
                text
            )

        await message.reply(
            answer,
            mention_author=False
        )

    await bot.process_commands(message)


# ============================================================
# 테스트 명령어
# ============================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def 테스트(ctx):

    await ctx.send(
        "정상 작동 중이야 👍"
    )


# ============================================================
# 실행
# ============================================================

bot.run(DISCORD_TOKEN)
