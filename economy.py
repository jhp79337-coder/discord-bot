# -*- coding: utf-8 -*-
"""
소개팅/연애 서버용 가상 코인 경제 시스템
실제 돈이나 현금 환전 없이 서버 내부 가상 코인만 사용합니다.
제작자: 백구
"""

from datetime import datetime, timedelta, timezone
import random

import discord
from discord import app_commands
from discord.ext import tasks

import core


# =========================================================
# 기본 설정
# =========================================================

COIN_NAME = "하트 코인"

CHAT_REWARD = 3
CHAT_COOLDOWN_MINUTES = 5

VOICE_REWARD = 5
VOICE_TICK_MINUTES = 10

DAILY_REWARD = 100
MAX_BET = 500
AUCTION_MINUTES = 10

_active_quizzes = {}


# =========================================================
# 데이터베이스
# =========================================================

def _pool():
    if core.db_pool is None:
        raise RuntimeError(
            "PostgreSQL 연결이 없습니다. "
            "core.init_database() 이후 사용하세요."
        )

    return core.db_pool


async def init_economy_database():
    """경제 시스템 테이블을 생성합니다."""
    pool = _pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_wallets (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                balance BIGINT NOT NULL DEFAULT 0
                    CHECK (balance >= 0),
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
    await conn.execute("""
        INSERT INTO economy_wallets (guild_id, user_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, guild_id, user_id)


async def _balance(conn, guild_id, user_id):
    await _ensure_wallet(conn, guild_id, user_id)

    return await conn.fetchval("""
        SELECT balance
        FROM economy_wallets
        WHERE guild_id = $1 AND user_id = $2
    """, guild_id, user_id)


async def _change(conn, guild_id, user_id, amount, reason):
    """잔액을 변경하고 거래 내역을 기록합니다. 잔액 부족 시 False."""
    await _ensure_wallet(conn, guild_id, user_id)

if amount < 0:
    row = await conn.fetchrow("""
        UPDATE economy_wallets
        SET balance = balance + $3::BIGINT
        WHERE guild_id = $1
          AND user_id = $2
          AND balance >= ($3::BIGINT * -1)
        RETURNING balance
    """, guild_id, user_id, amount)

        if row is None:
            return False

    elif amount > 0:
        await conn.execute("""
            UPDATE economy_wallets
            SET balance = balance + $3
            WHERE guild_id = $1 AND user_id = $2
        """, guild_id, user_id, amount)

    await conn.execute("""
        INSERT INTO economy_transactions (
            guild_id, user_id, amount, reason
        )
        VALUES ($1, $2, $3, $4)
    """, guild_id, user_id, amount, reason)

    return True


# =========================================================
# 공통 응답
# =========================================================

async def _reply(
    interaction,
    content=None,
    *,
    embed=None,
    ephemeral=False
):
    if interaction.response.is_done():
        return await interaction.followup.send(
            content=content,
            embed=embed,
            ephemeral=ephemeral
        )

    return await interaction.response.send_message(
        content=content,
        embed=embed,
        ephemeral=ephemeral
    )


# =========================================================
# 공통 베팅 처리
# =========================================================

async def _play_bet_game(
    interaction,
    bet,
    game_name,
    outcome_text,
    payout_multiplier=0,
    refund=False
):
    if not interaction.response.is_done():
        await interaction.response.defer()

    if not 1 <= bet <= MAX_BET:
        return await _reply(
            interaction,
            f"❌ 베팅은 1~{MAX_BET} 코인까지 가능해요."
        )

    guild_id = interaction.guild_id
    user_id = interaction.user.id

    try:
        async with _pool().acquire() as conn:
            async with conn.transaction():
                success = await _change(
                    conn,
                    guild_id,
                    user_id,
                    -bet,
                    f"{game_name} 베팅"
                )

                if not success:
                    return await _reply(
                        interaction,
                        "❌ 코인이 부족해요."
                    )

                if refund:
                    await _change(
                        conn,
                        guild_id,
                        user_id,
                        bet,
                        f"{game_name} 환급"
                    )

                    net_text = (
                        f"베팅금 **{bet:,} 코인**을 돌려받았어요."
                    )

                elif payout_multiplier > 0:
                    payout = bet * payout_multiplier

                    await _change(
                        conn,
                        guild_id,
                        user_id,
                        payout,
                        f"{game_name} 당첨"
                    )

                    net_text = (
                        f"총 반환 **{payout:,} 코인** · "
                        f"순이익 **{payout - bet:,} 코인** 🎉"
                    )

                else:
                    net_text = f"**{bet:,} 코인**을 잃었어요."

                balance = await _balance(
                    conn,
                    guild_id,
                    user_id
                )

        await _reply(
            interaction,
            f"{outcome_text}\n"
            f"{net_text}\n"
            f"💗 잔액: **{balance:,} 코인**"
        )

    except Exception as e:
        print(
            f"[ECONOMY ERROR] {game_name}: "
            f"{type(e).__name__}: {e}"
        )

        await _reply(
            interaction,
            "❌ 게임 처리 중 오류가 발생했어요. "
            "관리자에게 문의해 주세요."
        )
# =========================================================
# /잔액
# =========================================================

@core.bot.tree.command(
    name="잔액",
    description="나 또는 다른 회원의 코인 잔액을 확인합니다."
)
@app_commands.describe(member="잔액을 확인할 회원")
@app_commands.guild_only()
async def wallet(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    async with _pool().acquire() as conn:
        balance = await _balance(
            conn,
            interaction.guild_id,
            member.id
        )

    await _reply(
        interaction,
        f"💗 **{member.display_name}**님의 잔액: "
        f"**{balance:,} {COIN_NAME}**"
    )


# =========================================================
# /일일
# =========================================================

@core.bot.tree.command(
    name="일일",
    description="24시간마다 하트 코인을 받습니다."
)
@app_commands.guild_only()
async def daily(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    user_id = interaction.user.id
    current_time = datetime.now(timezone.utc)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            await _ensure_wallet(conn, guild_id, user_id)

            row = await conn.fetchrow("""
                SELECT daily_at
                FROM economy_wallets
                WHERE guild_id=$1 AND user_id=$2
                FOR UPDATE
            """, guild_id, user_id)

            if (
                row["daily_at"]
                and current_time - row["daily_at"]
                < timedelta(hours=24)
            ):
                remaining = (
                    timedelta(hours=24)
                    - (current_time - row["daily_at"])
                )

                hours = int(
                    remaining.total_seconds() // 3600
                )
                minutes = int(
                    (remaining.total_seconds() % 3600) // 60
                )

                return await _reply(
                    interaction,
                    f"⏳ 일일 보상은 {hours}시간 "
                    f"{minutes}분 후에 받을 수 있어요.",
                    ephemeral=True
                )

            await conn.execute("""
                UPDATE economy_wallets
                SET daily_at=$3
                WHERE guild_id=$1 AND user_id=$2
            """, guild_id, user_id, current_time)

            await _change(
                conn,
                guild_id,
                user_id,
                DAILY_REWARD,
                "일일 출석 보상"
            )

            balance = await _balance(
                conn,
                guild_id,
                user_id
            )

    await _reply(
        interaction,
        f"🎁 출석 보상 **{DAILY_REWARD} 코인** 지급!\n"
        f"💗 현재 잔액: **{balance:,} 코인**"
    )


# =========================================================
# /코인송금
# =========================================================

@core.bot.tree.command(
    name="코인송금",
    description="다른 회원에게 코인을 송금합니다."
)
@app_commands.describe(
    member="송금받을 회원",
    amount="송금할 코인 수"
)
@app_commands.guild_only()
async def transfer(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 1000000]
):
    if member.bot or member.id == interaction.user.id:
        return await _reply(
            interaction,
            "❌ 본인이나 봇에게는 송금할 수 없어요.",
            ephemeral=True
        )

    async with _pool().acquire() as conn:
        async with conn.transaction():
            success = await _change(
                conn,
                interaction.guild_id,
                interaction.user.id,
                -amount,
                f"{member.id}에게 송금"
            )

            if not success:
                return await _reply(
                    interaction,
                    "❌ 코인이 부족해요.",
                    ephemeral=True
                )

            await _change(
                conn,
                interaction.guild_id,
                member.id,
                amount,
                f"{interaction.user.id}에게서 송금"
            )

            balance = await _balance(
                conn,
                interaction.guild_id,
                interaction.user.id
            )

    await _reply(
        interaction,
        f"💌 {member.mention}에게 **{amount:,} 코인**을 보냈어요.\n"
        f"💗 남은 잔액: **{balance:,} 코인**"
    )


# =========================================================
# /가위바위보
# =========================================================

@core.bot.tree.command(
    name="가위바위보",
    description="코인을 걸고 가위바위보를 합니다."
)
@app_commands.describe(
    bet="베팅 금액",
    choice="가위, 바위 또는 보"
)
@app_commands.choices(choice=[
    app_commands.Choice(name="가위", value="가위"),
    app_commands.Choice(name="바위", value="바위"),
    app_commands.Choice(name="보", value="보"),
])
@app_commands.guild_only()
async def rps(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET],
    choice: app_commands.Choice[str]
):
    mine = choice.value
    theirs = random.choice(["가위", "바위", "보"])
    beats = {
        "가위": "보",
        "바위": "가위",
        "보": "바위"
    }

    if mine == theirs:
        multiplier = 0
        refund = True
        result = "무승부!"
    elif beats[mine] == theirs:
        multiplier = 2
        refund = False
        result = "승리!"
    else:
        multiplier = 0
        refund = False
        result = "패배!"

    await _play_bet_game(
        interaction,
        bet,
        "가위바위보",
        f"✊ 내 선택: **{mine}** · "
        f"봇 선택: **{theirs}**\n{result}",
        multiplier,
        refund
    )


# =========================================================
# /주사위
# =========================================================

@core.bot.tree.command(
    name="주사위",
    description="주사위를 굴립니다. 4 이상이면 승리!"
)
@app_commands.describe(bet="베팅 금액")
@app_commands.guild_only()
async def dice(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET]
):
    roll = random.randint(1, 6)
    win = roll >= 4

    await _play_bet_game(
        interaction,
        bet,
        "주사위",
        f"🎲 주사위 결과: **{roll}** · "
        f"{'승리!' if win else '패배!'}",
        2 if win else 0
    )


# =========================================================
# /슬롯
# =========================================================

@core.bot.tree.command(
    name="슬롯",
    description="슬롯머신에 코인을 걸어보세요."
)
@app_commands.describe(bet="베팅 금액")
@app_commands.guild_only()
async def slots(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET]
):
    symbols = ["🍒", "🍋", "🍇", "💎", "💗"]
    result = [
        random.choice(symbols)
        for _ in range(3)
    ]

    if len(set(result)) == 1:
        multiplier = 5
    elif len(set(result)) == 2:
        multiplier = 2
    else:
        multiplier = 0

    await _play_bet_game(
        interaction,
        bet,
        "슬롯",
        f"🎰 {' | '.join(result)}",
        multiplier
    )


# =========================================================
# /코인던지기
# =========================================================

@core.bot.tree.command(
    name="코인던지기",
    description="앞면 또는 뒷면을 맞혀보세요."
)
@app_commands.describe(
    bet="베팅 금액",
    choice="예상하는 결과"
)
@app_commands.choices(choice=[
    app_commands.Choice(name="앞면", value="앞면"),
    app_commands.Choice(name="뒷면", value="뒷면"),
])
@app_commands.guild_only()
async def coin_flip(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET],
    choice: app_commands.Choice[str]
):
    result = random.choice(["앞면", "뒷면"])
    win = choice.value == result

    await _play_bet_game(
        interaction,
        bet,
        "코인던지기",
        f"🪙 결과: **{result}** · "
        f"선택: **{choice.value}**",
        2 if win else 0
    )


# =========================================================
# /홀짝
# =========================================================

@core.bot.tree.command(
    name="홀짝",
    description="숫자의 홀짝을 맞혀보세요."
)
@app_commands.describe(
    bet="베팅 금액",
    choice="홀수 또는 짝수"
)
@app_commands.choices(choice=[
    app_commands.Choice(name="홀수", value="홀"),
    app_commands.Choice(name="짝수", value="짝"),
])
@app_commands.guild_only()
async def odd_even(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET],
    choice: app_commands.Choice[str]
):
    number = random.randint(1, 100)
    result = "홀" if number % 2 else "짝"

    await _play_bet_game(
        interaction,
        bet,
        "홀짝",
        f"🔢 숫자 **{number}** · 결과 **{result}**",
        2 if choice.value == result else 0
    )


# =========================================================
# /숫자맞추기
# =========================================================

@core.bot.tree.command(
    name="숫자맞추기",
    description="1부터 10까지의 숫자를 맞혀보세요."
)
@app_commands.describe(
    bet="베팅 금액",
    guess="예상 숫자 1~10"
)
@app_commands.guild_only()
async def number_guess(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET],
    guess: app_commands.Range[int, 1, 10]
):
    number = random.randint(1, 10)

    await _play_bet_game(
        interaction,
        bet,
        "숫자맞추기",
        f"🎯 정답: **{number}** · 내 선택: **{guess}**",
        5 if guess == number else 0
    )


# =========================================================
# /룰렛
# =========================================================

@core.bot.tree.command(
    name="룰렛",
    description="룰렛에 코인을 걸어보세요."
)
@app_commands.describe(bet="베팅 금액")
@app_commands.guild_only()
async def roulette(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET]
):
    number = random.randint(0, 9)
    win = number >= 5

    await _play_bet_game(
        interaction,
        bet,
        "룰렛",
        f"🎡 룰렛 결과: **{number}** · "
        f"{'당첨!' if win else '꽝!'}",
        2 if win else 0
    )


# =========================================================
# /상자열기
# =========================================================

@core.bot.tree.command(
    name="상자열기",
    description="보물 상자를 열어 코인을 획득하세요."
)
@app_commands.describe(bet="베팅 금액")
@app_commands.guild_only()
async def chest(
    interaction: discord.Interaction,
    bet: app_commands.Range[int, 1, MAX_BET]
):
    roll = random.random()

    if roll < 0.05:
        multiplier = 5
        label = "💎 전설의 보물!"
    elif roll < 0.25:
        multiplier = 2
        label = "✨ 보물을 찾았어요!"
    else:
        multiplier = 0
        label = "🪹 빈 상자예요."

    await _play_bet_game(
        interaction,
        bet,
        "상자열기",
        label,
        multiplier
    )
# =========================================================
# /노예등록
# =========================================================

@core.bot.tree.command(
    name="노예등록",
    description="본인 동의로 가상 역할놀이 경매 등록을 신청합니다."
)
@app_commands.guild_only()
async def slave_register(interaction: discord.Interaction):
    async with _pool().acquire() as conn:
        await conn.execute("""
            INSERT INTO economy_slave_optins (guild_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, interaction.guild_id, interaction.user.id)

    await _reply(
        interaction,
        "🔐 가상 역할놀이 경매 등록 신청이 완료됐어요.\n"
        "본인이 직접 동의한 경우에만 경매에 올릴 수 있어요.\n"
        "취소하려면 `/노예등록취소`를 사용하세요."
    )


# =========================================================
# /노예등록취소
# =========================================================

@core.bot.tree.command(
    name="노예등록취소",
    description="가상 경매 등록 신청을 취소합니다."
)
@app_commands.guild_only()
async def slave_unregister(interaction: discord.Interaction):
    async with _pool().acquire() as conn:
        active = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM economy_auctions
                WHERE guild_id=$1
                  AND seller_id=$2
                  AND status='open'
            )
        """, interaction.guild_id, interaction.user.id)

        if active:
            return await _reply(
                interaction,
                "❌ 진행 중인 경매가 있어요. 먼저 `/경매취소`를 사용하세요.",
                ephemeral=True
            )

        await conn.execute("""
            DELETE FROM economy_slave_optins
            WHERE guild_id=$1 AND user_id=$2
        """, interaction.guild_id, interaction.user.id)

    await _reply(
        interaction,
        "✅ 경매 등록 신청을 취소했어요."
    )


# =========================================================
# /경매시작
# =========================================================

@core.bot.tree.command(
    name="경매시작",
    description="동의한 회원만 본인 경매를 시작할 수 있습니다."
)
@app_commands.describe(start_price="경매 시작 가격")
@app_commands.guild_only()
async def auction_start(
    interaction: discord.Interaction,
    start_price: app_commands.Range[int, 1, 1000000]
):
    guild_id = interaction.guild_id
    user_id = interaction.user.id

    async with _pool().acquire() as conn:
        opted = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM economy_slave_optins
                WHERE guild_id=$1 AND user_id=$2
            )
        """, guild_id, user_id)

        if not opted:
            return await _reply(
                interaction,
                "먼저 `/노예등록`으로 본인 동의를 등록해 주세요.",
                ephemeral=True
            )

        active = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM economy_auctions
                WHERE guild_id=$1
                  AND seller_id=$2
                  AND status='open'
            )
        """, guild_id, user_id)

        if active:
            return await _reply(
                interaction,
                "이미 진행 중인 경매가 있어요.",
                ephemeral=True
            )

        row = await conn.fetchrow("""
            INSERT INTO economy_auctions (
                guild_id, seller_id, channel_id,
                start_price, highest_bid, ends_at
            )
            VALUES ($1, $2, $3, $4, $4, $5)
            RETURNING id, ends_at
        """,
            guild_id,
            user_id,
            interaction.channel_id,
            start_price,
            datetime.now(timezone.utc)
            + timedelta(minutes=AUCTION_MINUTES)
        )

    embed = discord.Embed(
        title="🔨 하트 코인 가상 경매",
        description=(
            f"경매 ID: **#{row['id']}**\n"
            f"등록자: {interaction.user.mention}\n"
            f"시작가: **{start_price:,} 코인**\n"
            f"종료: <t:{int(row['ends_at'].timestamp())}:R>\n\n"
            "입찰: `/입찰` 명령어에서 경매 ID와 금액 입력\n"
            "취소: `/경매취소` 명령어에서 경매 ID 입력\n\n"
            "※ 서버 내부의 자발적인 가상 역할놀이입니다. "
            "실제 소유권이나 강제 의무는 발생하지 않아요."
        ),
        color=discord.Color.from_rgb(255, 105, 180)
    )

    await _reply(interaction, embed=embed)


# =========================================================
# /입찰
# =========================================================

@core.bot.tree.command(
    name="입찰",
    description="진행 중인 경매에 코인을 입찰합니다."
)
@app_commands.describe(
    auction_id="경매 ID",
    amount="입찰 금액"
)
@app_commands.guild_only()
async def auction_bid(
    interaction: discord.Interaction,
    auction_id: app_commands.Range[int, 1, 2147483647],
    amount: app_commands.Range[int, 1, 100000000]
):
    guild_id = interaction.guild_id
    bidder_id = interaction.user.id

    async with _pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM economy_auctions
                WHERE id=$1
                  AND guild_id=$2
                  AND status='open'
                FOR UPDATE
            """, auction_id, guild_id)

            if not row:
                return await _reply(
                    interaction,
                    "❌ 진행 중인 경매를 찾을 수 없어요.",
                    ephemeral=True
                )

            if row["ends_at"] <= datetime.now(timezone.utc):
                await conn.execute("""
                    UPDATE economy_auctions
                    SET status='ended'
                    WHERE id=$1
                """, auction_id)

                return await _reply(
                    interaction,
                    "⏰ 이 경매는 종료됐어요.",
                    ephemeral=True
                )

            if bidder_id in (
                row["seller_id"],
                row["highest_bidder"]
            ):
                return await _reply(
                    interaction,
                    "❌ 등록자 본인이나 현재 최고 입찰자는 입찰할 수 없어요.",
                    ephemeral=True
                )

            minimum = (
                row["start_price"]
                if row["highest_bidder"] is None
                else row["highest_bid"] + 1
            )

            if amount < minimum:
                return await _reply(
                    interaction,
                    f"❌ 다음 입찰은 최소 **{minimum:,} 코인**이어야 해요.",
                    ephemeral=True
                )

            success = await _change(
                conn,
                guild_id,
                bidder_id,
                -amount,
                f"경매 #{auction_id} 입찰 예약"
            )

            if not success:
                return await _reply(
                    interaction,
                    "❌ 잔액이 부족해요.",
                    ephemeral=True
                )

            if row["highest_bidder"] is not None:
                await _change(
                    conn,
                    guild_id,
                    row["highest_bidder"],
                    row["highest_bid"],
                    f"경매 #{auction_id} 최고입찰 교체 환불"
                )

            await conn.execute("""
                UPDATE economy_auctions
                SET highest_bid=$2,
                    highest_bidder=$3
                WHERE id=$1
            """, auction_id, amount, bidder_id)

    await _reply(
        interaction,
        f"🔨 경매 **#{auction_id}**에 "
        f"**{amount:,} 코인**으로 입찰했어요!"
    )


# =========================================================
# /경매현황
# =========================================================

@core.bot.tree.command(
    name="경매현황",
    description="경매의 현재 상태를 확인합니다."
)
@app_commands.describe(auction_id="확인할 경매 ID")
@app_commands.guild_only()
async def auction_status(
    interaction: discord.Interaction,
    auction_id: app_commands.Range[int, 1, 2147483647]
):
    async with _pool().acquire() as conn:
        row = await conn.fetchrow("""
            SELECT *
            FROM economy_auctions
            WHERE id=$1 AND guild_id=$2
        """, auction_id, interaction.guild_id)

    if not row:
        return await _reply(
            interaction,
            "경매를 찾을 수 없어요.",
            ephemeral=True
        )

    bidder = (
        f"<@{row['highest_bidder']}>"
        if row["highest_bidder"]
        else "아직 없음"
    )

    await _reply(
        interaction,
        f"🔨 경매 **#{auction_id}**\n"
        f"상태: **{row['status']}**\n"
        f"현재 입찰: **{row['highest_bid']:,} 코인**\n"
        f"최고 입찰자: {bidder}\n"
        f"종료: <t:{int(row['ends_at'].timestamp())}:R>"
    )


# =========================================================
# /경매취소
# =========================================================

@core.bot.tree.command(
    name="경매취소",
    description="본인 경매를 취소합니다."
)
@app_commands.describe(auction_id="취소할 경매 ID")
@app_commands.guild_only()
async def auction_cancel(
    interaction: discord.Interaction,
    auction_id: app_commands.Range[int, 1, 2147483647]
):
    async with _pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM economy_auctions
                WHERE id=$1
                  AND guild_id=$2
                  AND status='open'
                FOR UPDATE
            """, auction_id, interaction.guild_id)

            if not row:
                return await _reply(
                    interaction,
                    "❌ 진행 중인 경매를 찾을 수 없어요.",
                    ephemeral=True
                )

            allowed = (
                row["seller_id"] == interaction.user.id
                or interaction.user.guild_permissions.manage_guild
            )

            if not allowed:
                return await _reply(
                    interaction,
                    "❌ 등록자 또는 서버 관리 권한이 있는 사람만 취소할 수 있어요.",
                    ephemeral=True
                )

            if row["highest_bidder"] is not None:
                await _change(
                    conn,
                    interaction.guild_id,
                    row["highest_bidder"],
                    row["highest_bid"],
                    f"경매 #{auction_id} 취소 환불"
                )

            await conn.execute("""
                UPDATE economy_auctions
                SET status='cancelled'
                WHERE id=$1
            """, auction_id)

    await _reply(
        interaction,
        f"✅ 경매 #{auction_id}을 취소하고 입찰금을 환불했어요."
    )


# =========================================================
# 채팅 활동 보상
# =========================================================

async def on_message_economy(message):
    if (
        message.author.bot
        or not message.guild
        or not message.content.strip()
        or len(message.content.strip()) < 3
    ):
        return

    if message.content.startswith(("!", "/")):
        return

    current_time = datetime.now(timezone.utc)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO economy_activity (guild_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, message.guild.id, message.author.id)

            row = await conn.fetchrow("""
                SELECT chat_at
                FROM economy_activity
                WHERE guild_id=$1 AND user_id=$2
                FOR UPDATE
            """, message.guild.id, message.author.id)

            if (
                row["chat_at"]
                and current_time - row["chat_at"]
                < timedelta(minutes=CHAT_COOLDOWN_MINUTES)
            ):
                return

            await conn.execute("""
                UPDATE economy_activity
                SET chat_at=$3
                WHERE guild_id=$1 AND user_id=$2
            """, message.guild.id, message.author.id, current_time)

            await _change(
                conn,
                message.guild.id,
                message.author.id,
                CHAT_REWARD,
                "채팅 활동 보상"
            )


# =========================================================
# 음성 활동 보상
# =========================================================

async def on_voice_economy(member, before, after):
    if member.bot or not member.guild:
        return

    async with _pool().acquire() as conn:
        await conn.execute("""
            INSERT INTO economy_activity (guild_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, member.guild.id, member.id)


@tasks.loop(minutes=VOICE_TICK_MINUTES)
async def voice_rewards_loop():
    if core.db_pool is None:
        return

    for guild in list(core.bot.guilds):
        for channel in guild.voice_channels:
            if channel == guild.afk_channel:
                continue

            members = [
                member
                for member in channel.members
                if not member.bot
                and member.voice
                and not member.voice.self_deaf
                and not member.voice.deaf
            ]

            if len(members) < 2:
                continue

            async with core.db_pool.acquire() as conn:
                async with conn.transaction():
                    for member in members:
                        await _change(
                            conn,
                            guild.id,
                            member.id,
                            VOICE_REWARD,
                            "음성 활동 보상"
                        )


@voice_rewards_loop.before_loop
async def before_voice_rewards_loop():
    await core.bot.wait_until_ready()


# =========================================================
# 경매 자동 정산
# =========================================================

@tasks.loop(minutes=1)
async def auction_settlement_loop():
    if core.db_pool is None:
        return

    pool = core.db_pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id
            FROM economy_auctions
            WHERE status='open' AND ends_at <= NOW()
            ORDER BY id
            LIMIT 50
        """)

    for item in rows:
        settled = None

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    SELECT *
                    FROM economy_auctions
                    WHERE id=$1 AND status='open'
                    FOR UPDATE
                """, item["id"])

                if (
                    not row
                    or row["ends_at"] > datetime.now(timezone.utc)
                ):
                    continue

                await conn.execute("""
                    UPDATE economy_auctions
                    SET status='ended'
                    WHERE id=$1
                """, row["id"])

                if row["highest_bidder"] is not None:
                    await _change(
                        conn,
                        row["guild_id"],
                        row["seller_id"],
                        row["highest_bid"],
                        f"경매 #{row['id']} 낙찰 코인 수령"
                    )

                settled = dict(row)

        guild = core.bot.get_guild(settled["guild_id"])
        channel = (
            guild.get_channel(settled["channel_id"])
            if guild else None
        )

        if channel is None:
            continue

        if settled["highest_bidder"] is None:
            await channel.send(
                f"⏰ 경매 **#{settled['id']}**가 "
                "입찰 없이 종료됐어요.\n"
                f"등록자: <@{settled['seller_id']}>"
            )
        else:
            await channel.send(
                f"🏆 **경매 #{settled['id']} 종료!**\n"
                f"등록자: <@{settled['seller_id']}>\n"
                f"낙찰자: <@{settled['highest_bidder']}>\n"
                f"낙찰가: **{settled['highest_bid']:,} 하트 코인**\n\n"
                "※ 서버 내부 가상 역할놀이이며 "
                "실제 소유권이나 강제 의무가 발생하지 않아요."
            )


@auction_settlement_loop.before_loop
async def before_auction_settlement_loop():
    await core.bot.wait_until_ready()


def start_economy_loops():
    """bot.py의 main()에서 호출합니다."""
    if not voice_rewards_loop.is_running():
        voice_rewards_loop.start()

    if not auction_settlement_loop.is_running():
        auction_settlement_loop.start()


# =========================================================
# /복권
# =========================================================

@core.bot.tree.command(
    name="복권",
    description="24시간마다 무료 복권을 받을 수 있습니다."
)
@app_commands.guild_only()
async def lottery(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    user_id = interaction.user.id
    current_time = datetime.now(timezone.utc)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO economy_game_cooldowns (
                    guild_id, user_id, game, used_at
                )
                VALUES (
                    $1, $2, 'lottery',
                    $3 - INTERVAL '24 hours'
                )
                ON CONFLICT DO NOTHING
            """, guild_id, user_id, current_time)

            row = await conn.fetchrow("""
                SELECT used_at
                FROM economy_game_cooldowns
                WHERE guild_id=$1
                  AND user_id=$2
                  AND game='lottery'
                FOR UPDATE
            """, guild_id, user_id)

            if (
                row
                and current_time - row["used_at"]
                < timedelta(hours=24)
            ):
                remaining = (
                    timedelta(hours=24)
                    - (current_time - row["used_at"])
                )

                hours = int(
                    remaining.total_seconds() // 3600
                )
                minutes = int(
                    (remaining.total_seconds() % 3600) // 60
                )

                return await _reply(
                    interaction,
                    f"🎟️ 무료 복권은 {hours}시간 "
                    f"{minutes}분 후에 다시 받을 수 있어요.",
                    ephemeral=True
                )

            await conn.execute("""
                UPDATE economy_game_cooldowns
                SET used_at=$3
                WHERE guild_id=$1
                  AND user_id=$2
                  AND game='lottery'
            """, guild_id, user_id, current_time)

            prize = random.choices(
                [0, 25, 50, 100, 500],
                weights=[50, 25, 15, 9, 1]
            )[0]

            if prize:
                await _change(
                    conn,
                    guild_id,
                    user_id,
                    prize,
                    "무료 복권 당첨"
                )

            balance = await _balance(
                conn,
                guild_id,
                user_id
            )

    await _reply(
        interaction,
        f"🎟️ 복권 결과: **{prize:,} 코인** "
        f"{'당첨!' if prize else '꽝!'}\n"
        f"💗 잔액: **{balance:,} 코인**"
    )


# =========================================================
# /초성퀴즈
# =========================================================

@core.bot.tree.command(
    name="초성퀴즈",
    description="초성 퀴즈를 시작합니다."
)
@app_commands.guild_only()
async def initial_quiz(interaction: discord.Interaction):
    questions = [
        ("ㄱㅇ", "고양이"),
        ("ㅂㄴㄴ", "바나나"),
        ("ㅋㅍ", "커피"),
        ("ㄷㅅㅋㄷ", "디스코드"),
        ("ㅅㄱ", "사과"),
        ("ㅊㅋㄹ", "초콜릿"),
    ]

    initials, answer = random.choice(questions)
    key = (
        interaction.guild_id,
        interaction.channel_id
    )

    _active_quizzes[key] = {
        "answer": answer,
        "expires": datetime.now(timezone.utc)
        + timedelta(seconds=30)
    }

    await _reply(
        interaction,
        f"🧩 **초성 퀴즈**\n"
        f"초성: `{initials}`\n"
        "30초 안에 `/초성정답` 명령어로 정답을 제출하세요. "
        "맞히면 30 코인!"
    )


# =========================================================
# /초성정답
# =========================================================

@core.bot.tree.command(
    name="초성정답",
    description="진행 중인 초성 퀴즈의 정답을 제출합니다."
)
@app_commands.describe(answer="정답")
@app_commands.guild_only()
async def initial_answer(
    interaction: discord.Interaction,
    answer: str
):
    key = (
        interaction.guild_id,
        interaction.channel_id
    )

    active = _active_quizzes.get(key)

    if (
        not active
        or active["expires"] < datetime.now(timezone.utc)
    ):
        _active_quizzes.pop(key, None)

        return await _reply(
            interaction,
            "진행 중인 초성 퀴즈가 없어요.",
            ephemeral=True
        )

    submitted = answer.strip().replace(" ", "").lower()
    expected = active["answer"].replace(" ", "").lower()

    if submitted != expected:
        return await _reply(
            interaction,
            "❌ 아쉬워요! 다시 생각해 봐요.",
            ephemeral=True
        )

    _active_quizzes.pop(key, None)

    async with _pool().acquire() as conn:
        async with conn.transaction():
            await _change(
                conn,
                interaction.guild_id,
                interaction.user.id,
                30,
                "초성 퀴즈 정답"
            )

            balance = await _balance(
                conn,
                interaction.guild_id,
                interaction.user.id
            )

    await _reply(
        interaction,
        f"🎉 정답! **30 코인** 지급!\n"
        f"현재 잔액: **{balance:,} 코인**"
    )


# =========================================================
# /운세
# =========================================================

@core.bot.tree.command(
    name="운세",
    description="오늘의 운세를 확인합니다."
)
async def fortune(interaction: discord.Interaction):
    messages = [
        "오늘은 작은 행운이 찾아올지도 몰라요 🍀",
        "지갑을 지키는 게 최고의 전략이에요 💗",
        "친구와 미니게임을 하면 즐거운 일이 생길지도! 🎲",
        "오늘의 키워드는 인내심이에요 🌙",
        "행운은 랜덤! 무리한 베팅은 피하세요 ✨",
    ]

    await _reply(
        interaction,
        f"🔮 **오늘의 운세**\n{random.choice(messages)}"
    )


# =========================================================
# /코인랭킹
# =========================================================

@core.bot.tree.command(
    name="코인랭킹",
    description="하트 코인 부자 랭킹을 확인합니다."
)
@app_commands.guild_only()
async def coin_ranking(interaction: discord.Interaction):
    async with _pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, balance
            FROM economy_wallets
            WHERE guild_id=$1 AND balance > 0
            ORDER BY balance DESC
            LIMIT 10
        """, interaction.guild_id)

    if not rows:
        return await _reply(
            interaction,
            "아직 코인 잔액이 있는 회원이 없어요."
        )

    lines = []
    medals = ["🥇", "🥈", "🥉"]

    for i, row in enumerate(rows, 1):
        member = interaction.guild.get_member(row["user_id"])

        name = (
            member.display_name
            if member
            else f"탈퇴한 회원({row['user_id']})"
        )

        medal = (
            medals[i - 1]
            if i <= 3
            else f"**{i}.**"
        )

        lines.append(
            f"{medal} {name} — **{row['balance']:,} 코인**"
        )

    await _reply(
        interaction,
        "💰 **하트 코인 부자 랭킹**\n"
        + "\n".join(lines)
    )


# =========================================================
# 이벤트 연결
# =========================================================

if on_message_economy not in core.bot.extra_events.get(
    "on_message", []
):
    core.bot.add_listener(
        on_message_economy,
        "on_message"
    )


if on_voice_economy not in core.bot.extra_events.get(
    "on_voice_state_update", []
):
    core.bot.add_listener(
        on_voice_economy,
        "on_voice_state_update"
    )
