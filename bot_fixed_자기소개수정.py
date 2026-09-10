import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import re
from dotenv import load_dotenv

# ============================================================
# 새벽에너를기다리는중 서버용
# 기능:
# 1) 신규 멤버 기록
# 2) "자기소개" 채널에 자기소개를 쓰면 완료 처리
# 3) 채팅 또는 음성채널 활동을 기록
# 4) 가입 후 3일이 지나도 자기소개 X + 활동 X이면 자동 추방
# 5) 관리자 권한 보유자는 자동 추방 제외
# ============================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 화면에 보이는 채널 이름에 "자기소개"가 들어가면 자동으로 찾습니다.
INTRO_KEYWORD = "자기소개"

# 로그 채널은 아래 이름을 가진 채널이 있으면 사용합니다.
# 없으면 자동 추방은 정상 작동하지만 로그는 보내지 않습니다.
LOG_CHANNEL_NAME = "추방-로그"

# 가입 후 유예 기간
GRACE_DAYS = 3

# 30분마다 검사
CHECK_MINUTES = 30

DATA_FILE = Path("members.json")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


def utcnow():
    return datetime.now(timezone.utc)


def load_data():
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_data():
    DATA_FILE.write_text(
        json.dumps(members_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


members_data = load_data()


def ensure_member(member: discord.Member):
    key = str(member.id)

    if key not in members_data:
        members_data[key] = {
            "joined": utcnow().isoformat(),
            "last_activity": utcnow().isoformat(),
            "intro": False
        }
        save_data()

    return members_data[key]


def is_exempt(member: discord.Member):
    # 봇 제외
    if member.bot:
        return True

    # 서버 관리자 권한이 있는 사람 제외
    if member.guild_permissions.administrator:
        return True

    return False


def find_intro_channel(guild: discord.Guild):
    # "👋・자기소개"처럼 꾸며진 채널도 찾음
    for channel in guild.text_channels:
        if INTRO_KEYWORD in channel.name:
            return channel
    return None


def find_log_channel(guild: discord.Guild):
    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME
    )


@bot.event
async def on_ready():
    print("=" * 50)
    print(f"로그인 완료: {bot.user} / ID: {bot.user.id}")
    print(f"연결된 서버: {len(bot.guilds)}개")
    print("=" * 50)

    if not check_members.is_running():
        check_members.start()


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    members_data[str(member.id)] = {
        "joined": utcnow().isoformat(),
        "last_activity": utcnow().isoformat(),
        "intro": False
    }
    save_data()

    print(f"[입장] {member} ({member.id})")

    # 자기소개 채널을 자동으로 찾아 안내
    intro_channel = find_intro_channel(member.guild)

    if intro_channel:
        try:
            await intro_channel.send(
                f"{member.mention} 환영합니다! 👋\n"
                f"**3일 이내에 자기소개를 작성해주세요.**\n"
                f"그동안 서버 채팅이나 음성채널 활동도 가능합니다.\n"
                f"**자기소개도 없고 3일간 활동도 없으면 자동 퇴장 처리됩니다.**"
            )
        except discord.Forbidden:
            pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if isinstance(message.author, discord.Member):
        member = message.author
        data = ensure_member(member)

        # 모든 일반 채팅을 활동으로 기록
        data["last_activity"] = utcnow().isoformat()

        # "자기소개" 채널에서 "04 남", "04 여"처럼
        # 출생연도 2자리 + 성별 형식으로 작성하면 완료 처리
        if isinstance(message.channel, discord.TextChannel):
            if INTRO_KEYWORD in message.channel.name:
                intro_text = message.content.strip()
                if re.fullmatch(r"\\d{2}\\s*(남|여)", intro_text):
                    data["intro"] = True

                    try:
                        await message.add_reaction("✅")
                    except discord.HTTPException:
                        pass

        save_data()

    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    if member.bot:
        return

    # 음성채널에 새로 들어간 경우 활동으로 기록
    if before.channel is None and after.channel is not None:
        data = ensure_member(member)
        data["last_activity"] = utcnow().isoformat()
        save_data()
        print(f"[음성 활동] {member} -> {after.channel.name}")


@tasks.loop(minutes=CHECK_MINUTES)
async def check_members():
    current = utcnow()

    for guild in bot.guilds:
        # 캐시된 멤버를 기준으로 검사
        for member in guild.members:

            if is_exempt(member):
                continue

            data = members_data.get(str(member.id))
            if not data:
                continue

            try:
                joined = datetime.fromisoformat(data["joined"])
                last_activity = datetime.fromisoformat(data["last_activity"])
            except (KeyError, ValueError, TypeError):
                continue

            # 가입 후 3일이 안 지난 사람은 아직 검사하지 않음
            if current - joined < timedelta(days=GRACE_DAYS):
                continue

            # 자기소개를 작성했다면 제외
            if data.get("intro", False):
                continue

            # 최근 3일 안에 활동했다면 제외
            if current - last_activity < timedelta(days=GRACE_DAYS):
                continue

            # 여기까지 왔으면:
            # 가입 3일 이상 + 자기소개 없음 + 최근 3일 활동 없음
            try:
                log_channel = find_log_channel(guild)

                if log_channel:
                    embed = discord.Embed(
                        title="🚪 자동 추방",
                        description=(
                            f"{member.mention} 님이 **자기소개 미작성 + "
                            f"장기 미활동**으로 자동 추방되었습니다."
                        ),
                        timestamp=current
                    )
                    embed.add_field(
                        name="사용자",
                        value=f"{member} ({member.id})",
                        inline=False
                    )
                    embed.add_field(
                        name="사유",
                        value="가입 후 3일 경과 / 자기소개 없음 / 3일간 활동 없음",
                        inline=False
                    )
                    await log_channel.send(embed=embed)

                await member.kick(
                    reason="자기소개 미작성 + 3일간 활동 없음"
                )

                print(f"[자동 추방] {member}")

                members_data.pop(str(member.id), None)
                save_data()

            except discord.Forbidden:
                print(
                    f"[권한 오류] {member}을(를) 추방하지 못했습니다. "
                    "봇 역할을 대상 멤버보다 위로 올리고 Kick Members 권한을 확인하세요."
                )
            except Exception as e:
                print(f"[추방 오류] {member}: {e}")


@check_members.before_loop
async def before_check_members():
    await bot.wait_until_ready()


@bot.command(name="상태")
@commands.has_permissions(administrator=True)
async def status(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = members_data.get(str(member.id))

    if not data:
        await ctx.send("📌 이 사용자의 기록이 없습니다.")
        return

    intro = "✅ 작성 완료" if data.get("intro") else "❌ 미작성"
    last = datetime.fromisoformat(data["last_activity"])

    await ctx.send(
        f"**{member.display_name} 상태**\n"
        f"자기소개: {intro}\n"
        f"최근 활동: <t:{int(last.timestamp())}:R>"
    )


@bot.command(name="검사")
@commands.has_permissions(administrator=True)
async def manual_check(ctx):
    count = 0
    current = utcnow()

    for guild in bot.guilds:
        for member in guild.members:
            if is_exempt(member):
                continue

            data = members_data.get(str(member.id))
            if not data:
                continue

            try:
                joined = datetime.fromisoformat(data["joined"])
                last_activity = datetime.fromisoformat(data["last_activity"])
            except Exception:
                continue

            if current - joined < timedelta(days=GRACE_DAYS):
                continue
            if data.get("intro", False):
                continue
            if current - last_activity < timedelta(days=GRACE_DAYS):
                continue

            count += 1

    await ctx.send(f"🔍 현재 자동 추방 조건에 해당하는 멤버: **{count}명**")


@bot.command(name="자기소개초기화")
@commands.has_permissions(administrator=True)
async def reset_intro(ctx, member: discord.Member):
    data = ensure_member(member)
    data["intro"] = False
    save_data()
    await ctx.send(f"🔄 {member.mention}님의 자기소개 상태를 초기화했습니다.")


if not TOKEN:
    print("❌ DISCORD_TOKEN을 설정해주세요.")
else:
    bot.run(TOKEN)
