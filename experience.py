from core import *


# =========================================================
# 채팅 EXP
# =========================================================

@bot.listen("on_message")
async def experience_on_message(message):

    # 봇 무시
    if message.author.bot:
        return

    # DM 무시
    if not message.guild:
        return

    # 지정 서버만
    if message.guild.id != GUILD_ID:
        return

    # 채팅 EXP 지급
    user_id = message.author.id

    current_time = now().timestamp()

    last_time = exp_chat_cooldowns.get(
        user_id,
        0
    )

    # 5초 쿨다운
    if current_time - last_time >= CHAT_EXP_COOLDOWN:

        exp_chat_cooldowns[user_id] = current_time

        await add_exp(
            message.author,
            EXP_CHAT,
            "채팅"
        )
        # =========================================================
# 내 EXP 확인
# =========================================================

@bot.command(
    name="내EXP",
    aliases=["내경험치"]
)
async def my_exp(ctx):

    # 서버에서만 사용
    if not ctx.guild:
        return

    # 지정 서버만
    if ctx.guild.id != GUILD_ID:
        return

    # 현재 EXP
    current = await get_exp(
        ctx.author.id
    )

    # 목표까지 남은 EXP
    remaining = max(
        0,
        EXP_TARGET - current
    )

    # 진행도
    percent = min(
        100,
        current / EXP_TARGET * 100
    )

    # 진행바
    bar_length = 10

    filled = int(
        percent / 100 * bar_length
    )

    progress_bar = (
        "█" * filled
        + "░" * (bar_length - filled)
    )

    await ctx.send(
        f"📊 **{ctx.author.display_name}님의 EXP**\n"
        f"\n"
        f"현재 EXP : `{current:,}`\n"
        f"남은 EXP : `{remaining:,}`\n"
        f"진행도 : `{percent:.2f}%`\n"
        f"`{progress_bar}`"
    )
