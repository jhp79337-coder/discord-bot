from core import *


# =========================================================
# 자기소개 파싱
# =========================================================

def parse_intro(text):
    text = text.strip()

    # 4자리 연도
    match = re.search(
        r"(?<!\d)(19\d{2}|20\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)",
        text
    )

    if match:
        year = int(match.group(1))
        gender = match.group(2)

    else:
        # 2자리 연도
        match = re.search(
            r"(?<!\d)(\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)",
            text
        )

        if not match:
            return None

        short_year = int(match.group(1))
        gender = match.group(2)

        current_year = datetime.now().year
        current_short = current_year % 100

        if short_year > current_short:
            return None

        year = 2000 + short_year

    # 연도 검증
    current_year = datetime.now().year

    if year < 1900 or year > current_year:
        return None

    # 성별 정리
    if gender in ("남", "ㄴ"):
        gender = "남"
    else:
        gender = "여"

    return year, gender


# =========================================================
# 자기소개 역할 적용
# =========================================================

async def apply_intro_roles(member, year, gender):

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

    # 성별 역할
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

    # 나이 역할
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

    # 자기소개 완료
    await manage_role(
        member,
        ROLES["intro_complete"],
        True
    )


# =========================================================
# 자기소개 완료
# =========================================================

async def intro_complete(message, year, gender):

    member = message.author

    data = member_data(member)

    data.update({
        "intro_completed": True,
        "birth_year": year,
        "gender": gender,
        "intro_completed_at": iso(now()),
        "kicked": False
    })

    # PostgreSQL 저장
    await save_member_to_db(
        member.id,
        data
    )

    # 역할 적용
    await apply_intro_roles(
        member,
        year,
        gender
    )

    # 안내
    await message.channel.send(
        f"🖤 {member.mention} 자기소개 정보를 반영했어요 ♡\n\n"
        f"`{year}년생` · "
        f"`{gender_text(gender)}` · "
        f"`{age_type(year)}`\n\n"
        f"🎀 <#{ROLE_CHANNEL_ID}> 에서 역할을 골라주세요.\n"
        f"💬 <#{MAIN_CHAT_ID}> 에서 편하게 놀아요!"
    )


# =========================================================
# 멤버 입장
# =========================================================

@bot.event
async def on_member_join(member):

    if member.guild.id != GUILD_ID:
        return

    if member.bot:
        return

    members[str(member.id)] = {
        "joined_at": iso(now()),
        "intro_completed": False,
        "birth_year": None,
        "gender": None,
        "last_activity": iso(now()),
        "is_existing_member": False,
        "kicked": False
    }

    # PostgreSQL 저장
    await save_member_to_db(
        member.id,
        members[str(member.id)]
    )

    # 미인증 역할
    await manage_role(
        member,
        ROLES["unverified"],
        True
    )

    print(f"[JOIN] {member}")
