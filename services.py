import aiohttp
import asyncio
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from duckduckgo_search import DDGS
import re
import g4f
from g4f.Provider import (
    DDG,
    Blackbox,
    Liaobots,
    PollinationsAI
)
from database import Database
from telegram_client import TelegramAnalyzer
import logging
from logger_config import setup_logger
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

class WebAnalyzer:
    def __init__(self):
        self.session = None
        self.ddgs = DDGS()
        self.db = Database()
        self.telegram = TelegramAnalyzer()
        self.logger = setup_logger(__name__)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        try:
            # Инициализация Telegram-клиента
            await self.telegram.connect()
            self.logger.info("Инициализация Telegram-клиента выполнена успешно")
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации Telegram-клиента: {e}")
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        await self.telegram.disconnect()

    # Методы для работы с папками
    async def create_folder(self, name: str) -> Dict[str, Any]:
        """Создание новой папки для каналов"""
        try:
            success = self.db.create_folder(name)
            if success:
                return {"status": "success", "message": f"Папка '{name}' создана"}
            return {"status": "error", "message": "Папка с таким именем уже существует"}
        except Exception as e:
            self.logger.error(f"Error creating folder: {e}")
            return {"status": "error", "message": str(e)}

    async def delete_folder(self, folder_id: int) -> Dict[str, Any]:
        """Удаление папки"""
        try:
            success = self.db.delete_folder(folder_id)
            if success:
                return {"status": "success", "message": "Папка удалена"}
            return {"status": "error", "message": "Папка не найдена"}
        except Exception as e:
            self.logger.error(f"Error deleting folder: {e}")
            return {"status": "error", "message": str(e)}

    async def get_folders(self) -> List[Dict]:
        """Получение списка папок"""
        try:
            self.logger.info("Получение списка папок из базы данных")
            folders = self.db.get_folders()
            self.logger.info(f"Получено папок: {len(folders)}")
            for folder in folders:
                self.logger.info(f"Папка: {folder}")
            return folders
        except Exception as e:
            self.logger.error(f"Ошибка получения папок: {e}")
            return []

    # Методы для работы с каналами
    async def add_channel(self, folder_id: int, channel_username: str) -> Dict[str, Any]:
        """Добавление канала в папку"""
        try:
            # Убеждаемся, что Telegram клиент подключен
            await self.telegram.connect()
            self.logger.info(f"Соединение с Telegram установлено для добавления канала {channel_username}")
            
            # Получение информации о канале через Telethon
            channel_info = await self.telegram.get_channel_info(channel_username)
            if not channel_info:
                self.logger.error(f"Канал {channel_username} не найден")
                return {"status": "error", "message": "Канал не найден"}

            self.logger.info(f"Получена информация о канале: {channel_info}")
            # Добавление канала в базу данных
            success = self.db.add_channel(
                folder_id,
                channel_info["id"],
                channel_info["username"],
                channel_info["title"]
            )

            if success:
                self.logger.info(f"Канал {channel_info['title']} добавлен в папку {folder_id}")
                return {
                    "status": "success",
                    "message": f"Канал {channel_info['title']} добавлен в папку",
                    "channel_info": channel_info
                }
            return {"status": "error", "message": "Канал уже существует в этой папке"}

        except Exception as e:
            self.logger.error(f"Error adding channel: {e}")
            return {"status": "error", "message": str(e)}

    async def delete_channel(self, channel_id: int) -> Dict[str, Any]:
        """Удаление канала"""
        try:
            success = self.db.delete_channel(channel_id)
            if success:
                return {"status": "success", "message": "Канал удален"}
            return {"status": "error", "message": "Канал не найден"}
        except Exception as e:
            self.logger.error(f"Error deleting channel: {e}")
            return {"status": "error", "message": str(e)}

    async def get_channels(self, folder_id: Optional[int] = None) -> List[Dict]:
        """Получение списка каналов"""
        return self.db.get_channels(folder_id)

    async def analyze_channel(self, channel_username: str, days: int = 7) -> Dict[str, Any]:
        """Анализ Telegram-канала"""
        max_retries = 5
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                # Убеждаемся, что Telegram клиент подключен
                await self.telegram.connect()
                self.logger.info(f"Соединение с Telegram установлено для анализа канала {channel_username}")
                
                # Получение и анализ контента канала
                self.logger.info(f"Начинаем анализ канала {channel_username}")
                analysis = await asyncio.wait_for(
                    self.telegram.analyze_channel_content(channel_username, days),
                    timeout=120.0  # Увеличенный таймаут для анализа канала
                )
                
                if "error" in analysis:
                    self.logger.error(f"Ошибка при анализе канала: {analysis['error']}")
                    return {"status": "error", "message": analysis["error"]}

                # Сохранение сообщений в базу данных
                channel_info = await self.telegram.get_channel_info(channel_username)
                if channel_info:
                    channel_id = channel_info.get("id")
                    # Можно реализовать сохранение сообщений, если нужно
                
                return {
                    "status": "success",
                    "messages": analysis.get("messages", []),
                    "topics": analysis.get("topics", []),
                    "sentiment": analysis.get("sentiment", {}),
                    "channel_info": channel_info
                }
                
            except asyncio.TimeoutError:
                self.logger.warning(f"Таймаут при анализе канала {channel_username} (попытка {attempt+1}/{max_retries})")
                if attempt == max_retries - 1:
                    return {"status": "error", "message": f"Превышен таймаут при анализе канала после {max_retries} попыток"}
                
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
                
            except (ConnectionError, TimeoutError) as e:
                self.logger.warning(f"Ошибка соединения при анализе канала {channel_username}: {e} (попытка {attempt+1}/{max_retries})")
                if attempt == max_retries - 1:
                    return {"status": "error", "message": f"Ошибка сети при анализе канала: {str(e)}"}
                
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
                
            except Exception as e:
                self.logger.error(f"Непредвиденная ошибка при анализе канала {channel_username}: {e}")
                return {"status": "error", "message": f"Ошибка при анализе канала: {str(e)}"}
            
            finally:
                try:
                    await self.telegram.disconnect()
                except Exception as e:
                    self.logger.warning(f"Ошибка при закрытии соединения с Telegram: {e}")
        
        return {"status": "error", "message": "Превышено максимальное количество попыток"}

    async def search_news(self, query: str, max_results: int = 10) -> List[Dict[str, str]]:
        """Поиск новостей по запросу"""
        try:
            results = list(self.ddgs.text(query, region='ru-ru', max_results=max_results))
            return [
                {
                    'title': result['title'],
                    'link': result['link'],
                    'snippet': result.get('body', '')
                }
                for result in results
            ]
        except Exception as e:
            self.logger.error(f"Error in news search: {e}")
            return []

    async def fetch_article(self, url: str) -> Dict[str, str]:
        """Получение содержимого статьи"""
        if not self.session:
            self.session = aiohttp.ClientSession()
            
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    return self._extract_article_content(html)
                return {"error": f"Failed to fetch article: {response.status}"}
        except Exception as e:
            return {"error": f"Error fetching article: {e}"}

    def _extract_article_content(self, html: str) -> Dict[str, str]:
        """Извлечение содержимого статьи"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Удаление ненужных элементов
        for tag in soup.find_all(['script', 'style', 'iframe', 'form']):
            tag.decompose()
            
        # Поиск основного контента
        article = {
            "title": "",
            "content": "",
            "summary": "",
            "keywords": set()
        }
        
        # Извлечение заголовка
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            article["title"] = title_tag.get_text().strip()
            
        # Извлечение основного контента
        content_tags = soup.find_all(['p', 'h2', 'h3', 'h4', 'li'])
        content = []
        for tag in content_tags:
            text = tag.get_text().strip()
            if len(text) > 50:  # Фильтрация коротких фрагментов
                content.append(text)
                article["keywords"].update(self._extract_topics(text))
                
        article["content"] = "\n\n".join(content)
        
        # Создание краткого содержания
        article["summary"] = self._create_summary(article["content"])
        
        return article

    def _extract_topics(self, text: str) -> set:
        """Извлечение тем из текста"""
        # Поиск хештегов
        hashtags = set(re.findall(r'#(\w+)', text))
        
        # Поиск ключевых слов
        keywords = set()
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Простой список стоп-слов
        stop_words = {'и', 'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как', 'а', 'то', 'все', 'она', 'так', 'его', 'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'ее', 'мне', 'было', 'вот', 'от', 'меня', 'еще', 'нет', 'о', 'из', 'ему'}
        
        for word in words:
            if len(word) > 3 and word not in stop_words:
                keywords.add(word)
                
        return hashtags.union(keywords)

    def _create_summary(self, text: str, max_length: int = 200) -> str:
        """Создание краткого содержания текста"""
        # Разбиение на предложения
        sentences = re.split(r'[.!?]+', text)
        
        # Выбор наиболее важных предложений
        important_sentences = []
        current_length = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # Проверка длины
            if current_length + len(sentence) > max_length:
                break
                
            important_sentences.append(sentence)
            current_length += len(sentence)
            
        return '. '.join(important_sentences) + '...' if important_sentences else ""


from telethon import TelegramClient, events
from telethon.tl.types import Channel, Message
from typing import List, Dict, Optional, Union
import asyncio
import logging
from logger_config import setup_logger
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

class TelegramAnalyzer:
    def __init__(self):
        self.api_id = int(os.getenv('TELEGRAM_API_ID'))
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.client = None
        self.logger = setup_logger(__name__)

    async def connect(self):
        """Подключение к Telegram"""
        if not self.client:
            self.client = TelegramClient('anon', self.api_id, self.api_hash)
            await self.client.start()

    async def disconnect(self):
        """Отключение от Telegram"""
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def get_channel_info(self, channel_username: str) -> Optional[Dict]:
        """Получение информации о канале"""
        try:
            # Убедимся, что клиент подключен
            if not self.client or not self.client.is_connected():
                await self.connect()
                self.logger.info(f"Соединение с Telegram установлено для получения информации о канале {channel_username}")
            
            self.logger.info(f"Получение информации о канале {channel_username}")
            channel = await self.client.get_entity(channel_username)
            if isinstance(channel, Channel):
                return {
                    "id": channel.id,
                    "username": channel_username.replace("@", ""),
                    "title": channel.title
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting channel info: {e}")
            return None

    async def get_messages(self, 
                         channel_username: str,
                         limit: int = 100,
                         offset_date: Optional[datetime] = None) -> List[Dict]:
        """Получение сообщений из канала"""
        try:
            # Убедимся, что клиент подключен
            if not self.client or not self.client.is_connected():
                await self.connect()
                self.logger.info(f"Соединение с Telegram установлено для получения сообщений из канала {channel_username}")
            
            messages = []
            self.logger.info(f"Получение канала {channel_username}")
            channel = await self.client.get_entity(channel_username)
            
            # Если дата не указана, берем сообщения за последние 7 дней
            if not offset_date:
                offset_date = datetime.now() - timedelta(days=7)
            
            self.logger.info(f"Загрузка сообщений из канала {channel_username} с {offset_date}")
            async for message in self.client.iter_messages(
                channel,
                limit=limit,
                offset_date=offset_date
            ):
                if not message.text:
                    continue
                    
                messages.append({
                    "id": message.id,
                    "text": message.text,
                    "date": message.date.isoformat(),
                    "views": getattr(message, 'views', 0),
                    "forwards": getattr(message, 'forwards', 0)
                })
            
            self.logger.info(f"Загружено {len(messages)} сообщений из канала {channel_username}")
            return messages
            
        except Exception as e:
            self.logger.error(f"Error getting messages: {e}")
            return []

    async def analyze_channel_content(self, 
                                    channel_username: str,
                                    days: int = 7) -> Dict:
        """Анализ контента канала"""
        try:
            # Убедимся, что клиент подключен
            if not self.client or not self.client.is_connected():
                await self.connect()
                self.logger.info(f"Соединение с Telegram установлено для анализа канала {channel_username}")
            
            self.logger.info(f"Получение сообщений из канала {channel_username} за последние {days} дней")
            offset_date = datetime.now() - timedelta(days=days)
            messages = await self.get_messages(
                channel_username,
                limit=1000,
                offset_date=offset_date
            )
            
            # Базовая статистика
            total_messages = len(messages)
            total_views = sum(msg.get('views', 0) for msg in messages)
            total_forwards = sum(msg.get('forwards', 0) for msg in messages)
            
            # Средние значения
            avg_views = total_views / total_messages if total_messages > 0 else 0
            avg_forwards = total_forwards / total_messages if total_messages > 0 else 0
            
            self.logger.info(f"Анализ завершен. Получено {total_messages} сообщений.")
            return {
                "period_days": days,
                "total_messages": total_messages,
                "total_views": total_views,
                "total_forwards": total_forwards,
                "avg_views": avg_views,
                "avg_forwards": avg_forwards,
                "messages": messages[:100]  # Возвращаем только последние 100 сообщений
            }
            
        except Exception as e:
            self.logger.error(f"Error analyzing channel: {e}")
            return {
                "error": str(e),
                "messages": []
            }

    async def __aenter__(self):
        await self.connect()
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
        
import logging
import colorlog

def setup_logger(name=None, level=logging.INFO):
    """Настройка цветного логирования для модулей бота"""
    # Создаем форматтер с цветами для разных уровней логирования
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(blue)s[%(name)s]%(reset)s %(message)s",
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    )

    # Создаем обработчик для вывода в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Если имя не указано, настраиваем корневой логгер
    if name is None:
        logger = logging.getLogger()
        # Очищаем существующие обработчики корневого логгера
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
    else:
        logger = logging.getLogger(name)
        # Отключаем наследование обработчиков от родительских логгеров
        logger.propagate = False
        # Очищаем существующие обработчики
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    # Устанавливаем уровень логирования
    logger.setLevel(level)
    # Добавляем обработчик в логгер
    logger.addHandler(console_handler)

    return logger 