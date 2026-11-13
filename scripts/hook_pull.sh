#!/bin/sh
# Забор по стуку GitHub «обход закончен» (владелец 14.09.2026). Запускает
# app/crawl_hook.py через systemd-run. Нового на GitHub нет — ничего не
# делаем; есть — обычный /root/streams-update.sh под общим замком с заборами
# по часам (cron), чтобы два забора не шли разом.
cd /root/streams-schedule || exit 1
LOG=/var/log/streams-update.log
remote=$(timeout 30 git ls-remote origin refs/heads/main | cut -f1)
if [ -z "$remote" ]; then
  echo "$(date '+%d.%m %H:%M') стук: GitHub не ответил на ls-remote" >> $LOG
  exit 1
fi
if [ "$remote" = "$(git rev-parse HEAD)" ]; then
  # аудит 13.11: код забран, а заливка после него упала — раньше стук уходил
  # с «нового нет», и сбор лежал невлитым до забора по часам. Теперь упавшую
  # заливку повторяем (не больше двух раз подряд — scripts/import_retry.py)
  if venv/bin/python scripts/import_retry.py >> $LOG 2>&1; then
    echo "$(date '+%d.%m %H:%M') стук: нового нет, но прошлая заливка упала — повторяю" >> $LOG
    exec flock -w 900 /run/streams-update.lock /root/streams-update.sh
  fi
  echo "$(date '+%d.%m %H:%M') стук: нового на GitHub нет" >> $LOG
  exit 0
fi
echo "$(date '+%d.%m %H:%M') стук: забираю ${remote%${remote#???????}}" >> $LOG
exec flock -w 900 /run/streams-update.lock /root/streams-update.sh
