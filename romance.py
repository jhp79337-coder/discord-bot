from datetime import datetime, timedelta, timezone
import asyncio

import discord
from discord import app_commands
import core


MAX_AFFECTION = 100
AFFECTION_COOLDOWN_HOURS = 24
PINK = discord.Color.from_rgb(255, 153, 204)

ROMANCE_CHALLENGE_CATEGORY = "💗・소개팅 & 연애"
ROMANCE_CHALLENGE_PREFIX = "💌・쟁탈"
ROMANCE_CHALLENGE_COOLDOWN = 60

_romance_challenge_cooldowns = {}
_registered_bots = set()


# =========================================================
# PostgreSQL
# =========================================================

async def init_romance_database():
    if core.db_pool is None:
        raise RuntimeError("[ROMANCE] PostgreSQL 연결이 없습니다.")

    async with core.db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_affection (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                last_increase_at TIMESTAMPTZ,
                PRIMARY KEY (guild_id, user_id, target_id),
                CHECK (user_id <> target_id),
                CHECK (score BETWEEN 0 AND 100)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_couples (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                partner_id BIGINT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id),
                CHECK (user_id <> partner_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_pending_confessions (
                guild_id BIGINT NOT NULL,
                from_id BIGINT NOT NULL,
                to_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, from_id),
                CHECK (from_id <> to_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_settings (
                guild_id BIGINT PRIMARY KEY,
                couple_role_id BIGINT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_marriages (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                partner_id BIGINT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id),
                CHECK (user_id <> partner_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_pending_marriages (
                guild_id BIGINT NOT NULL,
                from_id BIGINT NOT NULL,
                to_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, from_id),
                CHECK (from_id <> to_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_challenge_logs (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                challenger_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                former_partner_id BIGINT NOT NULL,
                result TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    print("[ROMANCE] 연애/결혼 데이터베이스 초기화 완료")


# =========================================================
# 공통 함수
# =========================================================

async def get_partner_id(guild_id, user_id):
    async with core.db_pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT partner_id FROM romance_couples
            WHERE guild_id=$1 AND user_id=$2
        """, guild_id, user_id)


async def is_couple(guild_id, user_id):
    return await get_partner_id(guild_id, user_id) is not None


async def are_mutual_couple(guild_id, user_id, partner_id):
    async with core.db_pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_couples a
                JOIN romance_couples b
                  ON b.guild_id=a.guild_id
                 AND b.user_id=a.partner_id
                 AND b.partner_id=a.user_id
                WHERE a.guild_id=$1
                  AND a.user_id=$2
                  AND a.partner_id=$3
            )
        """, guild_id, user_id, partner_id)


async def get_couple_role(guild_id):
    async with core.db_pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT couple_role_id FROM romance_settings
            WHERE guild_id=$1
        """, guild_id)


async def change_couple_role(guild, member, give_role):
    role_id = await get_couple_role(guild.id)
    if not role_id:
        return False, "커플 역할이 설정되지 않았어요."

    role = guild.get_role(role_id)
    if role is None:
        return False, "설정된 커플 역할을 찾을 수 없어요."

    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return False, "봇에 역할 관리 권한이 없어요."

    if role >= bot_member.top_role:
        return False, "커플 역할을 봇의 최고 역할보다 아래로 옮겨 주세요."

    try:
        if give_role and role not in member.roles:
            await member.add_roles(role, reason="연애 시스템")
        elif not give_role and role in member.roles:
            await member.remove_roles(role, reason="연애 시스템")
        return True, "완료"
    except (discord.Forbidden, discord.HTTPException):
        return False, "역할 변경에 실패했어요."


async def sync_couple_roles(guild, user_ids, give_role):
    results = []
    for user_id in set(user_ids):
        member = guild.get_member(user_id)
        if member:
            results.append(await change_couple_role(guild, member, give_role))
    return results


async def send_target_dm(member, message):
    try:
        await member.send(message)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def get_marriage_row(guild_id, user_id):
    async with core.db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT partner_id, started_at FROM romance_marriages
            WHERE guild_id=$1 AND user_id=$2
        """, guild_id, user_id)


def duration_days(started_at):
    if started_at is None:
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - started_at).days)


def is_ready():
    return core.db_pool is not None


async def reply(interaction, content=None, *, embed=None, ephemeral=False, view=None):
    if interaction.response.is_done():
        await interaction.followup.send(
            content=content, embed=embed, ephemeral=ephemeral, view=view
        )
    else:
        await interaction.response.send_message(
            content=content, embed=embed, ephemeral=ephemeral, view=view
        )


# =========================================================
# 비공개 쟁탈 버튼
# =========================================================

class RomanceChallengeView(discord.ui.View):
    def __init__(self, guild_id, challenger_id, target_id, partner_id):
        super().__init__(timeout=3600)
        self.guild_id = guild_id
        self.challenger_id = challenger_id
        self.target_id = target_id
        self.partner_id = partner_id
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.target_id:
            await reply(
                interaction,
                "최종 선택은 쟁탈 대상 본인만 할 수 있어요.",
                ephemeral=True,
            )
            return False
        if self.finished:
            await reply(interaction, "이미 종료된 쟁탈전이에요.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction, choose_challenger):
        pool = core.db_pool
        guild = interaction.guild
        if pool is None or guild is None:
            await reply(interaction, "서버 또는
