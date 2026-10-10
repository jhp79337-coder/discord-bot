
# =========================================================
# /소개팅 슬래시 명령어 등록
# 기존 DatingLobbyView / DatingView 유지
# =========================================================

def setup(bot):
    # 중복 등록 방지
    if bot.tree.get_command("소개팅") is not None:
        bot.tree.remove_command("소개팅")

    @bot.tree.command(
        name="소개팅",
        description="소개팅 로비를 열어요."
    )
    async def dating_command(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있어요.",
                ephemeral=True
            )
            return

        if interaction.guild.id != GUILD_ID:
            await interaction.response.send_message(
                "❌ 이 서버에서는 사용할 수 없어요.",
                ephemeral=True
            )
            return

        member = interaction.user

        if not get_dating_group(member) or not get_dating_gender(member):
            await interaction.response.send_message(
                "❌ 먼저 자기소개와 성별·출생년도를 등록해 주세요.",
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
                "매칭되면 두 사람만 볼 수 있는 "
                "전용 채팅방이 생성됩니다."
            ),
            color=discord.Color.from_rgb(255, 82, 145)
        )

        embed.set_footer(text="상대방을 존중하면서 즐겨주세요.")

        await interaction.response.send_message(
            embed=embed,
            view=DatingLobbyView()
        )
