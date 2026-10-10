
import discord
from discord.ext import commands


# =========================================================
# 백구 봇 명령어 안내 UI
# =========================================================

CREATOR_NAME = "백구"
EMBED_COLOR = 0xF5A9D0

FOOTER_TEXT = "♡ 백구가 정성껏 만든 봇입니다 ♡"


def create_help_embed():
    embed = discord.Embed(
        title="📖  전체 명령어 안내",
        description=(
            "╭───────────────╮\n"
            "　　 ♡ USER COMMANDS ♡\n"
            "╰───────────────╯\n\n"
            "아래에서 원하는 기능의 명령어를 확인해 주세요!\n"
            "명령어는 봇에 실제로 구현된 기능만 작동합니다."
        ),
        color=EMBED_COLOR
    )

    embed.add_field(
        name="📊 EXP · 경험치",
        value=(
            "`!내EXP` — 내 경험치 확인\n"
            "`!내경험치` — 내 경험치 확인"
        ),
        inline=False
    )

    embed.add_field(
        name="👤 PROFILE · 프로필",
        value=(
            "`!프로필` — 내 프로필 확인\n"
            "`!프로필편집` — 프로필 변경\n"
            "`!프로필삭제` — 프로필 삭제"
        ),
        inline=False
    )

    embed.add_field(
        name="💗 DATING · 소개팅",
        value="`!소개팅` — 소개팅 기능 이용",
        inline=False
    )

    embed.add_field(
        name="💌 ROMANCE · 연애",
        value=(
            "`!호감도` — 호감도 확인\n"
            "`!호감도올리기 @유저` — 호감도 올리기\n"
            "`!고백 @유저` — 고백하기\n"
            "`!고백수락` — 고백 수락\n"
            "`!고백거절` — 고백 거절\n"
            "`!고백취소` — 보낸 고백 취소\n"
            "`!커플` — 커플 정보 확인\n"
            "`!이별` — 커플 관계 종료"
        ),
        inline=False
    )

    embed.add_field(
        name="🔨 AUCTION · 노예 경매",
        value=(
            "`!경매안내` — 경매 안내\n"
            "`!경매현황` — 진행 중인 경매\n"
            "`!입찰 금액` — 경매 입찰\n"
            "`!경매기록` — 경매 기록\n"
            "`!낙찰기록` — 낙찰 내역\n"
            "`!노예명단` — 노예 목록\n"
            "`!내노예` — 내가 낙찰받은 유저\n"
            "`!내주인` — 나를 낙찰받은 유저\n"
            "`!경매도움말` — 경매 도움말"
        ),
        inline=False
    )

    embed.add_field(
        name="🎮 MINIGAME · 미니게임",
        value=(
            "`!게임안내` — 게임 안내\n"
            "`!주사위` — 주사위 게임\n"
            "`!가위바위보 바위` — 가위바위보\n"
            "`!슬롯 100` — 슬롯머신\n"
            "`!홀짝 홀` — 홀짝 게임\n"
            "`!코인던지기 앞면` — 동전 게임\n"
            "`!복권` — 복권 이용\n"
            "`!블랙잭 100` — 블랙잭\n"
            "`!숫자야구` — 숫자 맞히기\n"
            "`!끝말잇기` — 끝말잇기"
        ),
        inline=False
    )

    embed.add_field(
        name="⚔️ BATTLE · 유저 대결",
        value=(
            "`!대결신청 @유저 금액` — 대결 신청\n"
            "`!대결수락` — 대결 수락\n"
            "`!대결거절` — 대결 거절\n"
            "`!대결취소` — 대결 신청 취소\n"
            "`!대결현황` — 진행 상황 확인\n"
            "`!대결기록` — 대결 기록"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 ECONOMY · 포인트",
        value=(
            "`!내포인트` — 포인트 확인\n"
            "`!포인트랭킹` — 포인트 순위\n"
            "`!송금 @유저 금액` — 포인트 송금\n"
            "`!일일출석` — 출석 보상\n"
            "`!일일미션` — 오늘의 미션\n"
            "`!상점` — 아이템 상점\n"
            "`!구매 아이템명` — 아이템 구매\n"
            "`!인벤토리` — 보유 아이템\n"
            "`!아이템사용 아이템명` — 아이템 사용\n"
            "`!내거래기록` — 거래 내역"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 RANKING · 랭킹 및 기록",
        value=(
            "`!랭킹` — 전체 랭킹\n"
            "`!부자랭킹` — 포인트 랭킹\n"
            "`!게임랭킹` — 게임 순위\n"
            "`!승률` — 내 승률\n"
            "`!업적` — 달성 업적\n"
            "`!내기록` — 내 활동 기록"
        ),
        inline=False
    )

    embed.add_field(
        name="ℹ️ ETC · 기타",
        value=(
            "`!상태` — 내 상태 확인\n"
            "`!명령어` — 전체 명령어\n"
            "`!도움말` — 봇 도움말"
        ),
        inline=False
    )

    embed.add_field(
        name="🐾 BOT INFORMATION",
        value=(
            f"୨୧ **제작자** ・ {CREATOR_NAME}\n"
            "୨୧ **BOT** ・ 서버 관리 & 미니게임\n"
            "୨୧ **CONTENTS** ・ EXP / PROFILE / DATING\n"
            "୨୧ **SYSTEM** ・ ROMANCE / AUCTION / GAME\n\n"
            f"₊˚⊹♡ {FOOTER_TEXT} ♡⊹˚₊"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"© 2026 {CREATOR_NAME} · 명령어 안내"
    )

    return embed


@commands.command(name="명령어")
async def command_help(ctx):
    await ctx.send(embed=create_help_embed())


@commands.command(name="도움말")
async def general_help(ctx):
    await ctx.send(embed=create_help_embed())


async def setup(bot):
    bot.add_command(command_help)
    bot.add_command(general_help)
