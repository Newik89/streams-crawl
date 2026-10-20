# -*- coding: utf-8 -*-
r"""Словарь-автоучёба «ответила программа» (правило (д) починки
самопроверки №13, слово владельца 20.10.2026).

Владелец: пара, у которой одна сторона узнана ТВЁРДО, лига та же и время
то же, а вторая буквами не читается, либо ждала его в очереди неделями,
либо закреплялась молча — он не видел, что программа решила сама.

Что проверяем (`app/canon.py`):
  * `_firm_side_bridge` — одна сторона ≥ FIRM_SIDE, лига та же, кандидат
    такой в лиге один, не теннис, пол/возраст те же → «уверенная» пара с
    пометкой `канон_как`; без лиги, при двух кандидатах, в теннисе и при
    разной категории — молчит;
  * решения программы (мост по лиге, явный лидер) помечены, пары ≥ SURE —
    нет;
  * `apply`: слабая сторона пары с пометкой учится через очередь
    «Названия» ответом «ответила программа», твёрдая — молча; ответ
    владельца (done/skipped) главнее; открытая строка закрывается.

В сеть не ходит. База — пустая, во временной папке. Запуск:

    python scripts/test_avtoucheba.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="avtoucheba-test-"))
os.environ["STREAMS_DB"] = str(TMP / "test0.db")

from app import canon, db, dictionary, names  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def свежая_база():
    # своя база на сценарий: прошлую Windows держит открытой до конца
    свежая_база.n = getattr(свежая_база, "n", 0) + 1
    os.environ["STREAMS_DB"] = str(TMP / f"test{свежая_база.n}.db")
    conn = db.connect()
    db.init_db(conn)
    names.set_overrides({})
    return conn


ЛИГА = "NETHERLANDS: Eredivisie"
ВРЕМЯ = "2026-10-20T19:00"
ТВЁРДО = canon.HOW_FIRM
НЕЧИТАЕМО = "Kvxzq Plorb"          # вторая сторона, которую буквы не читают


def игра(home, away, league=ЛИГА, sport="F"):
    return {"home": home, "away": away, "league": league, "sport": sport,
            "start_kyiv": ВРЕМЯ}


def эталон(home, away, league=ЛИГА, sport="F", start=ВРЕМЯ):
    return {"home": home, "away": away, "league": league, "sport": sport,
            "start_kyiv": start, "fs_id": f"{home}-{away}"}


#: «Heracles» = эталон на 100; «Hercules» той же лиги в тот же час — 87:
#: старый мост (две «узнанные» стороны у двух кандидатов) не решал
HERACLES = эталон("Heracles", "Twente")
HERCULES = эталон("Hercules", "Volendam")


def где(aligned: dict, game: dict) -> str:
    for key in ("sure", "ask"):
        if any(g is game for g, _, _ in aligned[key]):
            return key
    return "missed" if any(g is game for g in aligned["missed"]) else "нигде"


def moderation(conn, raw):
    return conn.execute("SELECT status, answered_by, suggestion FROM moderation "
                        "WHERE kind = 'team' AND raw_value = ?",
                        (raw,)).fetchall()


def алиас(conn, raw):
    row = conn.execute("SELECT t.canonical_name FROM team_aliases a JOIN teams t "
                       "ON t.id = a.team_id WHERE a.alias = ?", (raw,)).fetchone()
    return row[0] if row else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    print("Правило (д): вторая сторона твёрдо, лига и время сошлись")
    g = игра("Heracles", НЕЧИТАЕМО)
    a = canon.align([g], [HERACLES, HERCULES], {})
    проверка("твёрдая сторона + та же лига + один кандидат → уверенная",
             где(a, g), "sure")
    проверка("взят кандидат с твёрдой стороной",
             a["sure"][0][1]["away"] if a["sure"] else None, "Twente")
    проверка("пометка «программа: вторая сторона твёрдо…»",
             g.get("канон_как"), ТВЁРДО)

    g = игра("Heracles", НЕЧИТАЕМО, league="")
    a = canon.align([g], [HERACLES, HERCULES], {})
    проверка("без лиги правило молчит (пара мимо, как раньше)",
             где(a, g), "missed")
    проверка("без лиги пометки нет", g.get("канон_как"), None)

    g = игра("Heracles", НЕЧИТАЕМО)
    второй = эталон("Heracles", "Volendam")
    a = canon.align([g], [HERACLES, второй], {})
    проверка("два кандидата лиги с твёрдой стороной — молчит",
             где(a, g) != "sure", True)
    проверка("два кандидата — и сама проверка правила молчит",
             canon._firm_side_bridge(g, [(HERACLES, None), (второй, None)], {}),
             None)

    g = игра("Sinner J.", НЕЧИТАЕМО, sport="T",
             league="ATP - SINGLES: Vienna (Austria), hard indoor")
    sinner = эталон("Sinner J.", "Zverev A.", sport="T",
                    league="ATP - SINGLES: Vienna (Austria), hard indoor")
    a = canon.align([g], [sinner], {})
    проверка("теннис — молчит", где(a, g) != "sure", True)
    проверка("теннис — и сама проверка правила молчит",
             canon._firm_side_bridge(g, [(sinner, None)], {}), None)

    g = игра("Heracles W", "Kvxzq Plorb W")
    a = canon.align([g], [HERACLES], {})
    проверка("женская игра против мужского кандидата — молчит",
             где(a, g) != "sure", True)
    проверка("разная категория — сама проверка правила молчит",
             canon._firm_side_bridge(g, [(HERACLES, None)], {}), None)

    g = игра("Heracles", НЕЧИТАЕМО, league="Эредивизи")
    a = canon.align([g], [HERACLES, HERCULES], {"Эредивизи": ЛИГА})
    проверка("лига сайта переведена словарём лиг — правило работает",
             (где(a, g), g.get("канон_как")), ("sure", ТВЁРДО))

    print("Пометки решений программы")
    g = игра("Heracles", НЕЧИТАЕМО)
    a = canon.align([g], [HERACLES], {})
    проверка("единственный кандидат лиги — «мост по лиге»",
             (где(a, g), g.get("канон_как")), ("sure", canon.HOW_BRIDGE))
    g = игра("Heracles", "Almere City", league="")
    a = canon.align([g], [эталон("Heracles", "Almelo", league="")], {})
    проверка("без лиги, одна сторона твёрдо, соперников нет — «явный лидер»",
             (где(a, g), g.get("канон_как")), ("sure", canon.HOW_LEADER))
    g = игра("Heracles", "Twente")
    g["канон_как"] = "старая пометка"
    a = canon.align([g], [HERACLES], {})
    проверка("пара ≥ SURE — решение букв, пометки нет (и старая снята)",
             (где(a, g), g.get("канон_как")), ("sure", None))

    print("apply: учёба «ответила программа»")
    conn = свежая_база()
    g = игра("Heracles", НЕЧИТАЕМО)
    canon.apply(conn, canon.align([g], [HERACLES, HERCULES], {}))
    строки = moderation(conn, НЕЧИТАЕМО)
    проверка("слабая сторона — строка очереди закрыта (done)",
             [r["status"] for r in строки], ["done"])
    проверка("ответ помечен «ответила программа: <причина>»",
             строки[0]["answered_by"] if строки else None,
             f"{dictionary.PROGRAM_MARK}: вторая сторона твёрдо, "
             "лига и время сошлись")
    проверка("алиас слабой стороны лёг в словарь",
             алиас(conn, НЕЧИТАЕМО), "Twente")
    проверка("твёрдая сторона учится молча — без строки в очереди",
             (moderation(conn, "Heracles"), алиас(conn, "Heracles")),
             ([], "Heracles"))
    видно = [r["raw_value"] for r in dictionary.auto_answered(conn, "team")]
    проверка("вкладка «Ответила программа» показывает запись",
             видно, [НЕЧИТАЕМО])
    canon.apply(conn, canon.align([игра("Heracles", НЕЧИТАЕМО)],
                                  [HERACLES, HERCULES], {}))
    проверка("повторная заливка не плодит строк",
             len(moderation(conn, НЕЧИТАЕМО)), 1)

    conn = свежая_база()
    conn.execute("INSERT INTO moderation (kind, raw_value, suggestion, status) "
                 "VALUES ('team', ?, 'Twente', 'skipped')", (НЕЧИТАЕМО,))
    conn.commit()
    canon.apply(conn, canon.align([игра("Heracles", НЕЧИТАЕМО)],
                                  [HERACLES, HERCULES], {}))
    проверка("владелец сказал «пропустить» — не учим",
             алиас(conn, НЕЧИТАЕМО), None)
    проверка("и его строку не трогаем",
             [(r["status"], r["answered_by"]) for r in
              moderation(conn, НЕЧИТАЕМО)], [("skipped", None)])

    conn = свежая_база()
    dictionary.enqueue(conn, "team", НЕЧИТАЕМО, suggestion="Twente")
    canon.apply(conn, canon.align([игра("Heracles", НЕЧИТАЕМО)],
                                  [HERACLES, HERCULES], {}))
    строки = moderation(conn, НЕЧИТАЕМО)
    проверка("открытая строка очереди закрыта программой (одна строка)",
             [(r["status"], (r["answered_by"] or "").startswith(
                 dictionary.PROGRAM_MARK)) for r in строки], [("done", True)])
    проверка("и алиас лёг в словарь", алиас(conn, НЕЧИТАЕМО), "Twente")

    conn = свежая_база()
    canon.apply(conn, canon.align([игра("Heracles", "Twente")], [HERACLES], {}))
    проверка("пара ≥ SURE — учится молча, очередь пуста",
             conn.execute("SELECT COUNT(*) FROM moderation").fetchone()[0], 0)
    проверка("пара ≥ SURE — алиасы на месте",
             (алиас(conn, "Heracles"), алиас(conn, "Twente")),
             ("Heracles", "Twente"))

    conn = свежая_база()
    g = игра("Heracles", "Almere City", league="")
    canon.apply(conn, canon.align([g], [эталон("Heracles", "Almelo",
                                                league="")], {}))
    проверка("явный лидер — слабая сторона тоже через очередь",
             [(r["status"], r["answered_by"]) for r in
              moderation(conn, "Almere City")],
             [("done", f"{dictionary.PROGRAM_MARK}: явный лидер")])

    conn = свежая_база()
    g = игра("Heracles", "EVERTON X WOLVES")
    canon.apply(conn, canon.align([g], [HERACLES], {}))
    проверка("`_learnable` обязателен: весь матч в имени — ни строки, "
             "ни алиаса", (moderation(conn, "EVERTON X WOLVES"),
                           алиас(conn, "EVERTON X WOLVES")), ([], None))

    всего = зелёных + красных
    print(f"\nпроверок: {всего}, зелёных: {зелёных}, красных: {красных}")
    return 1 if красных else 0


if __name__ == "__main__":
    sys.exit(main())
