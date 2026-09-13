# -*- coding: utf-8 -*-
r"""Режим отдельного источника: потолок глубины и «только по кнопке».

Решение владельца 10.09 по случаю `mojtv.hr`: сайт закрылся защитой после
того, как заходов к нему стало больше. Вместо того чтобы выключать источник,
даём ему щадящий режим:

* `--max-days 4` — «сегодня + 3». Общее окно обхода этот сайт не касается:
  нажата кнопка «6 дней» — он всё равно возьмёт четыре;
* `--manual-only` — в обходы по расписанию не идёт вовсе, ходит только когда
  обход заказан кнопкой на сайте или руками.

    venv\Scripts\python.exe scripts/source_mode.py mojtv.hr --show
    venv\Scripts\python.exe scripts/source_mode.py mojtv.hr --max-days 4 --manual-only --apply
    venv\Scripts\python.exe scripts/source_mode.py mojtv.hr --auto --apply   # вернуть как было

Значения лежат в `selector_config` источника; после правки пересобрать план
(`scripts/crawl_plan.py`), иначе обход поедет по старому файлу. Гонять на
ОБЕИХ базах — локальной и серверной.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("domain", help="домен источника, как в базе")
    ap.add_argument("--max-days", type=int, default=None,
                    help="не глубже стольких дней (0 — снять потолок)")
    ap.add_argument("--channel", default="",
                    help="потолок задать не сайту, а этому каналу")
    ap.add_argument("--manual-only", action="store_true",
                    help="в обходы по расписанию не брать")
    ap.add_argument("--by-server", action="store_true",
                    help="сайт качает сервер, а не GitHub")
    ap.add_argument("--auto", action="store_true",
                    help="вернуть в обычные обходы (снять обе пометки)")
    ap.add_argument("--show", action="store_true", help="только показать")
    ap.add_argument("--apply", action="store_true", help="без него — показ")
    args = ap.parse_args()

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, domain, selector_config FROM sources WHERE domain=?",
            (args.domain,)).fetchone()
        if row is None:
            print(f"источника {args.domain} в базе нет")
            return 1
        config = json.loads(row["selector_config"] or "{}") or {}
        было = {"max_days": config.get("max_days") or 0,
                "manual_only": bool(config.get("manual_only")),
                "by_server": bool(config.get("by_server"))}
        print(f"{row['domain']}: сейчас потолок "
              f"{было['max_days'] or 'нет'}, только по кнопке: "
              f"{'да' if было['manual_only'] else 'нет'}, качает сервер: "
              f"{'да' if было['by_server'] else 'нет'}")
        if args.show:
            return 0

        if args.channel:
            свои = dict(config.get("channel_days") or {})
            if args.max_days and args.max_days > 0:
                свои[args.channel] = args.max_days
            else:
                свои.pop(args.channel, None)
            config["channel_days"] = свои
            print(f"глубина канала «{args.channel}»: "
                  f"{свои.get(args.channel) or 'как у сайта'}")
            if not args.apply:
                print("чтобы сделать — добавьте --apply")
                return 0
            conn.execute("UPDATE sources SET selector_config=? WHERE id=?",
                         (json.dumps(config, ensure_ascii=False), row["id"]))
            conn.commit()
            print("готово; пересоберите план: scripts/crawl_plan.py")
            return 0
        if args.auto:
            config.pop("max_days", None)
            config.pop("manual_only", None)
            config.pop("by_server", None)
        else:
            if args.max_days is not None:
                if args.max_days > 0:
                    config["max_days"] = args.max_days
                else:
                    config.pop("max_days", None)
            if args.manual_only:
                config["manual_only"] = True
            if args.by_server:
                # GitHub такой сайт не пускает — качает сервер
                # (scripts/server_crawl.py, решение владельца 10.09)
                config["by_server"] = True
                config["manual_only"] = True
        стало = {"max_days": config.get("max_days") or 0,
                 "manual_only": bool(config.get("manual_only")),
                 "by_server": bool(config.get("by_server"))}
        if стало == было:
            print("менять нечего")
            return 0
        print(f"станет: потолок {стало['max_days'] or 'нет'}, "
              f"только по кнопке: {'да' if стало['manual_only'] else 'нет'}, "
              f"качает сервер: {'да' if стало['by_server'] else 'нет'}")
        if not args.apply:
            print("чтобы сделать — добавьте --apply")
            return 0
        conn.execute("UPDATE sources SET selector_config=? WHERE id=?",
                     (json.dumps(config, ensure_ascii=False), row["id"]))
        conn.commit()
        print("готово; теперь пересоберите план: scripts/crawl_plan.py")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
