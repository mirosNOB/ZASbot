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
        try:
            # Убеждаемся, что Telegram клиент подключен
            await self.telegram.connect()
            self.logger.info(f"Соединение с Telegram установлено для анализа канала {channel_username}")
            
            # Получение и анализ контента канала
            self.logger.info(f"Начинаем анализ канала {channel_username}")
            analysis = await self.telegram.analyze_channel_content(channel_username, days)
            
            if "error" in analysis:
                self.logger.error(f"Ошибка при анализе канала: {analysis['error']}")
                return {"status": "error", "message": analysis["error"]}

            # Сохранение сообщений в базу данных
            channel_info = await self.telegram.get_channel_info(channel_username)
            if channel_info:
                self.logger.info(f"Сохранение {len(analysis['messages'])} сообщений в базу данных")
                self.db.save_messages(channel_info["id"], analysis["messages"])
            else:
                self.logger.error(f"Не удалось получить информацию о канале {channel_username}")

            self.logger.info(f"Анализ канала {channel_username} завершен успешно")
            return {
                "status": "success",
                "channel_info": channel_info,
                "analysis": analysis
            }

        except Exception as e:
            self.logger.error(f"Error analyzing channel: {e}")
            return {"status": "error", "message": str(e)}

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