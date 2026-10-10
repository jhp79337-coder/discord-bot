
# =========================================================
# /소개팅 슬래시 명령어
# =========================================================

@bot.tree.command(
    name="소개팅",
    description="소개팅 로비를 열고 새로운 상대를 만나보세요."
)
async def dating_command(
    interaction: discord.Interaction
):
    # 지정된 서버에서만 사용
    if (
        interaction.guild is None
        or interaction.guild.id != GUILD_ID
    ):
        await interaction.response.send_message(
            "❌ 이 서버에서만 사용할 수 있어요.",
            ephemeral=True
        )
        return

    member = interaction.user

    # 자기소개 및 성별·출생년도 확인
    member_group = get_dating_group(member)
    member_gender = get_dating_gender(member)

    if not member_group or not member_gender:
        await interaction.response.send_message(
            "❌ 자기소개를 완료하고 성별·출생년도를 "
            "정상적으로 등록한 회원만 참가할 수 있어요.",
            ephemeral=True
        )
        return

    # 이미 진행 중인 소개팅 확인
    active_id, _ = dating_member_session(member.id)

    if active_id:
        await interaction.response.send_message(
            f"❌ 이미 소개팅을 진행 중이에요. 세션: `{active_id}`",
            ephemeral=True
        )
        return

    # 소개팅 로비 표시
    embed = discord.Embed(
        title="💗 소개팅",
        description=(
            "새로운 사람을 만나볼래요?\n\n"
            "💞 **소개팅 참가** — 조건에 맞는 상대 찾기\n"
            "❌ **대기 취소** — 대기열에서 나가기\n"
            "👤 **내 프로필** — 등록된 프로필 확인\n\n"
            f"💗 현재 대기자 **{len(dating_queue)}명**\n\n"
            "매칭되면 두 사람만 볼 수 있는 "
            "전용 채팅방이 생성됩니다.\n\n"
            "⚠️ 서로 다른 연령 그룹끼리만 매칭되도록 "
            "설정된 것이 아니라, 같은 연령 그룹이면서 "
            "서로 다른 성별인 회원끼리 매칭됩니다."
        ),
        color=discord.Color.from_rgb(255, 82, 145)
    )

    embed.set_footer(
        text="상대방을 존중하면서 즐겨주세요."
    )

    await interaction.response.send_message(
        embed=embed,
        view=DatingLobbyView()
    )
