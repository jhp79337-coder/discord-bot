
# =========================================================
# Discord Server Management Bot
# bot.py
# 제작자: 백구
#
# 현재 파일 구조용 기본 실행 버전
# - core.py 유지
# - PostgreSQL 연결 및 기존 데이터 로드
# - 서버 구조 백업/복원 슬래시 명령어
# - 삭제된 모듈을 불러오지 않음
# =========================================================

import asyncio
import json
from pathlib import Path

import discord
from discord import app_commands

import core
from core import *

# =========================================================
# 데이터 로드
# =========================================================

load_data()

# =========================================================
# 서버 구조 백업 설정
# =========================================================

STRUCTURE_BACKUP = Path("data/server_structure_backup.json")
STRUCTURE_BACKUP.parent.mkdir(parents=True, exist_ok=True)

SOURCE_GUILD_ID = 1553419235701690428
TARGET_GUILD_ID = 1561036401263382672

STRUCTURE_ALLOWED_USER_IDS = {
    1391947061175517411
}


def can_run_structure_command(
    interaction: discord.Interaction
) -> bool:
    return (
        interaction.user.id in STRUCTURE_ALLOWED_USER_IDS
        or interaction.user.guild_permissions.administrator
    )


def overwrite_to_json(overwrites):
    result = []

    for target, overwrite in overwrites.items():
        kind = (
            "role"
            if isinstance(target, discord.Role)
            else "member"
        )

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

    for channel in sorted(
        guild.channels,
        key=lambda c: (c.position, c.id)
    ):
        entry = {
            "id": channel.id,
            "name": channel.name,
            "position": channel.position,
            "overwrites": overwrite_to_json(
                channel.overwrites
            ),
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

    return {
        "source_guild_id": guild.id,
        "source_guild_name": guild.name,
        "roles": roles,
        "categories": categories,
        "channels": channels,
    }


async def save_structure(guild: discord.Guild):
    data = build_structure(guild)

    STRUCTURE_BACKUP.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return data


async def restore_structure(guild: discord.Guild):
    if not STRUCTURE_BACKUP.exists():
        raise FileNotFoundError(
            "백업 파일이 없습니다. 원본 서버에서 "
            "/서버구조백업 명령어를 먼저 실행해 주세요."
        )

    data = json.loads(
        STRUCTURE_BACKUP.read_text(encoding="utf-8")
    )

    me = guild.me

    if (
        me is None
        or not me.guild_permissions.manage_channels
        or not me.guild_permissions.manage_roles
    ):
        raise PermissionError(
            "봇에 역할 관리 및 채널 관리 권한을 부여해 주세요."
        )

    role_map = {
        guild.default_role.id: guild.default_role
    }

    role_map_by_name = {
        role.name: role for role in guild.roles
    }

    for item in data.get("roles", []):
        role = role_map_by_name.get(item["name"])

        if role is None:
            role = await guild.create_role(
                name=item["name"],
                permissions=discord.Permissions(
                    item.get("permissions", 0)
                ),
                colour=discord.Colour(
                    item.get("colour", 0)
                ),
                hoist=item.get("hoist", False),
                mentionable=item.get("mentionable", False),
                reason="서버 구조 백업 복원",
            )

        role_map[item["id"]] = role

    category_map = {}
    category_by_name = {
        category.name: category
        for category in guild.categories
    }

    for item in sorted(
        data.get("categories", []),
        key=lambda x: x.get("position", 0)
    ):
        category = category_by_name.get(item["name"])

        if category is None:
            category = await guild.create_category(
                item["name"],
                reason="서버 구조 백업 복원",
            )

        category_map[item["id"]] = category

    def make_overwrites(items):
        overwrites = {}

        for item in items:
            if item["kind"] == "role":
                target = role_map.get(item["id"])

                if target is None:
                    target = role_map_by_name.get(
                        item.get("name")
                    )
            else:
                target = guild.get_member(item["id"])

            if target is None:
                continue

            allow = discord.Permissions(
                item.get("allow", 0)
            )
            deny = discord.Permissions(
                item.get("deny", 0)
            )

            overwrites[target] = (
                discord.PermissionOverwrite.from_pair(
                    allow, deny
                )
            )

        return overwrites

    existing_text = {
        channel.name for channel in guild.text_channels
    }
    existing_voice = {
        channel.name for channel in guild.voice_channels
    }
    existing_forum = {
        channel.name for channel in guild.forums
    }

    created = 0
    skipped = 0

    for item in sorted(
        data.get("channels", []),
        key=lambda x: x.get("position", 0)
    ):
        channel_type = item.get("type")
        name = item["name"]

        category = category_map.get(
            item.get("category_id")
        )

        overwrites = make_overwrites(
            item.get("overwrites", [])
        )

        try:
            if channel_type == "text":
                if name in existing_text:
                    skipped += 1
                    continue

                await guild.create_text_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    topic=item.get("topic"),
                    nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get(
                        "slowmode_delay", 0
                    ),
                    reason="서버 구조 백업 복원",
                )
                existing_text.add(name)

            elif channel_type == "voice":
                if name in existing_voice:
                    skipped += 1
                    continue

                await guild.create_voice_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    bitrate=min(
                        item.get("bitrate", 64000),
                        guild.bitrate_limit,
                    ),
                    user_limit=item.get("user_limit", 0),
                    reason="서버 구조 백업 복원",
                )
                existing_voice.add(name)

            elif channel_type == "stage":
                await guild.create_stage_channel(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    reason="서버 구조 백업 복원",
                )

            elif channel_type == "forum":
                if name in existing_forum:
                    skipped += 1
                    continue

                await guild.create_forum(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    topic=item.get("topic"),
                    nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get(
                        "slowmode_delay", 0
                    ),
                    reason="서버 구조 백업 복원",
                )
                existing_forum.add(name)

            else:
                skipped += 1
                continue

            created += 1

        except discord.HTTPException as error:
            print(
                f"[STRUCTURE RESTORE ERROR] "
                f"{name}: {error}"
            )

    return (
        len(data.get("roles", [])),
        len(data.get("categories", [])),
        created,
        skipped,
    )


# =========================================================
# 서버 구조 백업 명령어
# =========================================================

@bot.tree.command(
    name="서버구조백업",
    description="현재 서버의 역할과 채널 구조를 백업합니다.",
)
@app_commands.guild_only()
async def server_structure_backup(
    interaction: discord.Interaction
):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message(
            "이 명령어를 실행할 권한이 없어요.",
            ephemeral=True,
        )
        return

    if interaction.guild_id != SOURCE_GUILD_ID:
        await interaction.response.send_message(
            f"원본 서버에서만 사용할 수 있어요. "
            f"서버 ID: {SOURCE_GUILD_ID}",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True,
    )

    try:
        data = await save_structure(interaction.guild)

        await interaction.followup.send(
            f"✅ **{interaction.guild.name}** 백업 완료!\n"
            f"역할 {len(data['roles'])}개 · "
            f"카테고리 {len(data['categories'])}개 · "
            f"채널 {len(data['channels'])}개",
            ephemeral=True,
        )

    except Exception as error:
        await interaction.followup.send(
            f"❌ 백업 실패: "
            f"`{type(error).__name__}: {error}`",
            ephemeral=True,
        )


# =========================================================
# 서버 구조 복원 명령어
# =========================================================

@bot.tree.command(
    name="서버구조복원",
    description="저장된 서버 구조를 현재 서버에 복원합니다.",
)
@app_commands.guild_only()
async def server_structure_restore(
    interaction: discord.Interaction
):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message(
            "이 명령어를 실행할 권한이 없어요.",
            ephemeral=True,
        )
        return

    if interaction.guild_id != TARGET_GUILD_ID:
        await interaction.response.send_message(
            f"새 서버에서만 사용할 수 있어요. "
            f"서버 ID: {TARGET_GUILD_ID}",
            ephemeral=True,
        )
        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True,
    )

    try:
        roles, categories, channels, skipped = (
            await restore_structure(interaction.guild)
        )

        await interaction.followup.send(
            "✅ 서버 구조 복원 완료!\n"
            f"역할 처리 {roles}개 · "
            f"카테고리 처리 {categories}개 · "
            f"새 채널 {channels}개 · "
            f"건너뜀 {skipped}개",
            ephemeral=True,
        )

    except Exception as error:
        await interaction.followup.send(
            f"❌ 복원 실패: "
            f"`{type(error).__name__}: {error}`",
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
    print("=" * 45)

    try:
        synced = await bot.tree.sync()
        print(
            f"[SLASH] 전역 명령어 "
            f"{len(synced)}개 동기화 완료"
        )
    except Exception as error:
        print(
            f"[SLASH ERROR] "
            f"{type(error).__name__}: {error}"
        )


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
