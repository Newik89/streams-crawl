"""Синоним канала по написанию (книга 174; слова владельца 22.11.2026: «наш
список, это я мог отредактировать, но отредактированное должно быть как
синоним того что у нас уже было и если поменялось написание его тоже добавить
в синоним, например было 2 пробела стал 1 или убрался знак восклицания»;
про «Tvr Sport HD» и «TVR Sport HD» — «так это тоже синоним»).

Случай (находка тени книги 171, сбор 20.11.2026): у сайта с несколькими
каналами разборщик берёт только каналы из списка владельца (`include` плана
обхода ← `source_channels`) и сверяет имя БУКВА В БУКВУ. ntvplus.tv пишет
«МАТЧ! АРЕНА  (HD)» с двумя пробелами, в списке — с одним: 128 строк за 6
дней не доходили до базы. programetv.ro: имя из адреса «Tvr Sport HD», в
списке «TVR Sport HD» — 58 строк, канал ни разу не был прочитан. Синонимы
канала в базе есть (`channel_aliases`), но сверка со списком стоит раньше.

ПРАВИЛА (что случилось → что делаем):
  Н1. Имя с сайта стоит в списке буква в букву — это оно, как раньше.
  Н2. Буква в букву не нашлось — сверяем НАПИСАНИЕ (`key`): без регистра,
      пробелов и знаков препинания («МАТЧ! АРЕНА  (HD)» = «матч арена hd»,
      «Tvr» = «TVR»). Знаки, которыми каналы РАЗЛИЧАЮТСЯ, остаются: «+»,
      «&», «/», «#», «*», «@» — «ספורט 5+» и «ספורט 5» разные каналы.
  Н3. Одно написание у двух имён списка сайта («DAZN LALIGA» и «DAZN
      LaLiga») — не угадываем: строка решается, как раньше.
  Н4. Сошлось — строка идёт дальше с именем ИЗ СПИСКА (на витрине канал
      называется, как у владельца), написание сайта остаётся в строке
      (`SPELLED`) и едет в games.json (`KEY`: сайт → написание → имя списка).
  Н5. Сервер после заливки (`after_import`) записывает написание сайта
      синонимом того же канала (`channel_aliases`) и один раз пишет строку
      в «Прогоны»: владелец видит, что сайт сменил написание.
  Н6. Сверка стоит в ОДНОМ месте: список, который получают все разборщики
      (`Listed` — множество, у которого `in` знает Н1–Н3), и проход по
      строкам после разборщика (`apply`). Разборщики не правятся.
"""
from __future__ import annotations

import unicodedata

#: ключ games.json: {сайт: {написание с сайта: имя из списка владельца}}
KEY = "написания_каналов"
#: пометка строки: как канал написан на сайте (имя строки — из списка)
SPELLED = "написание_сайта"
WHO = "написание канала"
#: Н2: знаки, которыми различаются каналы, — в написании остаются
_KEEP = frozenset("+&/#*@")


def key(name: str | None) -> str:
    """Н2: написание имени для сверки — буквы, цифры и знаки `_KEEP`."""
    text = unicodedata.normalize("NFKC", name or "").casefold()
    return "".join(ch for ch in text if ch.isalnum() or ch in _KEEP)


class Listed(set):
    """Н6: список каналов сайта из списка владельца. Обычное множество имён,
    но `имя in список` верно и для другого написания того же имени (Н1–Н3)."""

    def __init__(self, names=()):
        super().__init__(n for n in names or () if isinstance(n, str))
        seen: dict[str, list[str]] = {}
        for name in self:
            seen.setdefault(key(name), []).append(name)
        # Н3: написание, общее для двух имён списка, не считается
        self._one = {k: v[0] for k, v in seen.items() if k and len(v) == 1}

    def listed(self, name) -> str:
        """Имя из списка для имени с сайта; пусто — такого канала в списке нет."""
        if not isinstance(name, str):
            return ""
        if set.__contains__(self, name):                                   # Н1
            return name
        return self._one.get(key(name), "")                                # Н2, Н3

    def __contains__(self, name) -> bool:
        return bool(self.listed(name))


def apply(programs: list, listed, found: dict) -> int:
    """Н4: строкам, чей канал написан иначе, чем в списке, ставит имя из
    списка. `found` — {написание с сайта: имя из списка} по этому сайту
    (копится за сбор). Возвращает, сколько строк поправлено."""
    if not isinstance(listed, Listed):
        return 0
    fixed = 0
    for program in programs or []:
        name = program.channel_raw or ""
        same = listed.listed(name)
        if not same or same == name:
            continue
        found[name] = same
        program.extra = {**(program.extra or {}), SPELLED: name}
        program.channel_raw = same
        fixed += 1
    return fixed


def words(found: dict) -> list[str]:
    """Строки для лога разбора: «сайт: «как на сайте» = «как в списке»»."""
    return [f"{site}: «{spelled}» = «{name}»"
            for site, pairs in sorted((found or {}).items())
            for spelled, name in sorted((pairs or {}).items())]


def after_import(conn, data: dict) -> list[str]:
    """Н5 на сервере (зовёт `games_import.py`): написание сайта — синонимом
    канала. Канал ищется по имени из списка у этого же сайта (сначала в
    синонимах, потом в списке каналов сайта). Синоним уже записан либо канал
    не найден — молчим. Возвращает строки, написанные в «Прогоны»."""
    from . import watch
    said: list[str] = []
    for site, pairs in sorted((data.get(KEY) or {}).items()):
        source = conn.execute(
            "SELECT id FROM sources WHERE domain IN (?, ?)",
            (site, "www." + site)).fetchone()
        if source is None or not isinstance(pairs, dict):
            continue
        source_id = source[0]
        for spelled, name in sorted(pairs.items()):
            row = conn.execute(
                "SELECT channel_id FROM channel_aliases WHERE alias = ? AND source_id = ?",
                (name, source_id)).fetchone() or conn.execute(
                "SELECT channel_id FROM source_channels WHERE raw_name = ? AND source_id = ? "
                "AND channel_id IS NOT NULL", (name, source_id)).fetchone()
            if row is None:
                continue
            if conn.execute("SELECT 1 FROM channel_aliases WHERE alias = ? AND source_id = ?",
                            (spelled, source_id)).fetchone():
                continue
            conn.execute("INSERT INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, ?)",
                         (row[0], spelled, source_id))
            conn.commit()
            line = f"{site} пишет канал «{spelled}», в списке он «{name}» — написание записано синонимом"
            watch.note(conn, line, who=WHO)
            said.append(line)
    return said
