from core import *

# !자기소개제외
# =========================================================

@bot.command(
    name="자기소개제외"
)
async def intro_exception_add(
    ctx,
    member: discord.Member = None
):

    if not is_admin(
        ctx.author
    ):

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    if member is None:

        await ctx.send(

            "❌ 사용법: "
            "`!자기소개제외 @회원`"

        )

        return


    intro_exceptions.add(
        member.id
    )


    save_json(

        FILES["exceptions"],

        list(intro_exceptions)

    )


    pending_kicks.discard(
        member.id
    )


    await ctx.send(

        f"✅ {member.mention}님을 "
        f"자기소개 검사에서 제외했습니다."

    )


# =========================================================
# !자기소개제외취소
# =========================================================

@bot.command(
    name="자기소개제외취소"
)
async def intro_exception_remove(
    ctx,
    member: discord.Member = None
):

    if not is_admin(
        ctx.author
    ):

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    if member is None:

        await ctx.send(

            "❌ 사용법: "
            "`!자기소개제외 @회원`"

        )

        return


    intro_exceptions.discard(
        member.id
    )


    save_json(

        FILES["exceptions"],

        list(intro_exceptions)

    )


    await ctx.send(

        f"✅ {member.mention}님의 "
        f"자기소개 제외를 해제했습니다."

    )


# =========================================================
# 제한 채널
# =========================================================

async def restricted_access(
    member,
    allow=False
):

    channels = []


    adult_channel = discord.utils.get(

        member.guild.text_channels,

        name="＃↝・19금"

    )


    if adult_channel:

        channels.append(
            adult_channel
        )


    body_channel = member.guild.get_channel(

        BODY_SHARE_ID

    )


    if isinstance(

        body_channel,

        discord.TextChannel

    ):

        channels.append(
            body_channel
        )


    for channel in channels:

        try:

            if allow:

                await channel.set_permissions(

                    member,

                    overwrite=None,

                    reason=
                    "경고 해제"

                )

            else:

                overwrite = channel.overwrites_for(

                    member

                )


                overwrite.view_channel = False

                overwrite.send_messages = False

                overwrite.read_message_history = False


                await channel.set_permissions(

                    member,

                    overwrite=overwrite,

                    reason=
                    "경고 제한"

                )

        except Exception as e:

            print(
                f"[제한 채널 오류] {e}"
            )


# =========================================================
# 경고 적용
# =========================================================

async def apply_warning(
    member,
    reason="사유 없음"
):

    member_id = str(
        member.id
    )


    count = warning_count(
        member
    ) + 1


    warnings[member_id] = {

        "count":
            count,

        "last_reason":
            reason,

        "updated_at":
            iso(now())

    }


    save_json(

        FILES["warnings"],

        warnings

    )


    await restricted_access(

        member,

        False

    )


    timeout = WARNING_TIMEOUT.get(
        count
    )


    if timeout:

        try:

            await member.timeout(

                now()
                +
                timedelta(
                    seconds=timeout
                ),

                reason=
                f"경고 {count}회"

            )

        except Exception as e:

            print(
                f"[TIMEOUT ERROR] {e}"
            )


    if count >= 5:

        try:

            await member.kick(

                reason=
                f"경고 {count}회 누적"

            )

        except Exception as e:

            print(
                f"[KICK ERROR] {e}"
            )


    return count


# =========================================================
# 경고 로그
# =========================================================

async def send_warning_log(
    guild,
    member,
    count,
    reason
):

    log = get_log_channel(
        guild
    )


    if not log:

        return


    if count >= 5:

        action = "🚪 추방"

    elif count == 4:

        action = "⏰ 24시간 타임아웃"

    elif count == 3:

        action = "⏰ 1시간 타임아웃"

    else:

        action = "🔒 제한 채널 차단"


    await log.send(

        f"⚠️ **경고 처리**\n\n"

        f"대상: {member.mention}\n"

        f"경고: `{count}회`\n"

        f"사유: `{reason}`\n"

        f"조치: {action}"

    )


# =========================================================
# !경고
# =========================================================

@bot.command(
    name="경고"
)
async def warning_command(

    ctx,

    member:
    discord.Member = None,

    *,

    reason="사유 없음"

):

    if not is_admin(
        ctx.author
    ):

        await ctx.send(
            "❌ 관리자만 사용할 수 있습니다."
        )

        return


    if member is None:

        await ctx.send(
            "❌ 회원을 멘션해주세요."
        )

        return


    if member.bot:

        await ctx.send(
            "❌ 봇에게 경고 불가"
        )

        return


    count = await apply_warning(

        member,

        reason

    )


    await send_warning_log(

        ctx.guild,

        member,

        count,

        reason

    )


    if count >= 5:

        text = (

            f"🚪 {member.mention}님 "
            f"경고 {count}회 누적으로 추방"

        )

    elif count == 4:

        text = (

            f"⚠️ {member.mention}님\n"

            f"경고 {count}회\n"

            f"24시간 타임아웃"

        )

    elif count == 3:

        text = (

            f"⚠️ {member.mention}님\n"

            f"경고 {count}회\n"

            f"1시간 타임아웃"

        )

    else:

        text = (

            f"⚠️ {member.mention}님\n"

            f"경고 {count}회 누적\n"

            f"제한 채널 차단"

        )


    await ctx.send(
        text
    )


# =========================================================
# !경고목록
# =========================================================

@bot.command(
    name="경고목록"
)
async def warning_list(

    ctx,

    member:
    discord.Member = None

):

    if not is_admin(
        ctx.author
    ):

        await ctx.send(
            "❌ 관리자만 사용 가능"
        )

        return


    if member:

        data = warnings.get(

            str(member.id),

            {}

        )


        await ctx.send(

            f"⚠️ {member.mention}\n"

            f"경고: "
            f"`{data.get('count', 0)}회`\n"

            f"사유: "
            f"`{data.get('last_reason', '없음')}`"

        )

        return


    if not warnings:

        await ctx.send(
            "📋 경고 기록 없음"
        )

        return


    result = []


    for uid, data in warnings.items():

        try:

            m = ctx.guild.get_member(
                int(uid)
            )

        except Exception:

            m = None


        name = (

            m.mention
            if m
            else uid

        )


        result.append(

            f"• {name} : "
            f"`{data.get('count', 0)}회`"

        )


    await ctx.send(

        "⚠️ **전체 경고 목록**\n\n"

        +
        "\n".join(result)

    )


# =========================================================
# !경고취소
# =========================================================

@bot.command(
    name="경고취소"
)
async def warning_remove(

    ctx,

    member:
    discord.Member = None

):

    if not is_admin(
        ctx.author
    ):

        return


    if member is None:

        return


    uid = str(
        member.id
    )


    count = warning_count(
        member
    )


    if count <= 0:

        await ctx.send(
            "❌ 경고 없음"
        )

        return


    count -= 1


    if count <= 0:

        warnings.pop(
            uid,
            None
        )


        await restricted_access(

            member,

            True

        )


        try:

            await member.timeout(

                None,

                reason=
                "경고 취소"

            )

        except Exception:

            pass

    else:

        warnings[uid] = {

            "count":
                count,

            "last_reason":
                warnings[uid].get(

                    "last_reason",

                    "없음"

                ),

            "updated_at":
                iso(now())

        }


    save_json(

        FILES["warnings"],

        warnings

    )


    await ctx.send(

        f"✅ {member.mention} "
        f"경고 취소\n"

        f"현재 `{count}회`"

    )


# =========================================================
# !경고초기화
# =========================================================

@bot.command(
    name="경고초기화"
)
async def warning_reset(

    ctx,

    member:
    discord.Member = None

):

    if not is_admin(
        ctx.author
    ):

        return


    if member is None:

        return


    warnings.pop(

        str(member.id),

        None

    )


    save_json(

        FILES["warnings"],

        warnings

    )


    await restricted_access(

        member,

        True

    )


    try:

        await member.timeout(

            None,

            reason=
            "경고 초기화"

        )

    except Exception:

        pass


    await ctx.send(

        f"✅ {member.mention} "
        f"경고 초기화 완료"

    )


# =========================================================
