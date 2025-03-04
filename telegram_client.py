from telethon import TelegramClient, events
from telethon.tl.types import Channel, Message
from typing import List, Dict, Optional, Union
import asyncio
import logging
from logger_config import setup_logger
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import re

load_dotenv()

class TelegramAnalyzer:
    def __init__(self):
        self.api_id = int(os.getenv('TELEGRAM_API_ID'))
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.client = None
        self.logger = setup_logger(__name__)
        self.last_connection_check = datetime.now()
        self.connection_check_interval = 30  # Уменьшаем интервал проверки до 30 секунд
        self.max_reconnect_attempts = 3
        self.last_activity = datetime.now()  # Добавляем отслеживание последней активности

    async def ensure_connected(self):
        """Проверка и восстановление соединения при необходимости"""
        now = datetime.now()
        
        # Проверяем соединение если прошло достаточно времени с последней проверки
        # или если давно не было активности
        if ((now - self.last_connection_check).total_seconds() > self.connection_check_interval or
            (now - self.last_activity).total_seconds() > 30):  # Уменьшаем до 30 секунд
            
            self.last_connection_check = now
            
            try:
                if not self.client:
                    self.logger.warning("Клиент Telegram не инициализирован, выполняем подключение...")
                    await self.reconnect()
                elif not await self.client.is_connected():
                    self.logger.warning("Соединение с Telegram потеряно, пытаемся переподключиться...")
                    await self.reconnect()
                else:
                    # Проверяем соединение пинг-запросом
                    try:
                        await asyncio.wait_for(self.client.ping(), timeout=5.0)
                        self.last_activity = now
                    except (asyncio.TimeoutError, Exception) as e:
                        self.logger.warning(f"Ошибка при проверке соединения: {e}")
                        await self.reconnect()
            except Exception as e:
                self.logger.error(f"Ошибка при проверке/восстановлении соединения: {e}")
                await self.reconnect()

    async def reconnect(self):
        """Переподключение к Telegram с повторными попытками"""
        for attempt in range(self.max_reconnect_attempts):
            try:
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                    self.client = None
                
                self.client = TelegramClient('anon', self.api_id, self.api_hash)
                await self.client.start()
                self.last_activity = datetime.now()
                self.logger.info("Успешно переподключились к Telegram")
                return True
            except Exception as e:
                self.logger.error(f"Ошибка при попытке переподключения (попытка {attempt + 1}/{self.max_reconnect_attempts}): {e}")
                if attempt < self.max_reconnect_attempts - 1:
                    await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
        
        self.logger.error("Не удалось переподключиться к Telegram после всех попыток")
        return False

    async def connect(self):
        """Подключение к Telegram"""
        if not self.client:
            try:
                self.client = TelegramClient('anon', self.api_id, self.api_hash)
                await self.client.start()
                self.logger.info("Успешно подключились к Telegram")
            except Exception as e:
                self.logger.error(f"Ошибка при подключении к Telegram: {e}")
                raise

    async def disconnect(self):
        """Отключение от Telegram"""
        if self.client:
            try:
                await self.client.disconnect()
                self.client = None
                self.logger.info("Успешно отключились от Telegram")
            except Exception as e:
                self.logger.error(f"Ошибка при отключении от Telegram: {e}")

    async def get_channel_info(self, channel_username: str) -> Optional[Dict]:
        """Получение информации о канале"""
        for attempt in range(self.max_reconnect_attempts):
            try:
                await self.ensure_connected()
                
                self.logger.info(f"Получение информации о канале {channel_username}")
                channel = await self.client.get_entity(channel_username)
                if isinstance(channel, Channel):
                    self.last_activity = datetime.now()
                    return {
                        "id": channel.id,
                        "username": channel_username.replace("@", ""),
                        "title": channel.title
                    }
                return None
            except Exception as e:
                self.logger.error(f"Ошибка при получении информации о канале (попытка {attempt + 1}): {e}")
                if "network" in str(e).lower() or "connection" in str(e).lower():
                    await self.reconnect()
                    if attempt < self.max_reconnect_attempts - 1:
                        await asyncio.sleep(2 ** attempt)
                    continue
                return None
        return None

    async def get_messages(self, 
                         channel_username: str,
                         limit: int = 100,
                         offset_date: Optional[datetime] = None) -> List[Dict]:
        """Получение сообщений из канала"""
        messages = []
        max_retries = 4
        retry_delay = 2.0
        chunk_size = 30  # Уменьшаем размер чанка
        
        try:
            await self.ensure_connected()
            
            entity = await self.client.get_entity(channel_username)
            if not entity:
                self.logger.error(f"Не удалось получить сущность канала {channel_username}")
                return []
            
            remaining = limit
            current_offset_date = offset_date
            
            while remaining > 0:
                current_chunk_size = min(remaining, chunk_size)
                
                for attempt in range(max_retries):
                    try:
                        chunk = await asyncio.wait_for(
                            self.client.get_messages(
                                entity,
                                limit=current_chunk_size,
                                offset_date=current_offset_date
                            ),
                            timeout=30.0  # Уменьшаем таймаут
                        )
                        
                        if not chunk:
                            break
                            
                        for message in chunk:
                            if message.text:
                                messages.append({
                                    "id": message.id,
                                    "date": message.date.isoformat(),
                                    "text": message.text,
                                })
                        
                        if chunk:
                            current_offset_date = chunk[-1].date
                            
                        remaining -= len(chunk)
                        
                        if len(chunk) < current_chunk_size:
                            remaining = 0
                            
                        await asyncio.sleep(0.5)  # Уменьшаем паузу
                        self.last_activity = datetime.now()
                        break
                        
                    except (asyncio.TimeoutError, ConnectionError) as e:
                        if attempt < max_retries - 1:
                            self.logger.warning(f"Ошибка сети при получении сообщений (попытка {attempt+1}/{max_retries}): {e}")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 1.5
                            await self.ensure_connected()
                        else:
                            self.logger.error(f"Не удалось получить сообщения после {max_retries} попыток")
                            return messages
                
                if remaining == limit:
                    break
            
            return messages
            
        except Exception as e:
            self.logger.error(f"Непредвиденная ошибка при получении сообщений: {e}")
            if "network" in str(e).lower() or "connection" in str(e).lower():
                await self.reconnect()
            return messages

    async def analyze_channel_content(self, 
                                    channel_username: str,
                                    days: int = 7) -> Dict:
        """Анализ контента канала"""
        try:
            # Проверяем соединение перед началом анализа
            await self.ensure_connected()
            
            self.logger.info(f"Получение сообщений из канала {channel_username} за последние {days} дней")
            offset_date = datetime.now() - timedelta(days=days)
            
            # Используем улучшенный метод получения сообщений с повторными попытками
            messages = await self.get_messages(
                channel_username,
                limit=1000,
                offset_date=offset_date
            )
            
            if not messages:
                self.logger.warning(f"Не найдено сообщений в канале {channel_username} за последние {days} дней")
                return {"error": "Не найдено сообщений в канале"}
            
            # Обновляем время последней активности
            self.last_activity = datetime.now()
            
            self.logger.info(f"Анализ {len(messages)} сообщений из канала {channel_username}")
            
            # Объединяем тексты сообщений для анализа
            all_text = "\n\n".join([msg.get("text", "") for msg in messages if msg.get("text")])
            
            # Простой анализ тем и настроения
            topics = self._extract_topics(all_text)
            sentiment = self._analyze_sentiment(all_text)
            
            self.logger.info(f"Анализ канала {channel_username} успешно завершен")
            return {
                "messages": messages,
                "topics": list(topics)[:10],
                "sentiment": sentiment
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при анализе контента канала {channel_username}: {e}")
            if "network" in str(e).lower() or "connection" in str(e).lower():
                await self.reconnect()
            return {"error": str(e)}
            
    def _extract_topics(self, text: str) -> set:
        """Извлечение ключевых тем из текста"""
        # Простая реализация извлечения тем
        # В реальном приложении здесь может быть более сложный алгоритм
        words = re.findall(r'\b\w{4,}\b', text.lower())
        stopwords = {'этот', 'который', 'такой', 'только', 'если', 'также', 'может', 'быть', 'когда', 'очень', 'всего', 'будет', 'более', 'можно', 'нужно'}
        topics = set()
        
        word_counts = {}
        for word in words:
            if word not in stopwords:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        # Выбираем наиболее часто встречающиеся слова
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        topics = {word for word, count in sorted_words[:50] if count > 1}
        
        return topics
        
    def _analyze_sentiment(self, text: str) -> Dict:
        """Простой анализ настроения текста"""
        # Простая реализация анализа настроения
        # В реальном приложении здесь может быть более сложный алгоритм
        positive_words = {'хорошо', 'отлично', 'прекрасно', 'замечательно', 'успешно', 'позитивно', 'радость', 'любовь', 'счастье'}
        negative_words = {'плохо', 'ужасно', 'проблема', 'неудача', 'негативно', 'грустно', 'печально', 'ненависть', 'трудности'}
        
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)
        
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        total_words = len(words)
        
        if total_words == 0:
            return {"positive": 0, "negative": 0, "neutral": 1.0}
        
        positive_score = positive_count / total_words
        negative_score = negative_count / total_words
        neutral_score = 1.0 - (positive_score + negative_score)
        
        return {
            "positive": round(positive_score, 2),
            "negative": round(negative_score, 2),
            "neutral": round(neutral_score, 2)
        }
    
    def _is_network_error(self, error_str: str) -> bool:
        """Проверяет, является ли ошибка сетевой"""
        network_error_keywords = ['connection', 'timeout', 'network', 'socket', 'connect', 'reset', 
                               'refused', 'aborted', 'failed', 'unreachable', 'dns', 'flood', 
                               'handshake', 'conn', 'proxy', 'ssl']
        
        error_lower = error_str.lower()
        return any(keyword in error_lower for keyword in network_error_keywords)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()