import os, json, re, asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import OpenAI

# =========================================================
# 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

GUILD_ID = 1542210983127425158

LOG_CHANNEL = "🚪・추방로그"
YACHA_CATEGORY = "[ 💬 ] ─ 채팅"
YACHA_NAME = "＃↝・야차"

INTRO_MINUTES = 30
ADULT_CUTOFF = 2007
MIN_ALLOWED_BIRTH_YEAR = 2011  # 2012년생(중2) 이하 입장 제한

ROLE_CHANNEL_ID = 1549631714769244261
MAIN_CHAT_ID = 1544032267855470644

ADULT_CHANNELS = {"＃↝・성인채팅", "＃↝・19금"}

ROLES = {
    "unverified": 1544031900295893112,
    "male": 1544031878812532858,
    "female": 1544031884227518525,
    "adult": 1544031894809616475,
    "minor": 1544031889533182043,
}

BODY_SHARE_ID = 1544276267522719794

FILES = {
    "members": "members.json",
    "chat": "chat_settings.json",
    "yacha": "yacha_data.json",
    "warnings": "warnings.json",
}

WARNING_TIMEOUT = {
    3: 60 * 60,
    4: 24 * 60 * 60,
}

# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
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

gemini = OpenAI(
    api_key=GEMINI_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
) if GEMINI_KEY else None

SYSTEM_PROMPT = """
너는 디스코드 서버의 AI 봇 JARVIS다.
한국어로 친근하고 자연스럽게 답한다.
너무 길게 답하지 않는다.
모르는 것은 아는 척하지 않는다.
개인정보를 요구하거나 노출하지 않는다.
불법행위를 구체적으로 돕지 않는다.
노골적인 성적 콘텐츠를 생성하지 않는다.
미성년자와 관련된 성적 콘텐츠는 절대 생성하지 않는다.
"""

# =========================================================
# 데이터
# =========================================================

members = {}
chat_settings = {}
yacha = {}
warnings = {}
history = {}
ai_cooldowns = {}
pending_kicks = set()


def load_json(file, default):
    try:
        with open(file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(file, data):
    try:
        tmp = file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    except Exception as e:
        print(f"[JSON 저장 오류] {file}: {e}")


def load_data():
    global members, chat_settings, yacha, warnings

    members = load_json(FILES["members"], {})
    chat_settings = load_json(FILES["chat"], {"enabled": True})
    yacha = load_json(FILES["yacha"], {})
    warnings = load_json(FILES["warnings"], {})

    print(f"[DATA] 회원 {len(members)}명")


# =========================================================
# 공통
# =========================================================

def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def parse_dt(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def member_data(member):
    return members.setdefault(str(member.id), {
        "joined_at": iso(member.joined_at or now()),
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": iso(now()),
        "is_existing_member": True,
        "kicked": False
    })


def warning_count(member):
    return int(warnings.get(str(member.id), {}).get("count", 0))


def is_admin(member):
    return member.guild_permissions.administrator


def age_type(year):
    return "성인" if year <= ADULT_CUTOFF else "미성년자"


def gender_text(gender):
    return {"남": "남자", "여": "여자"}.get(gender, "미확인")


def update_activity(member):
    data = members.get(str(member.id))
    if data:
        data["last_activity"] = iso(now())
        save_json(FILES["members"], members)


# =========================================================
# 자기소개
# =========================================================

def parse_intro(text):
    match = re.search(
        r"(?<!\d)((?:19|20)\d{2}|\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)",
        text.strip()
    )

    if not match:
        return None

    raw, gender = match.groups()
    current = datetime.now().year

    if len(raw) == 4:
        year = int(raw)
    else:
        n = int(raw)
        year = 2000 + n if n <= current % 100 else 1900 + n

    if not 1900 <= year <= current:
        return None

    return year, "남" if gender in ("남", "ㄴ") else "여"


async def role(member, role_id, add=True):
    r = member.guild.get_role(role_id)
    if not r:
        return

    try:
        if add and r not in member.roles:
            await member.add_roles(r)
        elif not add and r in member.roles:
            await member.remove_roles(r)
    except Exception as e:
        print(f"[역할 오류] {e}")


async def apply_intro_roles(member, year, gender):
    for key in ("unverified", "male", "female", "adult", "minor"):
        await role(member, ROLES[key], False)

    await role(
        member,
        ROLES["male"] if gender == "남" else ROLES["female"]
    )

    await role(
        member,
        ROLES["adult"] if age_type(year) == "성인" else ROLES["minor"]
    )


async def intro_complete(message, year, gender):
    # 2012년생(중2) 이하 서버 이용 제한
    if year > MIN_ALLOWED_BIRTH_YEAR:
        try:
            log = discord.utils.get(
                message.guild.text_channels,
                name=LOG_CHANNEL
            )
            if log:
                await log.send(
                    f"🚫 **연령 제한 추방**\n"
                    f"대상: {message.author.mention}\n"
                    f"출생연도: `{year}년생`\n"
                    f"사유: `초등학생~중학교 2학년 이하 이용 제한`"
                )
            await message.author.kick(
                reason="초등학생~중학교 2학년 이하 이용 제한"
            )
            return
        except Exception as e:
            print(f"[연령 제한 추방 오류] {e}")
            return

    data = member_data(message.author)

    data.update({
        "intro_completed": True,
        "birth_year": year,
        "gender": gender,
        "intro_completed_at": iso(now())
    })
    data.pop("kick_review_declined_until", None)

    save_json(FILES["members"], members)

    await apply_intro_roles(message.author, year, gender)

    await message.channel.send(
        f"🖤 {message.author.mention} 자기소개 확인했어 ♡\n"
        f"`{year}년생` · `{gender_text(gender)}` · `{age_type(year)}`\n\n"
        f"🎀 <#{ROLE_CHANNEL_ID}>에서 역할을 골라주세요.\n"
        f"💬 <#{MAIN_CHAT_ID}>에서 편하게 놀아요 ♡"
    )


# =========================================================
# 야차방
# =========================================================

def yacha_channel(guild):
    cid = yacha.get("channel_id")

    if cid:
        ch = guild.get_channel(int(cid))
        if isinstance(ch, discord.TextChannel):
            return ch

    return discord.utils.get(
        guild.text_channels,
        name=YACHA_NAME
    )


def yacha_members():
    return {int(x) for x in yacha.get("members", [])}


async def update_yacha(guild):
    ch = yacha_channel(guild)
    if not ch:
        return

    try:
        await ch.set_permissions(
            guild.default_role,
            view_channel=True,
            send_messages=False,
            add_reactions=False
        )
    except Exception:
        pass

    for uid in yacha_members():
        m = guild.get_member(uid)
        if not m:
            continue

        try:
            await ch.set_permissions(
                m,
                view_channel=True,
                send_messages=warning_count(m) < 2,
                add_reactions=warning_count(m) < 2
            )
        except Exception:
            pass


async def create_yacha(guild):
    old = yacha_channel(guild)
    if old:
        return old, False

    category = discord.utils.get(
        guild.categories,
        name=YACHA_CATEGORY
    )

    if not category:
        return None, None

    try:
        ch = await guild.create_text_channel(
            YACHA_NAME,
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    manage_channels=True
                )
            }
        )
        return ch, True
    except Exception as e:
        print(f"[야차 생성 오류] {e}")
        return None, None


@bot.group(name="야차방", invoke_without_command=True)
async def yacha_cmd(ctx):
    await ctx.send(
        "`!야차방 생성`\n"
        "`!야차방 추가 @회원`\n"
        "`!야차방 제거 @회원`\n"
        "`!야차방 목록`\n"
        "`!야차방 삭제`"
    )


@yacha_cmd.command(name="생성")
async def yacha_create(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    if warning_count(ctx.author) >= 2:
        return await ctx.send("🚫 경고 2회 이상이라 사용할 수 없어요.")

    ch, created = await create_yacha(ctx.guild)

    if created is None:
        return await ctx.send("❌ 야차방 카테고리를 찾지 못했어요.")

    if not created:
        return await ctx.send(f"ℹ️ 이미 {ch.mention}이 있어요.")

    yacha.update({
        "channel_id": ch.id,
        "members": [ctx.author.id],
        "created_by": ctx.author.id,
        "created_at": iso(now())
    })
    save_json(FILES["yacha"], yacha)

    await update_yacha(ctx.guild)

    await ch.send(
        f"🔥 **야차방 오픈**\n"
        f"👤 당사자: {ctx.author.mention}\n"
        f"👀 나머지는 구경만 가능해요."
    )

    await ctx.send(f"✅ {ch.mention} 생성 완료!")


@yacha_cmd.command(name="추가")
async def yacha_add(ctx, member: discord.Member):
    if not ctx.guild:
        return

    ch = yacha_channel(ctx.guild)

    if not ch:
        return await ctx.send("❌ 먼저 야차방을 생성해주세요.")

    members_set = yacha_members()

    if not is_admin(ctx.author) and ctx.author.id not in members_set:
        return await ctx.send("❌ 당사자 또는 관리자만 추가할 수 있어요.")

    if warning_count(member) >= 2:
        return await ctx.send("🚫 경고 2회 이상인 회원은 추가할 수 없어요.")

    members_set.add(member.id)
    yacha["members"] = list(members_set)
    save_json(FILES["yacha"], yacha)

    await update_yacha(ctx.guild)
    await ctx.send(f"✅ {member.mention} 추가 완료!")


@yacha_cmd.command(name="제거")
async def yacha_remove(ctx, member: discord.Member):
    if not ctx.guild:
        return

    ch = yacha_channel(ctx.guild)
    if not ch:
        return await ctx.send("❌ 야차방이 없어요.")

    members_set = yacha_members()

    if not is_admin(ctx.author) and ctx.author.id not in members_set:
        return await ctx.send("❌ 당사자 또는 관리자만 제거할 수 있어요.")

    members_set.discard(member.id)
    yacha["members"] = list(members_set)
    save_json(FILES["yacha"], yacha)

    try:
        await ch.set_permissions(member, overwrite=None)
    except Exception:
        pass

    await ctx.send(f"✅ {member.mention} 제거 완료!")


@yacha_cmd.command(name="목록")
async def yacha_list(ctx):
    ch = yacha_channel(ctx.guild)

    if not ch:
        return await ctx.send("❌ 야차방이 없어요.")

    lines = []

    for uid in yacha_members():
        m = ctx.guild.get_member(uid)
        if m:
            status = "🚫 제한" if warning_count(m) >= 2 else "💬 가능"
            lines.append(f"{m.mention} — {status}")

    await ctx.send(
        "🔥 **야차방 참여자**\n" +
        ("\n".join(lines) if lines else "없음")
    )


@yacha_cmd.command(name="삭제")
@commands.has_permissions(administrator=True)
async def yacha_delete(ctx):
    ch = yacha_channel(ctx.guild)

    if not ch:
        return await ctx.send("❌ 야차방이 없어요.")

    await ch.delete()
    yacha.clear()
    save_json(FILES["yacha"], yacha)

    await ctx.send("🗑️ 야차방을 삭제했어요.")


# =========================================================
# 경고
# =========================================================

async def restricted_access(member, allow=False):
    for ch in member.guild.channels:
        if ch.name != "＃↝・19금" and ch.id != BODY_SHARE_ID:
            continue

        try:
            if allow:
                await ch.set_permissions(member, overwrite=None)
            else:
                await ch.set_permissions(
                    member,
                    view_channel=False,
                    reason="경고 제한"
                )
        except Exception:
            pass


async def apply_warning(member):
    count = warning_count(member)

    await restricted_access(member, count == 0)

    ch = yacha_channel(member.guild)

    if ch and member.id in yacha_members():
        try:
            await ch.set_permissions(
                member,
                view_channel=True,
                send_messages=count < 2,
                add_reactions=count < 2
            )
        except Exception:
            pass

    if count >= 5:
        try:
            await member.kick(reason="경고 5회")
        except Exception:
            pass

    elif count >= 3:
        try:
            await member.timeout(
                discord.utils.utcnow() +
                timedelta(seconds=WARNING_TIMEOUT[4 if count >= 4 else 3]),
                reason=f"경고 {count}회"
            )
        except Exception:
            pass


async def add_warning(member, moderator, reason):
    key = str(member.id)

    data = warnings.setdefault(key, {
        "count": 0,
        "reasons": []
    })

    data["count"] += 1
    data["reasons"].append({
        "reason": reason,
        "moderator_id": moderator.id,
        "at": iso(now())
    })

    save_json(FILES["warnings"], warnings)
    await apply_warning(member)

    return data["count"]


@bot.command(name="경고")
@commands.has_permissions(administrator=True)
async def warning(ctx, member: discord.Member, *, reason="규칙 위반"):
    if member.bot:
        return await ctx.send("❌ 봇에게는 경고할 수 없어요.")

    count = await add_warning(member, ctx.author, reason)

    log = discord.utils.get(
        ctx.guild.text_channels,
        name=LOG_CHANNEL
    )

    if log:
        await log.send(
            f"⚠️ **경고 기록**\n"
            f"대상: {member.mention}\n"
            f"처리자: {ctx.author.mention}\n"
            f"사유: {reason}\n"
            f"현재 경고: **{count}회**"
        )

    actions = {
        1: "19금/몸공유방 차단",
        2: "야차방 채팅 차단",
        3: "1시간 타임아웃",
        4: "24시간 타임아웃",
        5: "서버 추방"
    }

    await ctx.send(
        f"⚠️ {member.mention} **{count}회 경고**\n"
        f"📝 {reason}\n"
        f"🔒 {actions[min(count, 5)]}"
    )


@bot.command(name="경고목록")
@commands.has_permissions(administrator=True)
async def warning_list(ctx, member: discord.Member):
    data = warnings.get(str(member.id), {})
    reasons = data.get("reasons", [])

    if not reasons:
        return await ctx.send(f"📋 {member.mention} 경고 0회")

    text = "\n".join(
        f"`{i}.` {x.get('reason', '사유 없음')}"
        for i, x in enumerate(reasons, 1)
    )

    await ctx.send(
        f"⚠️ **{member.display_name} 경고 기록**\n"
        f"현재: **{warning_count(member)}회**\n{text}"
    )


@bot.command(name="경고취소")
@commands.has_permissions(administrator=True)
async def warning_remove(ctx, member: discord.Member):
    key = str(member.id)

    if warning_count(member) <= 0:
        return await ctx.send("ℹ️ 경고가 없어요.")

    data = warnings[key]
    data["count"] -= 1

    if data.get("reasons"):
        data["reasons"].pop()

    if data["count"] <= 0:
        warnings.pop(key, None)

    save_json(FILES["warnings"], warnings)

    await apply_warning(member)

    if warning_count(member) == 0:
        await restricted_access(member, True)

    await ctx.send(
        f"↩️ {member.mention} 경고 1회 취소\n"
        f"현재: **{warning_count(member)}회**"
    )


@bot.command(name="경고초기화")
@commands.has_permissions(administrator=True)
async def warning_clear(ctx, member: discord.Member):
    warnings.pop(str(member.id), None)
    save_json(FILES["warnings"], warnings)

    await restricted_access(member, True)

    ch = yacha_channel(ctx.guild)
    if ch:
        try:
            await ch.set_permissions(member, overwrite=None)
        except Exception:
            pass

    await ctx.send(f"🧹 {member.mention} 경고 초기화 완료")


# =========================================================
# 추방 확인
# =========================================================

class KickView(discord.ui.View):
    def __init__(self, guild_id, member_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.member_id = member_id

    async def interaction_check(self, interaction):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(
                "❌ 추방 권한이 필요해요.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="예, 추방하기",
        style=discord.ButtonStyle.danger,
        emoji="🚪"
    )
    async def kick(self, interaction, button):
        guild = bot.get_guild(self.guild_id)
        member = guild.get_member(self.member_id) if guild else None

        if not member:
            return await interaction.response.edit_message(
                content="ℹ️ 이미 서버에 없는 멤버예요.",
                view=None
            )

        data = members.get(str(member.id))

        if not data:
            return await interaction.response.send_message(
                "⚠️ 회원 데이터를 찾지 못했어요.",
                ephemeral=True
            )

        if data.get("intro_completed"):
            pending_kicks.discard(member.id)
            return await interaction.response.edit_message(
                content="✅ 이미 자기소개를 완료해서 추방하지 않았어요.",
                view=None
            )

        try:
            await member.kick(reason="30분 이상 자기소개 미작성")
            data["kicked"] = True
            data["kicked_at"] = iso(now())
            save_json(FILES["members"], members)

            await interaction.response.edit_message(
                content=f"🚪 {member.mention} 추방 완료",
                view=None
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ 추방 실패: {e}",
                ephemeral=True
            )

        pending_kicks.discard(member.id)

    @discord.ui.button(
        label="취소",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(self, interaction, button):
        data = members.get(str(self.member_id))

        if data:
            data["kick_review_declined_until"] = iso(
                now() + timedelta(hours=24)
            )
            save_json(FILES["members"], members)

        pending_kicks.discard(self.member_id)

        await interaction.response.edit_message(
            content="❌ 추방을 취소했어요. 24시간 동안 다시 요청하지 않아요.",
            view=None
        )


async def send_kick_review(guild, member):
    if member.id in pending_kicks:
        return

    ch = discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL
    )

    if not ch:
        return

    pending_kicks.add(member.id)

    await ch.send(
        embed=discord.Embed(
            title="🚨 자기소개 미작성",
            description=(
                f"👤 대상: {member.mention}\n"
                f"🆔 ID: `{member.id}`\n"
                f"⏰ 입장 후 30분 경과\n\n"
                "이 회원을 추방할까요?"
            ),
            color=discord.Color.red()
        ),
        view=KickView(guild.id, member.id)
    )


@tasks.loop(minutes=1)
async def intro_check():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    changed = False

    for uid, data in list(members.items()):
        if (
            data.get("intro_completed") or
            data.get("kicked") or
            data.get("is_existing_member")
        ):
            continue

        joined = parse_dt(data.get("joined_at", ""))
        if not joined or now() < joined + timedelta(minutes=INTRO_MINUTES):
            continue

        member = guild.get_member(int(uid))

        if not member or member.bot or is_admin(member):
            continue

        declined = parse_dt(
            data.get("kick_review_declined_until", "")
        )

        if declined and now() < declined:
            continue

        if declined:
            data.pop("kick_review_declined_until", None)
            changed = True

        if not data.get("intro_completed"):
            await send_kick_review(guild, member)

    if changed:
        save_json(FILES["members"], members)


# =========================================================
# AI
# =========================================================

async def ai_message(message):
    if not gemini or not chat_settings.get("enabled", True):
        return

    content = message.content.strip()
    if not content:
        return

    is_ai = (
        message.channel.id == MAIN_CHAT_ID or
        message.channel.name in ADULT_CHANNELS or
        bot.user in message.mentions or
        any(x in content.lower() for x in ("봇아", "자비스"))
    )

    if not is_ai:
        return

    data = members.get(str(message.author.id), {})

    if message.channel.name in ADULT_CHANNELS:
        if not data.get("intro_completed"):
            return await message.reply("🖤 먼저 자기소개를 완료해주세요.")

        if age_type(data.get("birth_year", 9999)) != "성인":
            return await message.reply(
                "🔒 이 채널은 성인만 이용할 수 있어요."
            )

    uid = message.author.id

    if uid in ai_cooldowns:
        if (now() - ai_cooldowns[uid]).total_seconds() < 2:
            return

    ai_cooldowns[uid] = now()

    content = re.sub(
        rf"<@!?{bot.user.id}>",
        "",
        content
    ).strip() or "안녕"

    cid = str(message.channel.id)
    history.setdefault(cid, []).append({
        "role": "user",
        "content": content
    })
    history[cid] = history[cid][-12:]
    try:
        response = await asyncio.to_thread(
            gemini.chat.completions.create,
            model=GEMINI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *history[cid]
            ],
            temperature=0.7,
            max_tokens=500
        )

        reply = response.choices[0].message.content.strip()

        if not reply:
            return

        history[cid].append({
            "role": "assistant",
            "content": reply
        })

        await message.reply(
            reply[:2000],
            mention_author=False
        )

    except Exception as e:
        print(f"[AI 오류] {e}")
        await message.reply(
            "⚠️ AI 응답 중 오류가 발생했어요.",
            mention_author=False
        )


# =========================================================
# 메시지 이벤트
# =========================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.guild or message.guild.id != GUILD_ID:
        return

    # 회원 데이터 생성
    data = member_data(message.author)

    # 활동 시간 갱신
    data["last_activity"] = iso(now())

    # 자기소개 확인
    if not data.get("intro_completed"):
        intro = parse_intro(message.content)

        if intro:
            year, gender = intro
            await intro_complete(message, year, gender)

    # AI
    await ai_message(message)

    await bot.process_commands(message)


# =========================================================
# 서버 입장
# =========================================================

@bot.event
async def on_member_join(member):
    if member.guild.id != GUILD_ID:
        return

    data = member_data(member)

    data.update({
        "joined_at": iso(now()),
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": iso(now()),
        "is_existing_member": False,
        "kicked": False
    })

    save_json(FILES["members"], members)

    try:
        await role(member, ROLES["unverified"], True)
    except Exception:
        pass


# =========================================================
# 서버 퇴장
# =========================================================

@bot.event
async def on_member_remove(member):
    if member.guild.id != GUILD_ID:
        return

    pending_kicks.discard(member.id)

    if member.id in yacha_members():
        yacha["members"].remove(member.id)
        save_json(FILES["yacha"], yacha)


# =========================================================
# 봇 준비
# =========================================================

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"JARVIS 로그인 완료: {bot.user}")
    print(f"서버 ID: {GUILD_ID}")
    print("=" * 50)

    if not intro_check.is_running():
        intro_check.start()


# =========================================================
# 오류 처리
# =========================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("❌ 관리자 권한이 필요해요.")

    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send("❌ 명령어 사용법이 잘못됐어요.")

    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("❌ 해당 회원을 찾을 수 없어요.")

    if isinstance(error, commands.CommandNotFound):
        return

    print(f"[명령어 오류] {error}")


# =========================================================
# 실행
# =========================================================

def main():
    load_data()

    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN이 설정되지 않았어요.")

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
