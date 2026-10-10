
import asyncio
import random
import uuid
import discord

from core import *


# =========================================================
# 소개팅 설정
# =========================================================

DATING_CATEGORY_NAME = "💗・소개팅 & 연애"
DATING_CHANNEL_PREFIX = "💞・소개팅"

DATING_QUESTIONS = [
    "최근에 가장 재밌었던 일은?",
    "주말에 보통 뭐 하면서 보내요?",
    "요즘 가장 자주 듣는 노래는?",
    "같이 하루를 보낸다면 어디에 가고 싶어요?",
    "친해질 때 가장 중요하다고 생각하는 건?",
    "게임을 한다면 어떤 게임을 같이 하고 싶어요?",
    "여행을 간다면 바다와 산 중 어디가 좋아요?",
    "첫인상과 지금 느낌이 달라졌나요?"
]

DATING_GAMES = [
    "🎲 가위바위보 한 판 해보기",
    "🎯 서로에게 10초 안에 질문 하나씩 하기",
    "🧠 초성: ㅇㅅㅎ (상대가 맞혀보기)",
    "💭 서로의 첫인상을 한 단어로 말하기",
    "⚖️ 밸런스: 바다 여행 vs 도시 여행"
]


# =========================================================
# 데이터 저장
# =========================================================

def save_dating_data():
    save_json(
        FILES["dating"],
        {
            "queue": dating_queue,
            "sessions": dating_sessions
        }
    )


# =========================================================
# 현재 소개팅 세션 확인
# =========================================================

def dating_member_session(member_id):
    for session_id, session in dating_sessions.items():
        if session.get("status") != "active":
            continue

        member_ids = [
            int(uid) for uid in session.get("members", [])
        ]

        if int(member_id) in member_ids:
            return session_id, session

    return None, None


# =========================================================
# 연령 그룹
# =========================================================

def get_dating_group(member):
    if member.bot:
        return None

    data = member_data(member)

    if not data.get("intro_completed", False):
        return None

    birth_year = data.get("birth_year")

    if not isinstance(birth_year, int):
        return None

    if birth_year <= ADULT_CUTOFF:
        return "adult"

    return "minor"


# =========================================================
# 성별
# =========================================================

def get_dating_gender(member):
    if member.bot:
        return None

    data = member_data(member)

    if not data.get("intro_completed", False):
        return None

    gender = data.get("gender")

    if gender not in ("남", "여"):
        return None

    return gender


# =========================================================
# 매칭 조건
# =========================================================

def can_dating_match(member_a, member_b):
    if member_a.id == member_b.id:
        return False

    group_a = get_dating_group(member_a)
    group_b = get_dating_group(member_b)

    gender_a = get_dating_gender(member_a)
    gender_b = get_dating_gender(member_b)

    if not all((group_a, group_b, gender_a, gender_b)):
        return False

    # 동일 연령 그룹끼리 매칭
    if group_a != group_b:
        return False

    # 서로 다른 성별끼리 매칭
    if gender_a == gender_b:
        return False

    return True


# =========================================================
# 소개팅 카테고리 생성
# =========================================================

async def get_dating_category(guild):
    category = discord.utils.get(
        guild.categories,
        name=DATING_CATEGORY_NAME
    )

    if category:
        return category

    try:
        return await guild.create_category(
            DATING_CATEGORY_NAME,
            reason="소개팅 콘텐츠 카테고리 생성"
        )
    except Exception as e:
        print(f"[DATING CATEGORY ERROR] {e}")
        return None


# =========================================================
# 소개팅 전용 채널 생성
# =========================================================

async def create_dating_channel(guild, member_a, member_b):
    category = await get_dating_category(guild)

    if category is None:
        return None

    session_id = uuid.uuid4().hex[:6].upper()

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        member_a: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        member_b: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }

    bot_member = guild.me

    if bot_member:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True
        )

    try:
        channel = await guild.create_text_channel(
            f"{DATING_CHANNEL_PREFIX}-{session_id}",
            category=category,
            overwrites=overwrites,
            reason="소개팅 매칭 전용 채널 생성"
        )
    except Exception as e:
        print(f"[DATING CHANNEL ERROR] {e}")
        return None

    dating_sessions[session_id] = {
        "channel_id": channel.id,
        "members": [member_a.id, member_b.id],
        "status": "active",
        "created_at": iso(now()),
        "likes": [],
        "session_id": session_id
    }

    save_dating_data()

    return session_id, channel


# =========================================================
# 상대 프로필 Embed
# =========================================================

def dating_embed_for_member(viewer, opponent, session):
    profile_data = get_profile(opponent.id) or {}
    info = member_data(opponent)

    birth_year = (
        profile_data.get("age")
        or info.get("birth_year")
        or "미설정"
    )

    gender = (
        profile_data.get("gender")
        or gender_text(info.get("gender"))
        or "미설정"
    )

    location = profile_data.get("location") or "미설정"
    ideal_type = profile_data.get("ideal_type") or "미설정"
    likes = profile_data.get("likes") or "미설정"

    embed = discord.Embed(
        title=f"💗 소개팅 · {opponent.display_name}",
        description=(
            f"**{birth_year}** · **{gender}**\n"
            f"📍 {location}\n\n"
            f"♡ **이상형**\n{ideal_type}\n\n"
            f"🎮 **좋아하는 것**\n{likes}"
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )

    embed.set_thumbnail(url=opponent.display_avatar.url)
    embed.set_footer(
        text=f"소개팅 세션 · {session.get('session_id', '')}"
    )

    return embed


# =========================================================
# 소개팅 종료
# =========================================================

async def finish_dating_session(session_id, reason="소개팅 종료"):
    session = dating_sessions.get(session_id)

    if not session or session.get("status") != "active":
        return

    session["status"] = "ended"
    session["ended_at"] = iso(now())

    save_dating_data()

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        return

    channel = guild.get_channel(int(session.get("channel_id", 0)))

    if channel is None:
        return

    try:
        await channel.send(
            f"🚪 **소개팅이 종료되었습니다.**\n"
            f"사유: `{reason}`\n\n"
            "이 채널은 5초 후 삭제됩니다."
        )
        await asyncio.sleep(5)
    except Exception:
        pass

    try:
        await channel.delete(reason=reason)
    except Exception as e:
        print(f"[DATING DELETE ERROR] {e}")


# =========================================================
# 신고 모달
# =========================================================

class DatingReportModal(discord.ui.Modal, title="소개팅 신고"):
    reason = discord.ui.TextInput(
        label="신고 사유",
        placeholder="신고할 내용을 적어주세요.",
        required=True,
        max_length=500
    )

    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    async def on_submit(self, interaction: discord.Interaction):
        log = get_log_channel(interaction.guild)

        if log:
            await log.send(
                f"🚨 **소개팅 신고**\n"
                f"신고자: {interaction.user.mention}\n"
                f"세션: `{self.session_id}`\n"
                f"사유: {self.reason.value}"
            )

        await interaction.response.send_message(
            "✅ 신고가 접수되었습니다.",
            ephemeral=True
        )


# =========================================================
# 소개팅 진행 화면
# =========================================================

class DatingView(discord.ui.View):
    def __init__(self, session_id):
        super().__init__(timeout=None)
        self.session_id = session_id

    def get_session(self):
        return dating_sessions.get(self.session_id)

    def get_opponent(self, user_id):
        session = self.get_session()

        if not session:
            return None

        opponent_id = next(
            (
                int(uid)
                for uid in session.get("members", [])
                if int(uid) != int(user_id)
            ),
            None
        )

        if opponent_id is None:
            return None

        guild = bot.get_guild(GUILD_ID)

        return guild.get_member(opponent_id) if guild else None

    async def interaction_check(self, interaction):
        session = self.get_session()

        if not session or session.get("status") != "active":
            await interaction.response.send_message(
                "❌ 이미 종료된 소개팅입니다.",
                ephemeral=True
            )
            return False

        member_ids = [
            int(uid) for uid in session.get("members", [])
        ]

        if interaction.user.id not in member_ids:
            await interaction.response.send_message(
                "❌ 이 소개팅의 참가자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="상대정보",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:info"
    )
    async def info(self, interaction, button):
        opponent = self.get_opponent(interaction.user.id)
        session = self.get_session()

        if not opponent:
            await interaction.response.send_message(
                "❌ 상대를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=dating_embed_for_member(
                interaction.user, opponent, session
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="오늘의 질문",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:question"
    )
    async def question(self, interaction, button):
        await interaction.response.send_message(
            f"💭 **오늘의 질문**\n\n"
            f"「{random.choice(DATING_QUESTIONS)}」"
        )

    @discord.ui.button(
        label="💚 호감 보내기",
        style=discord.ButtonStyle.success,
        custom_id="dating:like"
    )
    async def like(self, interaction, button):
        session = self.get_session()
        likes = session.setdefault("likes", [])

        # JSON 저장 후에는 ID가 문자열일 수 있음
        likes = [int(uid) for uid in likes]
        session["likes"] = likes

        if interaction.user.id in likes:
            await interaction.response.send_message(
                "💚 이미 호감을 보냈어요.",
                ephemeral=True
            )
            return

        likes.append(interaction.user.id)
        session["likes"] = likes
        save_dating_data()

        opponent = self.get_opponent(interaction.user.id)

        if opponent and opponent.id in likes:
            await interaction.response.send_message(
                f"🎉 **서로 호감이 확인됐어요!**\n"
                f"{interaction.user.mention} × {opponent.mention}"
            )

            for recipient, other in (
                (interaction.user, opponent),
                (opponent, interaction.user)
            ):
                try:
                    await recipient.send(
                        f"💗 소개팅 결과\n"
                        f"{other.display_name}님과 서로 호감이 확인됐어요!"
                    )
                except Exception:
                    pass
        else:
            await interaction.response.send_message(
                "💚 호감을 보냈어요. 상대방도 호감을 보내면 서로 확인돼요!",
                ephemeral=True
            )

    @discord.ui.button(
        label="🎮 미니게임",
        style=discord.ButtonStyle.primary,
        custom_id="dating:game"
    )
    async def game(self, interaction, button):
        await interaction.response.send_message(
            f"🎮 **미니게임**\n\n{random.choice(DATING_GAMES)}"
        )

    @discord.ui.button(
        label="신고",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:report"
    )
    async def report(self, interaction, button):
        await interaction.response.send_modal(
            DatingReportModal(self.session_id)
        )

    @discord.ui.button(
        label="즉시 종료",
        style=discord.ButtonStyle.danger,
        custom_id="dating:end"
    )
    async def end(self, interaction, button):
        await interaction.response.send_message(
            "🚪 소개팅을 종료할게요.",
            ephemeral=True
        )

        await finish_dating_session(
            self.session_id,
            "참가자에 의해 종료"
        )


# =========================================================
# 소개팅 로비
# =========================================================

class DatingLobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="💗 소개팅 참가",
        style=discord.ButtonStyle.success,
        custom_id="dating:lobby_join"
    )
    async def join(self, interaction, button):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있어요.",
                ephemeral=True
            )
            return

        member = interaction.user

        if not get_dating_group(member) or not get_dating_gender(member):
            await interaction.response.send_message(
                "❌ 자기소개와 성별·출생년도를 먼저 등록해 주세요.",
                ephemeral=True
            )
            return

        active_id, _ = dating_member_session(member.id)

        if active_id:
            await interaction.response.send_message(
                "❌ 이미 진행 중인 소개팅이 있어요.",
                ephemeral=True
            )
            return

        # 대기열 ID는 저장 후 문자열일 수 있으므로 숫자로 비교
        queue_ids = [int(uid) for uid in dating_queue]

        if member.id in queue_ids:
            await interaction.response.send_message(
                "⏳ 이미 대기열에 들어가 있어요.",
                ephemeral=True
            )
            return

        candidates = []

        for uid in queue_ids:
            if uid == member.id:
                continue

            opponent = interaction.guild.get_member(uid)

            if opponent and can_dating_match(member, opponent):
                candidates.append(opponent)

        if not candidates:
            dating_queue.append(member.id)
            save_dating_data()

            await interaction.response.send_message(
                f"💗 소개팅 대기열에 들어갔어요!\n"
                f"현재 대기자: **{len(dating_queue)}명**\n"
                "조건에 맞는 상대가 참가하면 매칭됩니다.",
                ephemeral=True
            )
            return

        opponent = random.choice(candidates)

        # 두 사람을 대기열에서 제거
        dating_queue[:] = [
            int(uid) for uid in dating_queue
            if int(uid) not in (member.id, opponent.id)
        ]
        save_dating_data()

        result = await create_dating_channel(
            interaction.guild, member, opponent
        )

        if not result:
            await interaction.response.send_message(
                "❌ 채널 생성에 실패했어요. 봇의 채널 관리 권한을 확인해 주세요.",
                ephemeral=True
            )
            return

        session_id, channel = result

        await interaction.response.send_message(
            f"💗 **매칭 완료!** {channel.mention} 으로 이동해 주세요.",
            ephemeral=True
        )

        try:
            await opponent.send(
                f"💗 소개팅 매칭 완료!\n{channel.mention}에서 대화를 시작해 보세요."
            )
        except Exception:
            pass

        await channel.send(
            f"💗 **소개팅 매칭 완료!**\n\n"
            f"{member.mention} × {opponent.mention}\n\n"
            "이 채널은 두 참가자와 봇만 볼 수 있어요.\n\n"
            f"💭 **첫 질문:** 「{random.choice(DATING_QUESTIONS)}」",
            view=DatingView(session_id)
        )

    @discord.ui.button(
        label="❌ 대기 취소",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:lobby_leave"
    )
    async def leave(self, interaction, button):
        user_id = interaction.user.id

        if user_id not in [int(uid) for uid in dating_queue]:
            await interaction.response.send_message(
                "❌ 현재 대기열에 들어가 있지 않아요.",
                ephemeral=True
            )
            return

        dating_queue[:] = [
            int(uid) for uid in dating_queue
            if int(uid) != user_id
        ]
        save_dating_data()

        await interaction.response.send_message(
            "✅ 소개팅 대기열에서 나왔어요.",
            ephemeral=True
        )

    @discord.ui.button(
        label="👤 내 프로필",
        style=discord.ButtonStyle.primary,
        custom_id="dating:lobby_profile"
    )
    async def profile(self, interaction, button):
        profile_data = get_profile(interaction.user.id) or {}
        info = member_data(interaction.user)

        age = (
            profile_data.get("age")
            or info.get("birth_year")
            or "미설정"
        )
        gender = (
            profile_data.get("gender")
            or gender_text(info.get("gender"))
            or "미설정"
        )
        location = profile_data.get("location") or "미설정"
        ideal_type = profile_data.get("ideal_type") or "미설정"
        likes = profile_data.get("likes") or "미설정"

        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name}",
            description=(
                f"**{age}** · **{gender}**\n"
                f"📍 {location}\n\n"
                f"♡ **이상형**\n{ideal_type}\n\n"
                f"🎮 **좋아하는 것**\n{likes}"
            ),
            color=discord.Color.from_rgb(255, 82, 145)
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# =========================================================
# /소개팅 슬래시 명령어 등록
# =========================================================

def setup(bot):
    existing = bot.tree.get_command("소개팅")

    if existing is not None:
        bot.tree.remove_command("소개팅")

    @bot.tree.command(
        name="소개팅",
        description="소개팅 로비를 열어요."
    )
    async def dating_command(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.id != GUILD_ID:
            await interaction.response.send_message(
                "❌ 이 서버에서만 사용할 수 있어요.",
                ephemeral=True
            )
            return

        member = interaction.user

        if not get_dating_group(member) or not get_dating_gender(member):
            await interaction.response.send_message(
                "❌ 자기소개와 성별·출생년도를 먼저 등록해 주세요.",
                ephemeral=True
            )
            return

        active_id, _ = dating_member_session(member.id)

        if active_id:
            await interaction.response.send_message(
                f"❌ 이미 소개팅을 진행 중이에요. 세션: `{active_id}`",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💗 소개팅",
            description=(
                "새로운 사람을 만나볼래요?\n\n"
                "💞 **소개팅 참가** — 조건에 맞는 상대 찾기\n"
                "❌ **대기 취소** — 대기열에서 나가기\n"
                "👤 **내 프로필** — 내 프로필 확인\n\n"
                f"💗 현재 대기자 **{len(dating_queue)}명**\n\n"
                "매칭되면 두 사람만 볼 수 있는 전용 채널이 생성됩니다."
            ),
            color=discord.Color.from_rgb(255, 82, 145)
        )
        embed.set_footer(text="상대방을 존중하면서 즐겨주세요.")

        await interaction.response.send_message(
            embed=embed,
            view=DatingLobbyView()
        )
