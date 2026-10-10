from core import *
from discord import app_commands


# =========================================================
# 공통 관리자 확인
# =========================================================

def moderation_is_admin(interaction: discord.Interaction) -> bool:
    return is_admin(interaction.user)


# =========================================================
# 자기소개 검사 제외
# /자기소개제외 회원
# =========================================================

@bot.tree.command(name="자기소개제외", description="특정 회원을 자기소개 검사에서 제외합니다.")
@app_commands.describe(member="제외할 회원")
@app_commands.guild_only()
async def intro_exception_add(
    interaction: discord.Interaction,
    member: discord.Member
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    intro_exceptions.add(member.id)

    save_json(FILES["exceptions"], list(intro_exceptions))
    pending_kicks.discard(member.id)

    await interaction.response.send_message(
        f"✅ {member.mention}님을 자기소개 검사에서 제외했습니다."
    )


# =========================================================
# 자기소개 검사 제외 취소
# /자기소개제외취소 회원
# =========================================================

@bot.tree.command(name="자기소개제외취소", description="회원의 자기소개 검사 제외를 해제합니다.")
@app_commands.describe(member="제외를 해제할 회원")
@app_commands.guild_only()
async def intro_exception_remove(
    interaction: discord.Interaction,
    member: discord.Member
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    intro_exceptions.discard(member.id)

    save_json(FILES["exceptions"], list(intro_exceptions))

    await interaction.response.send_message(
        f"✅ {member.mention}님의 자기소개 제외를 해제했습니다."
    )


# =========================================================
# 제한 채널 관리
# =========================================================

async def restricted_access(member, allow=False):
    channels = []

    adult_channel = discord.utils.get(
        member.guild.text_channels,
        name="＃↝・19금"
    )

    if adult_channel:
        channels.append(adult_channel)

    body_channel = member.guild.get_channel(BODY_SHARE_ID)

    if isinstance(body_channel, discord.TextChannel):
        channels.append(body_channel)

    for channel in channels:
        try:
            if allow:
                # 기존 서버 권한 설정으로 복구
                await channel.set_permissions(
                    member,
                    overwrite=None,
                    reason="경고 해제"
                )
            else:
                overwrite = channel.overwrites_for(member)
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.read_message_history = False

                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason="경고 제한"
                )

        except Exception as e:
            print(f"[제한 채널 오류] {e}")


# =========================================================
# 경고 적용
# =========================================================

async def apply_warning(member, reason="사유 없음"):
    member_id = str(member.id)

    count = warning_count(member) + 1

    warnings[member_id] = {
        "count": count,
        "last_reason": reason,
        "updated_at": iso(now())
    }

    save_json(FILES["warnings"], warnings)

    await restricted_access(member, False)

    timeout = WARNING_TIMEOUT.get(count)

    if timeout:
        try:
            await member.timeout(
                now() + timedelta(seconds=timeout),
                reason=f"경고 {count}회"
            )
        except Exception as e:
            print(f"[TIMEOUT ERROR] {e}")

    if count >= 5:
        try:
            await member.kick(reason=f"경고 {count}회 누적")
        except Exception as e:
            print(f"[KICK ERROR] {e}")

    return count


# =========================================================
# 경고 로그
# =========================================================

async def send_warning_log(guild, member, count, reason):
    log = get_log_channel(guild)

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
# /경고
# =========================================================

@bot.tree.command(name="경고", description="회원에게 경고를 부여합니다.")
@app_commands.describe(
    member="경고를 부여할 회원",
    reason="경고 사유"
)
@app_commands.guild_only()
async def warning_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "사유 없음"
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    if member.bot:
        await interaction.response.send_message(
            "❌ 봇에게는 경고할 수 없습니다.",
            ephemeral=True
        )
        return

    if member.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ 자신에게 경고할 수 없습니다.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    count = await apply_warning(member, reason)

    await send_warning_log(
        interaction.guild,
        member,
        count,
        reason
    )

    if count >= 5:
        text = f"🚪 {member.mention}님 경고 {count}회 누적으로 추방 처리했습니다."
    elif count == 4:
        text = f"⚠️ {member.mention}님\n경고 {count}회\n24시간 타임아웃"
    elif count == 3:
        text = f"⚠️ {member.mention}님\n경고 {count}회\n1시간 타임아웃"
    else:
        text = f"⚠️ {member.mention}님\n경고 {count}회 누적\n제한 채널 차단"

    await interaction.followup.send(text)


# =========================================================
# /경고목록
# =========================================================

@bot.tree.command(name="경고목록", description="회원의 경고 기록을 확인합니다.")
@app_commands.describe(member="확인할 회원 (비워두면 전체 목록)")
@app_commands.guild_only()
async def warning_list(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    if member:
        data = warnings.get(str(member.id), {})

        await interaction.response.send_message(
            f"⚠️ {member.mention}\n"
            f"경고: `{data.get('count', 0)}회`\n"
            f"사유: `{data.get('last_reason', '없음')}`",
            ephemeral=True
        )
        return

    if not warnings:
        await interaction.response.send_message(
            "📋 경고 기록이 없습니다.",
            ephemeral=True
        )
        return

    result = []

    for uid, data in warnings.items():
        try:
            target = interaction.guild.get_member(int(uid))
        except (ValueError, TypeError):
            target = None

        name = target.mention if target else f"`{uid}`"

        result.append(
            f"• {name} : `{data.get('count', 0)}회`"
        )

    description = "\n".join(result)

    # Discord 메시지 길이 제한 방지
    if len(description) > 3800:
        description = description[:3800] + "\n… 목록이 길어 일부만 표시됩니다."

    await interaction.response.send_message(
        "⚠️ **전체 경고 목록**\n\n" + description,
        ephemeral=True
    )


# =========================================================
# /경고취소
# =========================================================

@bot.tree.command(name="경고취소", description="회원의 경고를 1회 취소합니다.")
@app_commands.describe(member="경고를 취소할 회원")
@app_commands.guild_only()
async def warning_remove(
    interaction: discord.Interaction,
    member: discord.Member
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    uid = str(member.id)
    count = warning_count(member)

    if count <= 0:
        await interaction.response.send_message(
            "❌ 해당 회원에게 경고가 없습니다.",
            ephemeral=True
        )
        return

    count -= 1

    if count <= 0:
        warnings.pop(uid, None)

        await restricted_access(member, True)

        try:
            await member.timeout(None, reason="경고 취소")
        except Exception as e:
            print(f"[경고 취소 타임아웃 해제 오류] {e}")

    else:
        warnings[uid] = {
            "count": count,
            "last_reason": warnings[uid].get("last_reason", "없음"),
            "updated_at": iso(now())
        }

    save_json(FILES["warnings"], warnings)

    await interaction.response.send_message(
        f"✅ {member.mention} 경고를 1회 취소했습니다.\n"
        f"현재 경고: `{count}회`"
    )


# =========================================================
# /경고초기화
# =========================================================

@bot.tree.command(name="경고초기화", description="회원의 경고 기록을 모두 초기화합니다.")
@app_commands.describe(member="경고를 초기화할 회원")
@app_commands.guild_only()
async def warning_reset(
    interaction: discord.Interaction,
    member: discord.Member
):
    if not moderation_is_admin(interaction):
        await interaction.response.send_message(
            "❌ 관리자만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    warnings.pop(str(member.id), None)

    save_json(FILES["warnings"], warnings)

    await restricted_access(member, True)

    try:
        await member.timeout(None, reason="경고 초기화")
    except Exception as e:
        print(f"[경고 초기화 타임아웃 해제 오류] {e}")

    await interaction.response.send_message(
        f"✅ {member.mention}님의 경고 기록을 초기화했습니다."
    )
