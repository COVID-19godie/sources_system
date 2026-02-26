from __future__ import annotations

import argparse

from app import models
from app.core.db_read_write import WriteSessionLocal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Purge chapter_aliases rows")
    parser.add_argument("--stage", default="senior", help="stage filter")
    parser.add_argument("--subject", default="物理", help="subject filter")
    parser.add_argument("--all", action="store_true", help="purge all aliases without stage/subject filter")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = WriteSessionLocal()
    try:
        query = db.query(models.ChapterAlias)
        if not args.all:
            query = query.filter(
                models.ChapterAlias.stage == args.stage,
                models.ChapterAlias.subject == args.subject,
            )
        count = query.count()
        deleted = query.delete(synchronize_session=False)
        db.commit()
        print(
            f"purge chapter_aliases done: deleted={deleted}, requested_count={count}, "
            f"scope={'all' if args.all else f'{args.stage}/{args.subject}'}"
        )
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
