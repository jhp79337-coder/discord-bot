```python
from core import *
from intro import intro_check, intro_complete, parse_intro
from dating import DatingLobbyView, DatingView

# 메시지 이벤트
# =========================================================

@bot.event
async def on_message(
    message
):

    # 봇 무시
    if message.author.bot:
        return

    # DM 무시
    if not message.guild:
        return

    # 지정 서버만
    if message.guild.id != GUILD_ID:
        return

    # 활동 기록
    data = member_data(
        message.author
    )

    data["last_activity"] = iso(
        now()
    )

    # =====================================================
    # 자기소개 감지
    # =====================================================

    if (
        message.channel.id
        ==
        INTRO_CHANNEL_ID

        and

        not data.get(
            "intro_completed",
            False
        )

        and

        message.author.id
        not in
        intro_exceptions
    ):

        result = parse_intro(
            message.content
        )

        if result:

            year, gender = result

            await intro_complete(
                message,
                year,
                gender
            )

    # 기존 JSON 저장 유지
    save_json(
        FILES["members"],
        members
    )

    # !명령어 처리
    await bot.process_commands(
        message
    )


# =========================================================
# 봇 준비 완료
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)

    print(
        f"로그인 완료 : {bot.user}"
    )

    print(
        f"서버 수 : {len(bot.guilds)}"
    )

    print("=" * 50)

    # 중요:
    # 여기서 load_data()를 다시 실행하면
    # PostgreSQL에서 불러온 members 데이터가
    # 오래된 JSON 데이터로 덮어써질 수 있음.
    #
    # bot.py에서 이미
    # load_data()
    # init_database()
    # load_members_from_db()
    # load_profiles_from_db()
    # 순서로 초기화하고 있으므로 여기서는 다시 호출하지 않음.

    global dating_views_registered

    if not dating_views_registered:

        bot.add_view(
            DatingLobbyView()
        )

        dating_views_registered = True

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:

        print(
            "❌ 서버를 찾을 수 없음"
        )

        return

    # 기존 소개팅 세션 버튼 복구
    for session_id, session in dating_sessions.items():

        if session.get(
            "status"
        ) == "active":

            bot.add_view(
                DatingView(session_id),
                message_id=None
            )

    print(
        f"[SERVER] {guild.name}"
    )

    # 자기소개 체크
    if not intro_check.is_running():

        intro_check.start()

        print(
            "[CHECK] 자기소개 감시 시작"
        )


# =========================================================
# 명령어 오류
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ 회원을 찾을 수 없습니다."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 필요한 값이 없습니다."
        )

        return

    print(
        f"[ERROR] "
        f"{type(error).__name__}: "
        f"{error}"
    )
```
