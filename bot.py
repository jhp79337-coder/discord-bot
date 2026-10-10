# =========================================================
# Discord Server Management Bot
# 분리된 메인 실행 파일
# 제작자: 백구
# =========================================================

from core import *

import intro
import profile
import moderation
import dating
import events
import experience
import backup
import status
import romance
import nickname_restore
import economy


# =========================================================
# 데이터 최초 로드
# =========================================================

load_data()


# =========================================================
# 슬래시 명령어 동기화
# =========================================================

_slash_synced = False


async def sync_slash_commands():
    global _slash_synced

    await bot.wait_until_ready()

    if _slash_synced:
        return

    try:
        guild = discord.Object(id=GUILD_ID)

        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)

        _slash_synced = True
        print(
            f"[BOT] 슬래시 명령어 "
            f"{len(synced)}개 동기화 완료"
        )

    except Exception as e:
        print(f"[BOT] 슬래시 명령어 동기화 실패: {e}")


# =========================================================
# 봇 실행
# =========================================================

async def main():

    # PostgreSQL 연결
    await init_database()

    # 하트 코인 경제 시스템 초기화
    await economy.init_economy_database()

    # 연애 시스템 데이터베이스 초기화
    await romance.init_romance_database()

    # 회원 / 자기소개 데이터 불러오기
    await load_members_from_db()
    await load_profiles_from_db()

    # 경고 / 소개팅 / 예외 상태 복원
    await backup.load_runtime_state_from_db()

    # 봇 토큰 확인
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN이 없습니다.")

    # 소개팅 슬래시 명령어 등록
    dating.setup(bot)

    # 상태 슬래시 명령어 등록
    status.setup(bot)

    print("[BOT] Discord 연결 중...")

    # 자동 백업 시작
    backup.start_backup_loop()

    # 경제 시스템 자동 작업 시작
    economy.start_economy_loops()

    # 로그인 완료 후 슬래시 명령어 동기화
    asyncio.create_task(sync_slash_commands())

    # Discord 봇 실행
    await bot.start(TOKEN)


# =========================================================
# 시작
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
