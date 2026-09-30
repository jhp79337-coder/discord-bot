```python
from core import *
from discord.ext import tasks


# =========================================================
# 채팅 EXP
# =========================================================

@bot.listen("on_message")
async def experience_on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    if message.guild.id != GUILD_ID:
        return

    user_id = message.author.id
    current_time = now().timestamp()

    last_time = exp_chat_cooldowns.get(
        user_id,
        0
    )

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

    if not ctx.guild:
        return

    if ctx.guild.id != GUILD_ID:
        return

    current = await get_exp(
        ctx.author.id
    )

    remaining = max(
        0,
        EXP_TARGET - current
    )

    percent = min(
        100,
        current / EXP_TARGET * 100
    )

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


# =========================================================
# 명령어 / 도움말
# =========================================================

@bot.command(
    name="명령어",
    aliases=["도움말"]
)
async def help_command(ctx):

    if not ctx.guild:
        return

    if ctx.guild.id != GUILD_ID:
        return

    await ctx.send(
        "╭───────────────╮\n"
        "     📖 **명령어 안내**\n"
        "╰───────────────╯\n"
        "\n"
        "📊 **EXP**\n"
        "`!내EXP` — 내 경험치 확인\n"
        "`!내경험치` — 내 경험치 확인\n"
        "\n"
        "💘 **소개팅**\n"
        "`!소개팅` — 소개팅 기능 이용\n"
        "\n"
        "ℹ️ **기타**\n"
        "`!명령어` — 명령어 목록\n"
        "`!도움말` — 도움말 보기\n"
    )


# =========================================================
# 관리자 EXP 테스트 지급
# =========================================================

@bot.command(
    name="EXP지급"
)
async def admin_add_exp(
    ctx,
    member: discord.Member,
    amount: int
):

    if not ctx.author.guild_permissions.administrator:

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return

    if not ctx.guild:
        return

    if ctx.guild.id != GUILD_ID:
        return

    if amount <= 0:

        await ctx.send(
            "❌ EXP는 1 이상 입력해주세요."
        )

        return

    new_exp = await add_exp(
        member,
        amount,
        "관리자 테스트 지급"
    )

    await ctx.send(
        f"✅ {member.mention}에게 "
        f"`{amount:,} EXP`를 지급했습니다.\n"
        f"현재 EXP : `{new_exp:,}`"
    )


# =========================================================
# 음성채널 EXP
# =========================================================

@tasks.loop(minutes=1)
async def voice_exp_loop():

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:
        return

    for channel in guild.voice_channels:

        for member in channel.members:

            if member.bot:
                continue

            await add_exp(
                member,
                EXP_VOICE_PER_MINUTE,
                "음성채널"
            )


@voice_exp_loop.before_loop
async def before_voice_exp_loop():

    await bot.wait_until_ready()


@bot.listen("on_ready")
async def start_voice_exp():

    if not voice_exp_loop.is_running():

        voice_exp_loop.start()
```
