# =========================================================
# Discord Server Management Bot
# 분리된 메인 실행 파일
# =========================================================

from core import *

import intro
import profile
import moderation
import dating
import events


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

    # PostgreSQL에서 프로필 불러오기
    await load_profiles_from_db()

    if not TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN이 없습니다."
        )

    print(
        "[BOT] Discord 연결 중..."
    )

    await bot.start(
        TOKEN
    )


# =========================================================
# 시작
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
