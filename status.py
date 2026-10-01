from core import *

# =========================================================
# 내 상태 확인
# =========================================================

@bot.command(
    name="상태"
)
async def status_command(ctx):
    if not ctx.guild:
        return

    if ctx.guild.id != GUILD_ID:
        return

    data = member_data(ctx.author)
    exp = await get_exp(ctx.author.id)
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
    exp_role = "🏅 10만 EXP 달성" if exp >= EXP_TARGET else "🔒 미달성"

    await ctx.send(
        f"╭───────────────╮\n"
        f"   🖤 **{ctx.author.display_name}님의 상태**\n"
        f"╰───────────────╯\n\n"
        f"📝 자기소개 : {intro_text}\n"
        f"🎂 출생년도 : `{age_info}`\n"
        f"⚧ 성별 : `{gender_info}`\n"
        f"✨ EXP : `{exp:,}`\n"
        f"🎯 10만 EXP까지 : `{remaining:,}`\n"
        f"📈 진행도 : `{percent:.2f}%`\n"
        f"🏅 10만 EXP 역할 : {exp_role}"
    )


