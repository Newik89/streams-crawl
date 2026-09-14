#!/bin/sh
# Стук серверу из обхода (владелец 14.09.2026): $1 — start | done-ok | done-fail,
# WHAT — что за обход. Само слово по сети не ездит: только время и подпись
# HMAC-SHA256 от «время.событие.что». Секретов нет (форк) — тихо выходим.
if [ -z "$HOOK_SECRET" ] || [ -z "$HOOK_URL" ]; then
  echo "стук не настроен — пропускаем"
  exit 0
fi
EVENT="$1"
STAMP=$(date +%s)
SIGN=$(printf '%s' "$STAMP.$EVENT.$WHAT" | openssl dgst -sha256 -hmac "$HOOK_SECRET" -r | cut -d' ' -f1)
CODE=$(curl -s -o /tmp/knock -w '%{http_code}' -m 30 -X POST \
  -H "X-Stamp: $STAMP" -H "X-Event: $EVENT" -H "X-What: $WHAT" -H "X-Sign: $SIGN" \
  "$HOOK_URL")
echo "стук $EVENT ($WHAT): $CODE $(cat /tmp/knock 2>/dev/null)"
[ "$CODE" = "200" ]
