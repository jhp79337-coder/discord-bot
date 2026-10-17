# =========================================================
# Discord Server Management Bot
# bot.py
# 제작자: 백구
#
# 기존 기능 모듈 유지 + 서버 구조 백업/복원 기능
# 백업 대상: 역할, 카테고리, 텍스트/음성 채널, 권한 덮어쓰기
# 주의: 봇이 원본/새 서버 양쪽에 있어야 하며 관리 권한이 필요합니다.
# =========================================================

import asyncio
import json
from pathlib import Path

import discord
from discord import app_commands
import core
from core import *

# =========================================================
# 기존 기능 모듈 - 삭제하지 말 것
# =========================================================
import intro
import profile
import moderation
import dating
import events
import experience
import backup
import status
import economy

try:
    import activity
except ImportError as e:
    activity = None
    print(f"[MODULE WARNING] activity 모듈 없음: {e}")

try:
    import romance
except ImportError as e:
    romance = None
    print(f"[MODULE WARNING] romance 모듈 없음: {e}")

try:
    import nickname_restore
except ImportError as e:
    nickname_restore = None
    print(f"[MODULE WARNING] nickname_restore 모듈 없음: {e}")

try:
    import help_menu
except ImportError as e:
    help_menu = None
    print(f"[MODULE WARNING] help_menu 모듈 없음: {e}")


load_data()

# =========================================================
# 서버 구조 백업 설정
# 원본 서버는 core.py의 GUILD_ID를 사용합니다.
# 백업 파일이 호스팅에서 유지되는지 반드시 확인하세요.
# =========================================================
STRUCTURE_BACKUP = Path("data/server_structure_backup.json")
STRUCTURE_BACKUP.parent.mkdir(parents=True, exist_ok=True)

# 복구 작업 대상 서버 및 허용 사용자
SOURCE_GUILD_ID = 1553419235701690428
TARGET_GUILD_ID = 1561036401263382672
STRUCTURE_ALLOWED_USER_IDS = {1391947061175517411}


def can_run_structure_command(interaction: discord.Interaction) -> bool:
    """지정된 부계정 또는 해당 서버의 관리자가 백업/복원을 실행할 수 있게 합니다."""
    return (
        interaction.user.id in STRUCTURE_ALLOWED_USER_IDS
        or interaction.user.guild_permissions.administrator
    )


def overwrite_to_json(overwrites):
    result = []
    for target, overwrite in overwrites.items():
        kind = "role" if isinstance(target, discord.Role) else "member"
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

    categories = []
    channels = []
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
                "default_auto_archive_duration": channel.default_auto_archive_duration,
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
            "백업 파일이 없습니다. 원본 서버에 봇이 접속해 백업을 먼저 만들어야 합니다."
        )

    data = json.loads(STRUCTURE_BACKUP.read_text(encoding="utf-8"))
    me = guild.me
    if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
        raise PermissionError("새 서버에서 봇에 역할 관리 및 채널 관리 권한을 주세요.")

    # 새 서버에 이미 있는 같은 이름의 역할은 재사용
    role_map = {guild.default_role.id: guild.default_role}
    role_map_by_name = {r.name: r for r in guild.roles}
    for item in data.get("roles", []):
        role = role_map_by_name.get(item["name"])
        if role is None:
            role = await guild.create_role(
                name=item["name"],
                permissions=discord.Permissions(item.get("permissions", 0)),
                colour=discord.Colour(item.get("colour", 0)),
                hoist=item.get("hoist", False),
                mentionable=item.get("mentionable", False),
                reason="서버 구조 백업 복원",
            )
        role_map[item["id"]] = role

    # 기존 카테고리는 이름으로 재사용
    category_map = {}
    category_by_name = {c.name: c for c in guild.categories}
    for item in sorted(data.get("categories", []), key=lambda x: x.get("position", 0)):
        category = category_by_name.get(item["name"])
        if category is None:
            category = await guild.create_category(item["name"], reason="서버 구조 백업 복원")
        category_map[item["id"]] = category

    def make_overwrites(items):
        overwrites = {}
        for item in items:
            target = None
            if item["kind"] == "role":
                target = role_map.get(item["id"])
                if target is None:
                    target = role_map_by_name.get(item.get("name"))
            else:
                target = guild.get_member(item["id"])
            if target is None:
                continue
            allow = discord.Permissions(item.get("allow", 0))
            deny = discord.Permissions(item.get("deny", 0))
            overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)
        return overwrites

    existing_text = {c.name: c for c in guild.text_channels}
    existing_voice = {c.name: c for c in guild.voice_channels}
    existing_forum = {c.name: c for c in guild.forums}
    created = 0
    skipped = 0

    for item in sorted(data.get("channels", []), key=lambda x: x.get("position", 0)):
        channel_type = item.get("type")
        category = category_map.get(item.get("category_id"))
        overwrites = make_overwrites(item.get("overwrites", []))
        name = item["name"]

        try:
            if channel_type == "text":
                if name in existing_text:
                    skipped += 1
                    continue
                await guild.create_text_channel(
                    name=name, category=category, overwrites=overwrites,
                    topic=item.get("topic"), nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get("slowmode_delay", 0),
                    reason="서버 구조 백업 복원",
                )
            elif channel_type == "voice":
                if name in existing_voice:
                    skipped += 1
                    continue
                await guild.create_voice_channel(
                    name=name, category=category, overwrites=overwrites,
                    bitrate=min(item.get("bitrate", 64000), guild.bitrate_limit),
                    user_limit=item.get("user_limit", 0),
                    reason="서버 구조 백업 복원",
                )
            elif channel_type == "stage":
                await guild.create_stage_channel(
                    name=name, category=category, overwrites=overwrites,
                    bitrate=min(item.get("bitrate", 64000), guild.bitrate_limit),
                    user_limit=item.get("user_limit", 0),
                    reason="서버 구조 백업 복원",
                )
            elif channel_type == "forum":
                if name in existing_forum:
                    skipped += 1
                    continue
                await guild.create_forum(
                    name=name, category=category, overwrites=overwrites,
                    topic=item.get("topic"), nsfw=item.get("nsfw", False),
                    slowmode_delay=item.get("slowmode_delay", 0),
                    reason="서버 구조 백업 복원",
                )
            else:
                skipped += 1
                continue
            created += 1
        except discord.HTTPException as e:
            print(f"[STRUCTURE RESTORE] 채널 {name} 실패: {e}")
    return len(data.get("roles", [])), len(data.get("categories", [])), created, skipped


# =========================================================
# 서버 구조 슬래시 명령어
# 원본 서버에서 백업 후, 새 서버에서 복원 명령을 실행합니다.
# =========================================================
@bot.tree.command(name="서버구조백업", description="현재 서버의 역할/카테고리/채널 구조를 백업합니다.")
@app_commands.guild_only()
async def server_structure_backup(interaction: discord.Interaction):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message("이 명령어를 실행할 권한이 없어요.", ephemeral=True)
        return
    if interaction.guild_id != SOURCE_GUILD_ID:
        await interaction.response.send_message(
            f"원본 서버에서만 백업할 수 있어요. 원본 서버 ID: `{SOURCE_GUILD_ID}`",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        data = await save_structure(interaction.guild)
        await interaction.followup.send(
            f"✅ **{interaction.guild.name}** 구조 백업 완료!\n"
            f"역할 {len(data['roles'])}개 · 카테고리 {len(data['categories'])}개 · "
            f"채널 {len(data['channels'])}개",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ 백업 실패: `{type(e).__name__}: {e}`", ephemeral=True)


@bot.tree.command(name="서버구조복원", description="저장된 서버 구조를 현재 서버에 복원합니다.")
@app_commands.guild_only()
async def server_structure_restore(interaction: discord.Interaction):
    if not can_run_structure_command(interaction):
        await interaction.response.send_message("이 명령어를 실행할 권한이 없어요.", ephemeral=True)
        return
    if interaction.guild_id != TARGET_GUILD_ID:
        await interaction.response.send_message(
            f"새 서버에서만 복원할 수 있어요. 새 서버 ID: `{TARGET_GUILD_ID}`",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        roles, categories, channels, skipped = await restore_structure(interaction.guild)
        await interaction.followup.send(
            "✅ 서버 구조 복원 작업 완료!\n"
            f"역할 처리 {roles}개 · 카테고리 처리 {categories}개 · "
            f"새 채널 {channels}개 · 이미 존재/건너뜀 {skipped}개\n\n"
            "※ 기존 이름과 같은 채널은 중복 생성하지 않았어요. 역할 순서와 일부 고급 설정은 수동 조정이 필요할 수 있어요.",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ 복원 실패: `{type(e).__name__}: {e}`", ephemeral=True)


# =========================================================
# 모듈 등록
# =========================================================
def setup_modules():
    modules = [
        ("intro", intro),
        ("profile", profile),
        ("moderation", moderation),
        ("dating", dating),
        ("events", events),
        ("experience", experience),
        ("status", status),
        ("economy", economy),
        ("activity", activity),
        ("romance", romance),
        ("nickname_restore", nickname_restore),
        ("help_menu", help_menu),
    ]
    for name, module in modules:
        if module is None:
            continue
        setup_func = getattr(module, "setup", None)
        if callable(setup_func):
            try:
                setup_func(bot)
                print(f"[MODULE] {name} 등록 완료")
            except Exception as e:
                print(f"[MODULE ERROR] {name}: {type(e).__name__}: {e}")


# =========================================================
# 슬래시 명령어 동기화
# =========================================================
async def sync_slash_commands():
    """전역 명령어와 봇이 현재 들어가 있는 모든 서버에 명령어를 동기화합니다."""
    try:
        synced_global = await bot.tree.sync()
        print(f"[SLASH] 전역 명령어 {len(synced_global)}개 동기화 완료")

        # 전역 명령어 반영 지연을 피하도록 현재 연결된 각 서버에도 직접 동기화
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=discord.Object(id=guild.id))
                synced_guild = await bot.tree.sync(guild=discord.Object(id=guild.id))
                print(f"[SLASH] 서버 동기화 완료: {guild.name} ({guild.id}) / {len(synced_guild)}개")
            except Exception as e:
                print(f"[SLASH ERROR] 서버 {guild.name} ({guild.id}): {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[SLASH ERROR] {type(e).__name__}: {e}")


# =========================================================
# 봇 접속 이벤트
# =========================================================
@bot.event
async def on_ready():
    print("=" * 50)
    print(f"[BOT] 로그인 완료: {bot.user}")
    print(f"[BOT] 봇 ID: {bot.user.id}")
    print(f"[BOT] 서버 수: {len(bot.guilds)}")
    print("=" * 50)

    try:
        economy.start_economy_loops()
    except Exception as e:
        print(f"[ECONOMY ERROR] {e}")

    try:
        if hasattr(dating, "register_persistent_views"):
            dating.register_persistent_views(bot)
    except Exception as e:
        print(f"[DATING VIEW ERROR] {e}")

    # 원본 서버가 온라인 상태라면 구조를 자동 백업합니다.
    try:
        source_guild = bot.get_guild(int(GUILD_ID))
        if source_guild is not None:
            await save_structure(source_guild)
            print(f"[STRUCTURE] 자동 백업 완료: {source_guild.name}")
    except Exception as e:
        print(f"[STRUCTURE BACKUP ERROR] {type(e).__name__}: {e}")

    await sync_slash_commands()


# =========================================================
# 봇 실행
# =========================================================
async def main():
    await init_database()

    if core.db_pool is None:
        raise RuntimeError("PostgreSQL 연결 실패: DATABASE_URL을 확인해 주세요.")

    await economy.init_economy_database()
    await load_members_from_db()
    await load_profiles_from_db()
    await backup.load_runtime_state_from_db()

    if romance is not None and hasattr(romance, "init_romance_database"):
        await romance.init_romance_database()

    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN 환경변수가 없습니다.")

    setup_modules()

    if hasattr(backup, "start_backup_loop"):
        backup.start_backup_loop()

    print("[BOT] Discord 연결 중...")
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
