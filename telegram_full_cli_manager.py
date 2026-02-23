"""
🚀 Повноцінний CLI Manager для Telegram акаунтів через Telethon
Автор: Ваше ім'я
Версія: 2.0

Можливості:
- Вибір сесії зі списку доступних
- Перегляд та управління діалогами
- Читання та відправка повідомлень
- Завантаження медіа-файлів
- Пересилання повідомлень
- Пошук у чатах
- Керування групами та каналами
- Експорт історії чатів
- Масові операції
- Статистика та аналітика
"""

import asyncio
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.panel import Panel
from rich.text import Text
from rich import box


# Імпорт конфігурації
try:
    from config import API_ID, API_HASH, SESSION_FOLDER, CHAT_FOLDER
except ImportError:
    print("❌ Не знайдено файл config.py!")
    print("Створіть файл config.py з наступним вмістом:")
    print("""
API_ID = your_api_id
API_HASH = "your_api_hash"
SESSION_FOLDER = "sessions"
CHAT_FOLDER = "chats"
    """)
    exit(1)

# Ініціалізація Rich console
console = Console()


class TelegramCLIManager:
    """Клас для управління Telegram акаунтом через CLI"""

    def __init__(self, session_name: str):
        self.session_path = os.path.join(SESSION_FOLDER, f"{session_name}.session")
        self.session_name = session_name
        self.client = TelegramClient(self.session_path, API_ID, API_HASH)
        self.dialogs = []
        self.current_dialog = None
        self.me = None

    async def connect(self) -> bool:
        """Підключення до Telegram"""
        try:
            await self.client.connect()

            if not await self.client.is_user_authorized():
                console.print("[red]❌ Сесія не авторизована або застаріла![/red]")
                return False

            self.me = await self.client.get_me()

            # Красивий банер підключення
            welcome_panel = Panel(
                f"[bold green]✅ Успішно підключено![/bold green]\n\n"
                f"[cyan]👤 Ім'я:[/cyan] {self.me.first_name} {self.me.last_name or ''}\n"
                f"[cyan]📱 Username:[/cyan] @{self.me.username or 'немає'}\n"
                f"[cyan]📞 Телефон:[/cyan] {self.me.phone}\n"
                f"[cyan]🆔 ID:[/cyan] {self.me.id}\n"
                f"[cyan]⭐ Premium:[/cyan] {'✅ Так' if self.me.premium else '❌ Ні'}\n"
                f"[cyan]🤖 Бот:[/cyan] {'✅ Так' if self.me.bot else '❌ Ні'}",
                title=f"🚀 Telegram CLI Manager v2.0",
                subtitle=f"Сесія: {self.session_name}",
                border_style="green",
                box=box.DOUBLE
            )
            console.print(welcome_panel)

            return True

        except SessionPasswordNeededError:
            console.print("[red]❌ Акаунт захищений 2FA паролем![/red]")
            console.print("[yellow]Цей CLI не підтримує 2FA. Вимкніть 2FA або створіть нову сесію.[/yellow]")
            return False
        except Exception as e:
            console.print(f"[red]❌ Помилка підключення: {e}[/red]")
            return False

    async def load_dialogs(self, limit: int = 100, force_reload: bool = False) -> None:
        """Завантаження діалогів"""
        if self.dialogs and not force_reload:
            return

        self.dialogs = []

        console.print(f"[cyan]📥 Завантаження діалогів (max {limit})...[/cyan]")

        idx = 0
        async for dialog in self.client.iter_dialogs(limit=limit):
            idx += 1
            self.dialogs.append({
                'index': idx,
                'id': dialog.id,
                'name': dialog.name,
                'entity': dialog.entity,
                'dialog': dialog,
                'is_user': dialog.is_user,
                'is_group': dialog.is_group,
                'is_channel': dialog.is_channel,
                'unread_count': dialog.unread_count,
                'archived': dialog.archived
            })

            # Показуємо прогрес кожні 10 діалогів
            if idx % 10 == 0:
                console.print(f"[dim]Завантажено {idx}...[/dim]", end='\r')

        console.print(f"[green]✅ Завантажено {len(self.dialogs)} діалогів[/green]\n")

    async def show_dialogs(self, filter_type: Optional[str] = None, show_archived: bool = False) -> None:
        """Показати список діалогів з фільтрацією"""
        await self.load_dialogs()

        # Фільтрація
        filtered_dialogs = self.dialogs.copy()

        if filter_type == "users":
            filtered_dialogs = [d for d in filtered_dialogs if d['is_user']]
        elif filter_type == "groups":
            filtered_dialogs = [d for d in filtered_dialogs if d['is_group']]
        elif filter_type == "channels":
            filtered_dialogs = [d for d in filtered_dialogs if d['is_channel']]

        if not show_archived:
            filtered_dialogs = [d for d in filtered_dialogs if not d['archived']]

        # Створення таблиці
        table = Table(
            title="💬 Ваші діалоги",
            title_style="bold cyan",
            box=box.ROUNDED,
            show_lines=False
        )

        table.add_column("N", style="bold cyan", justify="center", width=6, no_wrap=True)
        table.add_column("ID", style="dim", width=20, no_wrap=True)
        table.add_column("Назва", style="bold", width=30)
        table.add_column("Тип", justify="center", width=14, no_wrap=True)
        table.add_column("Username", style="yellow", width=20)
        table.add_column("💬", justify="center", width=5)
        table.add_column("📊", justify="center", width=5)

        for dialog in filtered_dialogs:
            # Визначення типу
            if dialog['is_user']:
                dialog_type = "[blue]👤 Юзер[/blue]"
            elif dialog['is_group']:
                dialog_type = "[green]👥 Група[/green]"
            else:
                dialog_type = "[magenta]📢 Канал[/magenta]"

            # Username
            username = getattr(dialog['entity'], 'username', None)
            username_display = f"@{username}" if username else "[dim]немає[/dim]"

            # Непрочитані
            unread = f"[red]{dialog['unread_count']}[/red]" if dialog['unread_count'] > 0 else "[dim]-[/dim]"

            # Архів
            archive_mark = "📦" if dialog['archived'] else ""

            # DEBUG
            # console.print(f"[dim]DEBUG: index={dialog['index']}, id={dialog['id']}, name={dialog['name'][:20]}[/dim]")

            table.add_row(
                str(dialog['index']),
                str(dialog['id']),
                dialog['name'][:30],
                dialog_type,
                username_display,
                unread,
                archive_mark
            )

        console.print(table)

        # Статистика
        stats_panel = Panel(
            f"[cyan]📊 Статистика:[/cyan]\n"
            f"Всього: {len(filtered_dialogs)} | "
            f"👤 Користувачів: {sum(1 for d in filtered_dialogs if d['is_user'])} | "
            f"👥 Груп: {sum(1 for d in filtered_dialogs if d['is_group'])} | "
            f"📢 Каналів: {sum(1 for d in filtered_dialogs if d['is_channel'])} | "
            f"💬 Непрочитаних: {sum(d['unread_count'] for d in filtered_dialogs)}",
            border_style="blue"
        )
        console.print(stats_panel)

    async def show_messages(self, dialog_index: int, limit: int = 30,
                           search_query: Optional[str] = None) -> None:
        """Показати повідомлення з діалогу"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        self.current_dialog = dialog

        console.print(f"\n[cyan]📨 Завантаження повідомлень з:[/cyan] [bold]{dialog['name']}[/bold]")

        # Таблиця повідомлень
        table = Table(
            title=f"📨 Повідомлення: {dialog['name']}",
            box=box.SIMPLE,
            show_lines=False
        )

        table.add_column("ID", style="dim", width=8)
        table.add_column("Дата", style="cyan", width=16)
        table.add_column("Від", style="yellow", width=15)
        table.add_column("Повідомлення", style="white", width=60)
        table.add_column("📎", justify="center", width=3)

        messages_list = []

        console.print("[dim]Завантаження...[/dim]")

        async for message in self.client.iter_messages(
            dialog['entity'],
            limit=limit,
            search=search_query
        ):
            messages_list.append(message)

        # Відображення повідомлень (від старих до нових)
        for message in reversed(messages_list):
            # Відправник
            if message.out:
                sender = "[green]Ви ➡️[/green]"
            else:
                if message.sender:
                    sender_name = getattr(message.sender, 'first_name', 'Unknown')
                    sender = f"[blue]{sender_name}[/blue]"
                else:
                    sender = "[dim]Невідомий[/dim]"

            # Текст повідомлення
            text = message.text or "[dim italic]медіа/стікер[/dim italic]"
            text = text.replace('\n', ' ')[:60]

            # Медіа маркер
            media_mark = "📎" if message.media else ""

            # Дата
            date_str = message.date.strftime('%d.%m.%y %H:%M')

            table.add_row(
                str(message.id),
                date_str,
                sender,
                text,
                media_mark
            )

        console.print(table)
        console.print(f"\n[dim]Показано {len(messages_list)} повідомлень[/dim]")

    async def send_message(self, dialog_index: int, text: str) -> None:
        """Відправити повідомлення"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        try:
            await self.client.send_message(dialog['entity'], text)
            console.print(f"[green]✅ Повідомлення відправлено до:[/green] [bold]{dialog['name']}[/bold]")
        except FloodWaitError as e:
            console.print(f"[red]⏱ FloodWait! Зачекайте {e.seconds} секунд[/red]")
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")

    async def send_file(self, dialog_index: int, file_path: str, caption: str = "") -> None:
        """Відправити файл"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        if not os.path.exists(file_path):
            console.print(f"[red]❌ Файл не знайдено: {file_path}[/red]")
            return

        try:
            console.print(f"[cyan]📤 Відправка файлу...[/cyan]")

            await self.client.send_file(
                dialog['entity'],
                file_path,
                caption=caption
            )

            console.print(f"[green]✅ Файл відправлено до:[/green] [bold]{dialog['name']}[/bold]")
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")

    async def download_media(self, dialog_index: int, limit: int = 10,
                            download_folder: str = "downloads") -> None:
        """Завантажити медіа з діалогу"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        os.makedirs(download_folder, exist_ok=True)

        # Створюємо підпапку для кожного діалогу
        dialog_folder = os.path.join(download_folder, str(dialog['id']))
        os.makedirs(dialog_folder, exist_ok=True)

        downloaded_count = 0
        checked = 0

        console.print(f"[cyan]📥 Пошук та завантаження медіа...[/cyan]")

        async for message in self.client.iter_messages(dialog['entity'], limit=limit):
            checked += 1
            if message.media:
                try:
                    console.print(f"[dim]Завантаження {checked}/{limit}...[/dim]", end='\r')
                    file_path = await self.client.download_media(
                        message,
                        file=dialog_folder
                    )
                    if file_path:
                        filename = os.path.basename(file_path)
                        console.print(f"[green]✅ {filename}[/green]" + " " * 20)
                        downloaded_count += 1
                except Exception as e:
                    console.print(f"[red]❌ Помилка завантаження: {e}[/red]")

        console.print(f"\n[green]📥 Завантажено {downloaded_count} файлів у:[/green] {dialog_folder}/")

    async def export_chat_history(self, dialog_index: int, limit: int = 1000,
                                  output_format: str = "json") -> None:
        """Експорт історії чату"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        os.makedirs(CHAT_FOLDER, exist_ok=True)

        messages_list = []
        count = 0

        console.print(f"[cyan]💾 Експорт історії чату...[/cyan]")

        async for message in self.client.iter_messages(dialog['entity'], limit=limit):
            count += 1
            if count % 100 == 0:
                console.print(f"[dim]Зібрано {count} повідомлень...[/dim]", end='\r')

            msg_data = {
                'id': message.id,
                'date': message.date.isoformat(),
                'sender_id': message.sender_id,
                'text': message.text,
                'has_media': bool(message.media),
                'is_outgoing': message.out,
                'views': getattr(message, 'views', None),
                'forwards': getattr(message, 'forwards', None)
            }
            messages_list.append(msg_data)

        # Збереження
        filename = f"{dialog['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if output_format == "json":
            filepath = os.path.join(CHAT_FOLDER, f"{filename}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(messages_list, f, ensure_ascii=False, indent=2)
        elif output_format == "txt":
            filepath = os.path.join(CHAT_FOLDER, f"{filename}.txt")
            with open(filepath, 'w', encoding='utf-8') as f:
                for msg in reversed(messages_list):
                    date = datetime.fromisoformat(msg['date']).strftime('%Y-%m-%d %H:%M:%S')
                    sender = "Ви" if msg['is_outgoing'] else f"ID:{msg['sender_id']}"
                    text = msg['text'] or "[медіа]"
                    f.write(f"[{date}] {sender}: {text}\n")

        console.print(f"[green]✅ Експортовано {len(messages_list)} повідомлень у:[/green] {filepath}")

    async def forward_messages(self, from_dialog_index: int, to_dialog_index: int,
                              message_ids: List[int]) -> None:
        """Пересилання повідомлень"""
        from_dialog = self.get_dialog_by_index(from_dialog_index)
        to_dialog = self.get_dialog_by_index(to_dialog_index)

        if not from_dialog or not to_dialog:
            return

        try:
            await self.client.forward_messages(
                to_dialog['entity'],
                message_ids,
                from_dialog['entity']
            )
            console.print(
                f"[green]✅ Переслано {len(message_ids)} повідомлень[/green]\n"
                f"[cyan]З:[/cyan] {from_dialog['name']}\n"
                f"[cyan]До:[/cyan] {to_dialog['name']}"
            )
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")

    async def delete_messages(self, dialog_index: int, message_ids: List[int],
                             revoke: bool = True) -> None:
        """Видалення повідомлень"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        try:
            await self.client.delete_messages(
                dialog['entity'],
                message_ids,
                revoke=revoke
            )
            console.print(
                f"[green]✅ Видалено {len(message_ids)} повідомлень з:[/green] {dialog['name']}"
            )
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")

    async def mark_as_read(self, dialog_index: int) -> None:
        """Позначити всі повідомлення як прочитані"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        try:
            await self.client.send_read_acknowledge(dialog['entity'])
            console.print(f"[green]✅ Всі повідомлення позначено як прочитані в:[/green] {dialog['name']}")
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")

    async def search_in_chat(self, dialog_index: int, query: str, limit: int = 50) -> None:
        """Пошук у чаті"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        console.print(f"\n[cyan]🔍 Пошук '{query}' у:[/cyan] [bold]{dialog['name']}[/bold]")

        results = []
        async for message in self.client.iter_messages(
            dialog['entity'],
            search=query,
            limit=limit
        ):
            results.append(message)

        if not results:
            console.print("[yellow]❌ Нічого не знайдено[/yellow]")
            return

        # Відображення результатів
        table = Table(title=f"🔍 Результати пошуку: '{query}'", box=box.ROUNDED)
        table.add_column("Дата", style="cyan", width=16)
        table.add_column("Від", style="yellow", width=15)
        table.add_column("Фрагмент", style="white", width=70)

        for message in results:
            sender = "Ви" if message.out else (
                getattr(message.sender, 'first_name', 'Unknown') if message.sender else 'Unknown'
            )
            text = (message.text or '')[:70]
            date_str = message.date.strftime('%d.%m.%y %H:%M')

            table.add_row(date_str, sender, text)

        console.print(table)
        console.print(f"[green]✅ Знайдено {len(results)} результатів[/green]")

    async def get_chat_statistics(self, dialog_index: int, days: int = 30) -> None:
        """Статистика чату"""
        dialog = self.get_dialog_by_index(dialog_index)
        if not dialog:
            return

        date_limit = datetime.now() - timedelta(days=days)

        total_messages = 0
        my_messages = 0
        other_messages = 0
        media_count = 0
        total_chars = 0

        console.print(f"[cyan]📊 Аналіз чату '{dialog['name']}'...[/cyan]")

        async for message in self.client.iter_messages(dialog['entity'], limit=None):
            if message.date < date_limit:
                break

            total_messages += 1
            if total_messages % 100 == 0:
                console.print(f"[dim]Проаналізовано {total_messages} повідомлень...[/dim]", end='\r')

            if message.out:
                my_messages += 1
            else:
                other_messages += 1

            if message.media:
                media_count += 1

            if message.text:
                total_chars += len(message.text)

        # Розрахунок відсотків
        my_percent = my_messages/total_messages*100 if total_messages > 0 else 0
        other_percent = other_messages/total_messages*100 if total_messages > 0 else 0
        media_percent = media_count/total_messages*100 if total_messages > 0 else 0
        avg_length = total_chars//total_messages if total_messages > 0 else 0

        # Панель статистики
        stats_panel = Panel(
            f"[bold cyan]📊 Статистика чату: {dialog['name']}[/bold cyan]\n\n"
            f"[yellow]📅 Період:[/yellow] Останні {days} днів\n\n"
            f"[cyan]💬 Всього повідомлень:[/cyan] {total_messages}\n"
            f"[green]➡️  Від вас:[/green] {my_messages} ({my_percent:.1f}%)\n"
            f"[blue]⬅️  Від співрозмовника:[/blue] {other_messages} ({other_percent:.1f}%)\n"
            f"[magenta]📎 З медіа:[/magenta] {media_count} ({media_percent:.1f}%)\n\n"
            f"[yellow]📝 Середня довжина повідомлення:[/yellow] {avg_length} символів",
            border_style="cyan",
            box=box.DOUBLE
        )
        console.print(stats_panel)

    def get_dialog_by_index(self, index: int) -> Optional[Dict]:
        """Отримати діалог за індексом або ID"""
        # Спочатку шукаємо по індексу
        for dialog in self.dialogs:
            if dialog['index'] == index:
                return dialog

        # Якщо не знайшли по індексу, шукаємо по ID
        for dialog in self.dialogs:
            if dialog['id'] == index:
                return dialog

        console.print(f"[red]❌ Діалог #{index} не знайдено![/red]")
        console.print(f"[yellow]💡 Підказка: використовуйте номер зі стовпця '№' або ID зі стовпця 'ID'[/yellow]")
        return None

    async def disconnect(self) -> None:
        """Відключення від Telegram"""
        await self.client.disconnect()
        console.print("\n[yellow]👋 Відключено від Telegram[/yellow]")


def select_session() -> Optional[str]:
    """Вибір сесії зі списку доступних"""
    console.clear()

    # Заголовок
    title_panel = Panel(
        "[bold cyan]🚀 Telegram CLI Manager v2.0[/bold cyan]\n"
        "[yellow]Виберіть сесію для роботи[/yellow]",
        border_style="blue",
        box=box.DOUBLE
    )
    console.print(title_panel)

    # Перевірка існування папки
    if not os.path.exists(SESSION_FOLDER):
        console.print(f"[red]❌ Папка {SESSION_FOLDER}/ не знайдена![/red]")
        os.makedirs(SESSION_FOLDER, exist_ok=True)
        console.print(f"[green]✅ Створено папку {SESSION_FOLDER}/[/green]")
        return None

    # Пошук сесій
    session_files = [
        f[:-8] for f in os.listdir(SESSION_FOLDER)
        if f.endswith('.session')
    ]

    if not session_files:
        console.print(f"[red]❌ В папці {SESSION_FOLDER}/ не знайдено жодної сесії![/red]")
        console.print("[yellow]Створіть сесію та помістіть її у папку sessions/[/yellow]")
        return None

    # Таблиця з сесіями
    table = Table(
        title="📱 Доступні сесії",
        box=box.ROUNDED,
        show_lines=False
    )
    table.add_column("№", style="bold cyan", justify="center", width=6, no_wrap=True)
    table.add_column("Номер телефону", style="green", width=20)
    table.add_column("Файл", style="yellow", width=30)
    table.add_column("Розмір", style="blue", justify="right", width=12)
    table.add_column("Дата створення", style="magenta", width=20)

    for idx, session_name in enumerate(session_files, 1):
        file_path = os.path.join(SESSION_FOLDER, f"{session_name}.session")
        file_size = os.path.getsize(file_path)
        file_size_kb = f"{file_size / 1024:.1f} KB"

        modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        modified_str = modified_time.strftime('%d.%m.%Y %H:%M')

        table.add_row(
            Text(str(idx), style="bold cyan"),
            session_name,
            f"{session_name}.session",
            file_size_kb,
            modified_str
        )

    console.print(table)
    console.print(f"\n[dim]Знайдено {len(session_files)} сесій[/dim]\n")

    # Вибір сесії
    console.print("[cyan]Введіть номер телефону без .session (наприклад: 380123456789)[/cyan]")
    console.print("[cyan]Або введіть номер сесії зі списку (1, 2, 3...)[/cyan]")
    console.print("[dim]Для виходу натисніть Ctrl+C[/dim]\n")

    choice = Prompt.ask("Ваш вибір")

    # Перевірка чи це індекс зі списку
    try:
        idx = int(choice)
        if 1 <= idx <= len(session_files):
            return session_files[idx - 1]
    except ValueError:
        pass

    # Якщо не індекс - вважаємо що це номер телефону
    if choice in session_files:
        return choice

    console.print(f"[red]❌ Сесію '{choice}' не знайдено![/red]")
    return None


async def main_menu(manager: TelegramCLIManager) -> None:
    """Головне меню"""
    while True:
        console.print("\n" + "=" * 80)

        menu_panel = Panel(
            "[bold cyan]📋 ОСНОВНЕ МЕНЮ:[/bold cyan]\n\n"
            "[yellow]1.[/yellow]  📋 Показати діалоги (всі)\n"
            "[yellow]2.[/yellow]  👤 Показати тільки користувачів\n"
            "[yellow]3.[/yellow]  👥 Показати тільки групи\n"
            "[yellow]4.[/yellow]  📢 Показати тільки канали\n"
            "[yellow]5.[/yellow]  📦 Показати заархівовані\n\n"
            "[bold cyan]💬 РОБОТА З ПОВІДОМЛЕННЯМИ:[/bold cyan]\n\n"
            "[yellow]6.[/yellow]  📨 Читати повідомлення з діалогу\n"
            "[yellow]7.[/yellow]  ✉️  Відправити повідомлення\n"
            "[yellow]8.[/yellow]  📎 Відправити файл\n"
            "[yellow]9.[/yellow]  🔍 Пошук у чаті\n"
            "[yellow]10.[/yellow] ✅ Позначити як прочитане\n\n"
            "[bold cyan]📥 МЕДІА ТА ЕКСПОРТ:[/bold cyan]\n\n"
            "[yellow]11.[/yellow] 📥 Завантажити медіа з діалогу\n"
            "[yellow]12.[/yellow] 💾 Експортувати історію чату (JSON)\n"
            "[yellow]13.[/yellow] 📄 Експортувати історію чату (TXT)\n\n"
            "[bold cyan]⚙️  ДОДАТКОВІ ФУНКЦІЇ:[/bold cyan]\n\n"
            "[yellow]14.[/yellow] ➡️  Переслати повідомлення\n"
            "[yellow]15.[/yellow] 🗑️  Видалити повідомлення\n"
            "[yellow]16.[/yellow] 📊 Статистика чату\n"
            "[yellow]17.[/yellow] ℹ️  Мій профіль\n"
            "[yellow]18.[/yellow] 🔄 Оновити діалоги\n\n"
            "[yellow]0.[/yellow]  🚪 Вийти",
            border_style="blue",
            box=box.ROUNDED
        )
        console.print(menu_panel)

        choice = Prompt.ask("\n[bold cyan]Оберіть дію[/bold cyan]", default="1")

        try:
            # ОСНОВНЕ МЕНЮ
            if choice == "0":
                if Confirm.ask("[yellow]Ви впевнені, що хочете вийти?[/yellow]"):
                    break

            elif choice == "1":
                await manager.show_dialogs()

            elif choice == "2":
                await manager.show_dialogs(filter_type="users")

            elif choice == "3":
                await manager.show_dialogs(filter_type="groups")

            elif choice == "4":
                await manager.show_dialogs(filter_type="channels")

            elif choice == "5":
                await manager.show_dialogs(show_archived=True)

            # РОБОТА З ПОВІДОМЛЕННЯМИ
            elif choice == "6":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                limit = IntPrompt.ask("[cyan]Скільки повідомлень показати[/cyan]", default=30)
                await manager.show_messages(dialog_idx, limit)

            elif choice == "7":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                message_text = Prompt.ask("[cyan]Текст повідомлення[/cyan]")

                if Confirm.ask(f"[yellow]Відправити '{message_text[:50]}...'?[/yellow]"):
                    await manager.send_message(dialog_idx, message_text)

            elif choice == "8":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                file_path = Prompt.ask("[cyan]Шлях до файлу[/cyan]")
                caption = Prompt.ask("[cyan]Підпис (опціонально)[/cyan]", default="")
                await manager.send_file(dialog_idx, file_path, caption)

            elif choice == "9":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                query = Prompt.ask("[cyan]Що шукаємо?[/cyan]")
                limit = IntPrompt.ask("[cyan]Максимум результатів[/cyan]", default=50)
                await manager.search_in_chat(dialog_idx, query, limit)

            elif choice == "10":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                await manager.mark_as_read(dialog_idx)

            # МЕДІА ТА ЕКСПОРТ
            elif choice == "11":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                limit = IntPrompt.ask("[cyan]Скільки файлів перевірити[/cyan]", default=20)
                folder = Prompt.ask("[cyan]Папка для завантаження[/cyan]", default="downloads")
                await manager.download_media(dialog_idx, limit, folder)

            elif choice == "12":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                limit = IntPrompt.ask("[cyan]Скільки повідомлень експортувати[/cyan]", default=1000)
                await manager.export_chat_history(dialog_idx, limit, "json")

            elif choice == "13":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                limit = IntPrompt.ask("[cyan]Скільки повідомлень експортувати[/cyan]", default=1000)
                await manager.export_chat_history(dialog_idx, limit, "txt")

            # ДОДАТКОВІ ФУНКЦІЇ
            elif choice == "14":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                from_idx = IntPrompt.ask("[cyan]З якого діалогу (номер)[/cyan]")
                to_idx = IntPrompt.ask("[cyan]В який діалог (номер)[/cyan]")
                msg_ids_str = Prompt.ask("[cyan]ID повідомлень (через кому)[/cyan]")
                msg_ids = [int(x.strip()) for x in msg_ids_str.split(',')]
                await manager.forward_messages(from_idx, to_idx, msg_ids)

            elif choice == "15":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                msg_ids_str = Prompt.ask("[cyan]ID повідомлень для видалення (через кому)[/cyan]")
                msg_ids = [int(x.strip()) for x in msg_ids_str.split(',')]
                revoke = Confirm.ask("[yellow]Видалити для всіх?[/yellow]", default=True)

                if Confirm.ask(f"[red]Видалити {len(msg_ids)} повідомлень?[/red]"):
                    await manager.delete_messages(dialog_idx, msg_ids, revoke)

            elif choice == "16":
                if not manager.dialogs:
                    console.print("[yellow]⚠️  Спочатку завантажте діалоги (опція 1)[/yellow]")
                    continue

                dialog_idx = IntPrompt.ask("[cyan]Номер діалогу (стовпець '№' або 'ID')[/cyan]")
                days = IntPrompt.ask("[cyan]За скільки днів[/cyan]", default=30)
                await manager.get_chat_statistics(dialog_idx, days)

            elif choice == "17":
                profile_panel = Panel(
                    f"[bold cyan]ℹ️  Інформація про профіль[/bold cyan]\n\n"
                    f"[yellow]👤 Ім'я:[/yellow] {manager.me.first_name} {manager.me.last_name or ''}\n"
                    f"[yellow]📱 Username:[/yellow] @{manager.me.username or 'немає'}\n"
                    f"[yellow]📞 Телефон:[/yellow] {manager.me.phone}\n"
                    f"[yellow]🆔 ID:[/yellow] {manager.me.id}\n"
                    f"[yellow]⭐ Premium:[/yellow] {'✅ Так' if manager.me.premium else '❌ Ні'}\n"
                    f"[yellow]🤖 Бот:[/yellow] {'✅ Так' if manager.me.bot else '❌ Ні'}\n"
                    f"[yellow]🔒 Верифікований:[/yellow] {'✅ Так' if manager.me.verified else '❌ Ні'}",
                    border_style="cyan",
                    box=box.DOUBLE
                )
                console.print(profile_panel)

            elif choice == "18":
                limit = IntPrompt.ask("[cyan]Скільки діалогів завантажити[/cyan]", default=100)
                await manager.load_dialogs(limit, force_reload=True)
                console.print("[green]✅ Діалоги оновлено[/green]")

            else:
                console.print("[red]❌ Невірний вибір![/red]")

        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️  Дію скасовано[/yellow]")
        except ValueError as e:
            console.print(f"[red]❌ Помилка вводу: {e}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Помилка: {e}[/red]")


async def main():
    """Головна функція"""
    try:
        # Вибір сесії
        session_name = select_session()

        if not session_name:
            console.print("\n[red]Програму завершено[/red]")
            return

        # Створення менеджера
        manager = TelegramCLIManager(session_name)

        # Підключення
        if not await manager.connect():
            return

        # Головне меню
        await main_menu(manager)

    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Переривання користувачем[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Критична помилка: {e}[/red]")
    finally:
        if 'manager' in locals():
            await manager.disconnect()
        console.print("\n[green]Дякуємо за використання! 👋[/green]\n")


if __name__ == "__main__":
    # Інструкція для встановлення
    console.print("[dim]Для запуску встановіть залежності:[/dim]")
    console.print("[dim]pip install telethon rich[/dim]\n")

    asyncio.run(main())