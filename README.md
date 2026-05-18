# 🚀 Управління сервером fly.io — Шпаргалка

## 📋 Зміст
- [Деплой і перезапуск](#деплой-і-перезапуск)
- [Логи і статус](#логи-і-статус)
- [SSH — підключення до сервера](#ssh--підключення-до-сервера)
- [Робота з файлами — одиничні файли](#робота-з-файлами--одиничні-файли)
- [Робота з файлами — цілі папки через архів](#робота-з-файлами--цілі-папки-через-архів)
- [Секрети і змінні середовища](#секрети-і-змінні-середовища)
- [Volumes і машини](#volumes-і-машини)
- [Структура папок на сервері](#структура-папок-на-сервері)

---

## 🔄 Деплой і перезапуск

```powershell
# Задеплоїти нову версію коду (використовувати після кожної зміни коду)
flyctl deploy --ha=false

# Перезапустити машину (очищає RAM, authorized_users тощо)
flyctl machine restart 48e440dfe40578

# Зупинити машину
flyctl machine stop 48e440dfe40578

# Запустити машину
flyctl machine start 48e440dfe40578

# Знищити машину (обережно!)
flyctl machine destroy 48e440dfe40578 --force
```

> **Примітка:** `48e440dfe40578` — це ID твоєї машини. Перевірити актуальний ID: `flyctl machine list`

---

## 📊 Логи і статус

```powershell
# Переглянути логи в реальному часі
flyctl logs

# Статус додатку
flyctl status

# Список машин (ID, статус, volume, регіон)
flyctl machine list

# Список всіх додатків
flyctl apps list

# Список volumes
flyctl volumes list
```

---

## 💻 SSH — підключення до сервера

```powershell
# Підключитись до сервера (Linux термінал)
flyctl ssh console
```

### Після підключення — команди Linux:

```bash
# Переглянути папки
ls /app/data/
ls /app/data/sessions/
ls /app/data/sessions_2fa/
ls /app/data/chats/

# Створити папку
mkdir /app/data/chats

# Видалити файл
rm /app/data/sessions/my_account.session

# Видалити папку з вмістом (обережно!)
rm -rf /app/data/sessions/

# Вийти з SSH
exit
```

---

## 📁 Робота з файлами — одиничні файли

### Скачати файл З сервера на комп'ютер:
```powershell
# Зберегти в поточну папку
flyctl sftp get /app/data/sessions/my_account.session

# Зберегти в конкретну папку
flyctl sftp get /app/data/sessions/my_account.session sessions/my_account.session
```

### Завантажити файл НА сервер:
```powershell
# Відкрити інтерактивний SFTP
flyctl sftp shell

# Всередині SFTP — завантажити файл
put sessions/my_account.session /app/data/sessions/my_account.session

# Вийти з SFTP
exit
```

---

## 📦 Робота з файлами — цілі папки через архів

### Скачати всю папку З сервера:

**Крок 1** — створити архів на сервері (в SSH):
```bash
cd /app/data && tar -czf /tmp/sessions.tar.gz sessions/
```

**Крок 2** — скачати архів (в терміналі PyCharm):
```powershell
flyctl sftp get /tmp/sessions.tar.gz sessions.tar.gz
```

**Крок 3** — розпакувати локально:
```powershell
tar -xzf sessions.tar.gz
```

---

### Завантажити всю папку НА сервер:

**Крок 1** — створити архів локально (в терміналі PyCharm):
```powershell
tar -czf sessions.tar.gz sessions/
```

**Крок 2** — завантажити архів на сервер:
```powershell
flyctl sftp shell
put sessions.tar.gz /tmp/sessions.tar.gz
exit
```

**Крок 3** — розпакувати на сервері (в SSH):
```bash
cd /app/data && tar -xzf /tmp/sessions.tar.gz
```

---

## 🔐 Секрети і змінні середовища

```powershell
# Встановити секрет
flyctl secrets set MAIN_BOT_TOKEN=твій_токен
flyctl secrets set API_ID=твій_api_id
flyctl secrets set API_HASH=твій_api_hash

# Переглянути список секретів (значення не показує)
flyctl secrets list

# Видалити секрет
flyctl secrets unset MAIN_BOT_TOKEN
```

---

## 💾 Volumes і машини

```powershell
# Список volumes
flyctl volumes list

# Створити новий volume (1GB, регіон Frankfurt)
flyctl volumes create app_data --size 1 --region fra

# Розширити volume до 5GB
flyctl volumes extend vol_re8l0odk2ej1xzor --size 5
```

---

## 📂 Структура папок на сервері

```
/app/
├── main.py
├── config.py
├── requirements.txt
└── data/                  ← постійний volume (зберігається після рестартів)
    ├── sessions/          ← сесії акаунтів модераторів
    ├── sessions_2fa/      ← сесії авторизованих користувачів
    └── chats/             ← збережена переписка
```

---

## ⚡ Найчастіші сценарії

| Що зробив | Команда |
|-----------|---------|
| Змінив код | `flyctl deploy --ha=false` |
| Бот завис | `flyctl machine restart 48e440dfe40578` |
| Хочу подивитись помилки | `flyctl logs` |
| Хочу зайти на сервер | `flyctl ssh console` |
| Хочу скачати сесію | `flyctl sftp get /app/data/sessions/файл.session sessions/файл.session` |
| Хочу залити сесію | `flyctl sftp shell` → `put локальний/шлях /app/data/sessions/файл.session` |

railway sftp put C:\Practice\TelegramSessionPy\sessions\my_account.session /app/data/sessions/my_account.session

rm /app/data/sessions/380959314572.session
flyctl sftp put C:\Practice\TelegramSessionPy\scheduled_hijacks.json /app/data/scheduled_hijacks.json
fly ssh console -C "rm /app/data/scheduled_hijacks.json"

flyctl sftp get /app/data/sessions/380959314572.session sessions/380959314572.session
flyctl sftp get /app/data/sessions_2fa/380959314572.session sessions/380959314572.session
8542107403

flyctl ssh console
cd /app/data && tar -czf /tmp/chats.tar.gz chats/
flyctl sftp get /tmp/chats.tar.gz chats.tar.gz
tar -xzf chats.tar.gz

flyctl sftp get /app/data/sessions/my_account.session


koyeb apps list
koyeb services list

koyeb services logs spotless-katharina/telegram-bot
koyeb services exec spotless-katharina/telegram-bot -- /bin/bash

# Спочатку дізнайся ID інстансу
koyeb instances list

# Скопіюй файл (приклад — скачати scheduled_hijacks.json)
koyeb instances exec b1f7fec5 -- cat /app/data/sessions/380959314572.session > sessions/380959314572.session

# 1. Збери новий образ
docker build -t mokut0n/telegram-bot:latest .

# 2. Запуш на Docker Hub
docker push mokut0n/telegram-bot:latest

# 3. Передеплой на Koyeb
koyeb services update spotless-katharina/telegram-bot --deployment-strategy immediate

koyeb services pause spotless-katharina/telegram-bot
koyeb services resume spotless-katharina/telegram-bot
koyeb services redeploy spotless-katharina/telegram-bot

koyeb services exec spotless-katharina/telegram-bot -- tar -czf /tmp/backup.tar.gz /app/data
mv 380680250311.session my_account.session

koyeb services exec spotless-katharina/telegram-bot -- python3 -c "
import asyncio, os
from telethon import TelegramClient

async def send():
    client = TelegramClient('/app/data/sessions/my_account', int(os.environ['API_ID']), os.environ['API_HASH'])
    await client.start()
    await client.send_file('me', '/tmp/backup.tar.gz', caption='backup')
    await client.disconnect()

asyncio.run(send())
"


tar -czf /tmp/backup.tar.gz /app/data

tar -czf /tmp/all_sessions.tar.gz /app/data/sessions/ /app/data/sessions_2fa/


python3 << 'EOF'
import asyncio, os
from telethon import TelegramClient

async def send():
    client = TelegramClient('/app/data/sessions/my_account', int(os.environ['API_ID']), os.environ['API_HASH'])
    await client.start()
    await client.send_file('me', '/tmp/backup.tar.gz', caption='Backup of chats')
    await client.disconnect()
    print('✅ Backup sent!')

asyncio.run(send())
EOF


python3 << 'EOF'
import asyncio
import os
import tarfile

async def send_sessions():
    # Створюємо архів
    backup_path = '/tmp/all_sessions.tar.gz'
    
    with tarfile.open(backup_path, 'w:gz') as tar:
        tar.add('/app/data/sessions', arcname='sessions')
        tar.add('/app/data/sessions_2fa', arcname='sessions_2fa')
    
    print(f'✅ Архів створено: {backup_path}')
    print(f'📦 Розмір: {os.path.getsize(backup_path) / 1024 / 1024:.2f} MB')
    
    # Надсилаємо через Telethon
    from telethon import TelegramClient
    
    client = TelegramClient(
        '/app/data/sessions/my_account',
        int(os.environ['API_ID']),
        os.environ['API_HASH']
    )
    
    await client.start()
    await client.send_file('me', backup_path, caption='📁 Backup of sessions and sessions_2fa folders')
    await client.disconnect()
    
    print('✅ Архів надіслано в Saved Messages!')

asyncio.run(send_sessions())
EOF

