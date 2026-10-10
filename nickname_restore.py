
import re
import discord
import core


LEVEL_PREFIX_PATTERN = re.compile(
    r'^\s*(?:'
    r'\[\s*Lv\.?\s*\d+\s*\]'
    r'|'
    r'୨୧\s*LV\.?\s*\d+\s*୨୧'
    r')\s*',
    re.IGNORECASE
)


def clean_level_prefix(nickname: str) -> str:
    return LEVEL_PREFIX_PATTERN.sub("", nickname, count=1).strip()


@core.bot.command(name="레벨닉복구")
@core.commands.guild_only()
@core.commands.has_permissions(administrator=True)
async def restore_level_nicknames(ctx, action: str = "미리보기"):

    guild = ctx.guild

    if guild is None:
        await ctx.send("서버 안에서만 사용할 수 있어요.")
        return

    if action not in ("미리보기", "실행"):
        await ctx.send(
            "사용법:\n"
            "`!레벨닉복구 미리보기`\n"
            "`!레벨닉복구 실행`"
        )
        return

    bot_member = guild.me

    if bot_member is None:
        await ctx.send("봇의 서버 정보를 확인할 수 없어요.")
        return

    if not bot_member.guild_permissions.manage_nicknames:
        await ctx.send("봇에 별명 관리 권한을 부여해 주세요.")
        return

    matched = []

    for member in guild.members:
        if member.bot or not member.nick:
            continue

        cleaned = clean_level_prefix(member.nick)

        if cleaned != member.nick:
            matched.append((member, cleaned))

    if not matched:
        await ctx.send(
            "레벨 표시가 포함된 서버 별명을 찾지 못했어요."
        )
        return

    if action == "미리보기":
        examples = []

        for member, cleaned in matched[:20]:
            result_name = cleaned if cleaned else "(서버 별명 제거)"
            examples.append(
                f"• `{member.nick}` → `{result_name}`"
            )

        remaining = len(matched) - len(examples)

        if remaining > 0:
            examples.append(f"외 {remaining}명")

        await ctx.send(
            f"**레벨 닉네임 복구 미리보기**\n"
            f"변경 대상: **{len(matched)}명**\n\n"
            + "\n".join(examples)
            + "\n\n결과가 맞으면 `!레벨닉복구 실행`을 입력하세요."
        )
        return

    await ctx.send(
        f"닉네임 복구를 시작합니다. 대상: **{len(matched)}명**"
    )

    changed = 0
    failed = 0

    for member, cleaned in matched:
        try:
            await member.edit(
                nick=cleaned or None,
                reason=f"레벨 닉네임 복구 요청: {ctx.author}"
            )
            changed += 1

        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    await ctx.send(
        f"**닉네임 복구 완료**\n"
        f"• 변경 성공: **{changed}명**\n"
        f"• 변경 실패: **{failed}명**"
    )


@restore_level_nicknames.error
async def restore_level_nicknames_error(ctx, error):

    if isinstance(error, core.commands.MissingPermissions):
        await ctx.send("이 명령어는 서버 관리자만 사용할 수 있어요.")

    elif isinstance(error, core.commands.NoPrivateMessage):
        await ctx.send("서버 안에서만 사용할 수 있어요.")

    else:
        await ctx.send(
            f"명령어 오류: `{type(error).__name__}: {error}`"
        )
