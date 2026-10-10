from core import *

# =========================================================
# 내 상태 확인
# 슬래시 명령어: /상태
# =========================================================

def setup(bot):

    @bot.tree.command(
        name="상태",
        description="내 자기소개, 경험치, 레벨 달성 현황을 확인합니다."
    )
    async def status_command(interaction: discord.Interaction):

        if not interaction.guild:
            await interaction.response.send_message(
                "서버 안에서만 사용할 수 있어요.",
                ephemeral=True
            )
            return

        if interaction.guild.id != GUILD_ID:
            await interaction.response.send_message(
                "이 서버에서는 사용할 수 없는 명령어예요.",
                ephemeral=True
            )
            return

        data = member_data(interaction.user)
        exp = await get_exp(interaction.user.id)

        remaining = max(0, EXP_TARGET - exp)
        percent = min(100, exp / EXP_TARGET * 100)

        intro_done = data.get("intro_completed", False)
        birth_year = data.get("birth_year")
        gender = data.get("gender")

        if intro_done and birth_year:
            age_info = f"{birth_year}년생 · {age_type(birth_year)}"
        else:
            age_info = "미작성"

        gender_info = gender_text(gender) if gender else "미작성"
        intro_text = "✅ 완료" if intro_done else "❌ 미완료"
        exp_role = (
            "🏅 10만 EXP 달성"
            if exp >= EXP_TARGET
            else "🔒 미달성"
        )

        message = (
            f"╭───────────────╮\n"
            f"   🖤 **{interaction.user.display_name}님의 상태**\n"
            f"╰───────────────╯\n\n"
            f"📝 자기소개 : {intro_text}\n"
            f"🎂 출생년도 : `{age_info}`\n"
            f"⚧ 성별 : `{gender_info}`\n"
            f"✨ EXP : `{exp:,}`\n"
            f"🎯 10만 EXP까지 : `{remaining:,}`\n"
            f"📈 진행도 : `{percent:.2f}%`\n"
            f"🏅 10만 EXP 역할 : {exp_role}"
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )
