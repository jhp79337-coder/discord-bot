
from datetime import datetime, timedelta, timezone
import asyncio

import discord
from discord.ext import commands
import core


# =========================================================
# 설정
# =========================================================

MAX_AFFECTION = 100
AFFECTION_COOLDOWN_HOURS = 24

PINK = discord.Color.from_rgb(255, 153, 204)


# =========================================================
# PostgreSQL 초기화
# core.init_database() 실행 후 호출해야 함
# =========================================================

async def init_romance_database():
    pool = core.db_pool

    if pool is None:
        raise RuntimeError(
            "[ROMANCE] PostgreSQL 연결이 없습니다. "
            "core.init_database() 실행 순서를 확인하세요."
        )

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS romance_affection (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                last_increase_at TIMESTAMPTZ,
                PRIMARY KEY (guild_id, user_id, target_id),
                CHECK (user_id <> target_id),
                CHECK (score >= 0 AND score <= 100)
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

        # 결혼 관계: 배우자 양쪽에 각각 한 행 저장
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

        # 결혼 신청 대기
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

    print("[ROMANCE] PostgreSQL 연애 / 결혼 시스템 초기화 완료")


# =========================================================
# 공통 함수
# =========================================================

def get_guild_id(ctx):
    return ctx.guild.id if ctx.guild else None


async def get_partner_id(guild_id, user_id):
    pool = core.db_pool

    if pool is None:
        return None

    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT partner_id
            FROM romance_couples
            WHERE guild_id = $1 AND user_id = $2
        """, guild_id, user_id)


async def get_couple_role(guild_id):
    pool = core.db_pool

    if pool is None:
        return None

    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT couple_role_id
            FROM romance_settings
            WHERE guild_id = $1
        """, guild_id)


async def is_couple(guild_id, user_id):
    return await get_partner_id(guild_id, user_id) is not None


async def are_mutual_couple(guild_id, user_id, partner_id):
    """두 사람의 커플 정보가 서로 일치하는지 확인."""
    pool = core.db_pool

    if pool is None:
        return False

    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM romance_couples a
                JOIN romance_couples b
                  ON b.guild_id = a.guild_id
                 AND b.user_id = a.partner_id
                 AND b.partner_id = a.user_id
                WHERE a.guild_id = $1
                  AND a.user_id = $2
                  AND a.partner_id = $3
            )
        """, guild_id, user_id, partner_id)


async def change_couple_role(guild, member, give_role):
    role_id = await get_couple_role(guild.id)

    if not role_id:
        return False, "설정된 커플 역할이 없습니다."

    role = guild.get_role(role_id)

    if role is None:
        return False, "설정된 역할을 찾을 수 없습니다."

    bot_member = guild.me

    if bot_member is None:
        return False, "봇의 서버 정보를 확인할 수 없습니다."

    if not bot_member.guild_permissions.manage_roles:
        return False, "봇에 역할 관리 권한이 없습니다."

    if role >= bot_member.top_role:
        return False, "커플 역할이 봇의 최고 역할보다 위에 있습니다."

    try:
        if give_role and role not in member.roles:
            await member.add_roles(role, reason="연애 시스템: 커플 성립")
        elif not give_role and role in member.roles:
            await member.remove_roles(role, reason="연애 시스템: 커플 해제")

        return True, "완료"

    except discord.Forbidden:
        return False, "역할을 변경할 권한이 없습니다."

    except discord.HTTPException:
        return False, "Discord에서 역할 변경에 실패했습니다."


async def send_target_dm(member, message):
    try:
        await member.send(message)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def get_marriage_row(guild_id, user_id):
    pool = core.db_pool

    if pool is None:
        return None

    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT partner_id, started_at
            FROM romance_marriages
            WHERE guild_id = $1 AND user_id = $2
        """, guild_id, user_id)


def duration_days(started_at):
    if started_at is None:
        return 0

    now = datetime.now(timezone.utc)

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return max(0, (now - started_at).days)


# =========================================================
# 도움말
# =========================================================

@core.bot.command(name="연애도움말")
async def romance_help(ctx):
    embed = discord.Embed(
        title="💗 연애 시스템 도움말",
        description="호감도를 쌓고, 고백하고, 결혼까지 해보세요!",
        color=PINK
    )

    embed.add_field(
        name="💕 호감도",
        value=(
            "`!호감도 @유저` — 서로의 호감도 확인\n"
            "`!호감도올리기 @유저` — 호감도 +1\n"
            "같은 상대에게 24시간마다 한 번 올릴 수 있어요."
        ),
        inline=False
    )

    embed.add_field(
        name="💌 고백",
        value=(
            "`!고백 @유저` — 상대방에게 고백\n"
            "`!고백수락` — 받은 고백 수락\n"
            "`!고백거절` — 받은 고백 거절"
        ),
        inline=False
    )

    embed.add_field(
        name="💑 커플",
        value=(
            "`!커플` — 내 커플 상태 확인\n"
            "`!커플 @유저` — 상대방의 커플 상태 확인\n"
            "`!이별` — 커플 관계 해제\n"
            "`!커플역할설정 @역할` — 커플 역할 설정 (관리자)"
        ),
        inline=False
    )

    embed.add_field(
        name="💍 결혼",
        value=(
            "`!결혼신청 @연인` — 현재 연인에게 청혼\n"
            "`!결혼수락` — 받은 청혼 수락\n"
            "`!결혼거절` — 받은 청혼 거절\n"
            "`!배우자` — 내 배우자 확인\n"
            "`!결혼정보 [@유저]` — 결혼 정보 확인\n"
            "`!결혼랭킹` — 결혼 기간 랭킹\n"
            "`!이혼` — 결혼 관계 해제 (연애는 유지)"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# 호감도 확인
# =========================================================

@core.bot.command(name="호감도")
async def romance_affection(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!호감도 @유저`")

    if member.bot:
        return await ctx.send("봇에게는 호감도를 설정할 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게는 호감도를 설정할 수 없어요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    async with pool.acquire() as conn:
        mine = await conn.fetchval("""
            SELECT score FROM romance_affection
            WHERE guild_id = $1 AND user_id = $2 AND target_id = $3
        """, ctx.guild.id, ctx.author.id, member.id)

        theirs = await conn.fetchval("""
            SELECT score FROM romance_affection
            WHERE guild_id = $1 AND user_id = $2 AND target_id = $3
        """, ctx.guild.id, member.id, ctx.author.id)

    mine = mine or 0
    theirs = theirs or 0

    embed = discord.Embed(
        title="💗 서로의 호감도",
        color=PINK
    )

    embed.add_field(
        name=f"{ctx.author.display_name} → {member.display_name}",
        value=f"💖 {mine}/{MAX_AFFECTION}",
        inline=False
    )

    embed.add_field(
        name=f"{member.display_name} → {ctx.author.display_name}",
        value=f"💖 {theirs}/{MAX_AFFECTION}",
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# 호감도 증가
# =========================================================

@core.bot.command(name="호감도올리기")
async def romance_increase_affection(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!호감도올리기 @유저`")

    if member.bot:
        return await ctx.send("봇에게는 호감도를 올릴 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게는 호감도를 올릴 수 없어요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    target_id = member.id

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 행이 아직 없을 수 있으므로 최초 등록을 먼저 보장
            await conn.execute("""
                INSERT INTO romance_affection
                    (guild_id, user_id, target_id, score)
                VALUES ($1, $2, $3, 0)
                ON CONFLICT (guild_id, user_id, target_id) DO NOTHING
            """, guild_id, user_id, target_id)

            row = await conn.fetchrow("""
                SELECT score, last_increase_at
                FROM romance_affection
                WHERE guild_id = $1 AND user_id = $2 AND target_id = $3
                FOR UPDATE
            """, guild_id, user_id, target_id)

            now = datetime.now(timezone.utc)

            if row["last_increase_at"]:
                next_time = row["last_increase_at"] + timedelta(
                    hours=AFFECTION_COOLDOWN_HOURS
                )

                if now < next_time:
                    remaining = next_time - now
                    seconds = int(remaining.total_seconds())
                    hours, remainder = divmod(seconds, 3600)
                    minutes = remainder // 60

                    return await ctx.send(
                        f"⏳ {member.mention}님의 호감도는 이미 올렸어요.\n"
                        f"다음 증가는 **{hours}시간 {minutes}분 후** 가능해요."
                    )

            current_score = row["score"]

            if current_score >= MAX_AFFECTION:
                return await ctx.send(
                    f"💗 {member.mention}님에 대한 호감도가 이미 100이에요!"
                )

            new_score = min(current_score + 1, MAX_AFFECTION)

            await conn.execute("""
                UPDATE romance_affection
                SET score = $4, last_increase_at = $5
                WHERE guild_id = $1 AND user_id = $2 AND target_id = $3
            """, guild_id, user_id, target_id, new_score, now)

    await ctx.send(
        f"💗 {ctx.author.mention}님이 {member.mention}님의 호감도를 올렸어요!\n"
        f"현재 호감도: **{new_score}/{MAX_AFFECTION}**"
    )


# =========================================================
# 고백
# =========================================================

@core.bot.command(name="고백")
async def romance_confess(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!고백 @유저`")

    if member.bot:
        return await ctx.send("봇에게 고백할 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게 고백할 수는 없어요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    target_id = member.id

    async with pool.acquire() as conn:
        if await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_couples
                WHERE guild_id = $1 AND user_id = $2
            )
        """, guild_id, user_id):
            return await ctx.send("이미 커플 상태라서 고백할 수 없어요.")

        if await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_couples
                WHERE guild_id = $1 AND user_id = $2
            )
        """, guild_id, target_id):
            return await ctx.send("상대방은 이미 커플 상태예요.")

        if await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_pending_confessions
                WHERE guild_id = $1 AND from_id = $2
            )
        """, guild_id, user_id):
            return await ctx.send("이미 답변을 기다리는 고백이 있어요.")

        await conn.execute("""
            INSERT INTO romance_pending_confessions
                (guild_id, from_id, to_id)
            VALUES ($1, $2, $3)
        """, guild_id, user_id, target_id)

    delivered = await send_target_dm(
        member,
        f"💌 **{ctx.author.display_name}**님이 당신에게 고백했어요!\n"
        f"서버: **{ctx.guild.name}**\n\n"
        "수락: 해당 서버에서 `!고백수락`\n"
        "거절: 해당 서버에서 `!고백거절`"
    )

    message = (
        f"💌 {ctx.author.mention}님이 {member.mention}님에게 고백했어요!\n"
        "상대방이 `!고백수락`을 입력하면 커플이 됩니다."
    )

    if not delivered:
        message += "\n⚠️ DM을 보내지 못했어요. 상대방에게 서버에서 확인해 달라고 알려 주세요."

    await ctx.send(message)


# =========================================================
# 고백 수락
# =========================================================

@core.bot.command(name="고백수락")
async def romance_accept(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    from_id = None
    to_id = None

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                confession = await conn.fetchrow("""
                    SELECT from_id, to_id
                    FROM romance_pending_confessions
                    WHERE guild_id = $1 AND to_id = $2
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE
                """, guild_id, user_id)

                if confession is None:
                    return await ctx.send("수락할 고백이 없어요.")

                from_id = confession["from_id"]
                to_id = confession["to_id"]

                busy = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM romance_couples
                        WHERE guild_id = $1
                          AND user_id IN ($2, $3)
                    )
                """, guild_id, from_id, to_id)

                if busy:
                    await conn.execute("""
                        DELETE FROM romance_pending_confessions
                        WHERE guild_id = $1 AND from_id = $2
                    """, guild_id, from_id)

                    return await ctx.send(
                        "두 사람 중 한 명이 이미 커플 상태라서 수락할 수 없어요."
                    )

                await conn.execute("""
                    INSERT INTO romance_couples
                        (guild_id, user_id, partner_id)
                    VALUES ($1, $2, $3), ($1, $3, $2)
                """, guild_id, from_id, to_id)

                await conn.execute("""
                    DELETE FROM romance_pending_confessions
                    WHERE guild_id = $1
                      AND (from_id IN ($2, $3) OR to_id IN ($2, $3))
                """, guild_id, from_id, to_id)

    except Exception as exc:
        print(f"[ROMANCE ACCEPT ERROR] {exc}")
        return await ctx.send("고백 수락 처리 중 오류가 발생했어요. Railway 로그를 확인해 주세요.")

    role_results = []

    for member_id in (from_id, to_id):
        member_obj = ctx.guild.get_member(member_id)

        if member_obj is not None:
            success, message = await change_couple_role(
                ctx.guild, member_obj, True
            )
            role_results.append((success, message))

    result = (
        "💗 **커플 성립!**\n"
        f"<@{from_id}> ❤️ <@{to_id}>\n"
        "두 사람의 연애가 시작됐어요!"
    )

    if any(not success for success, _ in role_results):
        result += "\n⚠️ 커플은 성립했지만 역할 지급에 문제가 있을 수 있어요. 관리자에게 확인해 주세요."

    await ctx.send(result)


# =========================================================
# 고백 거절
# =========================================================

@core.bot.command(name="고백거절")
async def romance_reject(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    async with pool.acquire() as conn:
        confession = await conn.fetchrow("""
            SELECT from_id
            FROM romance_pending_confessions
            WHERE guild_id = $1 AND to_id = $2
            ORDER BY created_at ASC
            LIMIT 1
        """, ctx.guild.id, ctx.author.id)

        if confession is None:
            return await ctx.send("거절할 고백이 없어요.")

        await conn.execute("""
            DELETE FROM romance_pending_confessions
            WHERE guild_id = $1 AND from_id = $2
        """, ctx.guild.id, confession["from_id"])

    await ctx.send("💔 고백을 거절했어요.")


# =========================================================
# 커플 상태
# =========================================================

@core.bot.command(name="커플")
async def romance_couple(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    target = member or ctx.author
    partner_id = await get_partner_id(ctx.guild.id, target.id)

    if partner_id is None:
        if member is not None and member.id != ctx.author.id:
            return await ctx.send(f"💭 {target.mention}님은 현재 커플이 아니에요.")
        return await ctx.send("💭 현재 커플이 아니에요.")

    await ctx.send(
        f"💑 **현재 커플**\n"
        f"{target.mention} ❤️ <@{partner_id}>"
    )


# =========================================================
# 이별
# 이별 시 결혼도 해제하며 커플 역할을 회수함
# =========================================================

@core.bot.command(name="이별")
async def romance_breakup(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id

    async with pool.acquire() as conn:
        async with conn.transaction():
            partner_id = await conn.fetchval("""
                SELECT partner_id
                FROM romance_couples
                WHERE guild_id = $1 AND user_id = $2
                FOR UPDATE
            """, guild_id, user_id)

            if partner_id is None:
                return await ctx.send("현재 커플 상태가 아니에요.")

            await conn.execute("""
                DELETE FROM romance_couples
                WHERE guild_id = $1 AND user_id IN ($2, $3)
            """, guild_id, user_id, partner_id)

            await conn.execute("""
                DELETE FROM romance_pending_confessions
                WHERE guild_id = $1
                  AND (from_id IN ($2, $3) OR to_id IN ($2, $3))
            """, guild_id, user_id, partner_id)

            # 커플이 헤어지면 결혼도 함께 종료
            await conn.execute("""
                DELETE FROM romance_marriages
                WHERE guild_id = $1 AND user_id IN ($2, $3)
            """, guild_id, user_id, partner_id)

            await conn.execute("""
                DELETE FROM romance_pending_marriages
                WHERE guild_id = $1
                  AND (from_id IN ($2, $3) OR to_id IN ($2, $3))
            """, guild_id, user_id, partner_id)

    for member_id in (user_id, partner_id):
        member_obj = ctx.guild.get_member(member_id)

        if member_obj is not None:
            await change_couple_role(ctx.guild, member_obj, False)

    await ctx.send(
        f"💔 {ctx.author.mention}님의 요청으로 커플 관계가 해제됐어요.\n"
        f"상대방: <@{partner_id}>\n"
        "결혼 관계가 있었다면 함께 해제됐어요."
    )


# =========================================================
# 커플 역할 설정 (관리자)
# =========================================================

@core.bot.command(name="커플역할설정")
@commands.has_permissions(administrator=True)
async def romance_set_role(ctx, role: discord.Role = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if role is None:
        return await ctx.send("사용법: `!커플역할설정 @커플역할`")

    if role.is_default():
        return await ctx.send("서버 기본 역할은 설정할 수 없어요.")

    if ctx.guild.me is None or role >= ctx.guild.me.top_role:
        return await ctx.send(
            "⚠️ 커플 역할을 봇의 최고 역할보다 아래로 옮긴 뒤 다시 설정해 주세요."
        )

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO romance_settings (guild_id, couple_role_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET couple_role_id = EXCLUDED.couple_role_id
        """, ctx.guild.id, role.id)

    await ctx.send(f"💗 커플 역할을 {role.mention}(으)로 설정했어요!")


@romance_set_role.error
async def romance_set_role_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어는 서버 관리자만 사용할 수 있어요.")
    else:
        print(f"[ROMANCE ROLE ERROR] {error}")
        await ctx.send("역할 설정 중 오류가 발생했어요.")


# =========================================================
# 결혼 신청
# 현재 서로 커플인 두 사람만 결혼 가능
# =========================================================

@core.bot.command(name="결혼신청")
async def marriage_propose(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!결혼신청 @연인`")

    if member.bot or member.id == ctx.author.id:
        return await ctx.send("자신이나 봇에게 청혼할 수 없어요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    target_id = member.id

    async with pool.acquire() as conn:
        mutual = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM romance_couples a
                JOIN romance_couples b
                  ON b.guild_id = a.guild_id
                 AND b.user_id = a.partner_id
                 AND b.partner_id = a.user_id
                WHERE a.guild_id = $1
                  AND a.user_id = $2
                  AND a.partner_id = $3
            )
        """, guild_id, user_id, target_id)

        if not mutual:
            return await ctx.send(
                "💭 결혼은 현재 서로 커플인 두 사람만 신청할 수 있어요."
            )

        married = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_marriages
                WHERE guild_id = $1 AND user_id IN ($2, $3)
            )
        """, guild_id, user_id, target_id)

        if married:
            return await ctx.send("💍 두 사람 중 한 명은 이미 결혼했어요.")

        pending = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_pending_marriages
                WHERE guild_id = $1 AND from_id = $2
            )
        """, guild_id, user_id)

        if pending:
            return await ctx.send(
                "이미 답변을 기다리는 청혼이 있어요."
            )

        await conn.execute("""
            INSERT INTO romance_pending_marriages
                (guild_id, from_id, to_id)
            VALUES ($1, $2, $3)
        """, guild_id, user_id, target_id)

    delivered = await send_target_dm(
        member,
        f"💍 **{ctx.author.display_name}님이 청혼했어요!**\n"
        f"서버: **{ctx.guild.name}**\n\n"
        "수락: 해당 서버에서 `!결혼수락`\n"
        "거절: 해당 서버에서 `!결혼거절`"
    )

    message = (
        f"💍 {ctx.author.mention}님이 {member.mention}님에게 청혼했어요!\n"
        "상대방이 `!결혼수락`을 입력하면 결혼이 성립해요."
    )

    if not delivered:
        message += "\n⚠️ 상대방에게 DM을 보내지 못했어요. 서버에서 직접 알려 주세요."

    await ctx.send(message)


# =========================================================
# 결혼 수락
# =========================================================

@core.bot.command(name="결혼수락")
async def marriage_accept(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    from_id = None
    to_id = None

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                proposal = await conn.fetchrow("""
                    SELECT from_id, to_id
                    FROM romance_pending_marriages
                    WHERE guild_id = $1 AND to_id = $2
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE
                """, guild_id, user_id)

                if proposal is None:
                    return await ctx.send("수락할 청혼이 없어요.")

                from_id = proposal["from_id"]
                to_id = proposal["to_id"]

                mutual = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM romance_couples a
                        JOIN romance_couples b
                          ON b.guild_id = a.guild_id
                         AND b.user_id = a.partner_id
                         AND b.partner_id = a.user_id
                        WHERE a.guild_id = $1
                          AND a.user_id = $2
                          AND a.partner_id = $3
                    )
                """, guild_id, from_id, to_id)

                if not mutual:
                    await conn.execute("""
                        DELETE FROM romance_pending_marriages
                        WHERE guild_id = $1 AND from_id = $2
                    """, guild_id, from_id)

                    return await ctx.send(
                        "두 사람이 더 이상 커플이 아니어서 결혼할 수 없어요."
                    )

                married = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM romance_marriages
                        WHERE guild_id = $1 AND user_id IN ($2, $3)
                    )
                """, guild_id, from_id, to_id)

                if married:
                    await conn.execute("""
                        DELETE FROM romance_pending_marriages
                        WHERE guild_id = $1 AND from_id = $2
                    """, guild_id, from_id)

                    return await ctx.send(
                        "두 사람 중 한 명이 이미 결혼했어요."
                    )

                await conn.execute("""
                    INSERT INTO romance_marriages
                        (guild_id, user_id, partner_id)
                    VALUES ($1, $2, $3), ($1, $3, $2)
                """, guild_id, from_id, to_id)

                # 두 사람에게 걸려 있는 다른 청혼도 정리
                await conn.execute("""
                    DELETE FROM romance_pending_marriages
                    WHERE guild_id = $1
                      AND (
                          from_id IN ($2, $3)
                          OR to_id IN ($2, $3)
                      )
                """, guild_id, from_id, to_id)

    except Exception as exc:
        print(f"[MARRIAGE ACCEPT ERROR] {exc}")
        return await ctx.send(
            "결혼 수락 중 오류가 발생했어요. Railway 로그를 확인해 주세요."
        )

    await ctx.send(
        "💒 **결혼 성립!**\n"
        f"<@{from_id}> 💍 <@{to_id}>\n"
        "두 사람의 결혼을 축하해요! 💗"
    )


# =========================================================
# 결혼 거절
# =========================================================

@core.bot.command(name="결혼거절")
async def marriage_reject(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    async with pool.acquire() as conn:
        proposal = await conn.fetchrow("""
            SELECT from_id
            FROM romance_pending_marriages
            WHERE guild_id = $1 AND to_id = $2
            ORDER BY created_at ASC
            LIMIT 1
        """, ctx.guild.id, ctx.author.id)

        if proposal is None:
            return await ctx.send("거절할 청혼이 없어요.")

        await conn.execute("""
            DELETE FROM romance_pending_marriages
            WHERE guild_id = $1 AND from_id = $2
        """, ctx.guild.id, proposal["from_id"])

    await ctx.send("💔 청혼을 거절했어요.")


# =========================================================
# 배우자 확인
# =========================================================

@core.bot.command(name="배우자")
async def marriage_spouse(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    row = await get_marriage_row(ctx.guild.id, ctx.author.id)

    if row is None:
        return await ctx.send("💭 아직 결혼하지 않았어요.")

    days = duration_days(row["started_at"])

    embed = discord.Embed(
        title=f"💍 {ctx.author.display_name}님의 배우자",
        description=(
            f"배우자: <@{row['partner_id']}>\n"
            f"결혼 기간: **{days}일**"
        ),
        color=PINK
    )

    await ctx.send(embed=embed)


# =========================================================
# 결혼 정보
# =========================================================

@core.bot.command(name="결혼정보")
async def marriage_info(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    target = member or ctx.author
    row = await get_marriage_row(ctx.guild.id, target.id)

    if row is None:
        return await ctx.send(
            f"💭 {target.mention}님은 아직 결혼하지 않았어요."
        )

    days = duration_days(row["started_at"])

    embed = discord.Embed(
        title="💍 결혼 정보",
        description=(
            f"본인: {target.mention}\n"
            f"배우자: <@{row['partner_id']}>\n"
            f"결혼 기간: **{days}일**"
        ),
        color=PINK
    )

    await ctx.send(embed=embed)


# =========================================================
# 결혼 기간 랭킹
# =========================================================

@core.bot.command(name="결혼랭킹")
async def marriage_ranking(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, partner_id, started_at
            FROM romance_marriages
            WHERE guild_id = $1 AND user_id < partner_id
            ORDER BY started_at ASC
            LIMIT 10
        """, ctx.guild.id)

    if not rows:
        return await ctx.send("아직 등록된 결혼 커플이 없어요.")

    lines = []

    for index, row in enumerate(rows, start=1):
        days = duration_days(row["started_at"])

        lines.append(
            f"**{index}.** <@{row['user_id']}> 💍 "
            f"<@{row['partner_id']}> — **{days}일**"
        )

    embed = discord.Embed(
        title="🏆 결혼 기간 랭킹",
        description="\n".join(lines),
        color=PINK
    )

    await ctx.send(embed=embed)


# =========================================================
# 이혼
# 결혼만 해제하고 연애 커플 관계는 유지
# =========================================================

@core.bot.command(name="이혼")
async def marriage_divorce(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    partner_id = None

    async with pool.acquire() as conn:
        async with conn.transaction():
            partner_id = await conn.fetchval("""
                SELECT partner_id
                FROM romance_marriages
                WHERE guild_id = $1 AND user_id = $2
                FOR UPDATE
            """, guild_id, user_id)

            if partner_id is None:
                return await ctx.send("현재 결혼한 상태가 아니에요.")

            await conn.execute("""
                DELETE FROM romance_marriages
                WHERE guild_id = $1 AND user_id IN ($2, $3)
            """, guild_id, user_id, partner_id)

            await conn.execute("""
                DELETE FROM romance_pending_marriages
                WHERE guild_id = $1
                  AND (
                      (from_id = $2 AND to_id = $3)
                      OR
                      (from_id = $3 AND to_id = $2)
                  )
            """, guild_id, user_id, partner_id)

    await ctx.send(
        f"💔 {ctx.author.mention}님의 요청으로 결혼 관계가 해제됐어요.\n"
        f"전 배우자: <@{partner_id}>\n"
        "💗 기존 연애 관계는 유지돼요."
    )



# =========================================================
# 💘 연애 쟁탈 시스템
# 기존 romance_couples / romance_settings 테이블 사용
# 명령어: !쟁탈 @현재 커플인 사람
# =========================================================

ROMANCE_CHALLENGE_CATEGORY = "💘・연애 쟁탈"
ROMANCE_CHALLENGE_PREFIX = "💌・쟁탈"
ROMANCE_CHALLENGE_COOLDOWN = 60

_romance_challenge_cooldowns = {}


async def _get_romance_couple_pair(guild_id, user_id):
    """커플 테이블에서 대상과 상대방의 관계를 확인."""
    pool = core.db_pool
    if pool is None:
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT a.partner_id
            FROM romance_couples a
            JOIN romance_couples b
              ON b.guild_id = a.guild_id
             AND b.user_id = a.partner_id
             AND b.partner_id = a.user_id
            WHERE a.guild_id = $1 AND a.user_id = $2
        """, guild_id, user_id)

    return int(row["partner_id"]) if row else None


async def _close_romance_challenge_record(guild_id, challenger_id, target_id, partner_id):
    """쟁탈이 끝난 뒤 해당 커플 관계를 최신 상태로 확인하는 보조 함수."""
    pool = core.db_pool
    if pool is None:
        return
    # 쟁탈 기록 테이블은 별도 생성하며 기존 연애 데이터는 건드리지 않음.
    async with pool.acquire() as conn:
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


class RomanceChallengeView(discord.ui.View):
    """쟁탈 대상 본인이 최종 상대를 선택합니다. 버튼은 시간 제한 없이 유지됩니다."""

    def __init__(self, guild_id, challenger_id, target_id, partner_id):
        # timeout=None: 시간이 지나도 버튼이 만료되지 않음.
        # 버튼 custom_id는 기존 메시지와의 호환성을 위해 decorator 기본값을 유지합니다.
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.challenger_id = challenger_id
        self.target_id = target_id
        self.partner_id = partner_id
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                "최종 선택은 쟁탈 대상 본인만 할 수 있어요.",
                ephemeral=True,
            )
            return False
        if self.finished:
            await interaction.response.send_message(
                "이미 종료된 쟁탈전이에요.",
                ephemeral=True,
            )
            return False
        return True

    async def _finish(self, interaction, choose_challenger: bool):
        pool = core.db_pool
        guild = interaction.guild
        if pool is None or guild is None:
            await interaction.response.send_message(
                "데이터베이스 또는 서버 정보를 확인할 수 없어요.",
                ephemeral=True,
            )
            return

        challenger_id = self.challenger_id
        target_id = self.target_id
        partner_id = self.partner_id

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    current_partner = await conn.fetchval("""
                        SELECT partner_id
                        FROM romance_couples
                        WHERE guild_id = $1 AND user_id = $2
                        FOR UPDATE
                    """, self.guild_id, target_id)

                    if current_partner is None or int(current_partner) != partner_id:
                        await interaction.response.send_message(
                            "현재 커플 관계가 바뀌어서 쟁탈전을 종료할게요.",
                            ephemeral=True,
                        )
                        self.finished = True
                        for item in self.children:
                            item.disabled = True
                        await interaction.message.edit(view=self)
                        return

                    if choose_challenger:
                        challenger_busy = await conn.fetchval("""
                            SELECT EXISTS (
                                SELECT 1 FROM romance_couples
                                WHERE guild_id = $1 AND user_id = $2
                            )
                        """, self.guild_id, challenger_id)

                        if challenger_busy:
                            await interaction.response.send_message(
                                "신청자가 이미 다른 커플이어서 관계를 변경할 수 없어요.",
                                ephemeral=True,
                            )
                            return

                        # 기존 커플 관계 해제 후 대상과 신청자를 새 커플로 등록.
                        await conn.execute("""
                            DELETE FROM romance_couples
                            WHERE guild_id = $1 AND user_id IN ($2, $3)
                        """, self.guild_id, target_id, partner_id)

                        await conn.execute("""
                            INSERT INTO romance_couples (guild_id, user_id, partner_id)
                            VALUES ($1, $2, $3), ($1, $3, $2)
                        """, self.guild_id, target_id, challenger_id)

                        # 기존 결혼 관계와 대기 중인 청혼도 정리.
                        await conn.execute("""
                            DELETE FROM romance_marriages
                            WHERE guild_id = $1 AND user_id IN ($2, $3)
                        """, self.guild_id, target_id, partner_id)

                        await conn.execute("""
                            DELETE FROM romance_pending_marriages
                            WHERE guild_id = $1
                              AND (from_id IN ($2, $3) OR to_id IN ($2, $3))
                        """, self.guild_id, target_id, partner_id)

                        result = "💘 쟁탈 성공! 대상이 신청자를 선택했어요."
                        log_result = "challenger_selected"
                    else:
                        result = "💔 쟁탈 종료! 대상이 현재 연인을 선택했어요."
                        log_result = "partner_selected"

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

                    await conn.execute("""
                        INSERT INTO romance_challenge_logs
                            (guild_id, challenger_id, target_id, former_partner_id, result)
                        VALUES ($1, $2, $3, $4, $5)
                    """, self.guild_id, challenger_id, target_id, partner_id, log_result)

        except Exception as exc:
            print(f"[ROMANCE CHALLENGE ERROR] {exc}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "쟁탈 결과를 저장하는 중 오류가 발생했어요. Railway 로그를 확인해 주세요.",
                    ephemeral=True,
                )
            return

        self.finished = True
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{result}\n"
                f"쟁탈 신청자: <@{challenger_id}>\n"
                f"쟁탈 대상: <@{target_id}>\n"
                f"현재 연인: <@{partner_id}>"
            ),
            view=self,
        )

        # 커플 역할 동기화
        if choose_challenger:
            challenger_member = guild.get_member(challenger_id)
            target_member = guild.get_member(target_id)
            partner_member = guild.get_member(partner_id)

            if partner_member:
                await change_couple_role(guild, partner_member, False)
            if challenger_member:
                await change_couple_role(guild, challenger_member, True)
            if target_member:
                await change_couple_role(guild, target_member, True)

        # 결과를 남긴 뒤 잠시 후 쟁탈방 삭제
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            await asyncio.sleep(15)
            try:
                await channel.delete(reason="연애 쟁탈전 종료")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @discord.ui.button(
        label="신청자 선택",
        emoji="💘",
        style=discord.ButtonStyle.danger,
        custom_id="romance_challenge:choose_challenger",
    )
    async def choose_challenger(self, interaction, button):
        await self._finish(interaction, True)

    @discord.ui.button(
        label="현재 연인 선택",
        emoji="💑",
        style=discord.ButtonStyle.success,
        custom_id="romance_challenge:choose_partner",
    )
    async def choose_partner(self, interaction, button):
        await self._finish(interaction, False)


@core.bot.command(name="쟁탈")
@commands.guild_only()
async def romance_challenge(ctx, member: discord.Member = None):
    """현재 커플인 사람을 대상으로 비공개 쟁탈 채널 생성."""
    if member is None:
        return await ctx.send("사용법: `!쟁탈 @쟁탈하고 싶은 사람`")

    if member.bot or member.id == ctx.author.id:
        return await ctx.send("봇이나 자기 자신에게 쟁탈을 신청할 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게는 신청할 수 없어요.")

    pool = core.db_pool
    if pool is None:
        return await ctx.send("데이터베이스에 연결되지 않았어요.")

    now = datetime.now(timezone.utc).timestamp()
    previous = _romance_challenge_cooldowns.get(ctx.author.id, 0)
    if now - previous < ROMANCE_CHALLENGE_COOLDOWN:
        remaining = int(ROMANCE_CHALLENGE_COOLDOWN - (now - previous))
        return await ctx.send(f"⏳ {remaining}초 후에 다시 신청할 수 있어요.")

    partner_id = await _get_romance_couple_pair(ctx.guild.id, member.id)
    if partner_id is None:
        return await ctx.send(
            f"💭 {member.mention}님은 현재 커플이 아니어서 쟁탈할 대상이 없어요."
        )

    if partner_id == ctx.author.id:
        return await ctx.send("이미 본인이 상대방의 연인이에요.")

    if await is_couple(ctx.guild.id, ctx.author.id):
        return await ctx.send("현재 커플인 상태에서는 쟁탈 신청을 할 수 없어요. 먼저 관계를 정리해 주세요.")

    partner = ctx.guild.get_member(partner_id)
    if partner is None:
        try:
            partner = await ctx.guild.fetch_member(partner_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await ctx.send("현재 연인을 서버에서 찾을 수 없어요.")

    # 같은 대상 커플의 중복 쟁탈방 방지
    async with pool.acquire() as conn:
        existing = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM romance_challenge_logs
                WHERE guild_id = $1
                  AND target_id = $2
                  AND created_at > NOW() - INTERVAL '1 hour'
            )
        """, ctx.guild.id, member.id) if await conn.fetchval("""
            SELECT to_regclass('public.romance_challenge_logs') IS NOT NULL
        """) else False

    if existing:
        return await ctx.send("이 대상은 최근 쟁탈전을 진행했어요. 잠시 후 다시 시도해 주세요.")

    category = discord.utils.get(
        ctx.guild.categories,
        name=ROMANCE_CHALLENGE_CATEGORY,
    )
    if category is None:
        try:
            category = await ctx.guild.create_category(ROMANCE_CHALLENGE_CATEGORY)
        except discord.Forbidden:
            return await ctx.send("채널을 만들 권한이 없어요. 봇의 채널 관리 권한을 확인해 주세요.")

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        partner: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    }

    try:
        channel = await ctx.guild.create_text_channel(
            name=f"{ROMANCE_CHALLENGE_PREFIX}-{ctx.author.display_name}"[:100],
            category=category,
            overwrites=overwrites,
            topic=(
                f"쟁탈 신청자:{ctx.author.id} | "
                f"대상:{member.id} | 현재 연인:{partner.id}"
            ),
            reason="연애 쟁탈 시스템",
        )
    except discord.Forbidden:
        return await ctx.send("비공개 채널을 만들 수 없어요. 봇의 채널 관리 권한을 확인해 주세요.")
    except discord.HTTPException:
        return await ctx.send("쟁탈 채널 생성에 실패했어요. 잠시 후 다시 시도해 주세요.")

    _romance_challenge_cooldowns[ctx.author.id] = now

    embed = discord.Embed(
        title="💘 연애 쟁탈전이 시작됐어요!",
        description=(
            f"💌 **쟁탈 신청자:** {ctx.author.mention}\n"
            f"💗 **쟁탈 대상:** {member.mention}\n"
            f"💑 **현재 연인:** {partner.mention}\n\n"
            "이 채널은 위 세 사람만 볼 수 있어요.\n"
            "서로 대화한 뒤 **쟁탈 대상 본인**이 아래 버튼으로 최종 선택해 주세요.\n\n"
            "• `신청자 선택` — 현재 커플 관계를 종료하고 신청자와 새 커플이 됩니다.\n"
            "• `현재 연인 선택` — 기존 커플 관계를 유지합니다.\n\n"
            "선택은 쟁탈 대상 본인만 할 수 있으며, 선택 후 채널은 잠시 뒤 삭제됩니다."
        ),
        color=PINK,
        timestamp=datetime.now(timezone.utc),
    )

    try:
        await channel.send(
            content=f"{ctx.author.mention} {member.mention} {partner.mention}",
            embed=embed,
            view=RomanceChallengeView(
                ctx.guild.id, ctx.author.id, member.id, partner.id
            ),
        )
    except discord.HTTPException:
        try:
            await channel.delete(reason="쟁탈 안내 메시지 전송 실패")
        except discord.HTTPException:
            pass
        return await ctx.send("쟁탈 안내 메시지를 보내지 못했어요.")

    await ctx.send(f"💌 비공개 쟁탈방을 만들었어요: {channel.mention}")



# =========================================================
# /쟁탈 슬래시 명령어 (기존 !쟁탈도 그대로 유지)
# =========================================================

@core.bot.tree.command(name="쟁탈", description="커플인 회원을 대상으로 비공개 쟁탈전을 신청합니다.")
@discord.app_commands.guild_only()
@discord.app_commands.describe(member="쟁탈하고 싶은 현재 커플 회원")
async def romance_challenge_slash(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    author = interaction.user

    async def reply(message: str):
        await interaction.followup.send(message, ephemeral=True)

    if guild is None:
        return await reply("서버 안에서만 사용할 수 있어요.")
    if member.bot or member.id == author.id:
        return await reply("봇이나 자기 자신에게 쟁탈을 신청할 수 없어요.")

    pool = core.db_pool
    if pool is None:
        return await reply("데이터베이스에 연결되지 않았어요.")

    now = datetime.now(timezone.utc).timestamp()
    previous = _romance_challenge_cooldowns.get(author.id, 0)
    if now - previous < ROMANCE_CHALLENGE_COOLDOWN:
        remaining = int(ROMANCE_CHALLENGE_COOLDOWN - (now - previous))
        return await reply(f"⏳ {remaining}초 후에 다시 신청할 수 있어요.")

    partner_id = await _get_romance_couple_pair(guild.id, member.id)
    if partner_id is None:
        return await reply(f"💭 {member.mention}님은 현재 커플이 아니어서 쟁탈할 대상이 없어요.")
    if partner_id == author.id:
        return await reply("이미 본인이 상대방의 연인이에요.")
    if await is_couple(guild.id, author.id):
        return await reply("현재 커플인 상태에서는 쟁탈 신청을 할 수 없어요. 먼저 관계를 정리해 주세요.")

    partner = guild.get_member(partner_id)
    if partner is None:
        try:
            partner = await guild.fetch_member(partner_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await reply("현재 연인을 서버에서 찾을 수 없어요.")

    async with pool.acquire() as conn:
        table_exists = await conn.fetchval("SELECT to_regclass('public.romance_challenge_logs') IS NOT NULL")
        existing = False
        if table_exists:
            existing = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM romance_challenge_logs
                    WHERE guild_id = $1 AND target_id = $2
                      AND created_at > NOW() - INTERVAL '1 hour'
                )
            """, guild.id, member.id)
    if existing:
        return await reply("이 대상은 최근 쟁탈전을 진행했어요. 잠시 후 다시 시도해 주세요.")

    category = discord.utils.get(guild.categories, name=ROMANCE_CHALLENGE_CATEGORY)
    if category is None:
        try:
            category = await guild.create_category(ROMANCE_CHALLENGE_CATEGORY)
        except discord.Forbidden:
            return await reply("채널을 만들 권한이 없어요. 봇의 채널 관리 권한을 확인해 주세요.")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        partner: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    try:
        channel = await guild.create_text_channel(
            name=f"{ROMANCE_CHALLENGE_PREFIX}-{author.display_name}"[:100],
            category=category,
            overwrites=overwrites,
            topic=f"쟁탈 신청자:{author.id} | 대상:{member.id} | 현재 연인:{partner.id}",
            reason="연애 쟁탈 시스템 (/쟁탈)",
        )
    except discord.Forbidden:
        return await reply("비공개 채널을 만들 수 없어요. 봇의 채널 관리 권한을 확인해 주세요.")
    except discord.HTTPException:
        return await reply("쟁탈 채널 생성에 실패했어요. 잠시 후 다시 시도해 주세요.")

    _romance_challenge_cooldowns[author.id] = now
    embed = discord.Embed(
        title="💘 연애 쟁탈전이 시작됐어요!",
        description=(
            f"💌 **쟁탈 신청자:** {author.mention}\n"
            f"💗 **쟁탈 대상:** {member.mention}\n"
            f"💑 **현재 연인:** {partner.mention}\n\n"
            "이 채널은 위 세 사람만 볼 수 있어요.\n"
            "쟁탈 대상 본인이 아래 버튼으로 최종 선택해 주세요.\n\n"
            "• `신청자 선택` — 신청자와 새 커플이 됩니다.\n"
            "• `현재 연인 선택` — 기존 커플 관계를 유지합니다."
        ),
        color=PINK,
        timestamp=datetime.now(timezone.utc),
    )
    try:
        await channel.send(
            content=f"{author.mention} {member.mention} {partner.mention}",
            embed=embed,
            view=RomanceChallengeView(guild.id, author.id, member.id, partner.id),
        )
    except discord.HTTPException:
        try:
            await channel.delete(reason="쟁탈 안내 메시지 전송 실패")
        except discord.HTTPException:
            pass
        return await reply("쟁탈 안내 메시지를 보내지 못했어요.")

    await reply(f"💌 비공개 쟁탈방을 만들었어요: {channel.mention}")


# =========================================================
# 쟁탈 버튼 영구 등록 / 봇 재시작 후 복구
# =========================================================

_romance_challenge_registered_messages = set()
_romance_challenge_restore_lock = asyncio.Lock()


async def register_persistent_romance_challenge_views(target_bot=None):
    """기존 쟁탈 채널의 버튼을 봇 재시작 후에도 다시 연결합니다."""
    target_bot = target_bot or core.bot
    async with _romance_challenge_restore_lock:
        for guild in list(target_bot.guilds):
            for channel in list(guild.text_channels):
                topic = channel.topic or ""
                if "쟁탈 신청자:" not in topic or "대상:" not in topic or "현재 연인:" not in topic:
                    continue

                try:
                    fields = {}
                    for part in topic.split("|"):
                        if ":" not in part:
                            continue
                        key, value = part.strip().split(":", 1)
                        fields[key.strip()] = int(value.strip())
                    challenger_id = fields["쟁탈 신청자"]
                    target_id = fields["대상"]
                    partner_id = fields["현재 연인"]
                except (KeyError, TypeError, ValueError):
                    continue

                # 메시지 ID 단위 등록은 서로 다른 쟁탈방의 대상 정보를 분리합니다.
                try:
                    async for message in channel.history(limit=30, oldest_first=False):
                        if message.author.id != target_bot.user.id or not message.components:
                            continue
                        if message.id in _romance_challenge_registered_messages:
                            break
                        view = RomanceChallengeView(
                            guild.id, challenger_id, target_id, partner_id
                        )
                        # 기존 메시지의 버튼도 고정 custom_id를 사용하도록 갱신한 뒤 등록합니다.
                        await message.edit(view=view)
                        target_bot.add_view(view, message_id=message.id)
                        _romance_challenge_registered_messages.add(message.id)
                        print(f"[ROMANCE] 쟁탈 버튼 복구 완료: 채널={channel.id}, 메시지={message.id}")
                        break
                except (discord.Forbidden, discord.HTTPException) as exc:
                    print(f"[ROMANCE] 쟁탈 버튼 복구 실패: 채널={channel.id}, {type(exc).__name__}: {exc}")


@core.bot.listen("on_ready")
async def _restore_romance_challenge_views_on_ready():
    # on_ready는 재연결 때 다시 실행될 수 있으므로 등록 메시지를 기억합니다.
    await register_persistent_romance_challenge_views(core.bot)
