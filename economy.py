from pathlib import Path

source = r'''# -*- coding: utf-8 -*-
"""소개팅/연애 서버용 가상 코인 경제 시스템.
실제 돈·현금 환전 없이 서버 내부 가상 코인만 사용합니다.
"""
from datetime import datetime, timedelta, timezone
import random

import discord
from discord.ext import tasks

import core


COIN_NAME = "하트 코인"
CHAT_REWARD = 3
CHAT_COOLDOWN_MINUTES = 5
VOICE_REWARD = 5
VOICE_TICK_MINUTES = 10
DAILY_REWARD = 100
MAX_BET = 500
AUCTION_MINUTES = 10


def _pool():
    """PostgreSQL 연결 풀을 가져옵니다."""
    if core.db_pool is None:
        raise RuntimeError(
            "PostgreSQL 연결이 없습니다. core.init_database() 이후 사용하세요."
        )
    return core.db_pool


async def init_economy_database():
    """경제 시스템에서 사용하는 PostgreSQL 테이블을 생성합니다."""
    pool = _pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_wallets (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
                daily_at TIMESTAMPTZ,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_activity (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                chat_at TIMESTAMPTZ,
                voice_paid_at TIMESTAMPTZ,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_transactions (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                amount BIGINT NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_slave_optins (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_auctions (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                seller_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                start_price BIGINT NOT NULL CHECK (start_price > 0),
                highest_bid BIGINT NOT NULL,
                highest_bidder BIGINT,
                status TEXT NOT NULL DEFAULT 'open',
                ends_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_game_cooldowns (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                game TEXT NOT NULL,
                used_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (guild_id, user_id, game)
            )
        """)


async def _ensure_wallet(conn, guild_id, user_id):
    await conn.execute(
        """
        INSERT INTO economy_wallets(guild_id, user_id)
        VALUES($1, $2)
        ON CONFLICT DO NOTHING
        """,
        guild_id,
        user_id,
    )


async def _balance(conn, guild_id, user_id):
    await _ensure_wallet(conn, guild_id, user_id)
    return await conn.fetchval(
        """
        SELECT balance FROM economy_wallets
        WHERE guild_id=$1 AND user_id=$2
        """,
        guild_id,
        user_id,
    )


async def _change(conn, guild_id, user_id, amount, reason):
    """코인을 변경하고 거래 기록을 남깁니다. 잔액 부족 시 False를 반환합니다."""
    await _ensure_wallet(conn, guild_id, user_id)

    if amount < 0:
        row = await conn.fetchrow(
            """
            UPDATE economy_wallets
            SET balance = balance + $3
            WHERE guild_id=$1 AND user_id=$2 AND balance >= -$3
            RETURNING balance
            """,
            guild_id,
            user_id,
            amount,
        )
        if row is None:
            return False
    else:
        await conn.execute(
            """
            UPDATE economy_wallets
            SET balance = balance + $3
            WHERE guild_id=$1 AND user_id=$2
            """,
            guild_id,
            user_id,
            amount,
        )

    await conn.execute(
        """
        INSERT INTO economy_transactions(guild_id, user_id, amount, reason)
        VALUES($1, $2, $3, $4)
        """,
        guild_id,
        user_id,
        amount,
        reason,
    )
    return True


@core.bot.command(name="잔액", aliases=["지갑", "코인"])
async def wallet(ctx, member: discord.Member = None):
    if not ctx.guild:
        return
    member = member or ctx.author
    async with _pool().acquire() as conn:
        balance = await _balance(conn, ctx.guild.id, member.id)
    await ctx.reply(
        f"💗 **{member.display_name}**님의 잔액: **{balance:,} {COIN_NAME}**",
        mention_author=False,
    )


@core.bot.command(name="일일", aliases=["출석", "일일보상"])
async def daily(ctx):
    if not ctx.guild:
        return

    async with _pool().acquire() as conn:
        async with conn.transaction():
            await _ensure_wallet(conn, ctx.guild.id, ctx.author.id)
            row = await conn.fetchrow(
                """
                SELECT daily_at FROM economy_wallets
                WHERE guild_id=$1 AND user_id=$2 FOR UPDATE
                """,
                ctx.guild.id,
                ctx.author.id,
            )
            now = datetime.now(timezone.utc)

            if row["daily_at"] and now - row["daily_at"] < timedelta(hours=24):
                remaining = timedelta(hours=24) - (now - row["daily_at"])
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                return await ctx.reply(
                    f"⏳ 일일 보상은 {hours}시간 {minutes}분 후에 받을 수 있어요.",
                    mention_author=False,
                )

            await conn.execute(
                """
                UPDATE economy_wallets SET daily_at=$3
                WHERE guild_id=$1 AND user_id=$2
                """,
                ctx.guild.id,
                ctx.author.id,
                now,
            )
            await _change(
                conn, ctx.guild.id, ctx.author.id, DAILY_REWARD, "일일 출석 보상"
            )
            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"🎁 출석 보상 **{DAILY_REWARD} 코인** 지급! 현재 잔액: **{balance:,}**",
        mention_author=False,
    )


@core.bot.command(name="코인송금")
async def transfer(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        return
    if member.bot or member.id == ctx.author.id:
        return await ctx.reply(
            "❌ 본인이나 봇에게는 송금할 수 없어요.", mention_author=False
        )
    if amount <= 0 or amount > 1_000_000:
        return await ctx.reply(
            "❌ 송금액은 1~1,000,000 코인으로 입력해 주세요.",
            mention_author=False,
        )

    async with _pool().acquire() as conn:
        async with conn.transaction():
            if not await _change(
                conn, ctx.guild.id, ctx.author.id, -amount, f"{member.id}에게 송금"
            ):
                return await ctx.reply("❌ 코인이 부족해요.", mention_author=False)
            await _change(
                conn, ctx.guild.id, member.id, amount, f"{ctx.author.id}에게서 송금"
            )

    await ctx.reply(
        f"💌 {member.mention}에게 **{amount:,} 코인**을 보냈어요.",
        mention_author=False,
    )


@core.bot.command(name="가위바위보", aliases=["가위바위보게임", "가바보"])
async def rps(ctx, bet: int, choice: str):
    if not ctx.guild:
        return
    choice = choice.lower().strip()
    mapping = {
        "가위": "가위", "바위": "바위", "보": "보",
        "✌️": "가위", "✊": "바위", "🖐️": "보",
    }
    if choice not in mapping:
        return await ctx.reply(
            "사용법: `!가위바위보 50 가위` (가위/바위/보)",
            mention_author=False,
        )
    if bet < 1 or bet > MAX_BET:
        return await ctx.reply(
            f"❌ 베팅은 1~{MAX_BET} 코인까지 가능해요.",
            mention_author=False,
        )

    mine = mapping[choice]
    theirs = random.choice(["가위", "바위", "보"])
    beats = {"가위": "보", "바위": "가위", "보": "바위"}

    async with _pool().acquire() as conn:
        async with conn.transaction():
            if not await _change(
                conn, ctx.guild.id, ctx.author.id, -bet, "가위바위보 베팅"
            ):
                return await ctx.reply("❌ 코인이 부족해요.", mention_author=False)

            if mine == theirs:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, bet, "가위바위보 무승부 환급"
                )
                result = f"무승부! 베팅금 **{bet} 코인**을 돌려받았어요."
            elif beats[mine] == theirs:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, bet * 2, "가위바위보 승리"
                )
                result = f"승리! 순이익 **{bet} 코인** 🎉"
            else:
                result = f"패배! **{bet} 코인**을 잃었어요."

            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"✊ **가위바위보**\n내 선택: {mine} · 봇 선택: {theirs}\n"
        f"{result}\n💗 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


@core.bot.command(name="주사위")
async def dice(ctx, bet: int):
    if not ctx.guild:
        return
    if bet < 1 or bet > MAX_BET:
        return await ctx.reply(
            f"❌ 베팅은 1~{MAX_BET} 코인까지 가능해요.",
            mention_author=False,
        )

    roll = random.randint(1, 6)
    async with _pool().acquire() as conn:
        async with conn.transaction():
            if not await _change(
                conn, ctx.guild.id, ctx.author.id, -bet, "주사위 베팅"
            ):
                return await ctx.reply("❌ 코인이 부족해요.", mention_author=False)
            if roll >= 4:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, bet * 2, "주사위 승리"
                )
                result = f"🎉 {roll}이 나왔어요! **{bet} 코인 순이익**"
            else:
                result = f"아쉽게도 {roll}이 나왔어요. **{bet} 코인**을 잃었어요."
            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"🎲 주사위 결과: **{roll}**\n{result}\n💗 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


@core.bot.command(name="슬롯")
async def slots(ctx, bet: int):
    if not ctx.guild:
        return
    if bet < 1 or bet > MAX_BET:
        return await ctx.reply(
            f"❌ 베팅은 1~{MAX_BET} 코인까지 가능해요.",
            mention_author=False,
        )

    symbols = ["🍒", "🍋", "🍇", "💎", "💗"]
    result = [random.choice(symbols) for _ in range(3)]
    multiplier = 5 if len(set(result)) == 1 else (2 if len(set(result)) == 2 else 0)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            if not await _change(
                conn, ctx.guild.id, ctx.author.id, -bet, "슬롯 베팅"
            ):
                return await ctx.reply("❌ 코인이 부족해요.", mention_author=False)
            if multiplier:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, bet * (multiplier + 1), "슬롯 당첨"
                )
                result_text = f"🎉 당첨! 순이익 **{bet * multiplier} 코인**"
            else:
                result_text = f"꽝! **{bet} 코인**을 잃었어요."
            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"🎰 {' | '.join(result)}\n{result_text}\n💗 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


@core.bot.command(name="노예등록")
async def slave_register(ctx):
    if not ctx.guild:
        return
    async with _pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO economy_slave_optins(guild_id, user_id)
            VALUES($1, $2) ON CONFLICT DO NOTHING
            """,
            ctx.guild.id,
            ctx.author.id,
        )
    await ctx.reply(
        "🔐 노예 경매 등록 신청이 완료됐어요. 본인이 직접 신청한 경우에만 "
        "경매에 올릴 수 있어요. 취소하려면 `!노예등록취소`를 입력하세요.",
        mention_author=False,
    )


@core.bot.command(name="노예등록취소")
async def slave_unregister(ctx):
    if not ctx.guild:
        return
    async with _pool().acquire() as conn:
        active = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM economy_auctions
                WHERE guild_id=$1 AND seller_id=$2 AND status='open'
            )
            """,
            ctx.guild.id,
            ctx.author.id,
        )
        if active:
            return await ctx.reply(
                "❌ 진행 중인 경매가 있어 등록을 취소할 수 없어요. "
                "먼저 경매를 취소해 주세요.",
                mention_author=False,
            )
        await conn.execute(
            "DELETE FROM economy_slave_optins WHERE guild_id=$1 AND user_id=$2",
            ctx.guild.id,
            ctx.author.id,
        )
    await ctx.reply("✅ 노예 경매 등록을 취소했어요.", mention_author=False)


@core.bot.command(name="경매시작")
async def auction_start(ctx, start_price: int):
    if not ctx.guild:
        return
    if start_price < 1 or start_price > 1_000_000:
        return await ctx.reply(
            "사용법: `!경매시작 100` (시작가는 1~1,000,000 코인)",
            mention_author=False,
        )

    async with _pool().acquire() as conn:
        opted = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM economy_slave_optins
                WHERE guild_id=$1 AND user_id=$2
            )
            """,
            ctx.guild.id,
            ctx.author.id,
        )
        if not opted:
            return await ctx.reply(
                "먼저 `!노예등록`으로 본인 동의를 등록해 주세요.",
                mention_author=False,
            )

        active = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM economy_auctions
                WHERE guild_id=$1 AND seller_id=$2 AND status='open'
            )
            """,
            ctx.guild.id,
            ctx.author.id,
        )
        if active:
            return await ctx.reply("이미 진행 중인 경매가 있어요.", mention_author=False)

        row = await conn.fetchrow(
            """
            INSERT INTO economy_auctions(
                guild_id, seller_id, channel_id, start_price, highest_bid, ends_at
            )
            VALUES($1, $2, $3, $4, $4, $5)
            RETURNING id, ends_at
            """,
            ctx.guild.id,
            ctx.author.id,
            ctx.channel.id,
            start_price,
            datetime.now(timezone.utc) + timedelta(minutes=AUCTION_MINUTES),
        )

    embed = discord.Embed(
        title="🔨 하트 코인 노예 경매",
        description=(
            f"등록자: {ctx.author.mention}\n"
            f"시작가: **{start_price:,} 코인**\n"
            f"종료: <t:{int(row['ends_at'].timestamp())}:R>\n\n"
            f"입찰: `!입찰 {row['id']} 금액`\n"
            f"등록자는 언제든 `!경매취소 {row['id']}`로 취소할 수 있어요.\n\n"
            "※ 역할놀이용 가상 경매이며 실제 소유권이나 강제 의무는 발생하지 않아요."
        ),
        color=discord.Color.from_rgb(255, 105, 180),
    )
    await ctx.reply(embed=embed, mention_author=False)


@core.bot.command(name="입찰")
async def auction_bid(ctx, auction_id: int, amount: int):
    if not ctx.guild:
        return
    if amount < 1:
        return await ctx.reply("❌ 입찰 금액은 1 코인 이상이어야 해요.", mention_author=False)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM economy_auctions
                WHERE id=$1 AND guild_id=$2 AND status='open'
                FOR UPDATE
                """,
                auction_id,
                ctx.guild.id,
            )
            if not row:
                return await ctx.reply(
                    "❌ 진행 중인 경매를 찾을 수 없어요.", mention_author=False
                )
            if row["ends_at"] <= datetime.now(timezone.utc):
                await conn.execute(
                    "UPDATE economy_auctions SET status='ended' WHERE id=$1",
                    auction_id,
                )
                return await ctx.reply("⏰ 이 경매는 이미 종료됐어요.", mention_author=False)
            if ctx.author.id in (row["seller_id"], row["highest_bidder"]):
                return await ctx.reply(
                    "❌ 등록자 본인이나 현재 최고 입찰자는 입찰할 수 없어요.",
                    mention_author=False,
                )

            minimum = row["highest_bid"] + 1
            if amount < minimum:
                return await ctx.reply(
                    f"❌ 다음 입찰은 최소 **{minimum:,} 코인**이어야 해요.",
                    mention_author=False,
                )
            if await _balance(conn, ctx.guild.id, ctx.author.id) < amount:
                return await ctx.reply("❌ 잔액이 부족해요.", mention_author=False)
            if not await _change(
                conn,
                ctx.guild.id,
                ctx.author.id,
                -amount,
                f"경매 #{auction_id} 입찰 예약",
            ):
                return await ctx.reply("❌ 잔액이 부족해요.", mention_author=False)

            if row["highest_bidder"] is not None:
                await _change(
                    conn,
                    ctx.guild.id,
                    row["highest_bidder"],
                    row["highest_bid"],
                    f"경매 #{auction_id} 최고입찰 교체 환불",
                )
            await conn.execute(
                """
                UPDATE economy_auctions
                SET highest_bid=$2, highest_bidder=$3
                WHERE id=$1
                """,
                auction_id,
                amount,
                ctx.author.id,
            )

    await ctx.reply(
        f"🔨 경매 **#{auction_id}**에 **{amount:,} 코인**으로 입찰했어요!",
        mention_author=False,
    )


@core.bot.command(name="경매현황")
async def auction_status(ctx, auction_id: int):
    if not ctx.guild:
        return
    async with _pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM economy_auctions WHERE id=$1 AND guild_id=$2",
            auction_id,
            ctx.guild.id,
        )
    if not row:
        return await ctx.reply("경매를 찾을 수 없어요.", mention_author=False)

    bidder = f"<@{row['highest_bidder']}>" if row["highest_bidder"] else "아직 없음"
    await ctx.reply(
        f"🔨 경매 #{auction_id} · 상태: **{row['status']}**\n"
        f"현재 입찰: **{row['highest_bid']:,} 코인**\n"
        f"최고 입찰자: {bidder}\n"
        f"종료: <t:{int(row['ends_at'].timestamp())}:R>",
        mention_author=False,
    )


@core.bot.command(name="경매취소")
async def auction_cancel(ctx, auction_id: int):
    if not ctx.guild:
        return
    async with _pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM economy_auctions
                WHERE id=$1 AND guild_id=$2 AND status='open'
                FOR UPDATE
                """,
                auction_id,
                ctx.guild.id,
            )
            if not row or (
                row["seller_id"] != ctx.author.id
                and not ctx.author.guild_permissions.manage_guild
            ):
                return await ctx.reply(
                    "❌ 경매 등록자 또는 서버 관리 권한이 있는 사람만 취소할 수 있어요.",
                    mention_author=False,
                )

            if row["highest_bidder"] is not None:
                await _change(
                    conn,
                    ctx.guild.id,
                    row["highest_bidder"],
                    row["highest_bid"],
                    f"경매 #{auction_id} 취소 환불",
                )
            await conn.execute(
                "UPDATE economy_auctions SET status='cancelled' WHERE id=$1",
                auction_id,
            )

    await ctx.reply(
        f"✅ 경매 #{auction_id}을 취소하고 예약 입찰금을 환불했어요.",
        mention_author=False,
    )


async def on_message_economy(message):
    if (
        message.author.bot
        or not message.guild
        or not message.content.strip()
        or len(message.content.strip()) < 3
    ):
        return
    # 명령어/도배성 반복을 제외하고 사용자별 5분당 1회 지급
    if message.content.startswith(("!", "/")):
        return

    pool = _pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO economy_activity(guild_id, user_id)
                VALUES($1, $2) ON CONFLICT DO NOTHING
                """,
                message.guild.id,
                message.author.id,
            )
            row = await conn.fetchrow(
                """
                SELECT chat_at FROM economy_activity
                WHERE guild_id=$1 AND user_id=$2 FOR UPDATE
                """,
                message.guild.id,
                message.author.id,
            )
            if row["chat_at"] and now - row["chat_at"] < timedelta(
                minutes=CHAT_COOLDOWN_MINUTES
            ):
                return
            await conn.execute(
                """
                UPDATE economy_activity SET chat_at=$3
                WHERE guild_id=$1 AND user_id=$2
                """,
                message.guild.id,
                message.author.id,
                now,
            )
            await _change(
                conn, message.guild.id, message.author.id, CHAT_REWARD, "채팅 활동 보상"
            )


async def on_voice_economy(member, before, after):
    """음성 상태 변경을 기록합니다. 실제 보상은 주기 작업에서 지급합니다."""
    if member.bot or not member.guild:
        return
    pool = _pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO economy_activity(guild_id, user_id, voice_paid_at)
            VALUES($1, $2, $3)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET voice_paid_at=COALESCE(
                economy_activity.voice_paid_at, EXCLUDED.voice_paid_at
            )
            """,
            member.guild.id,
            member.id,
            now,
        )


@tasks.loop(minutes=VOICE_TICK_MINUTES)
async def voice_rewards_loop():
    """음성 채널에서 2명 이상 함께 있는 회원에게 주기적으로 코인을 지급합니다."""
    if core.db_pool is None:
        return

    for guild in list(core.bot.guilds):
        for channel in guild.voice_channels:
            if channel == guild.afk_channel:
                continue
            human_members = [m for m in channel.members if not m.bot]
            if len(human_members) < 2:
                continue

            for member in human_members:
                if (
                    member.voice is None
                    or member.voice.self_deaf
                    or member.voice.deaf
                ):
                    continue
                async with core.db_pool.acquire() as conn:
                    await _change(
                        conn, guild.id, member.id, VOICE_REWARD, "음성 활동 보상"
                    )


@voice_rewards_loop.before_loop
async def before_voice_rewards_loop():
    await core.bot.wait_until_ready()


# 리스너 등록만 수행합니다. 여기서는 Loop.start()를 호출하지 않습니다.
# 모듈 import 시점에는 실행 중인 이벤트 루프가 없을 수 있기 때문입니다.
core.bot.add_listener(on_message_economy, "on_message")
core.bot.add_listener(on_voice_economy, "on_voice_state_update")


@tasks.loop(minutes=1)
async def auction_settlement_loop():
    """종료된 경매를 정산하고 결과를 원래 경매 채널에 알립니다."""
    if core.db_pool is None:
        return

    pool = core.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM economy_auctions
            WHERE status='open' AND ends_at <= NOW()
            ORDER BY id LIMIT 50
            """
        )

    for row in rows:
        async with pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    """
                    SELECT * FROM economy_auctions
                    WHERE id=$1 AND status='open'
                    FOR UPDATE
                    """,
                    row["id"],
                )
                if not locked or locked["ends_at"] > datetime.now(timezone.utc):
                    continue

                await conn.execute(
                    "UPDATE economy_auctions SET status='ended' WHERE id=$1",
                    locked["id"],
                )
                if locked["highest_bidder"] is not None:
                    await _change(
                        conn,
                        locked["guild_id"],
                        locked["seller_id"],
                        locked["highest_bid"],
                        f"경매 #{locked['id']} 낙찰 코인 수령",
                    )

        guild = core.bot.get_guild(row["guild_id"])
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if channel:
            if row["highest_bidder"] is None:
                await channel.send(
                    f"⏰ 경매 **#{row['id']}**가 입찰 없이 종료됐어요. "
                    f"등록자 <@{row['seller_id']}>님, 등록은 유지됩니다."
                )
            else:
                await channel.send(
                    f"🏆 **경매 #{row['id']} 종료!**\n"
                    f"등록자: <@{row['seller_id']}>\n"
                    f"낙찰자: <@{row['highest_bidder']}>\n"
                    f"낙찰가: **{row['highest_bid']:,} 하트 코인**\n\n"
                    "이 경매는 서버 내 가상 역할/미션용이며 실제 사람의 "
                    "소유권이나 강제 의무가 생기는 것은 아니에요."
                )


@auction_settlement_loop.before_loop
async def before_auction_settlement_loop():
    await core.bot.wait_until_ready()


def start_economy_loops():
    """bot.py의 main() 안에서 호출해 경제 자동 작업을 시작합니다."""
    if not voice_rewards_loop.is_running():
        voice_rewards_loop.start()
    if not auction_settlement_loop.is_running():
        auction_settlement_loop.start()


# =========================================================
# 추가 미니게임
# =========================================================

async def _play_bet_game(
    ctx,
    bet: int,
    game_name: str,
    outcome_text: str,
    payout_multiplier: int = 0,
    refund: bool = False,
):
    """가상 코인 베팅 정산 공통 함수. multiplier는 총 반환 배수입니다."""
    if not ctx.guild:
        return
    if bet < 1 or bet > MAX_BET:
        return await ctx.reply(
            f"❌ 베팅은 1~{MAX_BET} 코인까지 가능해요.",
            mention_author=False,
        )

    async with _pool().acquire() as conn:
        async with conn.transaction():
            if not await _change(
                conn, ctx.guild.id, ctx.author.id, -bet, f"{game_name} 베팅"
            ):
                return await ctx.reply("❌ 코인이 부족해요.", mention_author=False)

            if refund:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, bet, f"{game_name} 환급"
                )
                net_text = f"베팅금 **{bet} 코인**을 돌려받았어요."
            elif payout_multiplier > 0:
                await _change(
                    conn,
                    ctx.guild.id,
                    ctx.author.id,
                    bet * payout_multiplier,
                    f"{game_name} 당첨",
                )
                net_text = (
                    f"총 반환 **{bet * payout_multiplier} 코인** · "
                    f"순이익 **{bet * (payout_multiplier - 1)} 코인** 🎉"
                )
            else:
                net_text = f"**{bet} 코인**을 잃었어요."

            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"{outcome_text}\n{net_text}\n💗 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


@core.bot.command(name="코인던지기", aliases=["동전", "앞뒤"])
async def coin_flip(ctx, bet: int, choice: str):
    if not ctx.guild:
        return
    choice = choice.strip().lower()
    sides = {
        "앞": "앞면", "앞면": "앞면",
        "뒤": "뒷면", "뒷면": "뒷면",
    }
    if choice not in sides:
        return await ctx.reply(
            "사용법: `!코인던지기 50 앞면` 또는 `!코인던지기 50 뒷면`",
            mention_author=False,
        )
    result = random.choice(["앞면", "뒷면"])
    win = sides[choice] == result
    await _play_bet_game(
        ctx, bet, "코인던지기",
        f"🪙 결과: **{result}** · 선택: **{sides[choice]}**",
        2 if win else 0,
    )


@core.bot.command(name="홀짝")
async def odd_even(ctx, bet: int, choice: str):
    if not ctx.guild:
        return
    choice = choice.strip().lower()
    mapping = {"홀": "홀", "홀수": "홀", "짝": "짝", "짝수": "짝"}
    if choice not in mapping:
        return await ctx.reply(
            "사용법: `!홀짝 50 홀` 또는 `!홀짝 50 짝`",
            mention_author=False,
        )
    number = random.randint(1, 100)
    result = "홀" if number % 2 else "짝"
    await _play_bet_game(
        ctx, bet, "홀짝", f"🔢 숫자 **{number}** · 결과 **{result}**",
        2 if mapping[choice] == result else 0,
    )


@core.bot.command(name="숫자맞추기", aliases=["숫자게임"])
async def number_guess(ctx, bet: int, guess: int):
    if not ctx.guild:
        return
    if not 1 <= guess <= 10:
        return await ctx.reply(
            "숫자는 1~10 사이로 입력해 주세요. 예: `!숫자맞추기 50 7`",
            mention_author=False,
        )
    number = random.randint(1, 10)
    multiplier = 5 if guess == number else 0
    await _play_bet_game(
        ctx, bet, "숫자맞추기",
        f"🎯 정답은 **{number}** · 내 선택은 **{guess}**",
        multiplier,
    )


@core.bot.command(name="룰렛")
async def roulette(ctx, bet: int):
    if not ctx.guild:
        return
    # 0~4는 꽝, 5~9는 당첨. 당첨 시 총 2배 반환입니다.
    number = random.randint(0, 9)
    win = number >= 5
    await _play_bet_game(
        ctx, bet, "룰렛",
        f"🎡 룰렛 결과: **{number}** · {'당첨 칸!' if win else '꽝 칸!'}",
        2 if win else 0,
    )


@core.bot.command(name="상자열기", aliases=["보물상자"])
async def chest(ctx, bet: int):
    if not ctx.guild:
        return
    roll = random.random()
    if roll < 0.05:
        multiplier, label = 5, "💎 전설의 보물!"
    elif roll < 0.25:
        multiplier, label = 2, "✨ 보물을 찾았어요!"
    else:
        multiplier, label = 0, "🪹 빈 상자예요."
    await _play_bet_game(ctx, bet, "상자열기", label, multiplier)


@core.bot.command(name="복권", aliases=["코인복권"])
async def lottery(ctx):
    if not ctx.guild:
        return

    pool = _pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT used_at FROM economy_game_cooldowns
                WHERE guild_id=$1 AND user_id=$2 AND game='lottery'
                FOR UPDATE
                """,
                ctx.guild.id,
                ctx.author.id,
            )
            if row and now - row["used_at"] < timedelta(hours=24):
                remaining = timedelta(hours=24) - (now - row["used_at"])
                return await ctx.reply(
                    f"🎟️ 무료 복권은 "
                    f"{int(remaining.total_seconds() // 3600)}시간 후에 다시 받을 수 있어요.",
                    mention_author=False,
                )

            await conn.execute(
                """
                INSERT INTO economy_game_cooldowns(guild_id,user_id,game,used_at)
                VALUES($1,$2,'lottery',$3)
                ON CONFLICT(guild_id,user_id,game)
                DO UPDATE SET used_at=EXCLUDED.used_at
                """,
                ctx.guild.id,
                ctx.author.id,
                now,
            )
            prize = random.choices(
                [0, 25, 50, 100, 500], weights=[50, 25, 15, 9, 1]
            )[0]
            if prize:
                await _change(
                    conn, ctx.guild.id, ctx.author.id, prize, "무료 복권 당첨"
                )
            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"🎟️ 복권 결과: **{prize:,} 코인** {'당첨!' if prize else '꽝!'}\n"
        f"💗 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


_active_quizzes = {}


@core.bot.command(name="초성퀴즈")
async def initial_quiz(ctx):
    if not ctx.guild:
        return
    questions = [
        ("ㄱㅇ", "고양이"),
        ("ㅂㄴㄴ", "바나나"),
        ("ㅋㅍ", "커피"),
        ("ㄷㅅㅋㄷ", "디스코드"),
        ("ㅅㄱ", "사과"),
        ("ㅊㅋㄹ", "초콜릿"),
    ]
    initials, answer = random.choice(questions)
    key = (ctx.guild.id, ctx.channel.id)
    _active_quizzes[key] = {
        "answer": answer,
        "expires": datetime.now(timezone.utc) + timedelta(seconds=30),
    }
    await ctx.reply(
        f"🧩 **초성 퀴즈**\n초성: `{initials}`\n"
        "`!초성정답 정답`으로 제출해 주세요. 30초 안에 맞히면 30 코인!",
        mention_author=False,
    )


@core.bot.command(name="초성정답")
async def initial_answer(ctx, *, answer: str):
    if not ctx.guild:
        return
    key = (ctx.guild.id, ctx.channel.id)
    active = _active_quizzes.get(key)
    if not active or active["expires"] < datetime.now(timezone.utc):
        _active_quizzes.pop(key, None)
        return await ctx.reply(
            "진행 중인 초성 퀴즈가 없어요. `!초성퀴즈`로 시작해 주세요.",
            mention_author=False,
        )

    if answer.strip().replace(" ", "").lower() != active["answer"].replace(" ", "").lower():
        return await ctx.reply("❌ 아쉬워요! 다시 생각해 봐요.", mention_author=False)

    _active_quizzes.pop(key, None)
    async with _pool().acquire() as conn:
        async with conn.transaction():
            await _change(conn, ctx.guild.id, ctx.author.id, 30, "초성 퀴즈 정답")
            balance = await _balance(conn, ctx.guild.id, ctx.author.id)

    await ctx.reply(
        f"🎉 정답! **30 코인** 지급! 현재 잔액: **{balance:,} 코인**",
        mention_author=False,
    )


@core.bot.command(name="운세")
async def fortune(ctx):
    messages = [
        "오늘은 작은 행운이 찾아올지도 몰라요 🍀",
        "지갑을 지키는 게 최고의 전략이에요 💗",
        "친구와 미니게임을 하면 즐거운 일이 생길지도! 🎲",
        "오늘의 키워드는 인내심이에요 🌙",
        "행운은 랜덤! 무리한 베팅은 피하세요 ✨",
    ]
    await ctx.reply(
        f"🔮 **오늘의 운세**\n{random.choice(messages)}",
        mention_author=False,
    )


@core.bot.command(name="코인랭킹", aliases=["부자랭킹", "재산랭킹"])
async def coin_ranking(ctx):
    if not ctx.guild:
        return
    async with _pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, balance FROM economy_wallets
            WHERE guild_id=$1 AND balance>0
            ORDER BY balance DESC LIMIT 10
            """,
            ctx.guild.id,
        )
    if not rows:
        return await ctx.reply(
            "아직 코인 잔액이 있는 회원이 없어요.", mention_author=False
        )

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows, 1):
        member = ctx.guild.get_member(row["user_id"])
        name = member.display_name if member else f"탈퇴한 회원({row['user_id']})"
        medal = medals[i - 1] if i <= 3 else f"**{i}.**"
        lines.append(f"{medal} {name} — **{row['balance']:,} 코인**")

    await ctx.reply(
        "💰 **하트 코인 부자 랭킹**\n" + "\n".join(lines),
        mention_author=False,
    )
'''

path = Path("/mnt/data/economy.py")
path.write_text(source, encoding="utf-8")

# Basic syntax validation without importing the user's project modules.
compile(source, str(path), "exec")

print(f"완료: {path.name} 파일 생성 및 Python 문법 검사 통과 ({len(source.splitlines())}줄)")
