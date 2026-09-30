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
