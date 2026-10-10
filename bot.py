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
import help_menu
import economy


# =========================================================
# 데이터 최초 로드
# =========================================================

load_data()


# =========================================================
# 봇 실행
# =========================================================

async def main():

    # PostgreSQL 연결
    await init_database()

    # 연애 시스템 데이터베이스 초기화
    await romance.init_romance_database()

    # PostgreSQL에서 회원 / 자기소개 데이터 불러오기
    await load_members_from_db()

    # PostgreSQL에서 프로필 불러오기
    await load_profiles_from_db()

    # PostgreSQL에 저장된 경고 / 소개팅 / 예외 상태 복원
    await backup.load_runtime_state_from_db()

    # 봇 토큰 확인
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN이 없습니다."
        )

    # 명령어 안내 등록
    await help_menu.setup(bot)

    print("[BOT] Discord 연결 중...")

    # 자동 백업 시작
    backup.start_backup_loop()

    # Discord 봇 실행
    await bot.start(TOKEN)


# =========================================================
# 시작
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
