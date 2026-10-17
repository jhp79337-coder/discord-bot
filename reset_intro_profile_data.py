
# =========================================================
# 백구 봇 - 자기소개 / 프로필 데이터 초기화
# 파일명: reset_intro_profile_data.py
#
# PostgreSQL:
#   - profiles 테이블의 프로필 데이터 삭제
#   - members 테이블에서 자기소개 관련 항목만 삭제
#
# 로컬 JSON:
#   - profiles.json 초기화
#   - members.json에서 자기소개 관련 항목만 삭제
#
# 다른 기능의 데이터는 삭제하지 않습니다.
# =========================================================

import os
import json
import asyncio
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 자기소개 전용으로 판단되는 키만 제거합니다.
INTRO_KEYS = [
    "intro_completed",
    "intro",
    "birth_year",
    "gender",
    "intro_completed_at",
]

# 프로젝트 파일과 같은 폴더의 백업 디렉터리
BACKUP_ROOT = "reset_backups"


def read_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    temporary = path + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    os.replace(temporary, path)


def backup_json(path, backup_dir):
    if not os.path.exists(path):
        print(f"[백업] 파일 없음: {path}")
        return False

    data = read_json(path, None)
    backup_path = os.path.join(
        backup_dir,
        os.path.basename(path),
    )

    with open(backup_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"[백업 완료] {path} -> {backup_path}")
    return True


def remove_intro_keys(data):
    """회원 데이터에서 자기소개 전용 키만 제거합니다."""
    if not isinstance(data, dict):
        return data

    result = dict(data)

    for key in INTRO_KEYS:
        result.pop(key, None)

    return result


async def main():
    print("=" * 55)
    print("백구 봇 자기소개 / 프로필 데이터 초기화")
    print("=" * 55)

    if not DATABASE_URL:
        print("[중단] DATABASE_URL 환경변수가 없습니다.")
        print(".env 파일 또는 실행 환경변수를 확인하세요.")
        return

    # 백업 폴더 준비
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BACKUP_ROOT, timestamp)
    os.makedirs(backup_dir, exist_ok=False)

    pool = None

    try:
        # -------------------------------------------------
        # 1. PostgreSQL 연결 및 테이블 확인
        # -------------------------------------------------
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=2,
        )

        async with pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('members', 'profiles')
            """)

            existing_tables = {
                row["table_name"] for row in tables
            }

            if not {"members", "profiles"}.issubset(existing_tables):
                print("[중단] members 또는 profiles 테이블이 없습니다.")
                print("DB 구조를 확인한 후 실행해야 합니다.")
                return

            for table in ("members", "profiles"):
                columns = await conn.fetch("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = $1
                """, table)

                column_types = {
                    row["column_name"]: row["data_type"]
                    for row in columns
                }

                if (
                    column_types.get("user_id") != "text"
                    or column_types.get("data") != "jsonb"
                ):
                    print(
                        f"[중단] {table} 테이블 구조가 예상과 다릅니다."
                    )
                    print(column_types)
                    print("데이터를 변경하지 않았습니다.")
                    return

            # -------------------------------------------------
            # 2. DB 데이터 백업
            # -------------------------------------------------
            async with conn.transaction(readonly=True):
                for table in ("members", "profiles"):
                    rows = await conn.fetch(
                        f"SELECT user_id, data FROM {table}"
                    )

                    backup_path = os.path.join(
                        backup_dir,
                        f"postgres_{table}.json",
                    )

                    records = [
                        {
                            "user_id": row["user_id"],
                            "data": row["data"],
                        }
                        for row in rows
                    ]

                    with open(
                        backup_path,
                        "w",
                        encoding="utf-8",
                    ) as file:
                        json.dump(
                            records,
                            file,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )

                    print(
                        f"[DB 백업 완료] {table}: {len(records)}개"
                    )

            # -------------------------------------------------
            # 3. 로컬 JSON 파일 백업
            # -------------------------------------------------
            backup_json("members.json", backup_dir)
            backup_json("profiles.json", backup_dir)

            # 백업 파일 확인
            required_backups = [
                "postgres_members.json",
                "postgres_profiles.json",
            ]

            for filename in required_backups:
                path = os.path.join(backup_dir, filename)

                if not os.path.isfile(path):
                    print("[중단] PostgreSQL 백업이 없습니다.")
                    return

                with open(path, "r", encoding="utf-8") as file:
                    json.load(file)

            print()
            print("백업이 완료되었습니다.")
            print(f"백업 위치: {os.path.abspath(backup_dir)}")
            print()
            print("실제 삭제 대상:")
            print("- PostgreSQL profiles 테이블의 모든 행")
            print("- PostgreSQL members의 자기소개 전용 JSON 키")
            print("- 로컬 profiles.json의 프로필 데이터")
            print("- 로컬 members.json의 자기소개 전용 JSON 키")
            print()
            print("경매, 연애, 경험치, 경고 데이터는 대상으로 삼지 않습니다.")
            print()

            confirmation = input(
                "계속하려면 DELETE_PROFILE_INTRO_DATA 를 정확히 입력하세요: "
            ).strip()

            if confirmation != "DELETE_PROFILE_INTRO_DATA":
                print("[취소] 데이터를 변경하지 않았습니다.")
                return

            # -------------------------------------------------
            # 4. PostgreSQL 변경
            # -------------------------------------------------
            async with conn.transaction():
                # 프로필 테이블은 프로필 데이터만 보관하는 구조인지
                # 사전에 확인한 뒤 해당 테이블 행만 삭제합니다.
                profile_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM profiles"
                )

                await conn.execute("DELETE FROM profiles")

                # 회원 전체 행을 지우지 않고 지정한 키만 제거합니다.
                member_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM members"
                )

                await conn.execute("""
                    UPDATE members
                    SET data = data - $1::text[]
                """, INTRO_KEYS)

                # 변경 결과 확인
                remaining_profiles = await conn.fetchval(
                    "SELECT COUNT(*) FROM profiles"
                )

                if remaining_profiles != 0:
                    raise RuntimeError(
                        "프로필 테이블 초기화 확인에 실패했습니다."
                    )

                print(
                    f"[DB 완료] 프로필 {profile_count}개 삭제"
                )
                print(
                    f"[DB 완료] 회원 {member_count}명의 "
                    "자기소개 전용 키 초기화"
                )

            # -------------------------------------------------
            # 5. 로컬 JSON 파일 변경
            # -------------------------------------------------
            if os.path.exists("members.json"):
                local_members = read_json("members.json", {})

                if not isinstance(local_members, dict):
                    raise RuntimeError(
                        "members.json 구조가 예상과 다릅니다."
                    )

                cleaned_members = {
                    user_id: remove_intro_keys(data)
                    for user_id, data in local_members.items()
                }

                write_json("members.json", cleaned_members)
                print("[파일 완료] members.json 자기소개 정보 초기화")

            if os.path.exists("profiles.json"):
                local_profiles = read_json("profiles.json", {})

                # 프로필 파일 전체를 빈 객체로 초기화합니다.
                if isinstance(local_profiles, (dict, list)):
                    write_json("profiles.json", {})
                    print("[파일 완료] profiles.json 프로필 초기화")
                else:
                    raise RuntimeError(
                        "profiles.json 구조가 예상과 다릅니다."
                    )

            print()
            print("=" * 55)
            print("초기화 작업이 끝났습니다.")
            print(f"백업 위치: {os.path.abspath(backup_dir)}")
            print("=" * 55)

    except Exception as error:
        print()
        print(f"[오류] {type(error).__name__}: {error}")
        print("백업 폴더를 보존하고 데이터 상태를 확인하세요.")
        print(
            "PostgreSQL 변경은 트랜잭션으로 처리되지만, "
            "로컬 파일 변경은 별도로 확인해야 합니다."
        )

    finally:
        if pool is not None:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
