# -*- coding: utf-8 -*-
r"""Книга 155 (16.11.2026): парный теннисный матч на греческом шёл отдельной строкой.

cosmotetv.gr 16.11 19:00: «Κρίστιαν Χάρισον / Νιλ Σκούπσκι — Κέβιν Κράβιτς/Τιµ
Πιουτς» не сошёлся с эталонным «Harrison C./Skupski N. — Krawietz K./Puetz T.»
(греческое у эталона — «Χάρισον Κ./Σκάπσκι Ν.»). Причин две, обе общие:
  П1. транслит читал «ού» (то же «ου» под ударением) как «oy»: «Σκούπσκι» —
      «SKOYPSKI» вместо «SKUPSKI» (`translit._GREEK_PAIRS`);
  П2. инициал «C.» английского «Christian» не равнялся слову «KRISTIAN»
      (`names._initial_pair`: «C» и «K» — одна буква).
Заодно закрыты две дыры, которые эти правки открыли бы шире:
  П3. один инициал закрывает одно слово (`names._own_initial_each`): «Carlos
      Cabal/Andrey Rublev» сходилась с «Cerundolo C./Rublev A.» на 100;
  П4. имя греческими буквами — страна только по её греческому написанию
      (`names._greek_stranger`, правило Т9 справочника): «Κολούμπια»
      (университет) читается «KOLUMBIA» — так Колумбию пишут поляки.
В сеть не ходит. Запуск: python scripts/test_grecheskaya_tennisnaya_para.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import canon, names, translit  # noqa: E402

зелёных = красных = 0


def проверка(имя: str, вышло, ждём=True) -> None:
    global зелёных, красных
    if вышло == ждём:
        зелёных += 1
        print(f"  ✔ {имя}")
    else:
        красных += 1
        print(f"  ✘ {имя}: вышло {вышло!r}, ждём {ждём!r}")


def матч(home, away, start, **местные):
    return {"sport": "T", "home": home, "away": away, "start_kyiv": start, "fs_id": home[:4] + away[:4],
            "league": "ATP - DOUBLES: Finals - Turin (World), hard (indoor)", "names": местные}


def игра(home, away, start):
    return {"sport": "T", "home": home, "away": away, "start_kyiv": start, "league": "",
            "entries": [{"source": "cosmotetv.gr"}]}


def сверка(game, эталон):
    """→ (вердикт, пара эталона, как решено)."""
    out = canon.align([game], эталон)
    for verdict in ("sure", "ask"):
        for g, ref, _score in out[verdict]:
            return verdict, f"{ref['home']} - {ref['away']}", g.get("канон_как") or ""
    return "missed", "", ""


print("П1. Греческое «ού» — тот же звук «u», что и «ου» без ударения")
проверка("«Σκούπσκι» → Skupski, «Λούτον» → Luton, «Ρούμπλεφ» → Rumblef; без ударения — как раньше",
         [translit.to_english(x) for x in ("Σκούπσκι", "Λούτον", "Ρούμπλεφ", "Ντόρτμουντ", "Πιουτς", "ΛΟΥΤΟΝ")],
         ["Skupski", "Luton", "Rumblef", "Dortmund", "Piuts", "LUTON"])
проверка("ударение на ПЕРВОЙ букве сочетания его разрывает, прочие сочетания не тронуты: «Κρουζέιρο», «Φεραίος»",
         [translit.to_english(x) for x in ("Κρουζέιρο", "Φεραίος", "Νεϊμάρ")], ["Kruzeiro", "Feraios", "Neimar"])
проверка("страна заглавными без ударений и строчными с ударением читается одинаково",
         (names.country_of("ΛΟΥΞΕΜΒΟΥΡΓΟ"), names.country_of("Λουξεμβούργο"), names.country_of("Μαυροβούνιο")),
         ("LUXEMBOURG", "LUXEMBOURG", "MONTENEGRO"))

print("П2. Инициалы «C» и «K» — одна буква")
проверка("«C.» закрывает «KRISTIAN» и «KARLOS», «K.» — «CARLOS»; «K.» не закрывает «CHARISON», «Q.» — «CONNAH»",
         [names._initial_pair(a, b) for a, b in (("C", "KRISTIAN"), ("KARLOS", "C"), ("K", "CARLOS"),
                                                 ("K", "CHARISON"), ("Q", "CONNAH"), ("V", "WIKTOR"))],
         [True, True, True, False, False, False])
проверка("греческая пара с полными именами сходится с эталоном: и с английским, и с греческим написанием",
         (names.similarity("Κρίστιαν Χάρισον / Νιλ Σκούπσκι", "Harrison C./Skupski N.") >= canon.TENNIS_SIDE,
          names.similarity("Κρίστιαν Χάρισον / Νιλ Σκούπσκι", "Χάρισον Κ./Σκάπσκι Ν.") >= canon.SURE,
          names.similarity("Кристиан Харрисон", "Harrison C.") >= canon.SURE,
          names.similarity("Connah's Quay", "Connahs Q.") >= canon.SURE), (True, True, True, True))

print("П3. Один инициал закрывает одно слово")
проверка("чужая пара с той же второй фамилией не сходится: буква «C» не закрывает и имя, и фамилию",
         [names.similarity(a, "Cerundolo C./Rublev A.") < canon.SURE
          for a in ("Carlos Cabal/Andrey Rublev", "Karen Khachanov/Andrey Rublev", "Κάρεν Κατσάνοφ / Αντρέι Ρούμπλεφ")],
         [True, True, True])
проверка("свои пары и имена сходятся, как раньше: инициал достаётся слову без своего целого слова",
         [names.similarity(a, b) for a, b in (
             ("Kevin Krawietz/Tim Puetz", "Krawietz K./Puetz T."),
             ("Juan Manuel Cerundolo", "Cerundolo J. M."), ("Maccabi Herzliya", "M. Herzliya"),
             ("Christian Harrison/Neal Skupski", "Harrison C./Skupski N."), ("Novak Djokovic", "Djokovic N."),
             ("Μαρσέλο Αρέβαλο/Μέιτ Πάβιτς", "Αρεβάλο Μ./Πάβιτς Μ."))], [100] * 6)
проверка("однофамилец с другим именем по-прежнему не сходится",
         [names.similarity(a, b) < canon.SURE for a, b in (("Αλεξάντερ Μεντβέντεφ", "Μεντβέντεφ Ν. (Κοσ)"),
                                                           ("Francisco Cerundolo", "Cerundolo J. M."))], [True, True])

print("П4. Имя греческими буквами — страна только по греческому написанию (Т9)")
проверка("«Κολούμπια» (университет), «Μπραζίλια» (клуб), «Μπόνερ» — не страны; «Κολομβία», «Βραζιλία» — страны",
         [names.country_of(x) for x in ("Κολούμπια", "Κολούμπια Γ", "Μπραζίλια", "Μπόνερ", "Κολομβία", "Βραζιλία")],
         ["", "", "", "", "COLOMBIA", "BRAZIL"])
проверка("чтения «Κολούμπια» страной не подменяются; латинское «Kolumbia» (польское) — Колумбия, как было",
         ("COLOMBIA" not in names.readings("Κολούμπια"), names.similarity("Κολούμπια", "Columbia") >= canon.SURE,
          names.country_of("Kolumbia")), (True, True, "COLOMBIA"))
проверка("греческая буква-сокращение, записанная в старом разделе словаря, читается: «Β. Ιρλανδία», «Β. Μακεδονία»",
         [names.country_of(x) for x in ("Β. Ιρλανδία", "Β. Μακεδονία")], ["NORTHERN IRELAND", "NORTH MACEDONIA"])

print("Сведение с эталоном (`canon.align`, теннисное правило книги 141)")
ЭТАЛОН = [
    матч("Granollers M./Zeballos H.", "Bolelli S./Vavassori A.", "2026-11-16T12:30",
         el=["Γκρανολέρ Μ./Σεμπάλος Χ.", "Μπολέλι Σ./Βαβασόρι Α."]),
    матч("Harrison C./Skupski N.", "Krawietz K./Puetz T.", "2026-11-16T19:00",
         el=["Χάρισον Κ./Σκάπσκι Ν.", "Κράβιετζ Κ./Πουέτζ Τ."]),
]
проверка("«Κρίστιαν Χάρισον / Νιλ Σκούπσκι — Κέβιν Κράβιτς/Τιµ Πιουτς» в 19:00 — матч эталона Harrison/Skupski",
         сверка(игра("Κρίστιαν Χάρισον / Νιλ Σκούπσκι", "Κέβιν Κράβιτς/Τιµ Πιουτς", "2026-11-16T19:00"), ЭТАЛОН),
         ("sure", "Harrison C./Skupski N. - Krawietz K./Puetz T.", canon.HOW_TENNIS))
проверка("стороны записаны наоборот — тот же матч",
         сверка(игра("Κέβιν Κράβιτς/Τιµ Πιουτς", "Κρίστιαν Χάρισον / Νιλ Σκούπσκι", "2026-11-16T19:00"), ЭТАЛОН)[:2],
         ("sure", "Harrison C./Skupski N. - Krawietz K./Puetz T."))
проверка("дневная пара с инициалами впереди («Μ. Γκρανογέρς/Χ. Σέµπαλος») сходится, как раньше",
         сверка(игра("Μ. Γκρανογέρς/Χ. Σέµπαλος", "Σιμόνε Μπολέλι/Αντρέα Βαβασόρι", "2026-11-16T12:30"), ЭТАЛОН)[:2],
         ("sure", "Granollers M./Zeballos H. - Bolelli S./Vavassori A."))
проверка("чужая пара в тот же час (другие игроки) к матчу эталона не сводится",
         сверка(игра("Κάρεν Κατσάνοφ / Αντρέι Ρούμπλεφ", "Τέιλορ Φριτς / Τόμι Πολ", "2026-11-16T19:00"), ЭТАЛОН)[0],
         "missed")
проверка("пара, где свой только один игрок из двух («Χάρισον» с другим напарником), не сводится",
         сверка(игра("Κρίστιαν Χάρισον / Έβαν Κινγκ", "Τέιλορ Φριτς / Τόμι Πολ", "2026-11-16T19:00"), ЭТАЛОН)[0],
         "missed")
проверка("одиночный матч Харрисона в час парного к парному не сводится: в теннисе одна сторона матч не решает "
         "(`canon._clear_leader`)",
         сверка(игра("Κρίστιαν Χάρισον", "Κέβιν Κράβιτς", "2026-11-16T19:00"), ЭТАЛОН)[0], "missed")

print(f"\nпроверок: {зелёных + красных}, зелёных: {зелёных}, красных: {красных}")
sys.exit(1 if красных else 0)
