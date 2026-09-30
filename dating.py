from core import *


# =========================================================
# 소개팅 콘텐츠
# =========================================================

DATING_CATEGORY_NAME = "💗・소개팅"
DATING_CHANNEL_PREFIX = "💞・소개팅"
DATING_TIMEOUT_MINUTES = 10


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
    "💭 서로의 첫인상 한 단어로 말하기",
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

        if member_id in session.get("members", []):
            return session_id, session

    return None, None


# =========================================================
# 소개팅 연령 그룹
# =========================================================

def get_dating_group(member):

    if member.bot:
        return None

    data = member_data(member)

    if not data.get(
        "intro_completed",
        False
    ):
        return None

    birth_year = data.get(
        "birth_year"
    )

    if not isinstance(
        birth_year,
        int
    ):
        return None

    # 2007년생까지 성인
    if birth_year <= ADULT_CUTOFF:
        return "adult"

    # 2008년생 이후는 미성년 그룹
    return "minor"


# =========================================================
# 소개팅 성별
# =========================================================

def get_dating_gender(member):

    if member.bot:
        return None

    data = member_data(member)

    if not data.get(
        "intro_completed",
        False
    ):
        return None

    gender = data.get(
        "gender"
    )

    if gender not in (
        "남",
        "여"
    ):
        return None

    return gender


# =========================================================
# 소개팅 매칭 조건
# =========================================================

def can_dating_match(
    member_a,
    member_b
):

    group_a = get_dating_group(
        member_a
    )

    group_b = get_dating_group(
        member_b
    )

    gender_a = get_dating_gender(
        member_a
    )

    gender_b = get_dating_gender(
        member_b
    )

    if not group_a or not group_b:
        return False

    if not gender_a or not gender_b:
        return False

    # 서로 같은 연령 그룹끼리만
    if group_a != group_b:
        return False

    # 같은 성별 매칭 방지
    if gender_a == gender_b:
        return False

    return True


# =========================================================
# 소개팅 카테고리
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

        print(
            f"[DATING CATEGORY ERROR] {e}"
        )

        return None


# =========================================================
# 소개팅 채널 생성
# =========================================================

async def create_dating_channel(
    guild,
    member_a,
    member_b
):

    category = await get_dating_category(
        guild
    )

    if not category:
        return None

    session_id = uuid.uuid4().hex[:6].upper()

    overwrites = {

        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        member_a:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),

        member_b:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
    }

    if guild.me:

        overwrites[guild.me] = (
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True
            )
        )

    try:

        channel = await guild.create_text_channel(
            f"{DATING_CHANNEL_PREFIX}-{session_id}",
            category=category,
            overwrites=overwrites,
            reason="소개팅 매칭 전용 채널 생성"
        )

    except Exception as e:

        print(
            f"[DATING CHANNEL ERROR] {e}"
        )

        return None

    session = {

        "channel_id":
            channel.id,

        "members":
            [
                member_a.id,
                member_b.id
            ],

        "status":
            "active",

        "created_at":
            iso(now()),

        "likes":
            [],

        "session_id":
            session_id
    }

    dating_sessions[
        session_id
    ] = session

    save_dating_data()

    return (
        session_id,
        channel
    )


# =========================================================
# 상대 프로필
# =========================================================

def dating_embed_for_member(
    viewer,
    opponent,
    session
):

    profile = get_profile(
        opponent.id
    )

    info = member_data(
        opponent
    )

    birth_year = (
        profile.get("age")
        or info.get("birth_year")
        or "미설정"
    )

    gender = (
        profile.get("gender")
        or gender_text(
            info.get("gender")
        )
    )

    location = (
        profile.get("location")
        or "미설정"
    )

    ideal_type = (
        profile.get("ideal_type")
        or "미설정"
    )

    likes = (
        profile.get("likes")
        or "미설정"
    )

    embed = discord.Embed(

        title=(
            f"💗 소개팅 · "
            f"{opponent.display_name}"
        ),

        description=(

            f"**{birth_year}** · "
            f"**{gender}**\n"

            f"📍 {location}\n\n"

            f"♡ **이상형**\n"
            f"{ideal_type}\n\n"

            f"🎮 **좋아하는 것**\n"
            f"{likes}"
        ),

        color=discord.Color.from_rgb(
            255,
            82,
            145
        )
    )

    embed.set_thumbnail(
        url=opponent.display_avatar.url
    )

    embed.set_footer(
        text=(
            f"소개팅 세션 · "
            f"{session.get('session_id', '')}"
        )
    )

    return embed


# =========================================================
# 소개팅 종료
# =========================================================

async def finish_dating_session(
    session_id,
    reason="소개팅 종료"
):

    session = dating_sessions.get(
        session_id
    )

    if not session:
        return

    session["status"] = "ended"
    session["ended_at"] = iso(now())

    save_dating_data()

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:
        return

    channel = guild.get_channel(
        session.get("channel_id")
    )

    if channel:

        try:

            await channel.send(
                f"🚪 **소개팅이 종료되었습니다.**\n"
                f"사유: `{reason}`\n\n"
                "이 채널은 잠시 후 정리됩니다."
            )

            await asyncio.sleep(5)

        except Exception:
            pass

        try:

            await channel.delete(
                reason=reason
            )

        except Exception as e:

            print(
                f"[DATING DELETE ERROR] {e}"
            )


# =========================================================
# 신고 모달
# =========================================================

class DatingReportModal(
    discord.ui.Modal,
    title="소개팅 신고"
):

    reason = discord.ui.TextInput(
        label="신고 사유",
        placeholder="신고할 내용을 적어주세요.",
        required=True,
        max_length=500
    )

    async def on_submit(
        self,
        interaction
    ):

        session_id = getattr(
            self,
            "session_id",
            None
        )

        session = (
            dating_sessions.get(
                session_id
            )
            if session_id
            else None
        )

        log = get_log_channel(
            interaction.guild
        )

        if log:

            await log.send(

                f"🚨 **소개팅 신고**\n"
                f"신고자: {interaction.user.mention}\n"
                f"세션: `{session_id or '알 수 없음'}`\n"
                f"사유: `{self.reason.value}`"
            )

        await interaction.response.send_message(
            "✅ 신고가 접수되었습니다. 관리자에게 전달했어요.",
            ephemeral=True
        )


# =========================================================
# 소개팅 진행 View
# =========================================================

class DatingView(
    discord.ui.View
):

    def __init__(
        self,
        session_id
    ):

        super().__init__(
            timeout=None
        )

        self.session_id = session_id

        for item in self.children:

            if isinstance(
                item,
                discord.ui.Button
            ):

                item.custom_id = (
                    f"dating:"
                    f"{session_id}:"
                    f"{item.custom_id.split(':')[-1]}"
                )

    def get_session(self):

        return dating_sessions.get(
            self.session_id
        )

    def get_opponent(
        self,
        user_id
    ):

        session = self.get_session()

        if not session:
            return None

        opponent_id = next(

            (
                uid
                for uid in session.get(
                    "members",
                    []
                )
                if uid != user_id
            ),

            None
        )

        if opponent_id is None:
            return None

        guild = bot.get_guild(
            GUILD_ID
        )

        return (
            guild.get_member(
                opponent_id
            )
            if guild
            else None
        )

    async def interaction_check(
        self,
        interaction
    ):

        session = self.get_session()

        if (
            not session
            or session.get("status") != "active"
        ):

            await interaction.response.send_message(
                "❌ 이미 종료된 소개팅입니다.",
                ephemeral=True
            )

            return False

        if (
            interaction.user.id
            not in session.get(
                "members",
                []
            )
        ):

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
    async def info(
        self,
        interaction,
        button
    ):

        opponent = self.get_opponent(
            interaction.user.id
        )

        session = self.get_session()

        if not opponent:

            await interaction.response.send_message(
                "❌ 상대를 찾을 수 없습니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(

            embed=dating_embed_for_member(
                interaction.user,
                opponent,
                session
            ),

            ephemeral=True
        )

    @discord.ui.button(
        label="오늘의 질문",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:question"
    )
    async def question(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(

            f"💭 **오늘의 질문**\n\n"
            f"「{random.choice(DATING_QUESTIONS)}」",

            ephemeral=False
        )

    @discord.ui.button(
        label="💚 호감 보내기",
        style=discord.ButtonStyle.success,
        custom_id="dating:like"
    )
    async def like(
        self,
        interaction,
        button
    ):

        session = self.get_session()

        likes = session.setdefault(
            "likes",
            []
        )

        if interaction.user.id not in likes:

            likes.append(
                interaction.user.id
            )

            save_dating_data()

        opponent = self.get_opponent(
            interaction.user.id
        )

        if (
            opponent
            and opponent.id in likes
        ):

            await interaction.response.send_message(

                f"🎉 **서로 호감이 확인됐어요!**\n\n"
                f"💗 {interaction.user.mention} × "
                f"{opponent.mention}\n"
                "두 분 모두 서로에게 호감을 보냈습니다!",

                ephemeral=False
            )

            try:

                await interaction.user.send(
                    f"💗 소개팅 결과\n"
                    f"{opponent.display_name}님과 "
                    f"서로 호감이 확인됐어요!"
                )

            except Exception:
                pass

            try:

                await opponent.send(
                    f"💗 소개팅 결과\n"
                    f"{interaction.user.display_name}님과 "
                    f"서로 호감이 확인됐어요!"
                )

            except Exception:
                pass

        else:

            await interaction.response.send_message(

                "💚 호감을 보냈어요. "
                "상대방도 호감을 보내면 서로 매칭됩니다!",

                ephemeral=True
            )

    @discord.ui.button(
        label="🎮 미니게임",
        style=discord.ButtonStyle.primary,
        custom_id="dating:game"
    )
    async def game(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(

            f"🎮 **미니게임**\n\n"
            f"{random.choice(DATING_GAMES)}",

            ephemeral=False
        )

    @discord.ui.button(
        label="신고/차단",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:report"
    )
    async def report(
        self,
        interaction,
        button
    ):

        modal = DatingReportModal()

        modal.session_id = self.session_id

        await interaction.response.send_modal(
            modal
        )

    @discord.ui.button(
        label="즉시 종료",
        style=discord.ButtonStyle.danger,
        custom_id="dating:end"
    )
    async def end(
        self,
        interaction,
        button
    ):

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

class DatingLobbyView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="💗 소개팅 참가",
        style=discord.ButtonStyle.success,
        custom_id="dating:lobby_join"
    )
    async def join(
        self,
        interaction,
        button
    ):

        member = interaction.user

        member_group = get_dating_group(
            member
        )

        member_gender = get_dating_gender(
            member
        )

        if (
            not member_group
            or not member_gender
        ):

            await interaction.response.send_message(

                "❌ 자기소개를 완료하고 "
                "성별·출생년도가 정상적으로 등록된 "
                "회원만 소개팅에 참가할 수 있어요.",

                ephemeral=True
            )

            return

        active_id, _ = dating_member_session(
            member.id
        )

        if active_id:

            await interaction.response.send_message(
                "❌ 이미 진행 중인 소개팅이 있어요.",
                ephemeral=True
            )

            return

        if member.id in dating_queue:

            await interaction.response.send_message(
                "⏳ 이미 소개팅 대기열에 들어가 있어요.",
                ephemeral=True
            )

            return

        dating_queue.append(
            member.id
        )

        candidates = []

        for uid in dating_queue:

            if uid == member.id:
                continue

            opponent = interaction.guild.get_member(
                uid
            )

            if not opponent:
                continue

            if can_dating_match(
                member,
                opponent
            ):

                candidates.append(
                    uid
                )

        opponent_id = (
            random.choice(candidates)
            if candidates
            else None
        )

        if opponent_id is None:

            save_dating_data()

            await interaction.response.send_message(

                f"💗 소개팅 대기열에 들어갔어요!\n"
                f"현재 대기자: `{len(dating_queue)}명`\n\n"
                "조건에 맞는 상대가 참가하면 "
                "자동으로 매칭됩니다.",

                ephemeral=True
            )

            return

        dating_queue.remove(
            member.id
        )

        dating_queue.remove(
            opponent_id
        )

        opponent = interaction.guild.get_member(
            opponent_id
        )

        if not opponent:

            if opponent_id not in dating_queue:
                dating_queue.append(
                    opponent_id
                )

            save_dating_data()

            await interaction.response.send_message(
                "⏳ 상대를 찾지 못해서 다시 대기열로 돌렸어요.",
                ephemeral=True
            )

            return

        if not can_dating_match(
            member,
            opponent
        ):

            if opponent_id not in dating_queue:
                dating_queue.append(
                    opponent_id
                )

            if member.id not in dating_queue:
                dating_queue.append(
                    member.id
                )

            save_dating_data()

            await interaction.response.send_message(
                "⏳ 현재 조건에 맞는 상대가 없어 대기열에 남아있어요.",
                ephemeral=True
            )

            return

        result = await create_dating_channel(
            interaction.guild,
            member,
            opponent
        )

        if not result:

            dating_queue.extend(
                [
                    member.id,
                    opponent.id
                ]
            )

            save_dating_data()

            await interaction.response.send_message(

                "❌ 소개팅 채널을 만들지 못했습니다. "
                "봇의 채널 관리 권한을 확인해주세요.",

                ephemeral=True
            )

            return

        session_id, channel = result

        await interaction.response.send_message(

            f"💗 **소개팅 매칭 완료!**\n"
            f"{channel.mention} 으로 이동해주세요.",

            ephemeral=True
        )

        try:

            await opponent.send(

                f"💗 소개팅 매칭이 완료됐어요!\n"
                f"{channel.mention} 에서 상대방과 대화해보세요."
            )

        except Exception:
            pass

        await channel.send(

            f"💗 **소개팅 매칭 완료!**\n\n"
            f"{member.mention} × "
            f"{opponent.mention}\n\n"

            "이 채널은 두 분과 봇만 볼 수 있는 "
            "전용 채팅방입니다.\n"

            f"💭 **첫 질문:** "
            f"「{random.choice(DATING_QUESTIONS)}」",

            view=DatingView(
                session_id
            )
        )

    @discord.ui.button(
        label="❌ 대기 취소",
        style=discord.ButtonStyle.secondary,
        custom_id="dating:lobby_leave"
    )
    async def leave(
        self,
        interaction,
        button
    ):

        if interaction.user.id not in dating_queue:

            await interaction.response.send_message(
                "❌ 현재 소개팅 대기열에 들어가 있지 않아요.",
                ephemeral=True
            )

            return

        dating_queue.remove(
            interaction.user.id
        )

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
    async def profile(
        self,
        interaction,
        button
    ):

        profile_data = get_profile(
            interaction.user.id
        )

        info = member_data(
            interaction.user
        )

        age = (
            profile_data.get("age")
            or info.get("birth_year")
            or "미설정"
        )

        gender = (
            profile_data.get("gender")
            or gender_text(
                info.get("gender")
            )
            or "미설정"
        )

        location = (
            profile_data.get("location")
            or "미설정"
        )

        ideal_type = (
            profile_data.get("ideal_type")
            or "미설정"
        )

        likes = (
            profile_data.get("likes")
            or "미설정"
        )

        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name}",
            description=(
                f"**{age}** · **{gender}**\n"
                f"📍 {location}\n\n"
                f"♡ 이상형\n"
                f"{ideal_type}\n\n"
                f"🎮 좋아하는 것\n"
                f"{likes}"
            ),
            color=discord.Color.from_rgb(
                255,
                82,
                145
            )
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# =========================================================
# !소개팅 명령어
# =========================================================

@bot.command(
    name="소개팅"
)
async def dating_command(
    ctx
):

    member_group = get_dating_group(
        ctx.author
    )

    member_gender = get_dating_gender(
        ctx.author
    )

    if (
        not member_group
        or not member_gender
    ):

        await ctx.send(

            "❌ 자기소개를 완료하고 "
            "성별·출생년도가 정상적으로 등록된 "
            "회원만 `!소개팅`을 이용할 수 있어요."

        )

        return

    active_id, _ = dating_member_session(
        ctx.author.id
    )

    if active_id:

        await ctx.send(
            f"❌ 이미 소개팅을 진행 중이에요. "
            f"세션: `{active_id}`"
        )

        return

    queue_count = len(
        dating_queue
    )

    embed = discord.Embed(

        title="💗 소개팅",

        description=(

            "새로운 사람을 만나볼래요?\n\n"

            "버튼을 눌러 참가하면 "
            "조건에 맞는 상대와 매칭됩니다.\n"

            "매칭되면 두 사람만 볼 수 있는 "
            "전용 채팅방이 자동으로 생성돼요.\n\n"

            f"💗 현재 대기자 "
            f"**{queue_count}명**\n\n"

            "⚠️ 연령대가 다른 회원끼리는 "
            "매칭되지 않습니다."

        ),

        color=discord.Color.from_rgb(
            255,
            82,
            145
        )
    )

    embed.set_footer(
        text="상대방을 존중하면서 즐겨주세요."
    )

    await ctx.send(
        embed=embed,
        view=DatingLobbyView()
    )
