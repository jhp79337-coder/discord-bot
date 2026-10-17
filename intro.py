
# =========================================================
# 백구 봇 - 자기소개 기능
# 파일명: intro.py
# PostgreSQL / 역할 설정은 core.py 사용
# =========================================================

from core import *
import re
import discord
from datetime import datetime


# =========================================================
# 자기소개 입력 해석
# 지원 형식:
# 04 남 / 04남 / 2004 남 / 2004년생 남성
# 2004 여 / 07 ㄴ / 07ㅇ / 07여
# =========================================================

def parse_intro(text):
    if not text:
        return None

    text = text.strip()

    # 한글 자기소개 형식: 2004년생 남성, 2004년생 여성
    korean_match = re.search(
        r"(?<!\d)(19\d{2}|20\d{2})\s*년생\s*(남성|여성|남자|여자)",
        text
    )

    if korean_match:
        year = int(korean_match.group(1))
        gender_text_value = korean_match.group(2)
        gender = "남" if gender_text_value in ("남성", "남자") else "여"
        return validate_intro(year, gender)

    # 연도 + 성별: 2004 남, 2004여, 2004 남성
    full_match = re.search(
        r"(?<!\d)(19\d{2}|20\d{2})\s*(남성|여성|남자|여자|남|여|ㄴ|ㅇ)(?!\S)",
        text
    )

    if full_match:
        year = int(full_match.group(1))
        gender_value = full_match.group(2)
        gender = "남" if gender_value in ("남성", "남자", "남", "ㄴ") else "여"
        return validate_intro(year, gender)

    # 두 자리 연도 + 성별: 04 남, 04남, 07 여, 07ㅇ
    short_match = re.search(
        r"(?<!\d)(\d{2})\s*(남성|여성|남자|여자|남|여|ㄴ|ㅇ)(?!\S)",
        text
    )

    if not short_match:
        return None

    short_year = int(short_match.group(1))
    gender_value = short_match.group(2)

    current_year = datetime.now().year

    if short_year > current_year % 100:
        return None

    year = 2000 + short_year
    gender = "남" if gender_value in ("남성", "남자", "남", "ㄴ") else "여"

    return validate_intro(year, gender)


def validate_intro(year, gender):
    current_year = datetime.now().year

    if year < 1900 or year > current_year:
        return None

    return year, gender


# =========================================================
# 역할 적용
# =========================================================

async def apply_intro_roles(member, year, gender):
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

    print(
        f"[INTRO SUCCESS] {member} ({member.id}) | "
        f"{year}년생 | {gender}"
    )


# =========================================================
# 자기소개 메시지 감지
# =========================================================

@bot.listen("on_message")
async def intro_message_listener(message):
    if message.author.bot or message.guild is None:
        return

    # 모든 서버 메시지 감지 여부를 Console에서 확인
    print(
        f"[INTRO DEBUG] 메시지 감지 | "
        f"guild={message.guild.id} | "
        f"channel={message.channel.id} | "
        f"content={message.content!r}"
    )

    if message.guild.id != GUILD_ID:
        print(
            f"[INTRO DEBUG] 서버 ID 불일치: "
            f"{message.guild.id} != {GUILD_ID}"
        )
        return

    if message.channel.id != INTRO_CHANNEL_ID:
        return

    parsed = parse_intro(message.content)

    if parsed is None:
        if (
            re.search(r"\d{2,4}", message.content)
            and re.search(r"남|여|ㄴ|ㅇ|남성|여성|남자|여자", message.content)
        ):
            await message.channel.send(
                f"{message.author.mention} 자기소개 형식을 확인해 주세요!\n"
                "예시: `04 남`, `04남`, `2004 남`, `2004년생 남성`"
            )
        return

    year, gender = parsed

    try:
        await intro_complete(message, year, gender)

    except discord.Forbidden as error:
        print(f"[INTRO ERROR] Discord 권한 오류: {error}")

        await message.channel.send(
            f"{message.author.mention} 역할을 지급할 수 없어요.\n"
            "봇 역할 위치와 역할 관리 권한을 확인해 주세요."
        )

    except Exception as error:
        print(
            f"[INTRO ERROR] {type(error).__name__}: {error}"
        )

        try:
            await message.channel.send(
                f"{message.author.mention} 자기소개 처리 중 오류가 발생했어요. "
                "관리자에게 알려주세요."
            )
        except Exception:
            pass


# =========================================================
# 새 멤버 입장 처리
# =========================================================

@bot.listen("on_member_join")
async def intro_member_join_listener(member):
    if member.guild.id != GUILD_ID or member.bot:
        return

    try:
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

    except Exception as error:
        print(
            f"[JOIN ERROR] {type(error).__name__}: {error}"
        )
