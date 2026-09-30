# Discord Server Management Bot
# 분리된 메인 실행 파일

from core import *
import intro
import profile
import moderation
import dating
import events

# 데이터 최초 로드
load_data()

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 없습니다.")

print("[BOT] Discord 연결 중...")
bot.run(TOKEN)
