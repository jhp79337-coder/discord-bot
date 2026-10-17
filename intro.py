# =========================================================
# 백구 봇 - 자기소개 기능
# 파일명: intro.py
# core.py의 PostgreSQL / 역할 설정을 사용합니다.
# =========================================================

from core import *


# =========================================================
# 자기소개 입력 해석
# 허용 예시: 07 남 / 07남 / 2007 여 / 2007여 / 07 ㄴ / 07ㅇ
# =========================================================

def parse_intro(text):
    text = (text or "").strip()

    match = re.search(r"(?<!\d)(19\d{2}|20\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)", text)
    if match:
        year = int(match.group(1))
        gender = match.group(2)
    else:
        match = re.search(r"(?<!\d)(\d{2})\s*(남|여|ㄴ|ㅇ)(?!\S)", text)
        if not match:
            return None

        short_year = int(match.group(1))
        gender = match.group(2)
        current_year = datetime.now().year
        if short_year > current_year % 100:
            return None
        year = 2000 + short_year

    current_year = datetime.now().year
    if year < 1900 or year > current_year:
        return None

    gender = "남" if gender in ("남", "ㄴ") else "여"
    return year, gender


# =========================================================
# 역할 적용
# =========================================================

async def apply_intro_roles(member, year, gender):
    # 자기소개 전 역할과 성별/나이 역할을 정리합니다.
    for key in ("unverified", "male", "female", "adult", "minor"):
        role_id = ROLES.get(key)
        if role_id:
            await manage_role(member, role_id, False)

    gender_key = "male" if gender == "남" else "female"
    age_key = "adult" if age_type(year) == "성인" else "minor"

    for key in (gender_key, age_key, "intro_complete"):
        role_id = ROLES.get(key)
        if role_id:
            await manage_role(member, role_id, True)


# =========================================================
# 자기소개 저장 및 완료 안내
# =========================================================

async def intro_complete(message, year, gender):
    member = message.author
    data = member_data(member)
    data.update({
        "intro_completed": True,
        "intro": True,
        "birth_year": year,
        "gender": gender,
        "intro_completed_at": iso(now()),
        "kicked": False,
    })

    members[str(member.id)] = data
    await save_member_to_db(member.id, data)

    await apply_intro_roles(member, year, gender)

    await message.channel.send(
        f"🖤 {member.mention} 자기소개 정보를 반영했어요 ♡\n\n"
        f"`{year}년생` · `{gender_text(gender)}` · `{age_type(year)}`\n\n"
        f"🎀 <#{ROLE_CHANNEL_ID}> 에서 역할을 골라주세요.\n"
        f"💬 <#{MAIN_CHAT_ID}> 에서 편하게 놀아요!"
    )


# =========================================================
# 자기소개 채널 메시지 감지
# @bot.listen을 사용해 다른 모듈의 이벤트를 덮어쓰지 않습니다.
# =========================================================

@bot.listen("on_message")
async def intro_message_listener(message):
    if message.author.bot or message.guild is None:
        return
    if message.guild.id != GUILD_ID:
        return
    if message.channel.id != INTRO_CHANNEL_ID:
        return

    parsed = parse_intro(message.content)
    if parsed is None:
        # 빈 메시지나 대화 메시지는 무시하고, 숫자/성별 입력 시도만 안내합니다.
        if re.search(r"\d{2,4}", message.content) and re.search(r"남|여|ㄴ|ㅇ", message.content):
            await message.channel.send(
                f"{message.author.mention} 자기소개 형식을 확인해 주세요!\n"
                "예시: `07 남`, `07여`, `2007 남`, `2007 여`"
            )
        return

    year, gender = parsed
    try:
        await intro_complete(message, year, gender)
    except discord.Forbidden:
        await message.channel.send(
            f"{message.author.mention} 역할을 지급할 수 없어요. "
            "봇 역할의 위치와 역할 관리 권한을 확인해 주세요."
        )
        print(f"[INTRO ERROR] 역할 권한 부족: {message.author} ({message.author.id})")
    except Exception as error:
        print(f"[INTRO ERROR] {type(error).__name__}: {error}")
        await message.channel.send(
            f"{message.author.mention} 자기소개 처리 중 오류가 발생했어요. 관리자에게 알려주세요."
        )


# =========================================================
# 새 멤버 입장 처리
# =========================================================

@bot.listen("on_member_join")
async def intro_member_join_listener(member):
    if member.guild.id != GUILD_ID or member.bot:
        return

    data = member_data(member)
    data.update({
        "joined_at": iso(now()),
        "intro_completed": False,
        "intro": False,
        "birth_year": None,
        "gender": None,
        "last_activity": iso(now()),
        "is_existing_member": False,
        "kicked": False,
    })
    members[str(member.id)] = data
    await save_member_to_db(member.id, data)

    unverified_role_id = ROLES.get("unverified")
    if unverified_role_id:
        await manage_role(member, unverified_role_id, True)

    print(f"[JOIN] 자기소개 대기: {member} ({member.id})")
