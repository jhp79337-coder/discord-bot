from core import *

# =========================================================
# 자기소개 파싱
#
# 1900~1999
# -> 1900 남
# -> 1999 여
#
# 2000년대
# -> 00 남
# -> 04 ㅇ
# -> 04 ㄴ
# -> 04 여
#
# 2012년생부터 추방
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

        year = int(
            raw_year
        )

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

        short_year = int(
            raw_year
        )

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
    # 연령 제한
    # -----------------------------------------------------

    if year >= MIN_ALLOWED_BIRTH_YEAR:

        try:

            log = get_log_channel(
                message.guild
            )

            if log:

                await log.send(

                    f"🚫 **연령 제한 추방**\n"
                    f"대상: {member.mention}\n"
                    f"출생년도: `{year}`\n"
                    f"사유: `2012년생부터 이용 제한`"

                )

            await member.kick(

                reason=
                "연령 제한"

            )

            data = member_data(
                member
            )

            data["kicked"] = True

            save_json(

                FILES["members"],

                members

            )

            return

        except Exception as e:

            print(
                f"[AGE KICK ERROR] {e}"
            )

            return


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

    save_json(

        FILES["members"],

        members

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
# 추방 확인 버튼
# =========================================================

class KickView(
    discord.ui.View
):

    def __init__(
        self,
        member
    ):

        super().__init__(
            timeout=300
        )

        self.member = member


    async def on_timeout(
        self
    ):

        pending_kicks.discard(
            self.member.id
        )


    @discord.ui.button(

        label="예, 추방하기",

        style=
        discord.ButtonStyle.danger

    )
    async def confirm(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

    ):

        if not interaction.user.guild_permissions.administrator:

            await interaction.response.send_message(

                "❌ 관리자만 사용할 수 있습니다.",

                ephemeral=True

            )

            return


        member = interaction.guild.get_member(

            self.member.id

        )


        if not member:

            await interaction.response.edit_message(

                content=
                "❌ 회원을 찾을 수 없습니다.",

                view=None

            )

            return


        data = member_data(
            member
        )


        if data.get(

            "intro_completed",

            False

        ):

            pending_kicks.discard(
                member.id
            )

            await interaction.response.edit_message(

                content=
                f"✅ {member.mention}님은 "
                f"이미 자기소개를 완료했습니다.",

                view=None

            )

            return


        try:

            await member.kick(

                reason=
                "자기소개 미작성"

            )

            data["kicked"] = True

            save_json(

                FILES["members"],

                members

            )

            pending_kicks.discard(
                member.id
            )

            await interaction.response.edit_message(

                content=
                f"🚪 {member.mention}님을 "
                f"자기소개 미작성으로 추방했습니다.",

                view=None

            )

        except Exception as e:

            print(
                f"[KICK ERROR] {e}"
            )

            await interaction.response.send_message(

                "❌ 추방 처리 실패",

                ephemeral=True

            )


    @discord.ui.button(

        label="취소",

        style=
        discord.ButtonStyle.secondary

    )
    async def cancel(

        self,

        interaction:
        discord.Interaction,

        button:
        discord.ui.Button

    ):

        if not interaction.user.guild_permissions.administrator:

            await interaction.response.send_message(

                "❌ 관리자만 사용할 수 있습니다.",

                ephemeral=True

            )

            return


        pending_kicks.discard(
            self.member.id
        )

        await interaction.response.edit_message(

            content=
            f"❎ {self.member.mention}님의 "
            f"추방 처리를 취소했습니다.",

            view=None

        )


# =========================================================
# 추방 확인
# =========================================================

async def send_kick_review(
    guild,
    member
):

    # 자기소개 제외 회원

    if member.id in intro_exceptions:

        return


    # 이미 대기 중

    if member.id in pending_kicks:

        return


    data = member_data(
        member
    )


    if data.get(
        "intro_completed",
        False
    ):

        return


    log = get_log_channel(
        guild
    )


    if not log:

        return


    pending_kicks.add(
        member.id
    )


    try:

        await log.send(

            f"⚠️ **자기소개 미작성 확인**\n\n"

            f"회원: {member.mention}\n"

            f"입장 후 "
            f"`{INTRO_MINUTES}분` 경과\n\n"

            f"추방 여부를 선택해주세요.",

            view=KickView(member)

        )

    except Exception as e:

        pending_kicks.discard(
            member.id
        )

        print(
            f"[KICK REVIEW ERROR] {e}"
        )


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


        await send_kick_review(

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


    save_json(

        FILES["members"],

        members

    )


    await manage_role(

        member,

        ROLES["unverified"],

        True

    )


    print(
        f"[JOIN] {member}"
    )


