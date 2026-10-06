from core import *

import io
import json


BACKUP_KEEP_COUNT = 20
BACKUP_INTERVAL_HOURS = 6


async def ensure_backup_table():
    if db_pool is None:
        return False

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_backups (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reason TEXT NOT NULL,
                data JSONB NOT NULL
            )
            """
        )
    return True


async def build_backup():
    if db_pool is None:
        raise RuntimeError("PostgreSQL 연결이 없습니다.")

    async with db_pool.acquire() as conn:
        member_rows = await conn.fetch(
            "SELECT user_id, data FROM members"
        )
        profile_rows = await conn.fetch(
            "SELECT user_id, data FROM profiles"
        )
        exp_rows = await conn.fetch(
            "SELECT user_id, exp FROM experience"
        )

    return {
        "backup_version": 1,
        "created_at": iso(now()),
        "members": {
            str(row["user_id"]): row["data"]
            for row in member_rows
        },
        "profiles": {
            str(row["user_id"]): row["data"]
            for row in profile_rows
        },
        "experience": {
            str(row["user_id"]): int(row["exp"])
            for row in exp_rows
        },
        "warnings": warnings,
        "intro_exceptions": sorted(int(x) for x in intro_exceptions),
        "dating": {
            "queue": dating_queue,
            "sessions": dating_sessions
        }
    }


async def save_backup(reason="manual"):
    await ensure_backup_table()
    data = await build_backup()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_backups (reason, data)
            VALUES ($1, $2::jsonb)
            """,
            reason,
            json.dumps(data, ensure_ascii=False)
        )
        await conn.execute(
            """
            DELETE FROM bot_backups
            WHERE id NOT IN (
                SELECT id FROM bot_backups
                ORDER BY id DESC
                LIMIT $1
            )
            """,
            BACKUP_KEEP_COUNT
        )

    return data


async def load_runtime_state_from_db():
    """JSON으로만 남아 있던 상태를 PostgreSQL 스냅샷에서 복원한다."""
    global warnings, intro_exceptions, dating_queue, dating_sessions

    if db_pool is None:
        return

    await ensure_backup_table()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data FROM bot_backups ORDER BY id DESC LIMIT 1"
        )

    if not row:
        return

    data = row["data"]

    if isinstance(data, str):
        data = json.loads(data)

    if isinstance(data.get("warnings"), dict):
        warnings = data["warnings"]

    exceptions = data.get("intro_exceptions", [])
    intro_exceptions = set()
    for value in exceptions:
        try:
            intro_exceptions.add(int(value))
        except (TypeError, ValueError):
            pass

    # 소개팅 대기열은 최신 DB 스냅샷으로 무조건 덮어쓰지 않는다.
    # 오래된 백업 때문에 현재 대기자가 사라지는 문제를 방지한다.
    dating = data.get("dating", {})

    if not dating_queue:
        restored_queue = []
        for value in dating.get("queue", []):
            try:
                restored_queue.append(int(value))
            except (TypeError, ValueError):
                pass
        dating_queue = restored_queue

    # 진행 중인 세션도 현재 메모리에 이미 있으면 유지한다.
    if not dating_sessions:
        restored_sessions = dating.get("sessions", {})
        dating_sessions = (
            restored_sessions
            if isinstance(restored_sessions, dict)
            else {}
        )

    print("[DB] 경고/소개팅/예외 데이터 스냅샷 복원 완료")


async def persist_runtime_state():
    """경고/소개팅/예외처럼 기존 JSON으로 저장되던 상태를 DB에 저장한다."""
    if db_pool is None:
        return

    await ensure_backup_table()
    data = await build_backup()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_backups (reason, data)
            VALUES ($1, $2::jsonb)
            """,
            "state-sync",
            json.dumps(data, ensure_ascii=False)
        )
        await conn.execute(
            """
            DELETE FROM bot_backups
            WHERE id NOT IN (
                SELECT id FROM bot_backups
                ORDER BY id DESC
                LIMIT $1
            )
            """,
            BACKUP_KEEP_COUNT
        )


async def restore_backup(data):
    if db_pool is None:
        raise RuntimeError("PostgreSQL 연결이 없습니다.")

    required = {"members", "profiles", "experience", "warnings", "dating"}
    if not required.issubset(data):
        raise ValueError("올바른 봇 백업 파일이 아닙니다.")

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM members")
            await conn.execute("DELETE FROM profiles")
            await conn.execute("DELETE FROM experience")

            for user_id, value in data["members"].items():
                await conn.execute(
                    """
                    INSERT INTO members (user_id, data)
                    VALUES ($1, $2::jsonb)
                    """,
                    str(user_id),
                    json.dumps(value, ensure_ascii=False)
                )

            for user_id, value in data["profiles"].items():
                await conn.execute(
                    """
                    INSERT INTO profiles (user_id, data)
                    VALUES ($1, $2::jsonb)
                    """,
                    str(user_id),
                    json.dumps(value, ensure_ascii=False)
                )

            for user_id, value in data["experience"].items():
                await conn.execute(
                    """
                    INSERT INTO experience (user_id, exp)
                    VALUES ($1, $2)
                    """,
                    str(user_id),
                    int(value)
                )

    global members, profiles, warnings, intro_exceptions, dating_queue, dating_sessions

    members = {
        str(k): v for k, v in data["members"].items()
    }
    profiles = {
        str(k): v for k, v in data["profiles"].items()
    }
    warnings = data.get("warnings", {})

    intro_exceptions = set()
    for value in data.get("intro_exceptions", []):
        try:
            intro_exceptions.add(int(value))
        except (TypeError, ValueError):
            pass

    dating = data.get("dating", {})
    dating_queue = []
    for value in dating.get("queue", []):
        try:
            dating_queue.append(int(value))
        except (TypeError, ValueError):
            pass

    dating_sessions = dating.get("sessions", {})
    if not isinstance(dating_sessions, dict):
        dating_sessions = {}

    save_json(FILES["members"], members)
    save_json(FILES["profiles"], profiles)
    save_json(FILES["warnings"], warnings)
    save_json(
        FILES["exceptions"],
        sorted(int(x) for x in intro_exceptions)
    )
    save_json(
        FILES["dating"],
        {
            "queue": dating_queue,
            "sessions": dating_sessions
        }
    )


@bot.command(name="백업")
@commands.has_permissions(administrator=True)
async def backup_command(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    try:
        data = await save_backup("manual")
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = discord.File(io.BytesIO(payload), filename="discord_bot_backup.json")
        await ctx.send(
            "✅ 전체 백업을 완료했습니다.\n"
            "회원 / 프로필 / EXP / 경고 / 소개팅 / 자기소개 예외 데이터를 포함했습니다.",
            file=file
        )
    except Exception as e:
        await ctx.send(f"❌ 백업 실패: `{e}`")


@bot.command(name="복구")
@commands.has_permissions(administrator=True)
async def restore_command(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    if not ctx.message.attachments:
        await ctx.send(
            "❌ 백업 JSON 파일을 이 메시지에 첨부해서 `!복구`를 사용해주세요."
        )
        return

    attachment = ctx.message.attachments[0]

    if not attachment.filename.lower().endswith(".json"):
        await ctx.send("❌ JSON 백업 파일만 복구할 수 있습니다.")
        return

    try:
        raw = await attachment.read()
        data = json.loads(raw.decode("utf-8"))
        await restore_backup(data)
        await ctx.send("✅ 백업 데이터 복구가 완료되었습니다.")
    except Exception as e:
        await ctx.send(f"❌ 복구 실패: `{e}`")


@bot.command(name="백업목록")
@commands.has_permissions(administrator=True)
async def backup_list_command(ctx):
    if not ctx.guild or ctx.guild.id != GUILD_ID:
        return

    if db_pool is None:
        await ctx.send("❌ PostgreSQL 연결이 없습니다.")
        return

    await ensure_backup_table()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, created_at, reason
            FROM bot_backups
            ORDER BY id DESC
            LIMIT 10
            """
        )

    if not rows:
        await ctx.send("📦 저장된 백업이 없습니다.")
        return

    lines = ["📦 **최근 백업 10개**"]
    for row in rows:
        created = row["created_at"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"`#{row['id']}` · {created} · `{row['reason']}`")

    await ctx.send("\n".join(lines))


@tasks.loop(hours=BACKUP_INTERVAL_HOURS)
async def automatic_backup_loop():
    try:
        await save_backup("automatic")
        print("[BACKUP] 자동 백업 완료")
    except Exception as e:
        print(f"[BACKUP ERROR] {e}")


@automatic_backup_loop.before_loop
async def before_automatic_backup_loop():
    await bot.wait_until_ready()


def start_backup_loop():
    if not automatic_backup_loop.is_running():
        automatic_backup_loop.start()
