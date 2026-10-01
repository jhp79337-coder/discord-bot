from core import *


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(text):

    text = text.strip()

    # -----------------------------------------------------
    # 4자리 연도
    # -----------------------------------------------------

    match = re.search(
        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"\s*"
        r"(남|여|ㄴ|ㅇ)"
        r"(?!\S)",
        text
    )

    if match:

        raw_year = match.group(1)
        gender = match.group(2)

        year = int(raw_year)

    else:

        # -------------------------------------------------
        # 2자리 연도
        # 2000년대만 허용
        # -------------------------------------------------

        match = re.search(
            r"(?<!\d)"
            r"(\d{2})"
            r"\s*"
            r"(남|여|ㄴ|ㅇ)"
            r"(?!\S)",
            text
        )

        if not match:
            return None

        raw_year = match.group(1)
        gender = match.group(2)

        short_year = int(raw_year)

        current_year = datetime.now().year
        current_short = current_year % 100

        # 미래 연도 방지
        if short_year > current_short:
            return None

        year = 2000 + short_year

    # -----------------------------------------------------
    # 연도 검증
    # -----------------------------------------------------

    current_year = datetime.now().year

    if year < 1900:
        return None

    if year > current_year:
        return None

    # -----------------------------------------------------
    # 성별
    # -----------------------------------------------------

    if gender in (
        "남",
        "ㄴ"
    ):

        gender = "남"

    else:

        gender = "여"

    return (
        year,
        gender
    )


# =========================================================
# 자기소개 역할 적용
# =========================================================

async def apply_intro_roles(
    member,
    year,
    gender
):

    # 기존 역할 제거

    for key in (
        "unverified",
        "male",
        "female",
        "adult",
        "minor"
    ):

        await manage_role(
            member,
            ROLES[key],
            False
        )

    # 성별

    if gender == "남":

        await manage_role(
            member,
            ROLES["male"],
            True
        )

    else:

        await manage_role(
            member,
            ROLES["female"],
            True
        )

    # 나이

    if age_type(year) == "성인":

        await manage_role(
            member,
            ROLES["adult"],
            True
        )

    else:

        await manage_role(
            member,
            ROLES["minor"],
            True
        )

    # 자기소개 완료 역할

    await manage_role(
        member,
        ROLES["intro_complete"],
        True
    )


# =========================================================
# 자기소개 완료
# =========================================================

async def intro_complete(
    message,
    year,
    gender
):

    member = message.author

    # -----------------------------------------------------
    # 회원 데이터
    # -----------------------------------------------------

    data = member_data(
        member
    )

    data.update({

        "intro_completed":
            True,

        "birth_year":
            year,

        "gender":
            gender,

        "intro_completed_at":
            iso(now()),

        "kicked":
            False

    })

    # PostgreSQL 저장
    await save_member_to_db(
        member.id,
        data
    )

    pending_kicks.discard(
        member.id
    )

    # -----------------------------------------------------
    # 역할
    # -----------------------------------------------------

    await apply_intro_roles(
        member,
        year,
        gender
    )

    # -----------------------------------------------------
    # 안내
    # -----------------------------------------------------

    await message.channel.send(

        f"🖤 {member.mention} "
        f"자기소개 확인했어요 ♡\n\n"

        f"`{year}년생` · "
        f"`{gender_text(gender)}` · "
        f"`{age_type(year)}`\n\n"

        f"🎀 <#{ROLE_CHANNEL_ID}> "
        f"에서 역할을 골라주세요.\n"

        f"💬 <#{MAIN_CHAT_ID}> "
        f"에서 편하게 놀아요!"

    )


# =========================================================
# 자기소개 미작성 자동 추방
# =========================================================

async def auto_kick_no_intro(guild, member):

    if member.id in intro_exceptions:
        return

    data = member_data(member)

    if data.get("intro_completed", False):
        return

    try:
        await member.kick(reason="자기소개 미작성")

        data["kicked"] = True
        await save_member_to_db(member.id, data)
        pending_kicks.discard(member.id)

        log = get_log_channel(guild)
        if log:
            await log.send(
                f"🚪 {member.mention}님을 자기소개 미작성으로 자동 추방했습니다.\n"
                f"입장 후 `{INTRO_MINUTES}분`이 지나도록 자기소개를 작성하지 않았습니다."
            )

    except Exception as e:
        print(f"[AUTO KICK ERROR] {e}")


# =========================================================
# 자기소개 시간 체크
# =========================================================

@tasks.loop(
    minutes=1
)
async def intro_check():

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:
        return

    current = now()

    for member in guild.members:

        if member.bot:
            continue

        # 제외 회원

        if member.id in intro_exceptions:
            continue

        data = member_data(
            member
        )

        if data.get(
            "intro_completed",
            False
        ):
            continue

        # 기존 회원 제외

        if data.get(
            "is_existing_member",
            True
        ):
            continue

        joined = parse_dt(
            data.get(
                "joined_at"
            )
        )

        if not joined:
            continue

        elapsed = (
            current - joined
        ).total_seconds()

        if elapsed < INTRO_MINUTES * 60:
            continue

        await auto_kick_no_intro(
            guild,
            member
        )


# =========================================================
# 멤버 입장
# =========================================================

@bot.event
async def on_member_join(
    member
):

    if member.guild.id != GUILD_ID:
        return

    if member.bot:
        return

    members[str(member.id)] = {

        "joined_at":
            iso(now()),

        "intro_completed":
            False,

        "birth_year":
            None,

        "gender":
            None,

        "last_activity":
            iso(now()),

        "is_existing_member":
            False,

        "kicked":
            False

    }

    # PostgreSQL 저장
    await save_member_to_db(
        member.id,
        members[str(member.id)]
    )

    await manage_role(
        member,
        ROLES["unverified"],
        True
    )

    print(
        f"[JOIN] {member}"
    )
