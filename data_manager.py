import sqlite3
from typing import List, Dict, Optional
import json

class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Создание таблицы папок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создание таблицы каналов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER,
                    channel_id INTEGER,
                    username TEXT,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scanned_at TIMESTAMP,
                    FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE
                )
            """)
            
            # Создание таблицы сообщений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER,
                    message_id INTEGER,
                    text TEXT,
                    date TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()

    # Методы для работы с папками
    def create_folder(self, name: str) -> bool:
        """Создание новой папки"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO folders (name) VALUES (?)", (name,))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def delete_folder(self, folder_id: int) -> bool:
        """Удаление папки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_folders(self) -> List[Dict]:
        """Получение списка всех папок"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.id, f.name, f.created_at, COUNT(c.id) as channel_count
                FROM folders f
                LEFT JOIN channels c ON f.id = c.folder_id
                GROUP BY f.id
            """)
            return [{"id": row[0], "name": row[1], "created_at": row[2], "channel_count": row[3]} for row in cursor.fetchall()]

    # Методы для работы с каналами
    def add_channel(self, folder_id: int, channel_id: int, username: str, title: str) -> bool:
        """Добавление канала в папку"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO channels (folder_id, channel_id, username, title)
                    VALUES (?, ?, ?, ?)
                """, (folder_id, channel_id, username, title))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def delete_channel(self, channel_id: int) -> bool:
        """Удаление канала"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_channels(self, folder_id: Optional[int] = None) -> List[Dict]:
        """Получение списка каналов в папке"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # Возвращает строки как словари
                cursor = conn.cursor()
                
                if folder_id is not None:
                    print(f"Получение каналов для папки {folder_id}")
                    cursor.execute("""
                        SELECT id, channel_id, username, title, created_at, last_scanned_at
                        FROM channels WHERE folder_id = ?
                    """, (folder_id,))
                    
                    result = [{
                        "id": row["id"],
                        "channel_id": row["channel_id"],
                        "username": row["username"],
                        "title": row["title"],
                        "created_at": row["created_at"],
                        "last_scanned_at": row["last_scanned_at"]
                    } for row in cursor.fetchall()]
                else:
                    print("Получение всех каналов")
                    cursor.execute("""
                        SELECT c.id, c.channel_id, c.username, c.title, c.created_at, c.last_scanned_at, f.name as folder_name
                        FROM channels c
                        JOIN folders f ON c.folder_id = f.id
                    """)
                    
                    result = [{
                        "id": row["id"],
                        "channel_id": row["channel_id"],
                        "username": row["username"],
                        "title": row["title"],
                        "created_at": row["created_at"],
                        "last_scanned_at": row["last_scanned_at"],
                        "folder_name": row["folder_name"]
                    } for row in cursor.fetchall()]
                
                print(f"Найдено каналов: {len(result)}")
                return result
        except Exception as e:
            print(f"Ошибка при получении каналов: {e}")
            return []

    # Методы для работы с сообщениями
    def save_messages(self, channel_id: int, messages: List[Dict]) -> bool:
        """Сохранение сообщений канала"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT INTO messages (channel_id, message_id, text, date)
                    VALUES (?, ?, ?, ?)
                """, [(channel_id, msg["id"], msg["text"], msg["date"]) for msg in messages])
                
                # Обновление времени последнего сканирования
                cursor.execute("""
                    UPDATE channels
                    SET last_scanned_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (channel_id,))
                
                conn.commit()
                return True
        except sqlite3.Error:
            return False

    def get_messages(self, channel_id: int, limit: int = 100) -> List[Dict]:
        """Получение сообщений канала"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT message_id, text, date, created_at
                FROM messages
                WHERE channel_id = ?
                ORDER BY date DESC
                LIMIT ?
            """, (channel_id, limit))
            return [{
                "message_id": row[0],
                "text": row[1],
                "date": row[2],
                "created_at": row[3]
            } for row in cursor.fetchall()] 