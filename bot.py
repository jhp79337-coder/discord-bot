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
