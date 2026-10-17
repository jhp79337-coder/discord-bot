# =========================================================
# Discord Server Management Bot
# bot.py
# 제작자: 백구
#
# - core.py 유지
# - PostgreSQL 연결 및 기존 데이터 로드
# - 어느 서버에서든 구조 백업 / 복원 가능
# - 백업은 JSON 파일 첨부로 전달 (호스팅 재배포 후에도 사용 가능)
# - 역할 / 카테고리 / 채널 / 권한 덮어쓰기 저장
# =========================================================

import asyncio
import json
import os
from pathlib import Path
from io import BytesIO

import discord
from discord import app_commands

import core
from core import *

# =========================================================
# 데이터 로드
# =========================================================

load_data()

# 새 Discord 서버 ID
GUILD_ID = int(os.getenv("GUILD_ID", "1561036401263382672"))

# =========================================================
# 서버 구조 백업 설정
# =========================================================

BACKUP_DIR = Path("data/server_backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# 이 ID는 구조 백업 명령어를 사용할 수 있는 추가 허용 사용자입니다.
# 서버 관리자 권한이 있는 사용자는 별도 등록 없이 사용할 수 있습니다.
STRUCTURE_ALLOWED_USER_IDS = {
    1391947061175517411,
}


def can_run_structure_command(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False

    return (
        interaction.user.id in STRUCTURE_ALLOWED_USER_IDS
        or interaction.user.guild_permissions.administrator
    )


def overwrite_to_json(overwrites):
    result = []

    for target, overwrite in overwrites.items():
        if isinstance(target, discord.Role):
            kind = "role"
        elif isinstance(target, discord.Member):
            kind = "member"
        else:
            continue

        allow, deny = overwrite.pair()
        result.append({
            "kind": kind,
            "id": target.id,
            "name": getattr(target, "name", str(target)),
            "allow": allow.value,
            "deny": deny.value,
        })

    return result


def build_structure(guild: discord.Guild):
    roles = []
    categories = []
    channels = []

    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default() or role.managed:
            continue

        roles.append({
            "id": role.id,
            "name": role.name,
            "permissions": role.permissions.value,
            "colour": role.colour.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position,
        })

    for channel in sorted(guild.channels, key=lambda c: (c.position, c.id)):
        entry = {
            "id": channel.id,
            "name": channel.name,
            "position": channel.position,
            "overwrites": overwrite_to_json(channel.overwrites),
        }

        if isinstance(channel, discord.CategoryChannel):
            categories.append(entry)

        elif isinstance(channel, discord.TextChannel):
            entry.update({
                "type": "text",
                "category_id": channel.category_id,
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
            })
            channels.append(entry)

        elif isinstance(channel, discord.VoiceChannel):
            entry.update({
                "type": "voice",
                "category_id": channel.category_id,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
            })
            channels.append(entry)

        elif isinstance(channel, discord.StageChannel):
            entry.update({
                "type": "stage",
                "category_id": channel.category_id,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
            })
            channels.append(entry)

        elif isinstance(channel, discord.ForumChannel):
            entry.update({
                "type": "forum",
                "category_id": channel.category_id,
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
            })
            channels.append(entry)

        elif getattr(channel, "type", None) == getattr(discord.ChannelType, "media", None):
            # discord.py 버전에 따라 MediaChannel 클래스가 없을 수 있어 type으로 판별
            entry.update({
                "type": "media",
                "topic": getattr(channel, "topic", None),
                "nsfw": getattr(channel, "nsfw", False),
            })
            channels.append(entry)

    return {
        "format_version": 1,
        "source_guild_id": guild.id,
        "source_guild_name": guild.name,
        "roles": roles,
        "categories": categories,
        "channels": channels,
    }


async def save_structure(guild: discord.Guild):
    data = build_structure(guild)
    safe_name = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_"
        for ch in guild.name
    )[:60] or "server"
    filename = f"server_structure_{safe_name}_{guild.id}.json"
    path = BACKUP_DIR / filename

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return data, path, filename


def load_backup_attachment(attachment: discord.Attachment):
    if not attachment.filename.lower().endswith(".json"):
        raise ValueError("JSON 백업 파일(.json)만 첨부할 수 있어요.")

    # Discord 첨부 파일 크기 제한은 앱/서버 설정에 따라 달라질 수 있습니다.
    if attachment.size > 8 * 1024 * 1024:
        raise ValueError("백업 파일이 너무 커요. 8MB 이하 파일을 첨부해 주세요.")


async def read_structure_attachment(attachment: discord.Attachment):
    load_backup_attachment(attachment)
    raw = await attachment.read()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON 파일을 읽을 수 없어요. 올바른 백업 파일인지 확인해 주세요.") from error

    if not isinstance(data, dict):
        raise ValueError("백업 파일 형식이 올바르지 않아요.")

    for key in ("roles", "categories", "channels"):
        if not isinstance(data.get(key, []), list):
            raise ValueError(f"백업 파일의 `{key}` 항목이 올바르지 않아요.")

    return data


async def restore_structure(guild: discord.Guild, data: dict):
    me = guild.me
    if me is None:
        me = await guild.fetch_member(bot.user.id)

    if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
        raise PermissionError("봇에 역할 관리 및 채널 관리 권한을 부여해 주세요.")

    # 역할 이름으로 먼저 연결해 중복 역할 생성을 줄입니다.
    role_map = {guild.default_role.id: guild.default_role}
    role_map_by_name = {role.name: role for role in guild.roles}

    roles_created = 0
    roles_reused = 0

    for item in data.get("roles", []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        role = role_map_by_name.get(name)
        if role is None:
            role = await guild.create_role(
                name=name,
                permissions=discord.Permissions(item.get("permissions", 0)),
                colour=discord.Colour(item.get("colour", 0)),
                hoist=item.get("hoist", False),
                mentionable=item.get("mentionable", False),
                reason="서버 구조 백업 복원",
            )
            role_map_by_name[name] = role
            roles_created += 1
        else:
            roles_reused += 1

        role_map[item.get("id")] = role

    # 카테고리도 이름으로 재사용합니다.
    category_map = {}
    category_by_name = {category.name: category for category in guild.categories}
    categories_created = 0
    categories_reused = 0

    for item in sorted(data.get("categories", []), key=lambda x: x.get("position", 0)):
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        category = category_by_name.get(name)
        if category is None:
            category = await guild.create_category(
                name,
                reason="서버 구조 백업 복원",
            )
            category_by_name[name] = category
            categories_created += 1
        else:
            categories_reused += 1

        category_map[item.get("id")] = category

    def make_overwrites(items):
        overwrites = {}

        for item in items:
            target = None
            if item.get("kind") == "role":
                target = role_map.get(item.get("id"))
                if target is None:
                    target = role_map_by_name.get(item.get("name"))
            elif item.get("kind") == "member":
                # 원본 서버의 멤버 ID가 대상 서버에서 같을 때만 적용
                target = guild.get_member(item.get("id"))

            if target is None:
                continue

            allow = discord.Permissions(item.get("allow", 0))
            deny = discord.Permissions(item.get("deny", 0))
            overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)

        return overwrites

    existing_text = {channel.name for channel in guild.text_channels}
    existing_voice = {channel.name for channel in guild.voice_channels}
    existing_stage = {channel.name for channel in guild.stage_channels}
    existing_forum = {channel.name for channel in guild.forums}
    existing_media = {
        channel.name for channel in guild.channels
        if getattr(channel, "type", None) == getattr(discord.ChannelType, "media", object())
    }

    channels_created = 0
    channels_skipped = 0
    errors = []

    for item in sorted(data.get("channels", []), key=lambda x: x.get("position", 0)):
        channel_type = item.get("type")
        name = str(item.get("name", "")).strip()
        if not name:
            channels_skipped += 1
            continue

        category = category_map.get(item.get("category_id"))
        overwrites = make_overwrites(item.get("overwrites", []))

        try:
            if channel_type == "text":
                if name in existing_text:
                    channels_skipped += 1
                    continue
                await guild.create_text_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    topic=item.get("topic"),
                    nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get("slowmode_delay", 0),
                    reason="서버 구조 백업 복원",
                )
                existing_text.add(name)

            elif channel_type == "voice":
                if name in existing_voice:
                    channels_skipped += 1
                    continue
                await guild.create_voice_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    bitrate=min(item.get("bitrate", 64000), guild.bitrate_limit),
                    user_limit=item.get("user_limit", 0),
                    reason="서버 구조 백업 복원",
                )
                existing_voice.add(name)

            elif channel_type == "stage":
                if name in existing_stage:
                    channels_skipped += 1
                    continue
                await guild.create_stage_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    reason="서버 구조 백업 복원",
                )
                existing_stage.add(name)

            elif channel_type == "forum":
                if name in existing_forum:
                    channels_skipped += 1
                    continue
                await guild.create_forum(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    topic=item.get("topic"),
                    nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get("slowmode_delay", 0),
                    reason="서버 구조 백업 복원",
                )
                existing_forum.add(name)

            elif channel_type == "media":
                create_media = getattr(guild, "create_media_channel", None)
                if create_media is None or name in existing_media:
                    channels_skipped += 1
                    continue
                await create_media(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    topic=item.get("topic"),
                    nsfw=item.get("nsfw", False),
                    reason="서버 구조 백업 복원",
                )
                existing_media.add(name)

            else:
                channels_skipped += 1
                continue

            channels_created += 1

        except (discord.HTTPException, TypeError, AttributeError) as error:
            errors.append(f"{name}: {type(error).__name__}: {error}")
            print(f"[STRUCTURE RESTORE ERROR] {name}: {error}")

    return {
        "roles_created": roles_created,
        "roles_reused": roles_reused,
        "categories_created": categories_created,
        "categories_reused": categories_reused,
        "channels_created": channels_created,
        "channels_skipped": channels_skipped,
        "errors": errors,
    }


# =========================================================
# 백업 명령어: 현재 서버에서 실행하고 JSON을 다운로드
# =========================================================

@bot.tree.command(
    name="서버구조백업",
    description="현재 서버의 역할과 채널 구조를 JSON 파일로 백업합니다.",
)
@app_commands.guild_only()
async def server_structure_backup(interaction: discord.Interaction):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message(
            "이 명령어는 서버 관리자만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        data, path, filename = await save_structure(interaction.guild)
        file = discord.File(path, filename=filename)

        await interaction.followup.send(
            content=(
                f"✅ **{interaction.guild.name}** 서버 구조 백업 완료!\n"
                f"역할 {len(data['roles'])}개 · "
                f"카테고리 {len(data['categories'])}개 · "
                f"채널 {len(data['channels'])}개\n\n"
                "이 JSON 파일을 안전하게 보관한 뒤, 복원할 서버에서 "
                "`/서버구조복원` 명령어에 첨부해 주세요."
            ),
            file=file,
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(
            f"❌ 백업 실패: `{type(error).__name__}: {error}`",
            ephemeral=True,
        )


# =========================================================
# 복원 명령어: 대상 서버에서 JSON 백업 파일을 첨부
# =========================================================

@bot.tree.command(
    name="서버구조복원",
    description="첨부한 JSON 백업 파일의 구조를 현재 서버에 복원합니다.",
)
@app_commands.guild_only()
@app_commands.describe(백업파일="이전에 /서버구조백업으로 받은 JSON 파일")
async def server_structure_restore_command(
    interaction: discord.Interaction,
    백업파일: discord.Attachment,
):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message(
            "이 명령어는 서버 관리자만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        data = await read_structure_attachment(백업파일)

        result = await restore_structure(interaction.guild, data)

        error_text = ""
        if result["errors"]:
            shown = result["errors"][:5]
            error_text = "\n\n⚠️ 일부 항목 오류:\n" + "\n".join(
                f"• {line}" for line in shown
            )
            if len(result["errors"]) > 5:
                error_text += f"\n• 그 외 {len(result['errors']) - 5}개 오류"

        await interaction.followup.send(
            "✅ **서버 구조 복원 작업 완료!**\n"
            f"역할 새로 생성: {result['roles_created']}개 "
            f"(기존 사용 {result['roles_reused']}개)\n"
            f"카테고리 새로 생성: {result['categories_created']}개 "
            f"(기존 사용 {result['categories_reused']}개)\n"
            f"새 채널: {result['channels_created']}개 · "
            f"건너뜀: {result['channels_skipped']}개"
            f"{error_text}\n\n"
            "※ 기존 채널이나 역할을 삭제하지 않았어요. "
            "이미 존재하는 채널은 중복 방지를 위해 건너뛰었어요.",
            ephemeral=True,
        )

    except Exception as error:
        await interaction.followup.send(
            f"❌ 복원 실패: `{type(error).__name__}: {error}`",
            ephemeral=True,
        )


# =========================================================
# 이벤트
# =========================================================

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"[BOT] 로그인 완료: {bot.user}")
    print(f"[BOT] 봇 ID: {bot.user.id}")
    print(f"[BOT] 연결된 서버: {len(bot.guilds)}개")
    print(f"[BOT] 명령어 대상 서버 ID: {GUILD_ID}")
    print("=" * 45)

    guild = discord.Object(id=GUILD_ID)

    # true일 때만 전역 명령어를 한 번 삭제합니다.
    # 삭제 전에 현재 코드의 명령어를 새 서버에 먼저 동기화합니다.
    delete_global_once = os.getenv("DELETE_GLOBAL_COMMANDS_ONCE", "false").lower() == "true"

    if delete_global_once:
        try:
            server_commands = bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            print(f"[SLASH] 새 서버 명령어 {len(synced_guild)}개 동기화 완료")

            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            print("[SLASH] 전역 명령어 전체 삭제 완료")
            print("[SLASH] DELETE_GLOBAL_COMMANDS_ONCE를 false로 바꿔 주세요.")
        except Exception as error:
            print(f"[SLASH ERROR] {type(error).__name__}: {error}")
        return

    # 평상시에는 새 서버에만 동기화합니다.
    # 전역 sync()를 실행하지 않으므로 삭제한 전역 명령어가 다시 등록되지 않습니다.
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"[SLASH] 새 서버 명령어 {len(synced)}개 동기화 완료")
    except Exception as error:
        print(f"[SLASH ERROR] {type(error).__name__}: {error}")


# =========================================================
# 실행
# =========================================================

async def main():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN 환경변수를 확인해 주세요."
        )

    await init_database()

    if core.db_pool is None:
        raise RuntimeError(
            "PostgreSQL 연결 실패. DATABASE_URL을 확인해 주세요."
        )

    await load_members_from_db()
    await load_profiles_from_db()

    print("[BOT] Discord 연결 중...")
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
