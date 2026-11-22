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
А где разборщик регистр не различал (movistarplus.es: «DAZN LALIGA» на
сайте, «DAZN LaLiga» в списке), новое написание рождало в базе ВТОРОЙ канал.

ПРАВИЛА (что случилось → что делаем):
  Н1. Имя с сайта стоит в списке буква в букву — это оно, как раньше.
  Н2. Буква в букву не нашлось — сверяем НАПИСАНИЕ (`key`): без регистра,
      пробелов и знаков препинания («МАТЧ! АРЕНА  (HD)» = «матч арена hd»,
      «Tvr» = «TVR»). Знаки, которыми каналы РАЗЛИЧАЮТСЯ, остаются: «+»,
      «&», «/», «#», «*», «@» — «ספורט 5+» и «ספורט 5» разные каналы.
  Н3. Одно написание у двух имён списка сайта — не угадываем: строка
      решается, как раньше.
  Н4. Разбор сбора: список, который получают все разборщики, — `Listed`
      (множество, у которого `in` знает Н1–Н3), поэтому строка с другим
      написанием проходит сверку `channel not in channels` у любого
      разборщика; сами разборщики не правятся. Строка идёт дальше С
      НАПИСАНИЕМ САЙТА; что сошлось по написанию, пишется в лог разбора и в
      games.json (`note`, ключ `KEY`) — это детектор «сайт пишет канал иначе».
  Н5. Сервер при заливке (`resolve`, зовёт `store._channel_id`): у написания
      сайта УЖЕ есть свой синоним — канал тот, на который он указывает, как
      раньше (сложившиеся привязки не трогаем). Синонима нет — прежде чем
      заводить новый канал, ищем по написанию канал списка этого сайта:
      нашёлся один — строка идёт на ЕГО канал (на витрине он называется,
      как у владельца), написание сайта записывается синонимом этого канала,
      в «Прогоны» — одна строка. Канала у имени списка ещё нет (ни разу не
      был прочитан) — он заводится с именем ИЗ СПИСКА.
"""
from __future__ import annotations

import unicodedata

#: ключ games.json: {сайт: {написание с сайта: имя из списка владельца}}
KEY = "написания_каналов"
WHO = "написание канала"
#: Н2: знаки, которыми различаются каналы, — в написании остаются
_KEEP = frozenset("+&/#*@")


def key(name: str | None) -> str:
    """Н2: написание имени для сверки — буквы, цифры и знаки `_KEEP`."""
    text = unicodedata.normalize("NFKC", name or "").casefold()
    return "".join(ch for ch in text if ch.isalnum() or ch in _KEEP)


class Listed(set):
    """Н4: список каналов сайта из списка владельца. Обычное множество имён,
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


def note(programs: list, listed, found: dict) -> int:
    """Н4: детектор — у каких строк канал написан иначе, чем в списке.
    Строки НЕ меняются. `found` — {написание с сайта: имя из списка} по
    этому сайту (копится за сбор). Возвращает число таких строк."""
    if not isinstance(listed, Listed):
        return 0
    seen = 0
    for program in programs or []:
        name = program.channel_raw or ""
        same = listed.listed(name)
        if same and same != name:
            found[name] = same
            seen += 1
    return seen


def words(found: dict) -> list[str]:
    """Строки для лога разбора: «сайт: «как на сайте» = «как в списке»»."""
    return [f"{site}: «{spelled}» = «{name}»"
            for site, pairs in sorted((found or {}).items())
            for spelled, name in sorted((pairs or {}).items())]


def resolve(conn, raw: str, source) -> int | None:
    """Н5 на сервере: канал для написания сайта, у которого своего синонима
    нет. `source` — строка таблицы `sources` (нужны `id` и `country`).
    Возвращает id канала из списка этого сайта либо None — тогда канал
    решается, как раньше (заводится новый)."""
    if source is None or not raw:
        return None
    source_id = source["id"]
    spelled = key(raw)
    if not spelled:
        return None
    same = {r[0]: r[1] for r in conn.execute(
        "SELECT raw_name, channel_id FROM source_channels WHERE source_id = ?", (source_id,))
        if r[0] != raw and key(r[0]) == spelled}
    if len(same) != 1:                                                     # Н3
        return None
    name, channel_id = next(iter(same.items()))
    alias = conn.execute("SELECT channel_id FROM channel_aliases WHERE alias = ? AND source_id = ?",
                         (name, source_id)).fetchone()
    if alias is not None:
        channel_id = alias[0]
    if channel_id is None:
        # канал списка ни разу не был прочитан — заводим его с именем из списка
        from . import channel_rules, dictionary
        country = (source["country"] or "") or "??"
        channel_id = dictionary.remember_channel(conn, name, channel_rules.apply(name, country),
                                                 country, source_id)
    conn.execute("INSERT OR IGNORE INTO channel_aliases (channel_id, alias, source_id) VALUES (?, ?, ?)",
                 (channel_id, raw, source_id))
    conn.commit()
    from . import watch
    site = source["domain"] if "domain" in source.keys() else "сайт"
    watch.note(conn, f"{site} пишет канал «{raw}», в списке он «{name}» — написание записано синонимом",
               who=WHO)
    return channel_id
