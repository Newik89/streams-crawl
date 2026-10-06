# -*- coding: utf-8 -*-
r"""Ответить на вопросы очереди «Названия» по готовому списку.

Владелец 06.10: «нужно её по максимуму разобрать — переводчики, поиск в
интернете, чтобы не было незакрытых вопросов». Что правила программы не
решили сами (`app/sport_question.py`, `scripts/review_queue.py`), разбирается
вручную: перевод, поиск справки (Википедия, сайты лиг и клубов), эталон
flashscore. Итог — файл ответов (`data/queue_answers/<дата>.json`; папка
`data/` в git не едет — файл кладётся на сервер рядом с базой), а этот
скрипт пишет ответы ТЕМ ЖЕ путём, что кнопки админки:

* вид спорта «F»/«B»/«T» — `dictionary.resolve` (подсказка с днём матча);
* «не матч», «не команда», «не лига», «не канал» — `dictionary.skip`
  (вкладка «Отсеянные», кнопка «Вернуть в вопросы»);
* название команды, лиги — `dictionary.resolve`.

У каждого ответа пометка «ответила программа: разбор <дата> — <кратко>»
(`moderation.answered_by`, видно во вкладке «Ответила программа»).

Отвечает только на тот вопрос, что ждёт ответа (открыт или отложен) и чья
строка совпала с файлом ДОСЛОВНО: если правила уже закрыли его сами или
строка другая — пропуск с причиной. По умолчанию только показ.

    python scripts/answer_queue.py --file data/queue_answers/2026-10-06.json
    python scripts/answer_queue.py --file data/queue_answers/2026-10-06.json --apply

Порядок на сервере после выкладки: сперва уборка правилами
(`review_queue.py --kind team --apply`, `review_queue.py --apply`), потом
этот скрипт — ему останется только то, что правила не решили.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, dictionary  # noqa: E402

#: ответы «закрыть без ответа» → `dictionary.skip`
SKIP_WORDS = {"не матч", "не команда", "не лига", "не канал", "не название"}
#: ответ «вид спорта»
SPORT_LETTERS = {"F", "B", "T"}


def plan(conn, answers: list[dict]) -> list[tuple[dict, str]]:
    """Каждому ответу файла — что будет сделано: «skip», «resolve» или
    причина пропуска словами."""
    out = []
    for a in answers:
        row = conn.execute("SELECT * FROM moderation WHERE id = ?",
                           (a.get("id"),)).fetchone()
        answer = (a.get("ответ") or "").strip()
        if row is None:
            out.append((a, "пропуск: такого вопроса нет"))
        elif row["raw_value"] != a.get("строка"):
            out.append((a, "пропуск: строка вопроса не совпала с файлом"))
        elif row["status"] not in ("open", "later"):
            out.append((a, f"пропуск: уже закрыт ({row['status']}"
                           + (f", {row['answered_by']}" if row["answered_by"]
                              else "") + ")"))
        elif answer.lower() in SKIP_WORDS:
            out.append((a, "skip"))
        elif row["kind"] == "sport" and answer not in SPORT_LETTERS:
            out.append((a, f"пропуск: вид спорта «{answer}» — не F/B/T"))
        elif not answer:
            out.append((a, "пропуск: пустой ответ"))
        else:
            out.append((a, "resolve"))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="файл ответов (JSON)")
    ap.add_argument("--apply", action="store_true",
                    help="записать; без него — только показ")
    args = ap.parse_args()

    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    разбор = data.get("разбор") or Path(args.file).stem
    conn = db.connect()
    try:
        db.init_db(conn)                     # колонка answered_by
        шаги = plan(conn, data.get("ответы") or [])
        for a, шаг in шаги:
            print(f"#{a.get('id')} {str(a.get('строка'))[:60]} → "
                  f"{a.get('ответ')}: {шаг}")
        к_делу = [(a, шаг) for a, шаг in шаги if шаг in ("skip", "resolve")]
        print(f"\nответов в файле: {len(шаги)}; будет записано: {len(к_делу)}")
        if not args.apply:
            if к_делу:
                print("чтобы записать — добавьте --apply")
            return 0
        for a, шаг in к_делу:
            note = (f"{dictionary.PROGRAM_MARK}: разбор {разбор} — "
                    f"{a.get('кратко') or a.get('основание') or ''}")
            if шаг == "skip":
                dictionary.skip(conn, a["id"], answered_by=note)
            else:
                dictionary.resolve(conn, a["id"], a["ответ"].strip(),
                                   answered_by=note)
        print(f"записано: {len(к_делу)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
