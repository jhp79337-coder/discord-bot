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
            await reply(interaction, "서버 또는 데이터베이스를 확인할 수 없어요.", ephemeral=True)
            return

        challenger_id = self.challenger_id
        target_id = self.target_id
        partner_id = self.partner_id

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    current_partner = await conn.fetchval("""
                        SELECT partner_id FROM romance_couples
                        WHERE guild_id=$1 AND user_id=$2
                        FOR UPDATE
                    """, self.guild_id, target_id)

                    if current_partner is None or int(current_partner) != partner_id:
                        await reply(interaction, "현재 커플 관계가 바뀌어 쟁탈전을 종료해요.", ephemeral=True)
                        self.finished = True
                        for item in self.children:
                            item.disabled = True
                        await interaction.message.edit(view=self)
                        return

                    if choose_challenger:
                        busy = await conn.fetchval("""
                            SELECT EXISTS (
                                SELECT 1 FROM romance_couples
                                WHERE guild_id=$1 AND user_id=$2
                            )
                        """, self.guild_id, challenger_id)

                        if busy:
                            await reply(interaction, "신청자가 이미 커플 상태라 진행할 수 없어요.", ephemeral=True)
                            return

                        await conn.execute("""
                            DELETE FROM romance_couples
                            WHERE guild_id=$1 AND user_id IN ($2,$3)
                        """, self.guild_id, target_id, partner_id)

                        await conn.execute("""
                            INSERT INTO romance_couples (guild_id,user_id,partner_id)
                            VALUES ($1,$2,$3),($1,$3,$2)
                        """, self.guild_id, target_id, challenger_id)

                        await conn.execute("""
                            DELETE FROM romance_marriages
                            WHERE guild_id=$1 AND user_id IN ($2,$3)
                        """, self.guild_id, target_id, partner_id)

                        await conn.execute("""
                            DELETE FROM romance_pending_marriages
                            WHERE guild_id=$1
                              AND (from_id IN ($2,$3) OR to_id IN ($2,$3))
                        """, self.guild_id, target_id, partner_id)

                        result = "💘 쟁탈 성공! 대상이 신청자를 선택했어요."
                        log_result = "challenger_selected"
                    else:
                        result = "💑 대상이 현재 연인을 선택했어요. 기존 커플이 유지됩니다."
                        log_result = "partner_selected"

                    await conn.execute("""
                        INSERT INTO romance_challenge_logs
                            (guild_id,challenger_id,target_id,former_partner_id,result)
                        VALUES ($1,$2,$3,$4,$5)
                    """, self.guild_id, challenger_id, target_id, partner_id, log_result)

        except Exception as exc:
            print(f"[ROMANCE CHALLENGE ERROR] {exc}")
            await reply(interaction, "쟁탈 처리 중 오류가 발생했어요. Railway 로그를 확인해 주세요.", ephemeral=True)
            return

        self.finished = True
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{result}\n신청자: <@{challenger_id}>\n"
                f"대상: <@{target_id}>\n현재 연인: <@{partner_id}>"
            ),
            view=self,
        )

        if choose_challenger:
            await change_couple_role(guild, guild.get_member(partner_id), False) if guild.get_member(partner_id) else asyncio.sleep(0)
            await change_couple_role(guild, guild.get_member(challenger_id), True) if guild.get_member(challenger_id) else asyncio.sleep(0)
            await change_couple_role(guild, guild.get_member(target_id), True) if guild.get_member(target_id) else asyncio.sleep(0)

        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            await asyncio.sleep(15)
            try:
                await channel.delete(reason="연애 쟁탈전 종료")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @discord.ui.button(label="신청자 선택", emoji="💘", style=discord.ButtonStyle.danger)
    async def choose_challenger(self, interaction, button):
        await self._finish(interaction, True)

    @discord.ui.button(label="현재 연인 선택", emoji="💑", style=discord.ButtonStyle.success)
    async def choose_partner(self, interaction, button):
        await self._finish(interaction, False)


# =========================================================
# 슬래시 명령어 등록
# bot.py에서 romance.setup(bot) 호출
# =========================================================

def setup(bot):
    if id(bot) in _registered_bots:
        return
    _registered_bots.add(id(bot))

    @bot.tree.command(name="연애도움말", description="연애 및 결혼 시스템 명령어를 확인합니다.")
    @app_commands.guild_only()
    async def romance_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="💗 연애 시스템 도움말",
            description="호감도를 쌓고 고백하고 결혼까지 해보세요!",
            color=PINK,
        )
        embed.add_field(
            name="💕 호감도",
            value="`/호감도` · `/호감도올리기`",
            inline=False,
        )
        embed.add_field(
            name="💌 고백",
            value="`/고백` · `/고백수락` · `/고백거절`",
            inline=False,
        )
        embed.add_field(
            name="💑 커플",
            value="`/커플` · `/이별` · `/커플역할설정`",
            inline=False,
        )
        embed.add_field(
            name="💍 결혼",
            value="`/결혼신청` · `/결혼수락` · `/결혼거절` · `/배우자` · `/결혼정보` · `/결혼랭킹` · `/이혼`",
            inline=False,
        )
        embed.add_field(name="💘 쟁탈", value="`/쟁탈` — 비공개 쟁탈방 생성", inline=False)
        await reply(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="호감도", description="서로의 호감도를 확인합니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="호감도를 확인할 상대")
    async def affection(interaction: discord.Interaction, 대상: discord.Member):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        if 대상.bot or 대상.id == interaction.user.id:
            return await reply(interaction, "봇이나 자기 자신은 선택할 수 없어요.")
        async with core.db_pool.acquire() as conn:
            mine = await conn.fetchval("""
                SELECT score FROM romance_affection
                WHERE guild_id=$1 AND user_id=$2 AND target_id=$3
            """, interaction.guild_id, interaction.user.id, 대상.id)
            theirs = await conn.fetchval("""
                SELECT score FROM romance_affection
                WHERE guild_id=$1 AND user_id=$2 AND target_id=$3
            """, interaction.guild_id, 대상.id, interaction.user.id)
        embed = discord.Embed(title="💗 서로의 호감도", color=PINK)
        embed.add_field(name=f"{interaction.user.display_name} → {대상.display_name}", value=f"💖 {mine or 0}/{MAX_AFFECTION}", inline=False)
        embed.add_field(name=f"{대상.display_name} → {interaction.user.display_name}", value=f"💖 {theirs or 0}/{MAX_AFFECTION}", inline=False)
        await reply(interaction, embed=embed)

    @bot.tree.command(name="호감도올리기", description="선택한 상대에 대한 호감도를 1 올립니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="호감도를 올릴 상대")
    async def increase_affection(interaction: discord.Interaction, 대상: discord.Member):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        if 대상.bot or 대상.id == interaction.user.id:
            return await reply(interaction, "봇이나 자기 자신은 선택할 수 없어요.")

        now = datetime.now(timezone.utc)
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO romance_affection (guild_id,user_id,target_id,score)
                    VALUES ($1,$2,$3,0)
                    ON CONFLICT DO NOTHING
                """, interaction.guild_id, interaction.user.id, 대상.id)
                row = await conn.fetchrow("""
                    SELECT score,last_increase_at FROM romance_affection
                    WHERE guild_id=$1 AND user_id=$2 AND target_id=$3 FOR UPDATE
                """, interaction.guild_id, interaction.user.id, 대상.id)
                last = row["last_increase_at"]
                if last:
                    next_time = last + timedelta(hours=AFFECTION_COOLDOWN_HOURS)
                    if now < next_time:
                        seconds = int((next_time - now).total_seconds())
                        hours, rem = divmod(seconds, 3600)
                        return await reply(interaction, f"⏳ 다음 호감도 증가는 **{hours}시간 {rem // 60}분 후** 가능해요.")
                if row["score"] >= MAX_AFFECTION:
                    return await reply(interaction, "💗 호감도가 이미 100이에요.")
                score = row["score"] + 1
                await conn.execute("""
                    UPDATE romance_affection SET score=$4,last_increase_at=$5
                    WHERE guild_id=$1 AND user_id=$2 AND target_id=$3
                """, interaction.guild_id, interaction.user.id, 대상.id, score, now)
        await reply(interaction, f"💗 {interaction.user.mention}님이 {대상.mention}님의 호감도를 올렸어요!\n현재 호감도: **{score}/100**")

    @bot.tree.command(name="고백", description="선택한 상대에게 고백합니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="고백할 상대")
    async def confess(interaction: discord.Interaction, 대상: discord.Member):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        if 대상.bot or 대상.id == interaction.user.id:
            return await reply(interaction, "봇이나 자기 자신에게 고백할 수 없어요.")
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                busy = await conn.fetchval("""
                    SELECT EXISTS (SELECT 1 FROM romance_couples
                    WHERE guild_id=$1 AND user_id IN ($2,$3))
                """, interaction.guild_id, interaction.user.id, 대상.id)
                if busy:
                    return await reply(interaction, "두 사람 중 한 명이 이미 커플 상태예요.")
                pending = await conn.fetchval("""
                    SELECT EXISTS (SELECT 1 FROM romance_pending_confessions
                    WHERE guild_id=$1 AND from_id=$2)
                """, interaction.guild_id, interaction.user.id)
                if pending:
                    return await reply(interaction, "이미 답변을 기다리는 고백이 있어요.")
                await conn.execute("""
                    INSERT INTO romance_pending_confessions (guild_id,from_id,to_id)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (guild_id,from_id) DO UPDATE SET
                    to_id=EXCLUDED.to_id,created_at=NOW()
                """, interaction.guild_id, interaction.user.id, 대상.id)
        delivered = await send_target_dm(
            대상,
            f"💌 **{interaction.user.display_name}**님이 고백했어요!\n"
            f"서버: **{interaction.guild.name}**\n"
            "서버에서 `/고백수락` 또는 `/고백거절`을 사용해 주세요."
        )
        msg = f"💌 {interaction.user.mention}님이 {대상.mention}님에게 고백했어요!\n상대방은 `/고백수락` 또는 `/고백거절`을 사용할 수 있어요."
        if not delivered:
            msg += "\n⚠️ DM을 보내지 못했어요. 상대방에게 직접 알려 주세요."
        await reply(interaction, msg)

    @bot.tree.command(name="고백수락", description="받은 고백을 수락합니다.")
    @app_commands.guild_only()
    async def accept_confession(interaction: discord.Interaction):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        from_id = None
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    SELECT from_id,to_id FROM romance_pending_confessions
                    WHERE guild_id=$1 AND to_id=$2
                    ORDER BY created_at ASC LIMIT 1 FOR UPDATE
                """, interaction.guild_id, interaction.user.id)
                if row is None:
                    return await reply(interaction, "수락할 고백이 없어요.")
                from_id = row["from_id"]
                busy = await conn.fetchval("""
                    SELECT EXISTS (SELECT 1 FROM romance_couples
                    WHERE guild_id=$1 AND user_id IN ($2,$3))
                """, interaction.guild_id, from_id, interaction.user.id)
                if busy:
                    await conn.execute("DELETE FROM romance_pending_confessions WHERE guild_id=$1 AND from_id=$2", interaction.guild_id, from_id)
                    return await reply(interaction, "두 사람 중 한 명이 이미 커플 상태예요.")
                await conn.execute("""
                    INSERT INTO romance_couples (guild_id,user_id,partner_id)
                    VALUES ($1,$2,$3),($1,$3,$2)
                """, interaction.guild_id, from_id, interaction.user.id)
                await conn.execute("""
                    DELETE FROM romance_pending_confessions
                    WHERE guild_id=$1 AND (from_id IN ($2,$3) OR to_id IN ($2,$3))
                """, interaction.guild_id, from_id, interaction.user.id)
        await sync_couple_roles(interaction.guild, [from_id, interaction.user.id], True)
        await reply(interaction, f"💗 **커플 성립!**\n<@{from_id}> ❤️ {interaction.user.mention}")

    @bot.tree.command(name="고백거절", description="받은 고백을 거절합니다.")
    @app_commands.guild_only()
    async def reject_confession(interaction: discord.Interaction):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        async with core.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT from_id FROM romance_pending_confessions
                WHERE guild_id=$1 AND to_id=$2 ORDER BY created_at ASC LIMIT 1
            """, interaction.guild_id, interaction.user.id)
            if row is None:
                return await reply(interaction, "거절할 고백이 없어요.")
            await conn.execute("""
                DELETE FROM romance_pending_confessions
                WHERE guild_id=$1 AND from_id=$2
            """, interaction.guild_id, row["from_id"])
        await reply(interaction, "💔 고백을 거절했어요.")

    @bot.tree.command(name="커플", description="본인 또는 선택한 사람의 커플 상태를 확인합니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="확인할 사람 (비워두면 본인)")
    async def couple(interaction: discord.Interaction, 대상: discord.Member = None):
        target = 대상 or interaction.user
        partner_id = await get_partner_id(interaction.guild_id, target.id)
        if partner_id is None:
            return await reply(interaction, f"💭 {target.mention}님은 현재 커플이 아니에요.")
        await reply(interaction, f"💑 **현재 커플**\n{target.mention} ❤️ <@{partner_id}>")

    @bot.tree.command(name="이별", description="현재 커플 관계를 해제합니다.")
    @app_commands.guild_only()
    async def breakup(interaction: discord.Interaction):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        user_id = interaction.user.id
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                partner_id = await conn.fetchval("""
                    SELECT partner_id FROM romance_couples
                    WHERE guild_id=$1 AND user_id=$2 FOR UPDATE
                """, interaction.guild_id, user_id)
                if partner_id is None:
                    return await reply(interaction, "현재 커플 상태가 아니에요.")
                await conn.execute("""
                    DELETE FROM romance_couples
                    WHERE guild_id=$1 AND user_id IN ($2,$3)
                """, interaction.guild_id, user_id, partner_id)
                await conn.execute("""
                    DELETE FROM romance_pending_confessions
                    WHERE guild_id=$1 AND (from_id IN ($2,$3) OR to_id IN ($2,$3))
                """, interaction.guild_id, user_id, partner_id)
                await conn.execute("""
                    DELETE FROM romance_marriages
                    WHERE guild_id=$1 AND user_id IN ($2,$3)
                """, interaction.guild_id, user_id, partner_id)
                await conn.execute("""
                    DELETE FROM romance_pending_marriages
                    WHERE guild_id=$1 AND (from_id IN ($2,$3) OR to_id IN ($2,$3))
                """, interaction.guild_id, user_id, partner_id)
        await sync_couple_roles(interaction.guild, [user_id, partner_id], False)
        await reply(interaction, f"💔 커플 관계가 해제됐어요.\n전 연인: <@{partner_id}>\n결혼 관계도 함께 해제됐어요.")

    @bot.tree.command(name="커플역할설정", description="커플 역할을 설정합니다. 관리자 전용.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(역할="자동 지급할 커플 역할")
    async def set_couple_role(interaction: discord.Interaction, 역할: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            return await reply(interaction, "❌ 서버 관리자만 사용할 수 있어요.", ephemeral=True)
        if 역할.is_default():
            return await reply(interaction, "서버 기본 역할은 설정할 수 없어요.")
        if interaction.guild.me is None or 역할 >= interaction.guild.me.top_role:
            return await reply(interaction, "커플 역할을 봇의 최고 역할보다 아래로 옮겨 주세요.")
        async with core.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO romance_settings (guild_id,couple_role_id)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET couple_role_id=EXCLUDED.couple_role_id
            """, interaction.guild_id, 역할.id)
        await reply(interaction, f"💗 커플 역할을 {역할.mention}(으)로 설정했어요!")

    @bot.tree.command(name="결혼신청", description="현재 연인에게 청혼합니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="현재 연인")
    async def marriage_propose(interaction: discord.Interaction, 대상: discord.Member):
        if not is_ready():
            return await reply(interaction, "데이터베이스에 연결되지 않았어요.")
        if 대상.bot or 대상.id == interaction.user.id:
            return await reply(interaction, "자신이나 봇에게 청혼할 수 없어요.")
        gid, uid, tid = interaction.guild_id, interaction.user.id, 대상.id
        async with core.db_pool.acquire() as conn:
            mutual = await conn.fetchval("""
                SELECT EXISTS (SELECT 1 FROM romance_couples a JOIN romance_couples b
                ON b.guild_id=a.guild_id AND b.user_id=a.partner_id AND b.partner_id=a.user_id
                WHERE a.guild_id=$1 AND a.user_id=$2 AND a.partner_id=$3)
            """, gid, uid, tid)
            if not mutual:
                return await reply(interaction, "현재 서로 커플인 두 사람만 결혼할 수 있어요.")
            married = await conn.fetchval("""
                SELECT EXISTS (SELECT 1 FROM romance_marriages
                WHERE guild_id=$1 AND user_id IN ($2,$3))
            """, gid, uid, tid)
            if married:
                return await reply(interaction, "두 사람 중 한 명은 이미 결혼했어요.")
            pending = await conn.fetchval("""
                SELECT EXISTS (SELECT 1 FROM romance_pending_marriages
                WHERE guild_id=$1 AND from_id=$2)
            """, gid, uid)
            if pending:
                return await reply(interaction, "이미 답변을 기다리는 청혼이 있어요.")
            await conn.execute("""
                INSERT INTO romance_pending_marriages (guild_id,from_id,to_id)
                VALUES ($1,$2,$3) ON CONFLICT (guild_id,from_id)
                DO UPDATE SET to_id=EXCLUDED.to_id,created_at=NOW()
            """, gid, uid, tid)
        delivered = await send_target_dm(대상, f"💍 **{interaction.user.display_name}님이 청혼했어요!**\n서버: {interaction.guild.name}\n`/결혼수락` 또는 `/결혼거절`을 사용해 주세요.")
        msg = f"💍 {interaction.user.mention}님이 {대상.mention}님에게 청혼했어요!\n`/결혼수락` 또는 `/결혼거절`로 답변할 수 있어요."
        if not delivered:
            msg += "\n⚠️ DM을 보내지 못했어요. 상대방에게 직접 알려 주세요."
        await reply(interaction, msg)

    @bot.tree.command(name="결혼수락", description="받은 청혼을 수락합니다.")
    @app_commands.guild_only()
    async def marriage_accept(interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    SELECT from_id,to_id FROM romance_pending_marriages
                    WHERE guild_id=$1 AND to_id=$2 ORDER BY created_at ASC LIMIT 1 FOR UPDATE
                """, gid, uid)
                if row is None:
                    return await reply(interaction, "수락할 청혼이 없어요.")
                from_id, to_id = row["from_id"], row["to_id"]
                mutual = await conn.fetchval("""
                    SELECT EXISTS (SELECT 1 FROM romance_couples a JOIN romance_couples b
                    ON b.guild_id=a.guild_id AND b.user_id=a.partner_id AND b.partner_id=a.user_id
                    WHERE a.guild_id=$1 AND a.user_id=$2 AND a.partner_id=$3)
                """, gid, from_id, to_id)
                if not mutual:
                    await conn.execute("DELETE FROM romance_pending_marriages WHERE guild_id=$1 AND from_id=$2", gid, from_id)
                    return await reply(interaction, "두 사람이 더 이상 커플이 아니에요.")
                married = await conn.fetchval("""
                    SELECT EXISTS (SELECT 1 FROM romance_marriages
                    WHERE guild_id=$1 AND user_id IN ($2,$3))
                """, gid, from_id, to_id)
                if married:
                    await conn.execute("DELETE FROM romance_pending_marriages WHERE guild_id=$1 AND from_id=$2", gid, from_id)
                    return await reply(interaction, "두 사람 중 한 명이 이미 결혼했어요.")
                await conn.execute("""
                    INSERT INTO romance_marriages (guild_id,user_id,partner_id)
                    VALUES ($1,$2,$3),($1,$3,$2)
                """, gid, from_id, to_id)
                await conn.execute("""
                    DELETE FROM romance_pending_marriages
                    WHERE guild_id=$1 AND (from_id IN ($2,$3) OR to_id IN ($2,$3))
                """, gid, from_id, to_id)
        await reply(interaction, f"💒 **결혼 성립!**\n<@{from_id}> 💍 <@{to_id}>\n축하해요! 💗")

    @bot.tree.command(name="결혼거절", description="받은 청혼을 거절합니다.")
    @app_commands.guild_only()
    async def marriage_reject(interaction: discord.Interaction):
        async with core.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT from_id FROM romance_pending_marriages
                WHERE guild_id=$1 AND to_id=$2 ORDER BY created_at ASC LIMIT 1
            """, interaction.guild_id, interaction.user.id)
            if row is None:
                return await reply(interaction, "거절할 청혼이 없어요.")
            await conn.execute("""
                DELETE FROM romance_pending_marriages
                WHERE guild_id=$1 AND from_id=$2
            """, interaction.guild_id, row["from_id"])
        await reply(interaction, "💔 청혼을 거절했어요.")

    @bot.tree.command(name="배우자", description="본인의 배우자와 결혼 기간을 확인합니다.")
    @app_commands.guild_only()
    async def spouse(interaction: discord.Interaction):
        row = await get_marriage_row(interaction.guild_id, interaction.user.id)
        if row is None:
            return await reply(interaction, "💭 아직 결혼하지 않았어요.")
        embed = discord.Embed(
            title=f"💍 {interaction.user.display_name}님의 배우자",
            description=f"배우자: <@{row['partner_id']}>\n결혼 기간: **{duration_days(row['started_at'])}일**",
            color=PINK,
        )
        await reply(interaction, embed=embed)

    @bot.tree.command(name="결혼정보", description="본인 또는 선택한 사람의 결혼 정보를 확인합니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="확인할 사람 (비워두면 본인)")
    async def marriage_info(interaction: discord.Interaction, 대상: discord.Member = None):
        target = 대상 or interaction.user
        row = await get_marriage_row(interaction.guild_id, target.id)
        if row is None:
            return await reply(interaction, f"💭 {target.mention}님은 아직 결혼하지 않았어요.")
        embed = discord.Embed(
            title="💍 결혼 정보",
            description=f"본인: {target.mention}\n배우자: <@{row['partner_id']}>\n결혼 기간: **{duration_days(row['started_at'])}일**",
            color=PINK,
        )
        await reply(interaction, embed=embed)

    @bot.tree.command(name="결혼랭킹", description="결혼 기간이 긴 커플 TOP 10을 확인합니다.")
    @app_commands.guild_only()
    async def marriage_ranking(interaction: discord.Interaction):
        async with core.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id,partner_id,started_at FROM romance_marriages
                WHERE guild_id=$1 AND user_id < partner_id
                ORDER BY started_at ASC LIMIT 10
            """, interaction.guild_id)
        if not rows:
            return await reply(interaction, "아직 등록된 결혼 커플이 없어요.")
        lines = [
            f"**{i}.** <@{r['user_id']}> 💍 <@{r['partner_id']}> — **{duration_days(r['started_at'])}일**"
            for i, r in enumerate(rows, start=1)
        ]
        await reply(interaction, embed=discord.Embed(title="🏆 결혼 기간 랭킹", description="\n".join(lines), color=PINK))

    @bot.tree.command(name="이혼", description="결혼 관계만 해제합니다. 연애 관계는 유지됩니다.")
    @app_commands.guild_only()
    async def divorce(interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        async with core.db_pool.acquire() as conn:
            async with conn.transaction():
                partner_id = await conn.fetchval("""
                    SELECT partner_id FROM romance_marriages
                    WHERE guild_id=$1 AND user_id=$2 FOR UPDATE
                """, gid, uid)
                if partner_id is None:
                    return await reply(interaction, "현재 결혼한 상태가 아니에요.")
                await conn.execute("""
                    DELETE FROM romance_marriages
                    WHERE guild_id=$1 AND user_id IN ($2,$3)
                """, gid, uid, partner_id)
                await conn.execute("""
                    DELETE FROM romance_pending_marriages
                    WHERE guild_id=$1 AND ((from_id=$2 AND to_id=$3) OR (from_id=$3 AND to_id=$2))
                """, gid, uid, partner_id)
        await reply(interaction, f"💔 결혼 관계가 해제됐어요.\n전 배우자: <@{partner_id}>\n💗 연애 관계는 유지돼요.")

    @bot.tree.command(name="쟁탈", description="현재 커플인 사람을 대상으로 비공개 쟁탈방을 만듭니다.")
    @app_commands.guild_only()
    @app_commands.describe(대상="쟁탈하고 싶은 현재 커플인 사람")
    async def challenge(interaction: discord.Interaction, 대상: discord.Member):
        if 대상.bot or 대상.id == interaction.user.id:
            return await reply(interaction, "봇이나 자기 자신에게 신청할 수 없어요.")
        now = datetime.now(timezone.utc).timestamp()
        previous = _romance_challenge_cooldowns.get(interaction.user.id, 0)
        if now - previous < ROMANCE_CHALLENGE_COOLDOWN:
            return await reply(interaction, f"⏳ {int(ROMANCE_CHALLENGE_COOLDOWN - (now - previous))}초 후 다시 신청할 수 있어요.")
        partner_id = await get_partner_id(interaction.guild_id, 대상.id)
        if partner_id is None or not await are_mutual_couple(interaction.guild_id, 대상.id, partner_id):
            return await reply(interaction, f"💭 {대상.mention}님은 현재 서로 확인된 커플 상태가 아니에요.")
        if partner_id == interaction.user.id:
            return await reply(interaction, "이미 상대방의 연인이에요.")
        if await is_couple(interaction.guild_id, interaction.user.id):
            return await reply(interaction, "현재 커플 상태에서는 쟁탈을 신청할 수 없어요.")
        partner = interaction.guild.get_member(partner_id)
        if partner is None:
            try:
                partner = await interaction.guild.fetch_member(partner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return await reply(interaction, "현재 연인을 서버에서 찾을 수 없어요.")
        async with core.db_pool.acquire() as conn:
            recent = await conn.fetchval("""
                SELECT EXISTS (SELECT 1 FROM romance_challenge_logs
                WHERE guild_id=$1 AND target_id=$2
                AND created_at > NOW() - INTERVAL '1 hour')
            """, interaction.guild_id, 대상.id)
        if recent:
            return await reply(interaction, "이 대상은 최근 쟁탈전을 진행했어요. 잠시 후 다시 시도해 주세요.")
        category = discord.utils.get(interaction.guild.categories, name=ROMANCE_CHALLENGE_CATEGORY)
        try:
            if category is None:
                category = await interaction.guild.create_category(ROMANCE_CHALLENGE_CATEGORY)
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                대상: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                partner: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            channel = await interaction.guild.create_text_channel(
                name=f"{ROMANCE_CHALLENGE_PREFIX}-{interaction.user.display_name}"[:100],
                category=category,
                overwrites=overwrites,
                topic=f"신청자:{interaction.user.id} | 대상:{대상.id} | 현재 연인:{partner.id}",
                reason="연애 쟁탈 시스템",
            )
        except discord.Forbidden:
            return await reply(interaction, "채널 생성 권한이 없어요. 봇의 채널 관리 권한을 확인해 주세요.")
        except discord.HTTPException:
            return await reply(interaction, "쟁탈 채널 생성에 실패했어요.")
        _romance_challenge_cooldowns[interaction.user.id] = now
        embed = discord.Embed(
            title="💘 연애 쟁탈전이 시작됐어요!",
            description=(
                f"💌 **신청자:** {interaction.user.mention}\n"
                f"💗 **대상:** {대상.mention}\n"
                f"💑 **현재 연인:** {partner.mention}\n\n"
                "이 채널은 위 세 사람만 볼 수 있어요.\n"
                "**쟁탈 대상 본인**이 아래 버튼으로 선택해 주세요.\n\n"
                "💘 신청자 선택 — 기존 커플을 종료하고 신청자와 새 커플이 됩니다.\n"
                "💑 현재 연인 선택 — 기존 커플을 유지합니다.\n\n"
                "선택 후 채널은 잠시 뒤 삭제됩니다."
            ),
            color=PINK,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await channel.send(
                content=f"{interaction.user.mention} {대상.mention} {partner.mention}",
                embed=embed,
                view=RomanceChallengeView(interaction.guild_id, interaction.user.id, 대상.id, partner.id),
            )
        except discord.HTTPException:
            try:
                await channel.delete(reason="쟁탈 안내 전송 실패")
            except discord.HTTPException:
                pass
            return await reply(interaction, "쟁탈 안내 메시지를 보내지 못했어요.")
        await reply(interaction, f"💌 비공개 쟁탈방을 만들었어요: {channel.mention}", ephemeral=True)
