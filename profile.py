
from core import *
from discord import app_commands


# =========================================================
# 프로필 공통
# =========================================================

def get_profile(user_id):
    uid = str(user_id)

    if uid not in profiles:
        profiles[uid] = {
            "age": None,
            "location": None,
            "gender": None,
            "ideal_type": None,
            "likes": None,
        }

    return profiles[uid]


# =========================================================
# 프로필 편집 모달
# =========================================================

class ProfileModal(discord.ui.Modal, title="프로필 편집"):
    age = discord.ui.TextInput(
        label="나이",
        placeholder="예: 04",
        required=False,
        max_length=10,
    )

    location = discord.ui.TextInput(
        label="사는 곳",
        placeholder="예: 서울",
        required=False,
        max_length=50,
    )

    gender = discord.ui.TextInput(
        label="성별",
        placeholder="예: 남 / 여",
        required=False,
        max_length=10,
    )

    ideal_type = discord.ui.TextInput(
        label="이상형",
        placeholder="예: 웃는 게 예쁜 사람",
        required=False,
        max_length=200,
    )

    likes = discord.ui.TextInput(
        label="좋아하는 것",
        placeholder="예: 게임, 음악, 영화",
        required=False,
        max_length=200,
    )

    def __init__(self, owner_id):
        super().__init__()
        self.owner_id = owner_id

        data = get_profile(owner_id)
        self.age.default = data.get("age") or ""
        self.location.default = data.get("location") or ""
        self.gender.default = data.get("gender") or ""
        self.ideal_type.default = data.get("ideal_type") or ""
        self.likes.default = data.get("likes") or ""

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ 본인 프로필만 수정할 수 있어요.",
                ephemeral=True,
            )

        uid = str(interaction.user.id)

        profiles[uid] = {
            "age": self.age.value.strip() or None,
            "location": self.location.value.strip() or None,
            "gender": self.gender.value.strip() or None,
            "ideal_type": self.ideal_type.value.strip() or None,
            "likes": self.likes.value.strip() or None,
        }

        try:
            await save_profile_to_db(uid, profiles[uid])
        except Exception as e:
            print(f"[PROFILE SAVE ERROR] {e}")
            return await interaction.response.send_message(
                "❌ 프로필 저장에 실패했어요. Railway 로그를 확인해 주세요.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "✅ 프로필을 저장했어요! `/프로필`로 확인할 수 있어요.",
            ephemeral=True,
        )


# =========================================================
# 프로필 카드 버튼
# =========================================================

class ProfileCardView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    @discord.ui.button(
        label="프로필 편집",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
    )
    async def edit_profile(self, interaction, button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ 본인 프로필에서만 수정할 수 있어요.",
                ephemeral=True,
            )

        await interaction.response.send_modal(
            ProfileModal(self.owner_id)
        )

    @discord.ui.button(
        label="소개팅",
        emoji="💗",
        style=discord.ButtonStyle.success,
    )
    async def dating(self, interaction, button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ 본인 프로필에서만 사용할 수 있어요.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "💗 소개팅에 참가하려면 `/소개팅` 명령어를 사용해 주세요.",
            ephemeral=True,
        )


class ProfileEditView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    @discord.ui.button(
        label="프로필 편집",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
    )
    async def edit(self, interaction, button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ 본인 프로필만 수정할 수 있어요.",
                ephemeral=True,
            )

        await interaction.response.send_modal(
            ProfileModal(self.owner_id)
        )


# =========================================================
# 슬래시 명령어 등록
# =========================================================

def setup(bot):

    @bot.tree.command(
        name="프로필",
        description="내 프로필을 확인합니다.",
    )
    @app_commands.guild_only()
    async def profile_command(interaction: discord.Interaction):
        profile = get_profile(interaction.user.id)

        member_info = members.get(
            str(interaction.user.id),
            {},
        )

        birth_year = (
            profile.get("age")
            or member_info.get("birth_year")
        )

        raw_gender = profile.get("gender")
        if raw_gender:
            gender = raw_gender
        else:
            gender = gender_text(member_info.get("gender"))

        location = profile.get("location") or "미설정"
        ideal_type = profile.get("ideal_type") or "미설정"
        likes = profile.get("likes") or "미설정"

        embed = discord.Embed(
            title=f"💗 {interaction.user.display_name}님의 프로필",
            description=(
                f"**{birth_year or '나이 미설정'}** · **{gender or '성별 미설정'}**\n"
                f"📍 {location}"
            ),
            color=discord.Color.from_rgb(255, 82, 145),
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        embed.add_field(
            name="♡ 이상형",
            value=ideal_type,
            inline=False,
        )

        embed.add_field(
            name="🎮 좋아하는 것",
            value=likes,
            inline=False,
        )

        embed.add_field(
            name="💬 소개팅",
            value="아래 버튼으로 프로필을 수정하거나 소개팅에 참가할 수 있어요.",
            inline=False,
        )

        embed.set_footer(
            text="프로필 편집은 아래 버튼을 이용해 주세요."
        )

        await interaction.response.send_message(
            embed=embed,
            view=ProfileCardView(interaction.user.id),
            ephemeral=True,
        )

    @bot.tree.command(
        name="프로필편집",
        description="내 프로필을 편집합니다.",
    )
    @app_commands.guild_only()
    async def profile_edit_command(interaction: discord.Interaction):
        await interaction.response.send_message(
            "✏️ 아래 버튼을 눌러 프로필을 편집해 주세요.",
            view=ProfileEditView(interaction.user.id),
            ephemeral=True,
        )

    @bot.tree.command(
        name="프로필삭제",
        description="저장된 내 프로필을 삭제합니다.",
    )
    @app_commands.guild_only()
    async def profile_delete_command(interaction: discord.Interaction):
        uid = str(interaction.user.id)

        if uid not in profiles:
            return await interaction.response.send_message(
                "❌ 저장된 프로필이 없어요.",
                ephemeral=True,
            )

        try:
            await delete_profile_from_db(uid)
            profiles.pop(uid, None)
        except Exception as e:
            print(f"[PROFILE DELETE ERROR] {e}")
            return await interaction.response.send_message(
                "❌ 프로필 삭제에 실패했어요. Railway 로그를 확인해 주세요.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "🗑️ 내 프로필을 삭제했어요.",
            ephemeral=True,
        )
