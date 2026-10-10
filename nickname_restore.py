import re
import core

# LeaderBoard가 닉네임 앞에 붙인 [Lv.10] 같은 표시만 제거합니다.
# 예: [Lv.10] 백구 -> 백구
LEVEL_PREFIX_PATTERN = re.compile(r'^\s*\[\s*Lv\.?\s*\d+\s*\]\s*', re.IGNORECASE)


def clean_level_prefix(nickname: str) -> str:
    return LEVEL_PREFIX_PATTERN.sub('', nickname, count=1).strip()


@core.bot.command(name="레벨닉복구")
@core.commands.has_permissions(administrator=True)
async def restore_level_nicknames(ctx, action: str = "미리보기"):
    """!레벨닉복구 미리보기 / !레벨닉복구 실행"""
    if ctx.guild is None:
        await ctx.send("이 명령어는 서버 안에서만 사용할 수 있어요.")
        return

    if action not in ("미리보기", "실행"):
        await ctx.send("사용법: `!레벨닉복구 미리보기` 또는 `!레벨닉복구 실행`")
        return

    matched = []
    for member in ctx.guild.members:
        # 서버 별명(nick)이 실제로 설정된 회원만 수정합니다.
        if member.bot or not member.nick:
            continue
        cleaned = clean_level_prefix(member.nick)
        if cleaned and cleaned != member.nick:
            matched.append((member, cleaned))

    if not matched:
        await ctx.send("`[Lv.숫자]`로 시작하는 서버 별명을 찾지 못했어요.")
        return

    if action == "미리보기":
        examples = [f"• `{member.nick}` → `{cleaned}`" for member, cleaned in matched[:15]]
        more = f"\n외 {len(matched) - 15}명" if len(matched) > 15 else ""
        await ctx.send(
            f"총 **{len(matched)}명**의 서버 별명에서 레벨 표시를 찾았어요.\n"
            + "\n".join(examples)
            + more
            + "\n\n확인 후 적용하려면 `!레벨닉복구 실행`을 입력하세요."
        )
        return

    changed = 0
    failed = 0
    for member, cleaned in matched:
        try:
            await member.edit(nick=cleaned, reason="LeaderBoard 레벨 접두사 제거 요청")
            changed += 1
        except Exception:
            failed += 1

    await ctx.send(
        f"닉네임 복구가 끝났어요.\n"
        f"• 변경 성공: **{changed}명**\n"
        f"• 변경 실패: **{failed}명**\n"
        "실패한 회원은 봇 역할 순위나 서버 권한을 확인해 주세요."
    )


@restore_level_nicknames.error
async def restore_level_nicknames_error(ctx, error):
    if isinstance(error, core.commands.MissingPermissions):
        await ctx.send("이 명령어는 서버 관리자만 사용할 수 있어요.")
    else:
        await ctx.send(f"명령어 실행 중 오류가 발생했어요: `{error}`")
