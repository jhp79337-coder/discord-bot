
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
import core


# =========================================================
# 연애 시스템 설정
# =========================================================

MAX_AFFECTION = 100
AFFECTION_COOLDOWN_HOURS = 24


# =========================================================
# PostgreSQL 초기화
# bot.py에서 core.init_database() 다음에 실행해야 함
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

    print("[ROMANCE] PostgreSQL 연애 시스템 초기화 완료")


# =========================================================
# 공통 함수
# =========================================================

def get_guild_id(ctx):
    if ctx.guild is None:
        return None
    return ctx.guild.id


async def get_partner_id(guild_id, user_id):
    pool = core.db_pool

    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT partner_id
            FROM romance_couples
            WHERE guild_id = $1 AND user_id = $2
        """, guild_id, user_id)


async def get_couple_role(guild_id):
    pool = core.db_pool

    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT couple_role_id
            FROM romance_settings
            WHERE guild_id = $1
        """, guild_id)


async def is_couple(guild_id, user_id):
    return await get_partner_id(guild_id, user_id) is not None


async def change_couple_role(guild, member, give_role):
    role_id = await get_couple_role(guild.id)

    if not role_id:
        return False, "설정된 커플 역할이 없습니다."

    role = guild.get_role(role_id)

    if role is None:
        return False, "설정된 역할을 찾을 수 없습니다. 역할을 다시 설정해 주세요."

    bot_member = guild.me

    if bot_member is None:
        return False, "봇의 서버 정보를 확인할 수 없습니다."

    if not bot_member.guild_permissions.manage_roles:
        return False, "봇에 역할 관리 권한이 없습니다."

    if role >= bot_member.top_role:
        return False, "커플 역할이 봇의 최고 역할보다 위에 있습니다. 역할 순서를 조정해 주세요."

    try:
        if give_role:
            if role not in member.roles:
                await member.add_roles(role, reason="연애 시스템: 커플 성립")
        else:
            if role in member.roles:
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


# =========================================================
# 도움말
# =========================================================

@core.bot.command(name="연애도움말")
async def romance_help(ctx):
    embed = discord.Embed(
        title="💗 연애 시스템 도움말",
        description="상대방과 호감도를 쌓고 고백해 보세요!",
        color=discord.Color.from_rgb(255, 153, 204)
    )

    embed.add_field(
        name="💕 호감도",
        value=(
            "`!호감도 @유저` — 상대방과 서로의 호감도 확인\n"
            "`!호감도올리기 @유저` — 상대방 호감도 +1\n"
            "호감도는 같은 상대에게 24시간마다 한 번 올릴 수 있어요."
        ),
        inline=False
    )

    embed.add_field(
        name="💌 고백",
        value=(
            "`!고백 @유저` — 상대방에게 고백하기\n"
            "`!고백수락` — 받은 고백 수락하기\n"
            "`!고백거절` — 받은 고백 거절하기"
        ),
        inline=False
    )

    embed.add_field(
        name="💑 커플",
        value=(
            "`!커플` — 내 연애 상태 확인\n"
            "`!커플 @유저` — 상대방과 커플인지 확인\n"
            "`!이별` — 현재 커플 관계 해제\n"
            "`!커플역할설정 @역할` — 커플 역할 설정 (관리자)"
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
        color=discord.Color.from_rgb(255, 153, 204)
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
async def romance_increase_affection(
    ctx,
    member: discord.Member = None
):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!호감도올리기 @유저`")

    if member.bot:
        return await ctx.send("봇에게는 호감도를 올릴 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게는 호감도를 올릴 수 없어요.")

    pool = core.db_pool
    guild_id = ctx.guild.id
    user_id = ctx.author.id
    target_id = member.id

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT score, last_increase_at
                FROM romance_affection
                WHERE guild_id = $1 AND user_id = $2 AND target_id = $3
                FOR UPDATE
            """, guild_id, user_id, target_id)

            now = datetime.now(timezone.utc)

            if row and row["last_increase_at"]:
                next_time = row["last_increase_at"] + timedelta(
                    hours=AFFECTION_COOLDOWN_HOURS
                )

                if now < next_time:
                    remaining = next_time - now
                    total_seconds = int(remaining.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes = remainder // 60

                    return await ctx.send(
                        f"⏳ {member.mention}의 호감도는 이미 올렸어요.\n"
                        f"다음 호감도 증가는 **{hours}시간 {minutes}분 후** 가능해요."
                    )

            current_score = row["score"] if row else 0

            if current_score >= MAX_AFFECTION:
                return await ctx.send(
                    f"💗 {member.mention}에 대한 호감도가 이미 100이에요!"
                )

            new_score = min(current_score + 1, MAX_AFFECTION)

            await conn.execute("""
                INSERT INTO romance_affection
                    (guild_id, user_id, target_id, score, last_increase_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, user_id, target_id)
                DO UPDATE SET
                    score = EXCLUDED.score,
                    last_increase_at = EXCLUDED.last_increase_at
            """, guild_id, user_id, target_id, new_score, now)

    await ctx.send(
        f"💗 {ctx.author.mention}님이 {member.mention}님의 호감도를 올렸어요!\n"
        f"현재 호감도: **{new_score}/{MAX_AFFECTION}**"
    )


# =========================================================
# 고백하기
# =========================================================

@core.bot.command(name="고백")
async def romance_confess(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if member is None:
        return await ctx.send("사용법: `!고백 @유저`")

    if member.bot:
        return await ctx.send("봇에게는 고백할 수 없어요.")

    if member.id == ctx.author.id:
        return await ctx.send("자기 자신에게 고백할 수는 없어요.")

    guild_id = ctx.guild.id
    user_id = ctx.author.id
    target_id = member.id
    pool = core.db_pool

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
            ON CONFLICT (guild_id, from_id)
            DO UPDATE SET
                to_id = EXCLUDED.to_id,
                created_at = NOW()
        """, guild_id, user_id, target_id)

    delivered = await send_target_dm(
        member,
        f"💌 **{ctx.author.display_name}**님이 당신에게 고백했어요!\n"
        f"서버: **{ctx.guild.name}**\n\n"
        f"수락하려면 해당 서버에서 `!고백수락`\n"
        f"거절하려면 해당 서버에서 `!고백거절`을 입력해 주세요."
    )

    if delivered:
        await ctx.send(
            f"💌 {ctx.author.mention}님의 고백을 보냈어요!\n"
            f"{member.mention}님이 수락하면 커플이 됩니다."
        )
    else:
        await ctx.send(
            f"💌 고백 요청은 저장했지만 {member.mention}님에게 DM을 보내지 못했어요.\n"
            f"상대방이 DM을 허용하는지 확인해 주세요. 고백은 아직 취소되지 않았어요."
        )


# =========================================================
# 고백 수락
# =========================================================

@core.bot.command(name="고백수락")
async def romance_accept(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool
    guild_id = ctx.guild.id
    user_id = ctx.author.id

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
                        "두 사람 중 한 명이 이미 커플 상태라서 고백을 수락할 수 없어요."
                    )

                await conn.execute("""
                    INSERT INTO romance_couples
                        (guild_id, user_id, partner_id)
                    VALUES ($1, $2, $3), ($1, $3, $2)
                """, guild_id, from_id, to_id)

                await conn.execute("""
                    DELETE FROM romance_pending_confessions
                    WHERE guild_id = $1 AND from_id = $2
                """, guild_id, from_id)

                await conn.execute("""
                    DELETE FROM romance_pending_confessions
                    WHERE guild_id = $1 AND to_id IN ($2, $3)
                """, guild_id, from_id, to_id)

    except Exception as exc:
        print(f"[ROMANCE ACCEPT ERROR] {exc}")
        return await ctx.send(
            "고백 수락 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."
        )

    first = ctx.guild.get_member(from_id)
    second = ctx.guild.get_member(to_id)

    role_results = []

    for member in (first, second):
        if member is not None:
            success, message = await change_couple_role(
                ctx.guild, member, True
            )
            role_results.append((success, message))

    result = (
        f"💗 **커플 성립!**\n"
        f"<@{from_id}> ❤️ <@{to_id}>\n"
        f"두 사람의 연애가 시작됐어요!"
    )

    if not role_results:
        result += "\n⚠️ 멤버를 확인하지 못해 역할은 지급하지 못했어요."
    elif any(not success for success, _ in role_results):
        result += "\n⚠️ 커플은 성립했지만 역할 지급에 문제가 있어요.\n"
        result += "관리자에게 커플 역할 설정과 봇 권한을 확인해 달라고 해 주세요."

    await ctx.send(result)


# =========================================================
# 고백 거절
# =========================================================

@core.bot.command(name="고백거절")
async def romance_reject(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool

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
# 커플 상태 확인
# =========================================================

@core.bot.command(name="커플")
async def romance_couple(ctx, member: discord.Member = None):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    target = member or ctx.author
    partner_id = await get_partner_id(ctx.guild.id, target.id)

    if partner_id is None:
        if member is not None and member.id != ctx.author.id:
            return await ctx.send(
                f"💭 {target.mention}님은 현재 커플이 아니에요."
            )
        return await ctx.send("💭 현재 커플이 아니에요.")

    partner = ctx.guild.get_member(partner_id)

    if partner is None:
        partner_text = f"<@{partner_id}>"
    else:
        partner_text = partner.mention

    await ctx.send(
        f"💑 **현재 커플**\n"
        f"{target.mention} ❤️ {partner_text}"
    )


# =========================================================
# 이별
# =========================================================

@core.bot.command(name="이별")
async def romance_breakup(ctx):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    pool = core.db_pool
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

    role_results = []

    for member_id in (user_id, partner_id):
        member = ctx.guild.get_member(member_id)
        if member is not None:
            success, message = await change_couple_role(
                ctx.guild, member, False
            )
            role_results.append((success, message))

    await ctx.send(
        f"💔 {ctx.author.mention}님의 요청으로 커플 관계가 해제됐어요.\n"
        f"상대방: <@{partner_id}>"
    )

    if any(not success for success, _ in role_results):
        await ctx.send(
            "⚠️ 관계는 해제됐지만 역할 회수에 실패했을 수 있어요. "
            "커플 역할 설정과 봇 권한을 확인해 주세요."
        )


# =========================================================
# 커플 역할 설정 (관리자 전용)
# =========================================================

@core.bot.command(name="커플역할설정")
@commands.has_permissions(administrator=True)
async def romance_set_role(
    ctx,
    role: discord.Role = None
):
    if ctx.guild is None:
        return await ctx.send("서버에서 사용해 주세요.")

    if role is None:
        return await ctx.send(
            "사용법: `!커플역할설정 @커플역할`\n"
            "예: `!커플역할설정 @💗・커플`"
        )

    if role.is_default():
        return await ctx.send("서버 기본 역할은 설정할 수 없어요.")

    if role >= ctx.guild.me.top_role:
        return await ctx.send(
            "⚠️ 커플 역할을 봇의 최고 역할보다 아래로 옮긴 뒤 다시 설정해 주세요."
        )

    pool = core.db_pool

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO romance_settings (guild_id, couple_role_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET couple_role_id = EXCLUDED.couple_role_id
        """, ctx.guild.id, role.id)

    await ctx.send(
        f"💗 커플 역할을 {role.mention}(으)로 설정했어요!"
    )


@romance_set_role.error
async def romance_set_role_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어는 서버 관리자만 사용할 수 있어요.")
    else:
        print(f"[ROMANCE ROLE ERROR] {error}")
        await ctx.send("역할 설정 중 오류가 발생했어요.")
