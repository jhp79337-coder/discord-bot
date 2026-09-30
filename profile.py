from core import *

# =========================================================
# 프로필
# =========================================================

def get_profile(
    user_id
):

    uid = str(
        user_id
    )


    if uid not in profiles:

        profiles[uid] = {

            "age":
                None,

            "location":
                None,

            "gender":
                None,

            "ideal_type":
                None,

            "likes":
                None

        }


    return profiles[uid]


# =========================================================
# 프로필 편집 Modal
# =========================================================

class ProfileModal(
    discord.ui.Modal,
    title="프로필 편집"
):

    age = discord.ui.TextInput(

        label="나이",

        placeholder="예: 04",

        required=False,

        max_length=10

    )


    location = discord.ui.TextInput(

        label="사는 곳",

        placeholder="예: 서울",

        required=False,

        max_length=50

    )


    gender = discord.ui.TextInput(

        label="성별",

        placeholder="예: 남 / 여",

        required=False,

        max_length=10

    )


    ideal_type = discord.ui.TextInput(

        label="이상형",

        placeholder="예: 웃는 게 예쁜 사람",

        required=False,

        max_length=200

    )


    likes = discord.ui.TextInput(

        label="좋아하는 것",

        placeholder="예: 게임, 음악, 영화",

        required=False,

        max_length=200

    )


    async def on_submit(
        self,
        interaction:
        discord.Interaction
    ):

        uid = str(
            interaction.user.id
        )


        profiles[uid] = {

            "age":
                self.age.value.strip()
                or None,

            "location":
                self.location.value.strip()
                or None,

            "gender":
                self.gender.value.strip()
                or None,

            "ideal_type":
                self.ideal_type.value.strip()
                or None,

            "likes":
                self.likes.value.strip()
                or None

        }


        save_json(

            FILES["profiles"],

            profiles

        )


        await interaction.response.send_message(

            "✅ 프로필을 저장했어요!\n"
            "이제 `!프로필`로 확인할 수 있어요.",

            ephemeral=True

        )


# =========================================================
# !프로필
# =========================================================

class ProfileCardView(discord.ui.View):

    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    @discord.ui.button(
        label="프로필 편집",
        emoji="✏️",
        style=discord.ButtonStyle.primary
    )
    async def edit_profile(self, interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ 본인 프로필만 수정할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(ProfileModal())

    @discord.ui.button(
        label="소개팅",
        emoji="💗",
        style=discord.ButtonStyle.success
    )
    async def dating(self, interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ 본인 프로필에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "`!소개팅` 명령어로 소개팅에 참가할 수 있어요.",
            ephemeral=True
        )


@bot.command(
    name="프로필"
)
async def profile_command(
    ctx
):

    profile = get_profile(
        ctx.author.id
    )

    member_info = members.get(
        str(ctx.author.id),
        {}
    )

    birth_year = profile.get("age") or member_info.get("birth_year")
    gender = profile.get("gender") or gender_text(member_info.get("gender"))
    location = profile.get("location") or "미설정"
    ideal_type = profile.get("ideal_type") or "미설정"
    likes = profile.get("likes") or "미설정"

    embed = discord.Embed(
        title=f"💗 {ctx.author.display_name}님의 프로필",
        description=(
            f"**{birth_year or '나이 미설정'}** · **{gender}**\n"
            f"📍 {location}"
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )

    embed.set_thumbnail(
        url=ctx.author.display_avatar.url
    )

    embed.add_field(
        name="♡ 이상형",
        value=ideal_type,
        inline=False
    )

    embed.add_field(
        name="🎮 좋아하는 것",
        value=likes,
        inline=False
    )

    embed.add_field(
        name="💬 소개팅",
        value="아래 버튼으로 프로필을 수정하거나 소개팅에 참가할 수 있어요.",
        inline=False
    )

    embed.set_footer(
        text="!프로필편집 으로도 수정할 수 있어요."
    )

    await ctx.send(
        embed=embed,
        view=ProfileCardView(ctx.author.id)
    )


# =========================================================
# !프로필편집
# =========================================================

@bot.command(
    name="프로필편집"
)
async def profile_edit_command(
    ctx
):

    await ctx.author.send(
        "프로필 편집창을 열어드릴게요."
    )

    try:

        await ctx.send(
            f"{ctx.author.mention} 📩 DM을 확인해주세요!",
            delete_after=5
        )

    except Exception:

        pass


    # -----------------------------------------------------
    # 주의:
    # prefix 명령어 자체는 interaction이 아니므로
    # Discord Modal을 직접 열 수 없습니다.
    #
    # 따라서 아래 버튼을 사용합니다.
    # -----------------------------------------------------

    view = ProfileEditView()


    try:

        await ctx.send(

            f"{ctx.author.mention}\n"
            f"아래 버튼을 눌러 프로필을 편집해주세요.",

            view=view

        )

    except Exception as e:

        print(
            f"[PROFILE VIEW ERROR] {e}"
        )


# =========================================================
# 프로필 편집 버튼
# =========================================================

class ProfileEditView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    @discord.ui.button(

        label="프로필 편집",

        emoji="✏️",

        style=
        discord.ButtonStyle.primary

    )
    async def edit(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

    ):

        await interaction.response.send_modal(
            ProfileModal()
        )


# =========================================================
# !프로필삭제
# =========================================================

@bot.command(
    name="프로필삭제"
)
async def profile_delete_command(
    ctx
):

    uid = str(
        ctx.author.id
    )


    if uid not in profiles:

        await ctx.send(
            "❌ 저장된 프로필이 없습니다."
        )

        return


    profiles.pop(
        uid,
        None
    )


    save_json(

        FILES["profiles"],

        profiles

    )


    await ctx.send(

        f"🗑️ {ctx.author.mention}님의 "
        f"프로필을 삭제했습니다."

    )


# =========================================================
