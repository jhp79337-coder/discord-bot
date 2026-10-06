from core import *
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput


# =========================================================
# 소개팅 설정
# =========================================================

DATING_CATEGORY_NAME = "💗・소개팅"
DATING_CHANNEL_PREFIX = "💞・소개팅"
DATING_TIMEOUT_MINUTES = 10


DATING_QUESTIONS = [
    "최근에 가장 재밌었던 일은?",
    "주말에 보통 뭐 하면서 보내요?",
    "요즘 가장 자주 듣는 노래는?",
    "좋아하는 음식은?",
    "이상형은 어떤 스타일이에요?",
    "첫인상은 어땠어요?",
    "요즘 가장 하고 싶은 것은?",
    "여행 간다면 어디로 가고 싶어요?",
    "연애할 때 가장 중요하다고 생각하는 것은?",
    "상대방에게 바라는 점은?"
]


DATING_GAMES = [
    "밸런스 게임",
    "초성 퀴즈",
    "이상형 월드컵",
    "진실 혹은 거짓",
    "랜덤 질문",
]


# =========================================================
# 저장
# =========================================================

def save_dating_data():
    try:
        save_json("dating_queue.json", dating_queue)
    except Exception as e:
        print(f"[DATING SAVE ERROR] dating_queue.json: {e}")

    try:
        save_json("dating_sessions.json", dating_sessions)
    except Exception as e:
        print(f"[DATING SAVE ERROR] dating_sessions.json: {e}")


# =========================================================
# 데이터
# =========================================================

def dating_member_session(member_id):
    return dating_sessions.get(str(member_id))


def get_dating_group(member):
    if not member:
        return None

    if member.bot:
        return None

    data = member_data(member)

    if not data.get("intro_completed", False):
        return None

    birth_year = data.get("birth_year")

    try:
        birth_year = int(birth_year)
    except (TypeError, ValueError):
        return None

    if birth_year <= ADULT_CUTOFF:
        return "adult"

    return "minor"


def get_dating_gender(member):
    if not member:
        return None

    if member.bot:
        return None

    data = member_data(member)

    if not data.get("intro_completed", False):
        return None

    gender = data.get("gender")

    if gender is None:
        return None

    gender = str(gender).strip()

    male_values = {
        "남",
        "남자",
        "ㄴ",
        "M",
        "m",
        "male",
        "Male",
        "MALE",
    }

    female_values = {
        "여",
        "여자",
        "ㅇ",
        "F",
        "f",
        "female",
        "Female",
        "FEMALE",
    }

    if gender in male_values:
        return "남"

    if gender in female_values:
        return "여"

    return None


# =========================================================
# 핵심 매칭 검사
# =========================================================

def can_dating_match(member_a, member_b):
    """
    소개팅 매칭 가능 여부

    조건:
    1. 서로 다른 사람
    2. 봇 아님
    3. 자기소개 완료
    4. 같은 연령 그룹
    5. 성별 정보 정상
    6. 남 ↔ 여만 허용
    """

    if not member_a or not member_b:
        return False

    if member_a.id == member_b.id:
        return False

    if member_a.bot or member_b.bot:
        return False

    group_a = get_dating_group(member_a)
    group_b = get_dating_group(member_b)

    gender_a = get_dating_gender(member_a)
    gender_b = get_dating_gender(member_b)

    print(
        f"[DATING CHECK] "
        f"{member_a.display_name} ({member_a.id}) = "
        f"{group_a}/{gender_a} | "
        f"{member_b.display_name} ({member_b.id}) = "
        f"{group_b}/{gender_b}"
    )

    if not group_a or not group_b:
        print(
            f"[DATING MATCH] "
            f"연령 그룹 확인 실패: "
            f"{member_a.id}={group_a}, "
            f"{member_b.id}={group_b}"
        )
        return False

    if not gender_a or not gender_b:
        print(
            f"[DATING MATCH] "
            f"성별 확인 실패: "
            f"{member_a.id}={gender_a}, "
            f"{member_b.id}={gender_b}"
        )
        return False

    # 성인 ↔ 미성년자 차단
    if group_a != group_b:
        print(
            f"[DATING MATCH] "
            f"연령 그룹 불일치: "
            f"{member_a.id}={group_a}, "
            f"{member_b.id}={group_b}"
        )
        return False

    # =====================================================
    # 남 ↔ 여만 허용
    # =====================================================

    if gender_a == "남" and gender_b == "여":
        print(
            f"[DATING MATCH] "
            f"매칭 가능: "
            f"{member_a.id}({group_a}/{gender_a}) ↔ "
            f"{member_b.id}({group_b}/{gender_b})"
        )
        return True

    if gender_a == "여" and gender_b == "남":
        print(
            f"[DATING MATCH] "
            f"매칭 가능: "
            f"{member_a.id}({group_a}/{gender_a}) ↔ "
            f"{member_b.id}({group_b}/{gender_b})"
        )
        return True

    # 남남 / 여여 차단
    print(
        f"[DATING MATCH] "
        f"동성 매칭 차단: "
        f"{member_a.id}={gender_a}, "
        f"{member_b.id}={gender_b}"
    )

    return False


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
        category = await guild.create_category(
            DATING_CATEGORY_NAME
        )
        return category

    except Exception as e:
        print(f"[DATING CATEGORY ERROR] {e}")
        return None


# =========================================================
# 소개팅 채널 생성
# =========================================================

async def create_dating_channel(member_a, member_b):
    if not member_a or not member_b:
        return None

    # 마지막 안전장치
    if not can_dating_match(member_a, member_b):
        print(
            f"[DATING BLOCK] "
            f"잘못된 매칭 차단: "
            f"{member_a.id} / {member_b.id}"
        )
        return None

    guild = member_a.guild

    category = await get_dating_category(guild)

    if not category:
        return None

    channel_name = (
        f"{DATING_CHANNEL_PREFIX}-"
        f"{member_a.display_name}-"
        f"{member_b.display_name}"
    )

    channel_name = channel_name[:90]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),

        member_a: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),

        member_b: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),
    }

    try:
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        return channel

    except Exception as e:
        print(f"[DATING CHANNEL ERROR] {e}")
        return None


# =========================================================
# 소개팅 임베드
# =========================================================

def create_dating_embed(member_a, member_b):
    embed = discord.Embed(
        title="💗 소개팅이 시작됐어요!",
        description=(
            f"{member_a.mention} × {member_b.mention}\n\n"
            "편하게 대화를 시작해보세요 💕\n"
            "서로 존중하면서 즐거운 시간 보내주세요!"
        ),
        color=discord.Color.from_rgb(
            255,
            170,
            200
        )
    )

    embed.add_field(
        name="💬 오늘의 질문",
        value="버튼을 눌러 질문을 확인해보세요!",
        inline=False
    )

    embed.add_field(
        name="💗 호감",
        value="상대방에게 호감이 있다면 눌러주세요.",
        inline=False
    )

    embed.add_field(
        name="🎮 미니게임",
        value="가볍게 게임하면서 친해져보세요!",
        inline=False
    )

    embed.set_footer(
        text="소개팅 채널은 10분 동안 유지됩니다."
    )

    return embed


# =========================================================
# 세션 종료
# =========================================================

async def finish_dating_session(
    channel,
    member_a=None,
    member_b=None
):
    try:
        if member_a:
            dating_sessions.pop(
                str(member_a.id),
                None
            )

        if member_b:
            dating_sessions.pop(
                str(member_b.id),
                None
            )

        save_dating_data()

        await channel.send(
            "💗 소개팅이 종료되었습니다.\n"
            "잠시 후 이 채널이 삭제됩니다."
        )

        await asyncio.sleep(5)

        try:
            await channel.delete(
                reason="소개팅 종료"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[DATING FINISH ERROR] {e}")


# =========================================================
# 신고 모달
# =========================================================

class DatingReportModal(Modal):
    def __init__(self):
        super().__init__(
            title="🚨 소개팅 신고"
        )

        self.reason = TextInput(
            label="신고 사유",
            placeholder="신고 내용을 입력해주세요.",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )

        self.add_item(self.reason)

    async def on_submit(self, interaction):
        guild = interaction.guild

        report_channel = None

        for name in (
            "신고",
            "🚨・신고",
            "관리자",
            "📋・관리자"
        ):
            report_channel = discord.utils.get(
                guild.text_channels,
                name=name
            )

            if report_channel:
                break

        if report_channel:
            embed = discord.Embed(
                title="🚨 소개팅 신고",
                color=discord.Color.red()
            )

            embed.add_field(
                name="신고자",
                value=(
                    f"{interaction.user.mention}\n"
                    f"`{interaction.user.id}`"
                ),
                inline=False
            )

            embed.add_field(
                name="채널",
                value=interaction.channel.mention,
                inline=False
            )

            embed.add_field(
                name="사유",
                value=self.reason.value,
                inline=False
            )

            await report_channel.send(
                embed=embed
            )

        await interaction.response.send_message(
            "🚨 신고가 접수되었습니다.",
            ephemeral=True
        )


# =========================================================
# 소개팅 버튼
# =========================================================

class DatingView(View):
    def __init__(
        self,
        member_a,
        member_b,
        timeout=DATING_TIMEOUT_MINUTES * 60
    ):
        super().__init__(
            timeout=timeout
        )

        self.member_a = member_a
        self.member_b = member_b

    # -----------------------------------------------------
    # 상대정보
    # -----------------------------------------------------

    @discord.ui.button(
        label="상대정보",
        emoji="👤",
        style=discord.ButtonStyle.secondary
    )
    async def opponent_profile(
        self,
        interaction,
        button
    ):
        if interaction.user.id not in (
            self.member_a.id,
            self.member_b.id
        ):
            await interaction.response.send_message(
                "❌ 이 소개팅 참가자가 아닙니다.",
                ephemeral=True
            )
            return

        opponent = (
            self.member_b
            if interaction.user.id == self.member_a.id
            else self.member_a
        )

        data = member_data(opponent)

        birth_year = data.get(
            "birth_year",
            "미등록"
        )

        gender = data.get(
            "gender",
            "미등록"
        )

        embed = discord.Embed(
            title="👤 상대방 정보",
            color=discord.Color.from_rgb(
                255,
                170,
                200
            )
        )

        embed.add_field(
            name="닉네임",
            value=opponent.display_name,
            inline=False
        )

        embed.add_field(
            name="성별",
            value=str(gender),
            inline=True
        )

        embed.add_field(
            name="출생년도",
            value=str(birth_year),
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # -----------------------------------------------------
    # 오늘의 질문
    # -----------------------------------------------------

    @discord.ui.button(
        label="오늘의 질문",
        emoji="💬",
        style=discord.ButtonStyle.primary
    )
    async def question(
        self,
        interaction,
        button
    ):
        import random

        question = random.choice(
            DATING_QUESTIONS
        )

        await interaction.response.send_message(
            f"💬 **오늘의 질문**\n\n{question}"
        )

    # -----------------------------------------------------
    # 호감
    # -----------------------------------------------------

    @discord.ui.button(
        label="호감",
        emoji="💗",
        style=discord.ButtonStyle.success
    )
    async def like(
        self,
        interaction,
        button
    ):
        if interaction.user.id == self.member_a.id:
            target = self.member_b
        elif interaction.user.id == self.member_b.id:
            target = self.member_a
        else:
            await interaction.response.send_message(
                "❌ 참가자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"💗 {target.display_name}님에게 호감을 표시했어요!",
            ephemeral=True
        )

        try:
            await target.send(
                "💗 현재 소개팅 상대가 당신에게 호감을 표시했어요!"
            )
        except Exception:
            pass

    # -----------------------------------------------------
    # 미니게임
    # -----------------------------------------------------

    @discord.ui.button(
        label="미니게임",
        emoji="🎮",
        style=discord.ButtonStyle.secondary
    )
    async def minigame(
        self,
        interaction,
        button
    ):
        import random

        game = random.choice(
            DATING_GAMES
        )

        await interaction.response.send_message(
            f"🎮 **오늘의 미니게임**\n\n"
            f"👉 {game}\n\n"
            "서로 질문하면서 즐겨보세요!"
        )

    # -----------------------------------------------------
    # 신고 / 차단
    # -----------------------------------------------------

    @discord.ui.button(
        label="신고/차단",
        emoji="🚨",
        style=discord.ButtonStyle.danger
    )
    async def report(
        self,
        interaction,
        button
    ):
        if interaction.user.id not in (
            self.member_a.id,
            self.member_b.id
        ):
            await interaction.response.send_message(
                "❌ 참가자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            DatingReportModal()
        )

    # -----------------------------------------------------
    # 즉시 종료
    # -----------------------------------------------------

    @discord.ui.button(
        label="즉시 종료",
        emoji="🛑",
        style=discord.ButtonStyle.danger
    )
    async def finish(
        self,
        interaction,
        button
    ):
        if interaction.user.id not in (
            self.member_a.id,
            self.member_b.id
        ):
            await interaction.response.send_message(
                "❌ 참가자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🛑 소개팅을 종료합니다."
        )

        await finish_dating_session(
            interaction.channel,
            self.member_a,
            self.member_b
        )


# =========================================================
# 소개팅 대기방
# =========================================================

class DatingLobbyView(View):
    def __init__(self):
        super().__init__(
            timeout=None
        )

    # -----------------------------------------------------
    # 참가
    # -----------------------------------------------------

    @discord.ui.button(
        label="소개팅 참가",
        emoji="💗",
        style=discord.ButtonStyle.success,
        custom_id="dating_join"
    )
    async def join(
        self,
        interaction,
        button
    ):
        member = interaction.user

        if member.bot:
            await interaction.response.send_message(
                "❌ 봇은 참가할 수 없습니다.",
                ephemeral=True
            )
            return

        data = member_data(member)

        if not data.get(
            "intro_completed",
            False
        ):
            await interaction.response.send_message(
                "❌ 자기소개를 먼저 완료해주세요.",
                ephemeral=True
            )
            return

        group = get_dating_group(member)
        gender = get_dating_gender(member)

        if not group or not gender:
            await interaction.response.send_message(
                "❌ 소개팅에 필요한 프로필 정보가 없습니다.",
                ephemeral=True
            )
            return

        # 이미 매칭 중인지 확인
        if dating_member_session(member.id):
            await interaction.response.send_message(
                "❌ 이미 소개팅을 진행 중입니다.",
                ephemeral=True
            )
            return

        user_id = str(member.id)

        # 이미 대기열에 있으면 중복 참가 방지
        if user_id in [
            str(x)
            for x in dating_queue
        ]:
            await interaction.response.send_message(
                "⏳ 이미 소개팅을 기다리고 있습니다.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # 대기열 검사
        # -------------------------------------------------

        opponent = None

        for queued_id in list(dating_queue):
            try:
                queued_member = interaction.guild.get_member(
                    int(queued_id)
                )

                if not queued_member:
                    continue

                # 핵심: 여기서 남남/여여를 다시 검사
                if can_dating_match(
                    member,
                    queued_member
                ):
                    opponent = queued_member
                    break

            except Exception as e:
                print(
                    f"[DATING QUEUE CHECK ERROR] {e}"
                )

        # -------------------------------------------------
        # 상대를 찾은 경우
        # -------------------------------------------------

        if opponent:
            # 대기열에서 상대 제거
            try:
                dating_queue.remove(
                    str(opponent.id)
                )
            except ValueError:
                pass

            # 현재 사용자도 대기열에 넣지 않음
            try:
                while str(member.id) in [
                    str(x)
                    for x in dating_queue
                ]:
                    dating_queue.remove(
                        str(member.id)
                    )
            except ValueError:
                pass

            # 마지막 안전 검사
            if not can_dating_match(
                member,
                opponent
            ):
                await interaction.response.send_message(
                    "❌ 상대방의 프로필 정보가 변경되어 매칭할 수 없습니다.",
                    ephemeral=True
                )
                save_dating_data()
                return

            channel = await create_dating_channel(
                member,
                opponent
            )

            if not channel:
                await interaction.response.send_message(
                    "❌ 소개팅 채널을 만들지 못했습니다.",
                    ephemeral=True
                )
                save_dating_data()
                return

            dating_sessions[str(member.id)] = {
                "partner_id": opponent.id,
                "channel_id": channel.id,
                "started_at": iso(now())
            }

            dating_sessions[str(opponent.id)] = {
                "partner_id": member.id,
                "channel_id": channel.id,
                "started_at": iso(now())
            }

            save_dating_data()

            await interaction.response.send_message(
                f"💗 **매칭 성공!**\n"
                f"{opponent.mention}님과 매칭되었습니다!\n"
                f"{channel.mention}",
                ephemeral=True
            )

            embed = create_dating_embed(
                member,
                opponent
            )

            await channel.send(
                content=(
                    f"{member.mention} {opponent.mention}"
                ),
                embed=embed,
                view=DatingView(
                    member,
                    opponent
                )
            )

            return

        # -------------------------------------------------
        # 상대를 못 찾은 경우
        # -------------------------------------------------

        dating_queue.append(
            str(member.id)
        )

        save_dating_data()

        await interaction.response.send_message(
            "⏳ 소개팅 대기열에 들어갔어요!\n"
            "알맞은 상대가 들어오면 자동으로 매칭됩니다 💗",
            ephemeral=True
        )

    # -----------------------------------------------------
    # 대기 취소
    # -----------------------------------------------------

    @discord.ui.button(
        label="대기 취소",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="dating_cancel"
    )
    async def cancel(
        self,
        interaction,
        button
    ):
        user_id = str(
            interaction.user.id
        )

        removed = False

        while user_id in [
            str(x)
            for x in dating_queue
        ]:
            try:
                dating_queue.remove(
                    user_id
                )
                removed = True
            except ValueError:
                break

        save_dating_data()

        if removed:
            await interaction.response.send_message(
                "❌ 소개팅 대기를 취소했습니다.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "현재 소개팅 대기 중이 아닙니다.",
                ephemeral=True
            )

    # -----------------------------------------------------
    # 내 프로필
    # -----------------------------------------------------

    @discord.ui.button(
        label="내 프로필",
        emoji="👤",
        style=discord.ButtonStyle.secondary,
        custom_id="dating_my_profile"
    )
    async def profile(
        self,
        interaction,
        button
    ):
        try:
            member = interaction.user

            data = member_data(member)

            if not isinstance(data, dict):
                data = {}

            birth_year = data.get(
                "birth_year",
                "미등록"
            )

            gender = data.get(
                "gender",
                "미등록"
            )

            location = data.get(
                "location",
                "미등록"
            )

            ideal_type = data.get(
                "ideal_type",
                "미등록"
            )

            likes = data.get(
                "likes",
                "미등록"
            )

            embed = discord.Embed(
                title="👤 내 소개팅 프로필",
                color=discord.Color.from_rgb(
                    255,
                    170,
                    200
                )
            )

            embed.set_author(
                name=member.display_name,
                icon_url=member.display_avatar.url
            )

            embed.add_field(
                name="🎂 출생년도",
                value=str(birth_year),
                inline=True
            )

            embed.add_field(
                name="⚧ 성별",
                value=str(gender),
                inline=True
            )

            embed.add_field(
                name="📍 지역",
                value=str(location),
                inline=True
            )

            embed.add_field(
                name="💗 이상형",
                value=str(ideal_type),
                inline=False
            )

            embed.add_field(
                name="❤️ 좋아하는 것",
                value=str(likes),
                inline=False
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except Exception as e:
            print(
                f"[DATING PROFILE ERROR] {e}"
            )

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ 프로필을 불러오는 중 오류가 발생했습니다.",
                    ephemeral=True
                )


# =========================================================
# !소개팅
# =========================================================

@bot.command(name="소개팅")
async def dating_command(ctx):
    try:
        member = ctx.author

        if member.bot:
            return

        data = member_data(member)

        if not data.get(
            "intro_completed",
            False
        ):
            await ctx.send(
                f"{member.mention} ❌ "
                "소개팅을 이용하려면 먼저 자기소개를 완료해주세요."
            )
            return

        group = get_dating_group(member)
        gender = get_dating_gender(member)

        if not group or not gender:
            await ctx.send(
                f"{member.mention} ❌ "
                "소개팅에 필요한 프로필 정보가 없습니다."
            )
            return

        embed = discord.Embed(
            title="💗 소개팅",
            description=(
                "새로운 인연을 만나보세요!\n\n"
                "아래 버튼을 눌러 소개팅에 참가할 수 있습니다.\n\n"
                "💗 **소개팅 참가**\n"
                "알맞은 상대가 있으면 자동으로 매칭됩니다.\n\n"
                "❌ **대기 취소**\n"
                "현재 대기 중인 소개팅을 취소합니다.\n\n"
                "👤 **내 프로필**\n"
                "현재 등록된 프로필을 확인합니다."
            ),
            color=discord.Color.from_rgb(
                255,
                170,
                200
            )
        )

        embed.set_footer(
            text="자기소개 완료 회원만 이용할 수 있습니다."
        )

        await ctx.send(
            embed=embed,
            view=DatingLobbyView()
        )

    except Exception as e:
        print(
            f"[DATING COMMAND ERROR] {e}"
        )

        await ctx.send(
            "❌ 소개팅 기능을 불러오는 중 오류가 발생했습니다."
        )
