# Discord Bot

기능별 모듈 구조로 분리된 Discord 봇입니다.

- `bot.py` — 실행/초기화
- `core.py` — 공통 설정, PostgreSQL, 공통 함수
- `modules/intro.py` — 자기소개/신규회원
- `modules/profile.py` — 프로필
- `modules/experience.py` — EXP/레벨
- `modules/status.py` — `!상태`
- `modules/dating.py` — 소개팅
- `modules/moderation.py` — 경고/제재
- `modules/backup.py` — 백업/복구
- `modules/events.py` — Discord 이벤트

Railway 시작 명령: `python bot.py`
