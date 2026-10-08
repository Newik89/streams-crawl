# -*- coding: utf-8 -*-
"""Канон имён по эталону flashscore (задание владельца 02.09).

Порядок, который назвал владелец:
  1. сырое имя сначала читается своим словарём (транслит + библиотека);
  2. новое имя ищется в эталоне flashscore (он в ежедневном обходе);
  3. найденное английское написание закрепляется в библиотеке НАВСЕГДА —
     в следующий раз flashscore для этого имени уже не нужен;
  4. сомнительное совпадение не пишется молча, а ложится в очередь
     «Названия» админки на подтверждение владельцем.

Эталон приезжает в `games.json` (ключ «эталон», кладёт `parse_live.py`):
весь мировой футбол дня с flashscore.mobi — имена, лига, fs_id, время Киева.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

from . import dictionary, names

#: с этого сходства пишем в библиотеку молча (порог склейки проекта)
SURE = names.SIMILAR_ENOUGH


def _learnable(mine: str, canon: str) -> bool:
    """Можно ли закрепить алиас mine → canon НАВСЕГДА. Пол/возраст/состав
    обязаны совпадать («Германия» с женского ЧМ становилась алиасом
    «Germany W», и мужская сборная шла по витрине с W), и пометка «3x3»
    тоже: «Nemačka» → «Germany 3x3» приклеивал турнир 3x3 к обычной
    сборной (оба случая — 06.09). Пол игре даёт лига через with_category,
    так что честное имя приходит сюда уже со своей категорией."""
    if names.is_placeholder(mine) or names.is_placeholder(canon):
        return False          # «TBC», «Winner QF1» — не имя команды (10.09)
    # в написании — весь матч или «Лига: клуб», а не клуб: «Eurocup: Tortona
    # - Le Mans» лежало алиасом Le Mans, «Premier League: Hull City» — Hull
    # (08.10: 125 + 636 таких записей в словаре, сторож test_sport_words
    # покраснел). Чистка `dict_clean.py --only матчи` их снимает, но учить
    # заново нельзя: `_one_team` раньше звала только чистка, не учёба
    if not _one_team(mine, canon) or (":" in mine and ":" not in canon):
        return False
    return (names.category(mine) == names.category(canon)
            and ("3x3" in mine.lower()) == ("3x3" in canon.lower()))
#: единственный кандидат в окне времени — достаточно и такого сходства,
#: чтобы спросить владельца (греческое `Φόλκερκ` против `Falkirk` даёт ~62)
LONE = 60
#: тот же одиночный кандидат для иврита: гласных на письме нет, транслит
#: честным парам даёт 33–80, до LONE многие не дотягиваются (6е, 03.09)
LONE_HE = 45
#: мост «та же лига + то же время»: с какими очками и отрывом лидер по
#: буквам закрепляется сам, без очереди на подтверждение (владелец 09.09 —
#: «иврит так и не переводится нормально»). Ниже — по-прежнему в очередь.
BRIDGE_SURE = 70
BRIDGE_GAP = 20
#: тот же мост, когда одна команда пары узнана уверенно, а вторая не читается
#: вовсе: `פורטונה סיטארד` = Sittard даёт 92, а `איאקס` = Ajax только 44, и
#: пара по худшей стороне не проходит нигде. Владелец 10.09: «нужно, чтобы
#: через алгоритм проходило всё, даже новый язык». Тогда решает не худшая
#: сторона, а лучшая — плюс отрыв от второго кандидата ТОЙ ЖЕ лиги
BRIDGE_BEST = 75
BRIDGE_FLOOR = 40
#: окно поиска: сетки ставят блок раньше матча, а mobi живёт в UTC+2
WINDOW = timedelta(hours=3)


#: пометки эфира и стадии, а не названия лиг: выученный с такого ярлыка
#: алиас цепляет лигу первого попавшегося матча ко всем чужим играм
#: (кейс #89 от 04.09 — «Прямая трансляция» приклеила Genoa - Como
#: к «BRAZIL: Serie A Betano»)
_NOT_LEAGUE_RE = re.compile(
    r"(?<!\w)(?:прямая\s+трансляция(\s+из\s+\S+)?|live|"
    r"\d+\s*тур|тур\s*\d+|1/\d+\s+финала|финал|полуфинал|"
    r"перенес\w+\s+матч(\s+\d+\s+тура)?|женщины|мужчины|"
    # «женский футбол» на любом языке — это ВИД соревнования, а не
    # лига: раньше ивритское «כדורגל נשים» стало алиасом ENGLAND: WSL,
    # и немецкий матч Leverkusen W — Bayern W уехал в английскую лигу
    # (разбор владельца 10.09). Пол команды всё равно ставится —
    # его даёт `leagues.category`, отсюда суффикс W
    r"женск\w*\s+(футбол|баскетбол|гандбол)\w*|"
    r"כדורגל\s+נשים|כדורסל\s+נשים|"
    r"pi[\u0142l]ka\s+no[\u017cz]na\s+kobiet|"
    r"f[\u00fau]tbol\s+femenino|futebol\s+feminino|"
    r"calcio\s+femminile|frauenfu[\u00dfs]ball|"
    r"football\s+f[\u00e9e]minin|"
    r"women.?s\s+(football|soccer|basketball)|"
    r"сезона?\s+\d+([/-]\d+)?)(?!\w)",
    re.IGNORECASE)


#: родовые слова лиг, которые носят десятки стран: голый ярлык «Superliga»
#: успел стать алиасом Румынии, Дании и Косова разом, и Viborg - Lyngby
#: показывался с «KOSOVO: Superliga» (кейс #374, 04.09). Ярлык, состоящий
#: только из таких слов, не учим — лигу назовёт полное написание со страной
_GENERIC_LEAGUE_WORDS = frozenset(
    "liga league lig ligue superliga superligaen super premier premijer "
    "prva serie seria championship division divizia fudbal football "
    "лига суперлига премьер чемпионат высшая первая дивизион футбол "
    "a b c i ii 1 2 3".split())


def league_worthy(label: str) -> bool:
    """Стоит ли учить алиас лиги с этого ярлыка: после вычета пометок
    эфира и стадии должно остаться хоть одно настоящее слово, и не все
    слова — родовые («Superliga» без страны лигу не называет)."""
    rest = _NOT_LEAGUE_RE.sub(" ", label)
    words = [w.lower() for w in re.findall(r"[^\W_]+", rest)]
    if not any(len(w) >= 3 and not w.isdigit() for w in words):
        return False
    return not all(w in _GENERIC_LEAGUE_WORDS for w in words)


def _parse(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


#: письменность языка локали: сравнивать греческое имя с венгерским
#: написанием незачем, а десятикратный перебор пар заметно тормозит импорт
_SCRIPT_OF_LANG = {"el": "el", "bg": "cyr", "ru": "cyr", "uk": "cyr"}

#: ивритские названия израильских турниров (sport1.maariv, sport5). Локали he
#: у flashscore нет, и буквы мостом не работают — израильскую игру узнаём по
#: лиге, а к эталону ведёт время (задание владельца 03.09)
_IL_HE = re.compile("ליגת העל|ליגה לאומית|הליגה הלאומית|ליגה א|ליגת ווינר"
                    "|גביע ווינר|גביע וינר|גביע המדינה|גביע הטוטו")

#: лига есть не у каждой строки — израильскую пару выдают и сами клубы: Хапоэль,
#: Маккаби, Бейтар, Ирони, Бней носят только израильские команды
_IL_CLUBS = re.compile('הפועל|מכבי|בית"ר|ביתר|עירוני|בני ')


def looks_israeli(game: dict) -> bool:
    """Игра с ивритской письменностью — израильская? Смотрим лигу (maariv,
    sport5) или клубные слова в самой паре."""
    league = (game.get("league") or "").strip()
    if league.upper().startswith("ISRAEL") or _IL_HE.search(league):
        return True
    return bool(_IL_CLUBS.search(f"{game.get('home') or ''} "
                                 f"{game.get('away') or ''}"))


def il_pick(game: dict, candidates: list[dict],
            same_league: bool = False) -> tuple[dict | None, str]:
    """Мост «лига + время»: выбрать израильской игре матч среди израильских
    записей эталона в окне. Один кандидат — это он и есть, буквы не
    спрашиваем (`sure`). Несколько (туры Лиги Леумит играют в один час) —
    буквы решают только между ними: заметно лучший — на подтверждение
    владельцу (`ask`), решить нельзя — (None, "").

    `same_league` — кандидаты уже отобраны по ТОЧНО той же лиге, что у игры
    (лигу перевёл словарь). Тогда явный лидер по буквам закрепляется сам, без
    очереди: у иврита буквы с латиницей полностью не совпадут, и ждать
    ручного подтверждения — значит держать ивритские имена на витрине
    неделями (жалоба владельца 09.09). Порог тут выше обычного —
    `BRIDGE_SURE` очков и отрыв `BRIDGE_GAP` от второго."""
    def alone(pick: dict) -> tuple[dict | None, str]:
        """Единственный кандидат. Отобранным по ТОЧНОЙ лиге (`same_league`)
        буквы обязаны не спорить: в «WORLD: Club Friendly» в один час стоит
        десяток чужих матчей, и одиночка легко оказывается не тем —
        `Partizan - Besiktas` цеплялся к `Trapani - Manresa` (10.09).
        Израильскому мосту раньше хватало своей лиги и часа, но у футбольной
        строки maariv стоял баскетбол, и единственным кандидатом оказывался
        чужой матч Кубка: «הפועל ר"ג — מכבי נתניה» закрепился за Maccabi
        Rishon — Ironi Eilat, и словарь выучил мусор (#2431, #2510, 14.09).
        Теперь и тут буквы пары не должны спорить (`BRIDGE_FLOOR`) — либо
        одна команда узнана твёрдо (`BRIDGE_BEST`)."""
        if same_league:
            # одна сторона узнана твёрдо (`BRIDGE_BEST`), пол/возраст те же:
            # клуб не играет два матча в один час, вторая сторона просто не
            # читается — «הפועל חולון — שולה באסקט» = Hapoel Holon — Cholet
            # (#4306, 01.10). Так вторая сторона и выучивается сама
            if _one_side_enough(game, pick):
                return pick, "sure"
            return (pick, "sure") if _pair_score(game, pick) >= LONE_HE \
                else (None, "")
        if _pair_score(game, pick) >= BRIDGE_FLOOR \
                or _best_side(game, pick) >= BRIDGE_BEST:
            return pick, "sure"
        return None, ""

    if len(candidates) == 1:
        return alone(candidates[0])
    league = (game.get("league") or "").strip()
    exact = [r for r in candidates if r.get("league") == league]
    if len(exact) == 1:
        return alone(exact[0])
    # одна сторона совпала ИДЕАЛЬНО (100 — имя эталона или словарный
    # алиас) и только у этого кандидата — это он: «מ.ס. אשדוד» = SC Ashdod
    # давал side 100 при паре 40 (вторая команда в сокращениях с обеих
    # сторон), и матч №2240 оставался ивритом (владелец 12.09). Буквы пары
    # при этом не должны спорить (`BRIDGE_FLOOR`)
    sided = [(r, _best_side(game, r)) for r in candidates]
    perfect = [r for r, s in sided if s >= 100]
    if len(perfect) == 1 \
            and all(s <= BRIDGE_BEST for r, s in sided if r is not perfect[0]) \
            and (_pair_score(game, perfect[0]) >= BRIDGE_FLOOR
                 # сторона на 100 и только у него: вторая не читается, но
                 # команда в один час два матча не играет (01.10)
                 or (same_league and _one_side_enough(game, perfect[0]))):
        return perfect[0], "sure"
    # одна сторона узнана твёрдо (не обязательно на 100) ровно у одного
    # кандидата той же лиги — это он: «הפועל חולון» = Hapoel Holon на 92,
    # а «שולה באסקט» (Cholet) не читается вовсе (#4306, 01.10)
    if same_league:
        strong = [r for r in candidates if _one_side_enough(game, r)]
        if len(strong) == 1:
            return strong[0], "sure"
    scored = sorted(((_pair_score(game, r), r) for r in candidates),
                    key=lambda x: -x[0])
    # порог LONE и маржа: честные пары после словаря _HE_WORDS набирают
    # 80+, а шум транслита к чужому матчу — до 50 (Araba против Ахи
    # Нацерет дал 46, когда настоящего матча в эталоне не было)
    # порог входа: если кандидаты уже отобраны по той же лиге и тому же
    # часу, довольно того, что буквы не спорят (`BRIDGE_FLOOR`) —
    # дальше решают отрыв от второго и твёрдо узнанная сторона.
    # Без отбора по лиге спрос прежний, `LONE`
    floor = BRIDGE_FLOOR if same_league else LONE
    if len(scored) >= 2 and scored[0][0] >= floor \
            and scored[0][0] - scored[1][0] >= 15:
        gap = scored[0][0] - scored[1][0]
        strong = (same_league and gap >= BRIDGE_GAP
                  and (scored[0][0] >= BRIDGE_SURE
                       # одна сторона узнана твёрдо — вторая просто не читается
                       or (scored[0][0] >= BRIDGE_FLOOR
                           and _best_side(game, scored[0][1]) >= BRIDGE_BEST)))
        return scored[0][1], "sure" if strong else "ask"
    return None, ""


def _script(text: str) -> str:
    for ch in text:
        o = ord(ch)
        if 0x0370 <= o <= 0x03FF:
            return "el"
        if 0x0400 <= o <= 0x04FF:
            return "cyr"
        if 0x0590 <= o <= 0x05FF:
            return "he"
    return "lat"


_TIER_RE = re.compile(
    r"\s+-\s+(League [A-D]|Group [A-Z0-9]+|Division \d|Play ?Offs?|"
    r"League phase|Qualification|Promotion.*|Relegation.*)$", re.I)


def _one_side_enough(game: dict, ref: dict) -> bool:
    """Твёрдо узнанная одна сторона решает матч: пол/возраст те же, и это не
    теннис — там игрок в один день стоит и в одиночке, и в паре
    («Etcheverry» на 100 совпал с «Darderi/Etcheverry», регресс 01.10)."""
    if (game.get("sport") or "") == "T" or "/" in (ref.get("home") or "") \
            or "/" in (ref.get("away") or ""):
        return False
    return _best_side(game, ref) >= BRIDGE_BEST and _same_category(game, ref)


def _league_core(label: str) -> str:
    """Лига без стадии и дивизиона: «EUROPE: UEFA Nations League - League C»
    → «EUROPE: UEFA Nations League». Родовой ярлык сайта («ליגת האומות»)
    словарь привязывает к одному дивизиону (последнему выученному), и мост
    искал Швейцарию — Сев. Македонию только в League C, а матч стоял в
    League B (#4320, 01.10). Сравниваем основы — дивизион решают буквы."""
    # режем только дивизион/группу/стадию: у тенниса «ATP - SINGLES: Tokyo»
    # и «ATP - DOUBLES: Tokyo» общей основой «ATP» слились, и одиночка
    # Этчеверри прицепилась к его же парному матчу (регресс 01.10)
    return _TIER_RE.sub("", (label or "").strip()).strip()


def _league_marks(game: dict) -> list[str]:
    """Пол и возраст из названия турнира — как на сайте и как его перевёл
    словарь (`league_canon`, ставит `align`). У израильского и болгарского
    сайтов возраст виден только в турнире и только на своём языке («עד גיל
    21», «за младежи»): буквы его не читают, а словарь лигу уже знает —
    `EUROPE: Euro U21 - Qualification`. Без этого «נורווגיה — ישראל» жила
    двойней рядом с «Norway U21 — Israel U21», а «България — Шотландия» шла
    взрослыми сборными без метки эталона (#4313, #4216, 03.10). «Вторая
    команда» (B) из турнира не берётся — см. `_pair_score`."""
    text = f"{game.get('league') or ''} {game.get('league_canon') or ''}"
    return [m for m in names.category(text).split() if m != "B"]


def _same_category(game: dict, ref: dict) -> bool:
    """Пол и возраст пары совпадают с кандидатом (та же стена, что в
    `_pair_score`, но без счёта по буквам)."""
    из_лиги = _league_marks(game)
    моя = names.category(f"{game.get('home') or ''} {game.get('away') or ''}")
    моя = sorted(set((моя + " " + " ".join(из_лиги)).split()))
    его = sorted(set(names.category(
        f"{ref.get('home') or ''} {ref.get('away') or ''}").split()))
    return моя == его


def _sides(ref: dict, script: str = "lat") -> list[tuple[str, str]]:
    """Написания пары в эталоне той же письменности, что и у игры: для
    греческой строки Cosmote — греческое написание flashscore (`names`:
    {"el": [home, away], ...}), для кириллицы — болгарское/русское/украинское,
    для латиницы — венгерское, румынское, турецкое, польское, чешское.
    Сравнивать по-своему честнее, чем с английским через транслит — там и
    ловились 45 % игр без канона (03.09)."""
    out = []
    for lang, pair in (ref.get("names") or {}).items():
        if _SCRIPT_OF_LANG.get(lang, "lat") != script:
            continue
        if isinstance(pair, (list, tuple)) and len(pair) == 2 \
                and pair[0] and pair[1]:
            out.append((str(pair[0]).strip(), str(pair[1]).strip()))
    return out


def _best_side(game: dict, ref: dict) -> int:
    """Насколько хорошо узнана ЛУЧШАЯ из двух команд. `_pair_score` берёт
    худшую — и честная пара, где одна команда не читается (иврит, греческий),
    проваливается целиком. Для моста по лиге важно другое: одна сторона
    опознана твёрдо, значит матч тот самый."""
    best = max(names.similarity(game["home"], ref.get("home") or ""),
               names.similarity(game["away"], ref.get("away") or ""))
    for h, a in _sides(ref, _script(f"{game['home']} {game['away']}")):
        best = max(best, names.similarity(game["home"], h),
                   names.similarity(game["away"], a))
    return best


def _clear_leader(game: dict, best: dict, best_score: int,
                  near: list) -> bool:
    """Лидер без лиги, но без сомнений: одна сторона узнана твёрдо
    (`BRIDGE_BEST`), буквы в целом не спорят (`BRIDGE_FLOOR`), и следующий
    кандидат в окне отстаёт не меньше чем на `BRIDGE_GAP`. Когда сторона
    совпала ИДЕАЛЬНО (100 — само имя эталона либо словарный алиас),
    достаточно половины отрыва: `סווי ריאנג` = Svay Rieng давал паре 60 и
    отрыв 16 — матч Мачиды оставался ивритом (#2228, владелец 12.09)."""
    side = _best_side(game, best)
    if best_score < BRIDGE_FLOOR or side < BRIDGE_BEST:
        return False
    второй = max((_pair_score(game, r) for r, _ in near if r is not best),
                 default=0)
    нужен = BRIDGE_GAP // 2 if side >= 100 else BRIDGE_GAP
    return best_score - второй >= нужен


def _pair_score(game: dict, ref: dict) -> int:
    """Похожесть пары с записью эталона: сперва английское написание, и
    только если его не хватило — местные той же письменности."""
    # категории не смешиваем: взрослая пара НЕ равна юношеской или женской
    # той же вывески — «Bayern - Bodo/Glimt» цеплял юношескую метку
    # «Bayern U19 - Bodo/Glimt U19» и уезжал на её время (кейс #918, 05.09)
    # Пол и возраст берём и из названия турнира — у части сайтов они видны
    # только там. А «вторая команда» (B/II/2) читается ТОЛЬКО по именам:
    # болгарское «Шампионска лига на Азия 2» — второй по силе турнир, а не
    # дубль клуба, и матч Arkadag — Al-Muharraq не лёг на эталон, хотя обе
    # команды совпали на 100 (#2061, разбор владельца 10.09)
    из_лиги = _league_marks(game)
    моя = names.category(f"{game.get('home') or ''} {game.get('away') or ''}")
    моя = sorted(set((моя + " " + " ".join(из_лиги)).split()))
    его = sorted(set(names.category(
        f"{ref.get('home') or ''} {ref.get('away') or ''}").split()))
    # В теннисе буква пола в имени ничего не значит: эталон пишет игроков с
    # инициалом («Zheng W.», «Osuigwe W.» — это не «женская», а имя), пол
    # задаёт турнир. Стена по категории тут только мешала: «Kraus W» с
    # sportklub.hr не сходилась с «Kraus S.», а эталонная «Zheng W.» — ни с
    # одним сайтом (#4597, владелец 04.10). Возраст сравниваем как раньше
    if (game.get("sport") or "") == "T":
        моя = [m for m in моя if m != "W"]
        его = [m for m in его if m != "W"]
    if моя != его:
        return 0
    # Соперник ещё не назван («España — TBC» у movistarplus за день до
    # жеребьёвки): судим по известной стороне. Владелец 10.09: «эталон уже
    # знает вторую команду, игра должна была исправиться сама»
    пусто_дома = names.is_placeholder(game.get("home") or "")
    пусто_в_гостях = names.is_placeholder(game.get("away") or "")
    if пусто_дома != пусто_в_гостях:
        known = game["away"] if пусто_дома else game["home"]
        best = max(names.similarity(known, ref.get("home") or ""),
                   names.similarity(known, ref.get("away") or ""))
        for h, a in _sides(ref, _script(known)):
            best = max(best, names.similarity(known, h),
                       names.similarity(known, a))
        return best
    score = min(names.similarity(game["home"], ref.get("home") or ""),
                names.similarity(game["away"], ref.get("away") or ""))
    if score >= SURE:
        return score
    for h, a in _sides(ref, _script(f"{game['home']} {game['away']}")):
        score = max(score, min(names.similarity(game["home"], h),
                               names.similarity(game["away"], a)))
        if score >= SURE:
            break
    return score


def fill_placeholder(game: dict, ref: dict) -> bool:
    """Заменить «TBC» именами пары из эталона. Заглушку в словарь не пишем —
    настоящий соперник просто встаёт на её место в самой игре, и следующая
    склейка сводит две строки канала (студия и матч) в одну."""
    пусто_дома = names.is_placeholder(game.get("home") or "")
    пусто_в_гостях = names.is_placeholder(game.get("away") or "")
    if пусто_дома == пусто_в_гостях:
        return False
    known = game["away"] if пусто_дома else game["home"]
    дома, в_гостях = ref.get("home") or "", ref.get("away") or ""
    # известная сторона могла стоять у эталона второй — тогда и пару меняем
    if names.similarity(known, в_гостях) > names.similarity(known, дома):
        дома, в_гостях = в_гостях, дома
    game["home"], game["away"] = дома, в_гостях
    return True


def learn_by_id(conn: sqlite3.Connection, reference: list[dict]) -> tuple[int, int]:
    """Этап 6е, A2: местные написания эталона → английские, по `fs_id`,
    без порогов — это один и тот же матч на одном и том же сайте.
    Возвращает (команд, лиг) — сколько НОВЫХ алиасов легло в библиотеку;
    уже известные пропускаются, чтобы не гонять тысячи записей каждый день."""
    known_teams = {(r["alias"], r["lang"]) for r in conn.execute(
        "SELECT alias, lang FROM team_aliases")}
    known_leagues = {(r["alias"], r["lang"]) for r in conn.execute(
        "SELECT alias, lang FROM league_aliases")}
    teams = leagues = 0
    for r in reference:
        en_home = (r.get("home") or "").strip()
        en_away = (r.get("away") or "").strip()
        en_league = (r.get("league") or "").strip()
        for lang, pair in (r.get("names") or {}).items():
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                continue
            for local, en in ((str(pair[0]).strip(), en_home),
                              (str(pair[1]).strip(), en_away)):
                if not local or not en or local == en \
                        or (local, lang) in known_teams:
                    continue
                dictionary.remember_team(conn, local, en, lang=lang)
                known_teams.add((local, lang))
                teams += 1
        for lang, league in (r.get("leagues") or {}).items():
            league = (league or "").strip()
            if not league or not en_league or league == en_league \
                    or (league, lang) in known_leagues:
                continue
            dictionary.remember_league(conn, league, en_league,
                                       sport=r.get("sport"), lang=lang)
            known_leagues.add((league, lang))
            leagues += 1
    conn.commit()
    return teams, leagues


def align(games: list[dict], reference: list[dict],
          league_names: dict[str, str] | None = None) -> dict:
    """Сопоставляет игры с эталоном. Возвращает
    {"sure": [(game, ref, score)], "ask": [...], "missed": [game, ...]}.

    `league_names` — словарь лиг из библиотеки (алиас → канон): у ивритских
    игр лига записана ивритом («הליגה ההולנדית»), и без перевода мост
    «лига + время» её с эталонной `NETHERLANDS: Eredivisie` не сведёт."""
    by_sport: dict[str, list] = {}
    for r in reference:
        start = _parse(r.get("start_kyiv") or "")
        if start and r.get("home") and r.get("away"):
            # старый эталон без поля sport — футбольный
            by_sport.setdefault(r.get("sport", "F"), []).append((r, start))

    out = {"sure": [], "ask": [], "missed": []}
    for game in games:
        ref = by_sport.get(game.get("sport") or "", [])
        if not ref:
            continue                      # вида спорта нет в эталоне
        start = _parse(game.get("start_kyiv") or "")
        if start is None:
            continue
        # турнир в переводе словаря — для пола и возраста (`_league_marks`)
        canon_league = (league_names or {}).get(
            (game.get("league") or "").strip(), "")
        if canon_league and not game.get("league_canon"):
            game["league_canon"] = canon_league
        near = [(r, s) for r, s in ref if abs(start - s) <= WINDOW]
        best, best_score = None, -1
        for r, _ in near:
            score = _pair_score(game, r)
            if score > best_score:
                best, best_score = r, score
        lone = LONE
        if (best_score < SURE
                and _script(f"{game['home']} {game['away']}") == "he"):
            lone = LONE_HE
            # Мост «лига + время» (6е): игра израильская — пару ей ищем
            # ТОЛЬКО среди израильских матчей эталона, к иностранным буквы
            # иврита не подпускаем. Эталон матч не знает — игра уходит в
            # missed, а не к ложному соседу по времени.
            # израильский клуб в ЕВРОКУБКЕ — не израильская игра: «הפועל חולון
            # — שולה באסקט» (Лига чемпионов по баскетболу) уходила в
            # израильский мост, там кандидатов нет — и в missed, не дойдя до
            # общего моста по лиге (#4306, 01.10). Лигу переводит словарь:
            # перевелась и не израильская — идём общим путём
            known = (league_names or {}).get(
                (game.get("league") or "").strip(), "")
            foreign = bool(known) and not known.upper().startswith("ISRAEL")
            if looks_israeli(game) and not foreign:
                il = [r for r, _ in near
                      if (r.get("league") or "").upper().startswith("ISRAEL")]
                if il:
                    pick, verdict = il_pick(game, il)
                    if verdict == "sure":
                        _sure(out, game, pick, SURE)
                    elif verdict == "ask":
                        _ask(out, game, pick, LONE_HE)
                    else:
                        out["missed"].append(game)
                    continue
                league = (game.get("league") or "").strip()
                if league.upper().startswith("ISRAEL") or _IL_HE.search(league):
                    # лига прямо израильская, но эталон матча не знает
                    out["missed"].append(game)
                    continue
                # израильские тут только клубы (евроматч Маккаби, женские
                # лиги) — обычный путь по буквам
            # Тот же мост «лига + время» для НЕизраильских ивритских игр:
            # sport5 показывает Бундеслигу и Кубок Либертадорес ивритом, а
            # лига у игры уже каноническая (её перевёл словарь лиг). Пару
            # ищем среди матчей эталона ТОЙ ЖЕ лиги в окне: единственный —
            # это он, несколько — буквы решают между ними (дочистка 06.09).
        # Мост «та же лига + то же время» — для ЛЮБОГО языка (владелец 10.09:
        # «нужно, чтоб всё проходило через алгоритм, даже если появляется
        # новый язык»). Раньше сюда пускали только иврит, и греческие,
        # литовские, испанские, чешские имена оставались на витрине как на
        # сайте: `זוולה — פיינורד` = Zwolle — Feyenoord набирает 66 из 85 и
        # своего матча в эталоне не получал, хотя тот стоял в той же лиге и в
        # ту же минуту.
        if best_score < SURE:
            in_league = (game.get("league") or "").strip()
            in_league = (league_names or {}).get(in_league, in_league)
            if in_league:
                cat = names.category(f"{game.get('home') or ''} "
                                     f"{game.get('away') or ''} {in_league}")
                core = _league_core(in_league)
                same = [r for r, _ in near
                        if _league_core(r.get("league")) == core
                        and names.category(f"{r.get('home') or ''} "
                                           f"{r.get('away') or ''}") == cat]
                if same:
                    pick, verdict = il_pick(game, same, same_league=True)
                    # израильскому мосту единственного кандидата хватает, а
                    # тут лиги континентальные: у Копа Судамерикана в окне
                    # может стоять единственный, но ЧУЖОЙ матч («Санта Фе -
                    # Васко» клеился к Santos - Atletico-MG, 06.09) — буквы
                    # обязаны хотя бы не спорить
                    if pick is not None and _pair_score(game, pick) < BRIDGE_FLOOR \
                            and not _one_side_enough(game, pick):
                        pick, verdict = None, ""
                    if verdict == "sure":
                        _sure(out, game, pick, SURE)
                    elif verdict == "ask":
                        _ask(out, game, pick, LONE_HE)
                    else:
                        out["missed"].append(game)
                    continue
        # Одинокий ВОЗРАСТНОЙ кандидат (владелец 22.09, #3037): сетка пишет
        # «Srbija - Bugarska» без возраста, а эталон в ту же минуту знает
        # единственный «Serbia U19 - Bulgaria U19» — арена возраст просто
        # не пишет. Принимаем канон эталона ЦЕЛИКОМ (имена с возрастом,
        # лига): потерянный возраст хуже лишнего (правило проекта, как с W).
        # Строгости, чтобы не повторить чужую граблю «сомнительное берёт
        # только время»: у нашей игры возраста нет, у кандидата он у ОБЕИХ
        # команд, имена без возраста сходятся на SURE, окно узкое (сетки
        # сборных время держат точно), кандидат такой в окне один.
        if best_score < SURE and not names._AGE_RE.search(
                f"{game.get('home') or ''} {game.get('away') or ''}"):
            aged = []
            for r, s in near:
                if abs(start - s) > timedelta(minutes=30):
                    continue
                home_ref = (r.get("home") or "").strip()
                away_ref = (r.get("away") or "").strip()
                bare_home = " ".join(names._AGE_RE.sub(" ", home_ref).split())
                bare_away = " ".join(names._AGE_RE.sub(" ", away_ref).split())
                if bare_home == home_ref or bare_away == away_ref:
                    continue          # возраст не у обеих — не наш случай
                if _pair_score(game, dict(r, home=bare_home,
                                          away=bare_away)) >= SURE:
                    aged.append(r)
            if len(aged) == 1:
                _sure(out, game, aged[0], SURE)
                continue
        if best is None:
            out["missed"].append(game)
        elif best_score >= SURE:
            _sure(out, game, best, best_score)
        elif _clear_leader(game, best, best_score, near):
            # Лиги нет, но одна команда узнана твёрдо, а соперники в окне
            # далеко позади: `לברקוזן W` = Bayer Leverkusen W (83), вторая
            # сторона на иврите читается хуже (66), а другого такого матча в
            # этот час нет. Раньше тут выручал мост по лиге, но ивритское
            # «женский футбол» лигой больше не считается — и #1793 остался
            # без перевода (разбор владельца 11.09)
            _sure(out, game, best, SURE)
        elif best_score >= (lone if len(near) == 1 else SURE - 15):
            _ask(out, game, best, best_score)
        else:
            out["missed"].append(game)
    return out


def _sure(out: dict, game: dict, ref: dict, score: int) -> None:
    """Уверенная пара — только если лига эталона той же страны, что и
    лига игры по словарю (`foreign_league`). Уверенная пара пишет НАВСЕГДА:
    алиасы команд и лиги в словарь, метку `fs:`, время. Буквам иврита
    этого мало: «בולאזאק — רואן» (французский баскетбол, записан футболом)
    при единственном кандидате в окне становилась уверенной парой с чешским
    футболом «Velke Hamry — Brozany» (одна сторона 85, `_clear_leader`), и
    словарь выучил бы «רואן» = «Brozany» (разбор 06.10). Лига другой страны —
    другая игра: в «мимо»."""
    if foreign_league(game, ref):
        out["missed"].append(game)
    else:
        out["sure"].append((game, ref, score))


def _ask(out: dict, game: dict, ref: dict, score: int) -> None:
    """Пара «с сомнением» — только когда эталон похож на НАШУ игру под
    другим написанием. Другая игра того же часа (`other_game`) идёт в
    «мимо», а не в «с сомнением»: «с сомнением» прятало игру от сверки
    задним числом — `canon_backfill` ищет вид спорта по эталону только у
    «мимо». Баскетбольная «נאנסי — פריז» (лига FRANCE: LNB, а записана
    футболом) держалась за испанский футбол «San Ignacio — Pasaia» и не
    доходила до своего «Nancy — Paris» (100 в баскетболе; прогон 24.09,
    разбор 06.10)."""
    if other_game(game, ref):
        out["missed"].append(game)
    else:
        out["ask"].append((game, ref, score))


_SEPS = (" - ", " – ", " — ")

#: заголовок сетки несёт лигу перед двоеточием и тур после запятой:
#: «ליגה צרפתית: פריז - שטרסבורג, מחזור 5», «Super League 7. Runde,
#: Grasshopper – FC Zürich». Без чистки в словарь ложились «ארצו, מחזור 3»
#: и «ליגה לאומית בכדורגל: הפועל עכו» (пакет C, 14.09). В голове дефиса нет:
#: «Arsenal - Chelsea: live» — это уже пара, её не режем
_TITLE_HEAD = re.compile(r"^[^:\-–—]{2,80}:\s+")
_ROUND_WORDS = r"(?:\d|מחזור|שלב|סיבוב|גמר|round|runde|jornada|giornata|kolo)"
_ROUND_HEAD = re.compile(rf"^[^,\-–—]*{_ROUND_WORDS}[^,\-–—]*,\s+", re.I)
_TITLE_TAIL = re.compile(rf"\s*,\s*[^,]*{_ROUND_WORDS}[^,]*$", re.I)
#: весь матч в одном написании: «EVERTON X WOLVERHAMPTON» (sporttv.pt).
#: Дефис сюда не входит — он бывает в имени клуба: «Ζλάτε Μόραφτσε -
#: Βράμπλε» = Z. Moravce-Vrable. Одиночная «v» — «vs» только перед именем
#: соперника: слово от 3 знаков («Everton v Wolves») или короткое, за
#: которым есть ещё слово («Rangers v St Mirren»). Голландская пометка
#: женской сборной тоже « V » («Marokko V WO» = Morocco W WO, 08.10), но
#: за ней либо конец, либо одинокий короткий ярлык эталона («WO»)
_VERSUS = re.compile(r"\s(?:x|vs\.?)\s|\sv\s+(?=\S{3}|\S{1,2}\s+\S)", re.I)


def bare_title(title: str) -> str:
    """Заголовок без лиги впереди и тура в конце."""
    title = _ROUND_HEAD.sub("", _TITLE_HEAD.sub("", (title or "").strip()))
    return _TITLE_TAIL.sub("", title).strip()


def _one_team(mine: str, canon: str) -> bool:
    """В написании один клуб, а не весь матч: «EVERTON X WOLVERHAMPTON»
    ложилось алиасом Everton (пакет C, 14.09)."""
    return not (_VERSUS.search(mine) and not _VERSUS.search(canon))


def _entry_sides(game: dict):
    """Написания пары в сырых строках сайтов: именно они придут и завтра,
    поэтому алиасы вяжем и к ним, а не только к склеенному имени игры."""
    for e in game.get("entries", []):
        title = bare_title(e.get("raw_title") or "")
        for sep in _SEPS:
            if sep in title:
                h, _, a = title.partition(sep)
                if 0 < len(h.strip()) <= 60 and 0 < len(a.strip()) <= 60:
                    yield h.strip(" «»\"'."), a.strip(" «»\"'.")
                break


# ── Очередь «Названия»: спрашивать ли владельца ─────────────────────────────

#: в очередь идёт пара «с сомнением», только если ВТОРАЯ команда совпала с
#: эталоном уверенно — тогда игра та же, и сомнение лишь в написании первой.
#: Иначе это соседняя игра того же часа, а не другое написание нашей (#2100,
#: 06.10: «Igokea — Bilbao» легла на «Slavia Prague ERA NBK — Alba Berlin»).
#: Замер 06.10 — пары «с сомнением» в 24 прогонах 20.09–06.10 против копии
#: серверной базы: у ЛОЖНЫХ пар вторая сторона набирает 40–63 («Igokea —
#: Bilbao» 44/60, «Zwitserland — Slowenien» ⇒ «Netherlands — Serbia»
#: 63/57, «Бамберг — Людвигсбург» ⇒ «Wurzburg — Oldenburg» 40/60), а
#: ивритский костяк согласных даёт ложным и 80–85 («נאנסי — פריז» ⇒ «San
#: Ignacio — Pasaia» 80/80; на 85 буквы бессильны вовсе). Верные пары, где
#: сомнительны ОБЕ стороны (новый язык сборных: «Greqi — Holande» = Greece
#: — Netherlands 72/55, «BIELORRÚSSIA — SÃO MARINO» = Belarus — San Marino
#: 70/66), лежат в той же полосе: буквами их от соседа по времени не
#: отличить. Поэтому порог — уверенное совпадение проекта, `SURE`; цена —
#: такие пары в очередь больше не идут (на витрину это не влияет: пара
#: «с сомнением» ничего у игры не ставит). Тот же порог не даёт паре, где
#: ни одна команда не совпала уверенно, и статуса «с сомнением» (`other_game`)
QUEUE_OTHER_SIDE = SURE
#: подсказка, похожая на имя меньше этого, — не подсказка. В истории
#: очереди (330 записей «команда» с 02.09) ни одна подтверждённая пара не
#: была ниже 50 («Meksyk U20 W» → «Mexico U20 W» 50, «Γουλβς» → «Wolves»
#: 54, «Queens Park Rangers» → «QPR» 57), а у трети ложных (8 из 24 —
#: все отсеянные и открытые на 06.10 оказались ложными) сходство 0–47:
#: «Denizli» → «Karsiyaka» 12, «Igokea» → «Slavia Prague ERA NBK» 44
QUEUE_HINT_MIN = 50


def _side_score(name: str, ref: dict, side: str) -> int:
    """Насколько имя похоже на команду эталона на той же стороне пары
    (`side` — «home» или «away»): английское написание flashscore или
    местное той же письменности (`_sides`), что лучше."""
    index = 0 if side == "home" else 1
    best = names.similarity(name, ref.get(side) or "")
    for pair in _sides(ref, _script(name)):
        best = max(best, names.similarity(name, pair[index]))
    return best


def _league_country(label: str) -> str:
    """Страна лиги в написании flashscore — часть до двоеточия:
    «FRANCE: LNB» → «FRANCE», «EUROPE: Champions League» → «EUROPE».
    Без двоеточия (лига словарю не знакома) — пусто."""
    head, colon, _ = (label or "").partition(":")
    return head.strip().upper() if colon else ""


def foreign_league(game: dict, ref: dict) -> bool:
    """Лига игры известна словарю (`league_canon`, ставит `align`), и её
    страна не та, что у лиги эталона: «בולאזאק — רואן» из французской
    баскетбольной лиги (FRANCE: LNB) — не чешский футбол «Velke Hamry —
    Brozany» (CZECH REPUBLIC: 3. CFL), как бы ни сошлись буквы иврита
    (85 и 72, разбор 06.10). Страна неизвестна с любой стороны — не судим.

    Теннис не судим вовсе: у его турнира до двоеточия не страна, а тур и
    разряд («WTA - SINGLES: Beijing (China), hard»), и ярлык сайта «WTA
    1000 Peking» словарь ведёт к парному разряду — одиночки Пекина с
    честными 100 по буквам уходили бы в «мимо» (регресс 06.10, 14 пар)."""
    if (game.get("sport") or "") == "T":
        return False
    mine = _league_country(game.get("league_canon") or "")
    theirs = _league_country(ref.get("league") or "")
    return bool(mine and theirs) and mine != theirs


def other_game(game: dict, ref: dict) -> str:
    """Запись эталона — ДРУГАЯ игра, а не другое написание нашей? Пусто —
    нет, иначе причина. Одна проверка на двоих: сопоставитель (`align`) по
    ней не даёт паре статуса «с сомнением», очередь (`queue_decision`) —
    вопроса владельцу.

      * лига другой страны (`foreign_league`);
      * ни одна команда пары не совпала уверенно (`QUEUE_OTHER_SIDE`):
        «Igokea — Bilbao» ⇒ «Slavia Prague ERA NBK — Alba Berlin», 44/60.
        Сторону-заглушку («TBC») не считаем: судит известная сторона,
        в любой позиции эталона — как в `_pair_score`."""
    if foreign_league(game, ref):
        return "лига другой страны — другая игра"
    sides = [s for s in ("home", "away")
             if not names.is_placeholder(game.get(s) or "")]
    best = 0
    for side in sides:
        name = (game.get(side) or "").strip()
        if len(sides) == 1:
            best = max(_side_score(name, ref, "home"),
                       _side_score(name, ref, "away"))
        elif name:
            best = max(best, _side_score(name, ref, side))
    if best < QUEUE_OTHER_SIDE:
        return "ни одна команда не совпала уверенно — другая игра"
    return ""


def known_team(conn: sqlite3.Connection, name: str, sport: str = "") -> bool:
    """Имя уже есть в библиотеке: это канон команды или её алиас (любого
    языка). Вид спорта команды узнаём по её играм в базе: вид известен и
    не тот — имя чужое (баскетбольный «Bilbao» футбольному не помощник).
    Игр у команды нет или вид игры неизвестен — имя считаем известным."""
    name = (name or "").strip()
    if not name:
        return False
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM teams WHERE canonical_name = ? "
        "UNION SELECT team_id FROM team_aliases WHERE alias = ?",
        (name, name))]
    if not ids:
        return False
    if not sport:
        return True
    marks = ",".join("?" * len(ids))
    sports = {r[0] for r in conn.execute(
        f"SELECT DISTINCT sport FROM events WHERE team_home_id IN ({marks}) "
        f"OR team_away_id IN ({marks})", ids + ids)}
    return not sports or sport in sports


def _flagged(conn: sqlite3.Connection, game: dict) -> bool:
    """У события этой игры в базе уже стоит метка эталона `fs:` — игра
    прежде сопоставлена уверенно. Событие ищем по номеру (сверка задним
    числом даёт `id`) или по паре имён в окне `WINDOW` (заливка обхода;
    порядок команд любой — склейка проверяет и обратный)."""
    if game.get("id"):
        row = conn.execute("SELECT flags FROM events WHERE id = ?",
                           (game["id"],)).fetchone()
        return bool(row) and str(row[0] or "").startswith("fs:")
    start = _parse(game.get("start_kyiv") or "")
    if start is None:
        return False
    home = (game.get("home") or "").strip()
    away = (game.get("away") or "").strip()
    for r in conn.execute(
            "SELECT start_kyiv FROM events WHERE flags LIKE 'fs:%' AND ("
            "(team_home_auto = ? AND team_away_auto = ?) OR "
            "(team_home_auto = ? AND team_away_auto = ?))",
            (home, away, away, home)):
        when = _parse((r[0] or "").replace(" ", "T"))
        if when is not None and abs(when - start) <= WINDOW:
            return True
    return False


def _sure_times(sure: list) -> dict[tuple[str, str], list[datetime]]:
    """Пара имён → время игр, уверенно сопоставленных в этом прогоне."""
    out: dict[tuple[str, str], list[datetime]] = {}
    for game, _, _ in sure:
        start = _parse(game.get("start_kyiv") or "")
        if start is not None:
            key = ((game.get("home") or "").strip(),
                   (game.get("away") or "").strip())
            out.setdefault(key, []).append(start)
    return out


def _in_sure(game: dict, sure_times: dict) -> bool:
    """Та же пара в том же окне уже легла в «уверенные» этого прогона."""
    start = _parse(game.get("start_kyiv") or "")
    key = ((game.get("home") or "").strip(), (game.get("away") or "").strip())
    return start is not None and any(
        abs(start - t) <= WINDOW for t in sure_times.get(key, []))


def queue_decision(conn: sqlite3.Connection, game: dict, ref: dict,
                   side: str, sure_times: dict | None = None
                   ) -> tuple[bool, str]:
    """Ставить ли команду `side` («home»/«away») пары «с сомнением»
    (`align` → «ask») в очередь «Названия» с подсказкой — именем эталона.
    Это ЕДИНСТВЕННОЕ место, где решается вопрос владельцу по команде.
    Возвращает (ставить ли, почему нет). Правила по порядку, решает первое
    сработавшее:

      1. Имени нет или это заглушка («TBC», «Winner QF1») — не команда.
      2. Имя и так совпало с эталоном (сходство ≥ SURE) — спрашивать нечего.
      3. Имя уже в библиотеке — канон команды или её алиас того же вида
         спорта (`known_team`): словарь его знает, а подсказка досталась от
         чужой игры (#2100 «Igokea» → «Slavia Prague ERA NBK», 06.10).
      4. Игра уже уверенно сопоставлена с эталоном: у её события в базе
         метка `fs:` или та же пара в этом прогоне легла в «уверенные» —
         пара «с сомнением» тут лишний сосед по времени.
      5. Вторая команда пары не совпала уверенно (ниже `QUEUE_OTHER_SIDE`)
         или это заглушка — это ДРУГАЯ игра, а не другое написание нашей.
      6. Подсказка похожа на имя меньше `QUEUE_HINT_MIN` — не подсказка.
      7. Лига игры известна словарю, а страна у неё не та, что у лиги
         эталона (`foreign_league`) — другая игра, как бы ни сошлись буквы
         («רואן» → «Brozany»: французский баскетбол против чешского
         футбола, 06.10).

    Ни одно не сработало — спрашиваем: это новое написание реальной
    команды («Queens Park Rangers» → «QPR», когда «West Ham» узнан)."""
    other = "away" if side == "home" else "home"
    mine = (game.get(side) or "").strip()
    hint = (ref.get(side) or "").strip()
    if not mine or not hint or names.is_placeholder(mine):
        return False, "не имя команды"
    if names.similarity(mine, hint) >= SURE:
        return False, "совпало с эталоном"
    if known_team(conn, mine, game.get("sport") or ""):
        return False, "имя уже в библиотеке"
    if _flagged(conn, game) or _in_sure(game, sure_times or {}):
        return False, "игра уже сопоставлена с эталоном"
    second = (game.get(other) or "").strip()
    if not second or names.is_placeholder(second) \
            or _side_score(second, ref, other) < QUEUE_OTHER_SIDE:
        return False, "вторая команда не совпала — другая игра"
    if _side_score(mine, ref, side) < QUEUE_HINT_MIN:
        return False, "подсказка не похожа на имя"
    if foreign_league(game, ref):
        return False, "лига другой страны — другая игра"
    return True, ""


def apply(conn: sqlite3.Connection, aligned: dict) -> tuple[int, int]:
    """Уверенные — в библиотеку, сомнительные — в очередь. Возвращает
    (сколько имён закреплено, сколько легло в очередь)."""
    fixed = queued = 0
    for game, ref, _ in aligned["sure"]:
        fill_placeholder(game, ref)
        for mine, canon in ((game["home"], ref["home"]),
                            (game["away"], ref["away"])):
            mine, canon = (mine or "").strip(), (canon or "").strip()
            if mine and canon and _learnable(mine, canon):
                dictionary.remember_team(conn, mine, canon)
                fixed += 1
        for h, a in _entry_sides(game):
            # ивритскую строку с английским эталоном буквами не сверить —
            # сверяем с ивритским же именем игры, раз пара уже уверенная
            if h != game["home"] and _learnable(h, ref["home"]) and (
                    names.similarity(h, ref["home"]) >= SURE
                    or (_script(h) == "he"
                        and names.similarity(h, game["home"]) >= SURE)):
                dictionary.remember_team(conn, h, ref["home"])
                fixed += 1
            if a != game["away"] and _learnable(a, ref["away"]) and (
                    names.similarity(a, ref["away"]) >= SURE
                    or (_script(a) == "he"
                        and names.similarity(a, game["away"]) >= SURE)):
                dictionary.remember_team(conn, a, ref["away"])
                fixed += 1
        league, canon_league = (game.get("league") or "").strip(), \
            (ref.get("league") or "").strip()
        if league and canon_league and league != canon_league \
                and league_worthy(league) \
                and not conn.execute(
                    "SELECT 1 FROM leagues WHERE canonical_name = ?",
                    (league,)).fetchone():
            # ярлык, сам являющийся каноном другой лиги, к чужой не вяжем:
            # «BRAZIL: Serie A Betano» успел стать алиасом LaLiga, Португалии
            # и Сербии разом (кейс #688, 04.09)
            dictionary.remember_league(conn, league, canon_league)
    # пары «с сомнением» — владельцу, но только настоящие вопросы:
    # решает `queue_decision`, правила — там
    sure_times = _sure_times(aligned["sure"])
    for game, ref, _ in aligned["ask"]:
        for side in ("home", "away"):
            ask, _why = queue_decision(conn, game, ref, side, sure_times)
            if ask and dictionary.enqueue(conn, "team", game[side].strip(),
                                          suggestion=ref[side].strip()):
                queued += 1
    conn.commit()
    return fixed, queued


def retime(aligned: dict) -> int:
    """Подтянуть время к эталону (решение владельца 31.08: «время важно,
    сверять по flashscore»). Случай Cosmote 03.09: их гид ставил Эспаньол —
    Севилью на 19:00 при настоящих 22:00, и игра висела дублем — окно
    склейки её не догоняло. Правим только ОДИНОЧНЫЕ игры (1–2 источника):
    когда время подтверждают три сайта и больше, а эталон спорит — верим
    большинству и не трогаем."""
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo as _Z
    fixed = 0
    for game, ref, _ in aligned["sure"]:
        if len(game.get("entries") or []) > 2:
            continue
        ours, its = _parse(game.get("start_kyiv") or ""), \
            _parse(ref.get("start_kyiv") or "")
        if ours is None or its is None:
            continue
        if _td(minutes=40) < abs(ours - its) <= WINDOW:
            game["start_kyiv"] = its.strftime("%Y-%m-%dT%H:%M")
            game["start_utc"] = its.replace(tzinfo=_Z("Europe/Kyiv")) \
                .astimezone(_Z("UTC")).strftime("%Y-%m-%dT%H:%M")
            fixed += 1
    return fixed


def stamp(conn: sqlite3.Connection, aligned: dict) -> int:
    """Пишет fs_id матча в events.flags — ПОСЛЕ заливки игр, когда события
    уже в базе. Пригодится межпрогонной сверке и сверке времени."""
    stamped = 0
    for game, ref, _ in aligned["sure"]:
        if ref.get("fs_id"):
            stamped += conn.execute(
                "UPDATE events SET flags = ? WHERE team_home_auto = ? "
                "AND team_away_auto = ? AND start_kyiv = ?",
                (f"fs:{ref['fs_id']}", game["home"], game["away"],
                 game["start_kyiv"])).rowcount
    conn.commit()
    return stamped
