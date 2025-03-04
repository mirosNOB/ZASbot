import asyncio
import logging
import traceback
import os
import time
import re
import uuid
import json
import tempfile
from functools import wraps
from typing import List, Dict, Optional, Any, Callable, Awaitable
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from logger_config import setup_logger
from services import WebAnalyzer
from ai_utils import AIManager

# Настройка логгера
logger = setup_logger(__name__)

# Импорт констант из config.py
from config import BOT_TOKEN, DATABASE_URL, MESSAGES

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация анализатора и ИИ менеджера
web_analyzer = WebAnalyzer()
ai_manager = AIManager()

# Функция для повторных попыток выполнения асинхронной функции с обработкой сетевых ошибок
async def retry_async(func: Callable[..., Awaitable], *args, max_retries: int = 3, 
                     retry_delay: float = 2.0, timeout: float = 60.0, **kwargs):
    """
    Декоратор для повторного выполнения асинхронных функций при ошибках сети
    """
    last_exception = None
    current_delay = retry_delay
    
    for attempt in range(max_retries):
        try:
            # Пытаемся выполнить функцию с таймаутом
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            return result  # Если успешно, возвращаем результат
            
        except asyncio.TimeoutError as e:
            logger.warning(f"Таймаут при выполнении {func.__name__} (попытка {attempt+1}/{max_retries})")
            last_exception = e
            
        except Exception as e:
            # Для других ошибок делаем повторную попытку только если это похоже на сетевую ошибку
            if "connection" in str(e).lower() or "timeout" in str(e).lower() or "network" in str(e).lower():
                logger.warning(f"Возможная сетевая ошибка при выполнении {func.__name__}: {e} (попытка {attempt+1}/{max_retries})")
                last_exception = e
            else:
                # Для других ошибок не делаем повторных попыток
                raise
        
        # Экспоненциальная задержка между попытками
        if attempt < max_retries - 1:
            await asyncio.sleep(current_delay)
            current_delay *= 1.5  # Увеличиваем задержку для следующей попытки
    
    # Если все попытки не удались, выбрасываем последнюю ошибку
    error_msg = f"Не удалось выполнить {func.__name__} после {max_retries} попыток"
    logger.error(error_msg)
    if last_exception:
        raise type(last_exception)(f"{error_msg}: {str(last_exception)}")
        else:
        raise Exception(error_msg)

# Декоратор для применения retry_async к методам бота
def retry_on_network_errors(max_retries=3, retry_delay=2.0, timeout=60.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = retry_delay

            for attempt in range(max_retries):
                try:
                    # Устанавливаем таймаут для всей операции
                    async with asyncio.timeout(timeout):
                        return await func(*args, **kwargs)
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут при выполнении {func.__name__} (попытка {attempt+1}/{max_retries})")
                    last_exception = asyncio.TimeoutError("Операция превысила таймаут")
                except Exception as e:
                    # Для сетевых ошибок делаем повторную попытку
                    if "connection" in str(e).lower() or "timeout" in str(e).lower() or "network" in str(e).lower():
                        logger.warning(f"Сетевая ошибка при выполнении {func.__name__}: {e} (попытка {attempt+1}/{max_retries})")
                        last_exception = e
                    else:
                        # Для других ошибок прекращаем попытки
                        raise

                # Если это была не последняя попытка, ждем перед следующей
                if attempt < max_retries - 1:
                    await asyncio.sleep(current_delay)
                    current_delay *= 1.5  # Увеличиваем задержку для следующей попытки

            # Если все попытки не удались, выбрасываем последнюю ошибку
            if last_exception:
                raise last_exception
            raise Exception(f"Не удалось выполнить {func.__name__} после {max_retries} попыток")

        return wrapper
    return decorator

# Функция для отправки длинных сообщений
@retry_on_network_errors()
async def send_long_message(chat_id: int, text: str, parse_mode=ParseMode.MARKDOWN, reply_markup=None) -> None:
    """
    Отправляет длинное сообщение, разбивая его на части, если оно превышает лимит
    """
    if not text:
        logger.warning(f"Попытка отправить пустое сообщение для chat_id={chat_id}")
        return

    # Если длина сообщения превышает 500 символов, отправляем его как файл
    if len(text) > 500:
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_file:
            temp_file.write(text)
            temp_file.flush()
            
            try:
                # Отправляем первые 500 символов как сообщение
                preview = text[:500] + "...\n\nПолный текст во вложенном файле 👇"
                await bot.send_message(
                    chat_id=chat_id,
                    text=preview,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                
                # Отправляем полный текст как файл
                with open(temp_file.name, 'rb') as file:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=file,
                        caption="Полный текст"
                    )
            finally:
                # Удаляем временный файл
                os.unlink(temp_file.name)
            return
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
                parse_mode=parse_mode,
            reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
        # Пробуем отправить без форматирования
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=None,
                reply_markup=reply_markup
                    )
        except Exception as e2:
            logger.error(f"Ошибка при отправке сообщения без форматирования: {e2}")
            raise

# Добавляем новые состояния

class UserState(StatesGroup):
    """Состояния пользователя"""
    waiting_point_a = State()
    waiting_point_b = State()
    waiting_timeframe = State()
    waiting_target_audience = State()
    waiting_channel_choice = State()  # Выбор добавления канала (да/нет)
    waiting_channel_selection = State()  # Выбор канала из списка
    waiting_channel_period = State()  # Выбор периода анализа канала
    waiting_channel_keyword = State()  # Выбор ключевого слова для фильтрации постов
    waiting_article_choice = State()  # Состояние для выбора добавления статьи
    waiting_article_url = State()  # Состояние для ожидания ссылки на статью
    waiting_strategy_confirmation = State()
    waiting_strategy_refinement = State()
    waiting_slogan_theme = State()
    waiting_channel_url = State()
    waiting_folder_name = State()
    waiting_folder_selection = State()
    waiting_model_selection = State()
    waiting_providers_selection = State()
    waiting_analysis = State()  # Состояние для анализа каналов
    waiting_search_confirmation = State()  # Новое состояние для подтверждения поиска в интернете
    waiting_news_url = State()  # Новое состояние для ожидания URL новостей
    waiting_search_query = State()  # Новое состояние для ввода поискового запроса
    waiting_channel_username = State()  # Состояние для ожидания имени пользователя канала


async def generate_strategy_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры для стратегии"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_strategy"),
        InlineKeyboardButton("🔄 Улучшить", callback_data="refine_strategy"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
    )
    return keyboard


@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(MESSAGES['start'], parse_mode=ParseMode.HTML)
    await message.answer(MESSAGES['help'], parse_mode=ParseMode.HTML)


@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = MESSAGES['help'] + "\n\n" + """Дополнительные команды:
/folders - Управление папками
/create_folder - Создать новую папку
/add_channel - Добавить канал
/channels - Список каналов
/analyze - Анализ канала
/models - Управление моделями ИИ
/providers - Управление провайдерами"""

    await message.answer(help_text, parse_mode=ParseMode.HTML)


@dp.message_handler(commands=['new_strategy'])
async def cmd_new_strategy(message: types.Message, state: FSMContext):
    """Начало создания новой стратегии"""
    # Сбрасываем текущее состояние, чтобы избежать конфликтов
    current_state = await state.get_state()
    if current_state is not None:
        logger.info(f"Сброс предыдущего состояния {current_state} перед началом новой стратегии")
        await state.finish()
        
    logger.info(f"Пользователь {message.from_user.id} начал создание новой стратегии")
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_operation"))
    
    await message.answer(
        "Опишите текущую ситуацию (точка А):",
        reply_markup=cancel_keyboard
    )
    await UserState.waiting_point_a.set()


@dp.message_handler(state=UserState.waiting_point_a)
async def process_point_a(message: types.Message, state: FSMContext):
    """Обработка точки А"""
    logger.info(f"Обработка точки А: {message.text[:20]}...")
    
    # Сохраняем точку A в состоянии
    await state.update_data(point_a=message.text)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_operation"))
    
    # Отправляем сообщение с клавиатурой
    await message.answer("Опишите цель, которую вы хотите достичь (точка Б):", reply_markup=cancel_keyboard)
    logger.info("Установлено состояние waiting_point_b")
    await UserState.waiting_point_b.set()


@dp.message_handler(state=UserState.waiting_point_b)
async def process_point_b(message: types.Message, state: FSMContext):
    """Обработка точки Б"""
    logger.info(f"Обработка точки Б: {message.text[:20]}...")
    
    # Сохраняем точку B в состоянии
    await state.update_data(point_b=message.text)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_operation"))
    
    # Отправляем сообщение с клавиатурой
    await message.answer("Укажите временные рамки для достижения цели (например, '3 месяца'):", reply_markup=cancel_keyboard)
    logger.info("Установлено состояние waiting_timeframe")
    await UserState.waiting_timeframe.set()


@dp.message_handler(state=UserState.waiting_timeframe)
async def process_timeframe(message: types.Message, state: FSMContext):
    """Обработка временных рамок"""
    logger.info(f"Сохранено время: {message.text}")
    
    # Сохраняем временные рамки в состоянии
    await state.update_data(timeframe=message.text)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_operation"))
    
    # Отправляем сообщение с клавиатурой
    await message.answer("Опишите целевую аудиторию:", reply_markup=cancel_keyboard)
    logger.info(f"Установлено состояние waiting_target_audience")
    await UserState.waiting_target_audience.set()


@dp.message_handler(state=UserState.waiting_target_audience)
async def process_target_audience(message: types.Message, state: FSMContext):
    """Обработка целевой аудитории и предложение добавить канал"""
    logger.info(f"Начинаю обработку целевой аудитории: {message.text}")
    
    # Сохраняем целевую аудиторию в состоянии
    await state.update_data(target_audience=message.text)
    
    # Создаем клавиатуру с вариантами действий
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✅ Добавить Telegram-канал", callback_data="add_channel_to_strategy"),
        InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
    )
    
    await message.answer(
        "Хотите добавить Telegram-канал для анализа и использования его данных при генерации стратегии?",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ожидания выбора канала
    await UserState.waiting_channel_choice.set()
    logger.info("Установлено состояние waiting_channel_choice")


@dp.callback_query_handler(lambda c: c.data == "add_channel_to_strategy", state=UserState.waiting_channel_choice)
async def add_channel_to_strategy(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик для добавления канала к стратегии"""
    await bot.answer_callback_query(callback_query.id)
    
    # Получаем список каналов из базы данных
    channels = await web_analyzer.get_channels()
    
    if not channels:
        # Если нет добавленных каналов, предлагаем добавить новый или продолжить без канала
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(так и не работает думаю не ток в инете дело бля
            InlineKeyboardButton("➕ Добавить новый канал", callback_data="add_new_channel"),
            InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
        )

        await bot.send_message(
            callback_query.from_user.id,
            "У вас нет добавленных каналов. Хотите добавить новый канал или продолжить без канала?",
            reply_markup=keyboard
        )
        return
    
    # Создаем клавиатуру с каналами
    keyboard = InlineKeyboardMarkup(row_width=1)
    for channel in channels:
        channel_title = channel.get('title', channel.get('username', 'Канал без названия'))
        keyboard.add(
            InlineKeyboardButton(
                f"{channel_title}",
                callback_data=f"select_channel:{channel['id']}"
            )
        )
    
    # Добавляем кнопки для других действий
    keyboard.add(
        InlineKeyboardButton("➕ Добавить новый канал", callback_data="add_new_channel"),
        InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите канал для анализа:",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние выбора канала
    await UserState.waiting_channel_selection.set()


@dp.callback_query_handler(lambda c: c.data.startswith("select_channel:"), state=UserState.waiting_channel_selection)
async def select_channel(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора канала для анализа"""
    await bot.answer_callback_query(callback_query.id)
    
    # Получаем ID выбранного канала
    channel_id = int(callback_query.data.split(":")[1])
    
    # Получаем информацию о канале
    channels = await web_analyzer.get_channels()
    selected_channel = None
    for channel in channels:
        if channel['id'] == channel_id:
            selected_channel = channel
            break
    
    if not selected_channel:
        await bot.send_message(
            callback_query.from_user.id,
            "Канал не найден. Попробуйте выбрать другой канал."
        )
        return
    
    # Сохраняем выбранный канал в состоянии
    await state.update_data(selected_channel=selected_channel)
    
    # Спрашиваем о периоде анализа
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("1 день", callback_data="period:1"),
        InlineKeyboardButton("4 дня", callback_data="period:4"),
        InlineKeyboardButton("1 неделя", callback_data="period:7"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_channel")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        f"Выбран канал: *{selected_channel.get('title', selected_channel.get('username', 'Канал'))}*\n\n"
        f"Выберите период анализа постов:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние выбора периода
    await UserState.waiting_channel_period.set()


@dp.callback_query_handler(lambda c: c.data.startswith("period:"), state=UserState.waiting_channel_period)
async def process_channel_period(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора периода анализа канала"""
    await bot.answer_callback_query(callback_query.id)
    # Получаем выбранный период
    period_days = int(callback_query.data.split(":")[1])
    
    # Сохраняем период в состоянии
    await state.update_data(channel_period=period_days)
    
    # Спрашиваем о ключевом слове для фильтрации
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("➡️ Без ключевого слова", callback_data="no_keyword"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_channel")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        f"Выбран период: *{period_days} дней*\n\n"
        f"Введите ключевое слово для фильтрации постов или нажмите кнопку, чтобы анализировать все посты:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ввода ключевого слова
    await UserState.waiting_channel_keyword.set()


@dp.message_handler(state=UserState.waiting_channel_keyword)
async def process_channel_keyword(message: types.Message, state: FSMContext):
    """Обработчик ввода ключевого слова для фильтрации постов"""
    keyword = message.text.strip()
    
    if not keyword or len(keyword) < 2:
        await message.answer("Пожалуйста, введите ключевое слово длиной не менее 2 символов или нажмите кнопку 'Без ключевого слова'.")
        return
    
    # Сохраняем ключевое слово в состоянии
    await state.update_data(channel_keyword=keyword)
    
    # Отправляем сообщение о начале анализа
    processing_msg = await message.answer(MESSAGES['processing'])
    
    try:
        # Получаем данные выбранного канала и периода
        data = await state.get_data()
        selected_channel = data.get('selected_channel')
        period_days = data.get('channel_period', 7)
        
        # Анализируем канал
        channel_analysis = await web_analyzer.analyze_channel(
            selected_channel.get('username', ''),
            days=period_days
        )
        
        # Фильтруем посты по ключевому слову
        filtered_messages = []
        for msg in channel_analysis.get('messages', []):
            if keyword.lower() in msg.get('text', '').lower():
                filtered_messages.append(msg)
        
        # Формируем текст из отфильтрованных сообщений
        channel_content = "\n\n".join([msg.get('text', '') for msg in filtered_messages])
        
        if not channel_content:
            await processing_msg.delete()
            await message.answer(
                f"❌ Не найдено сообщений с ключевым словом '{keyword}' за последние {period_days} дней.\n"
                f"Хотите продолжить без анализа канала или выбрать другое ключевое слово?"
            )

            keyboard = InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                InlineKeyboardButton("🔄 Выбрать другое слово", callback_data=f"period:{period_days}"),
                InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
            )
            
            await message.answer("Выберите действие:", reply_markup=keyboard)
            return
        
        # Сохраняем данные канала и контента
        await state.update_data(
            channel_title=selected_channel.get('title', selected_channel.get('username', '')),
            channel_content=channel_content,
            channel_url=f"https://t.me/{selected_channel.get('username', '')}",
            channel_analysis=channel_analysis
        )
        
        await processing_msg.delete()
        
        # Показываем результаты и переходим к вопросу о статье
        await message.answer(
            f"✅ Найдено {len(filtered_messages)} сообщений с ключевым словом '{keyword}'.\n\n"
            f"Теперь предлагаю добавить статью из интернета для ещё более точной генерации стратегии."
        )
        
        # Переходим к вопросу о добавлении статьи
        await ask_about_article(message.chat.id, state)
    
    except Exception as e:
        logger.error(f"Ошибка при анализе канала: {e}")
        await processing_msg.delete()
        
        await message.answer(
            f"❌ Произошла ошибка при анализе канала: {str(e)}\n"
            f"Предлагаю продолжить без канала или выбрать другой канал."
        )
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Выбрать другой канал", callback_data="add_channel_to_strategy"),
            InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
        )
        
        await message.answer("Выберите действие:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data == "no_keyword", state=UserState.waiting_channel_keyword)
async def process_no_keyword(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора анализа без ключевого слова"""
    await bot.answer_callback_query(callback_query.id)
    
    # Сохраняем отсутствие ключевого слова
    await state.update_data(channel_keyword="")
    
    # Отправляем сообщение о начале анализа
    processing_msg = await bot.send_message(
        callback_query.from_user.id,
        MESSAGES['processing']
    )

    try:
        # Получаем данные выбранного канала и периода
        data = await state.get_data()
        selected_channel = data.get('selected_channel')
        period_days = data.get('channel_period', 7)
        
        # Анализируем канал
        channel_analysis = await web_analyzer.analyze_channel(
            selected_channel.get('username', ''),
            days=period_days
        )
        
        # Формируем текст из всех сообщений
        messages = channel_analysis.get('messages', [])
        channel_content = "\n\n".join([msg.get('text', '') for msg in messages if msg.get('text')])
        
        if not channel_content:
            await processing_msg.delete()
            await bot.send_message(
                callback_query.from_user.id,
                f"❌ Не найдено сообщений за последние {period_days} дней.\n"
                f"Хотите продолжить без анализа канала или выбрать другой канал?"
            )
            
            keyboard = InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                InlineKeyboardButton("🔄 Выбрать другой канал", callback_data="add_channel_to_strategy"),
                InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
            )
            
            await bot.send_message(
                callback_query.from_user.id,
                "Выберите действие:",
                reply_markup=keyboard
            )
            return
        
        # Сохраняем данные канала и контента
        await state.update_data(
            channel_title=selected_channel.get('title', selected_channel.get('username', '')),
            channel_content=channel_content,
            channel_url=f"https://t.me/{selected_channel.get('username', '')}",
            channel_analysis=channel_analysis
        )
        
        await processing_msg.delete()
        
        # Показываем результаты и переходим к вопросу о статье
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Проанализировано {len(messages)} сообщений за последние {period_days} дней.\n\n"
            f"Теперь предлагаю добавить статью из интернета для ещё более точной генерации стратегии."
        )
        
        # Переходим к вопросу о добавлении статьи
        await ask_about_article(callback_query.from_user.id, state)
    
    except Exception as e:
        logger.error(f"Ошибка при анализе канала: {e}")
        await processing_msg.delete()
        
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Произошла ошибка при анализе канала: {str(e)}\n"
            f"Предлагаю продолжить без канала или выбрать другой канал."
        )
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Выбрать другой канал", callback_data="add_channel_to_strategy"),
            InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
        )
        
        await bot.send_message(
            callback_query.from_user.id,
            "Выберите действие:",
            reply_markup=keyboard
        )


@dp.callback_query_handler(lambda c: c.data == "add_new_channel", state=[UserState.waiting_channel_choice, UserState.waiting_channel_selection])
async def add_new_channel_to_strategy(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик добавления нового канала при создании стратегии"""
    await bot.answer_callback_query(callback_query.id)

    # Получаем список папок
    folders = await web_analyzer.get_folders()
    
    if not folders:
        # Если нет папок, просим создать сначала папку
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("➕ Создать папку", callback_data="create_folder"),
            InlineKeyboardButton("➡️ Продолжить без канала", callback_data="continue_without_channel"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
        )
        
        await bot.send_message(
            callback_query.from_user.id,
            "У вас нет папок для каналов. Сначала нужно создать папку.",
            reply_markup=keyboard
        )
        return

    # Создаем клавиатуру с папками
    keyboard = InlineKeyboardMarkup(row_width=1)
    for folder in folders:
        keyboard.add(
            InlineKeyboardButton(
                f"📁 {folder['name']}",
                callback_data=f"add_to_folder_strategy:{folder['id']}"
            )
        )
    
    # Добавляем кнопку отмены
    keyboard.add(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_channel")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите папку для нового канала:",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние выбора папки
    await UserState.waiting_folder_selection.set()


@dp.callback_query_handler(lambda c: c.data.startswith("add_to_folder_strategy:"), state=UserState.waiting_folder_selection)
async def add_to_folder_strategy(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора папки для нового канала при создании стратегии"""
    await bot.answer_callback_query(callback_query.id)
    
    # Получаем ID выбранной папки
    folder_id = int(callback_query.data.split(":")[1])
    
    # Сохраняем ID папки в состоянии
    await state.update_data(folder_id=folder_id)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_channel")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Введите имя пользователя канала (в формате @username):",
        reply_markup=cancel_keyboard
    )
    
    # Устанавливаем состояние ожидания имени пользователя канала
    await UserState.waiting_channel_username.set()


@dp.callback_query_handler(lambda c: c.data == "continue_without_channel", state=[UserState.waiting_channel_choice, UserState.waiting_channel_selection, UserState.waiting_channel_period, UserState.waiting_channel_keyword])
async def continue_without_channel(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик для продолжения без добавления канала"""
    await bot.answer_callback_query(callback_query.id)
    
    # Переходим к вопросу о добавлении статьи
    await ask_about_article(callback_query.from_user.id, state)


@dp.callback_query_handler(lambda c: c.data == "cancel_channel", state=[UserState.waiting_channel_choice, UserState.waiting_channel_selection, UserState.waiting_channel_period, UserState.waiting_channel_keyword, UserState.waiting_channel_url, UserState.waiting_folder_selection, UserState.waiting_channel_username])
async def cancel_channel(callback_query: types.CallbackQuery, state: FSMContext):
    """Отмена добавления канала"""
    await bot.answer_callback_query(callback_query.id)

    # Переходим к вопросу о добавлении статьи
    await ask_about_article(callback_query.from_user.id, state)


async def ask_about_article(chat_id: int, state: FSMContext):
    """Функция для перехода к вопросу о добавлении статьи"""
    # Создаем клавиатуру с вариантами действий
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✅ Добавить статью из интернета", callback_data="add_article"),
        InlineKeyboardButton("➡️ Продолжить без статьи", callback_data="continue_without_article"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
    )

    await bot.send_message(
        chat_id,
        "Хотите добавить статью из интернета для более точной генерации стратегии?",
        reply_markup=keyboard
    )

    # Устанавливаем состояние ожидания выбора
    await UserState.waiting_article_choice.set()
    logger.info("Установлено состояние waiting_article_choice")


@dp.callback_query_handler(lambda c: c.data == "add_article", state=UserState.waiting_article_choice)
async def add_article(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик для добавления статьи из интернета"""
    await bot.answer_callback_query(callback_query.id)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_article")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Пожалуйста, отправьте ссылку на статью или новость из интернета:",
        reply_markup=cancel_keyboard
    )
    
    # Устанавливаем состояние ожидания URL статьи
    await UserState.waiting_article_url.set()
    logger.info("Установлено состояние waiting_article_url")


@dp.callback_query_handler(lambda c: c.data == "continue_without_article", state=UserState.waiting_article_choice)
async def continue_without_article(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик для продолжения без добавления статьи"""
    await bot.answer_callback_query(callback_query.id)
    
    # Начинаем генерацию стратегии
    await generate_strategy(callback_query.from_user.id, state)


@dp.callback_query_handler(lambda c: c.data == "cancel_article", state=UserState.waiting_article_url)
async def cancel_article(callback_query: types.CallbackQuery, state: FSMContext):
    """Отмена добавления статьи"""
    await bot.answer_callback_query(callback_query.id)
    
    # Начинаем генерацию стратегии без статьи
    await generate_strategy(callback_query.from_user.id, state)


@dp.message_handler(state=UserState.waiting_article_url)
async def process_article_url(message: types.Message, state: FSMContext):
    """Обработка URL статьи"""
    url = message.text.strip()
    
    if not url.startswith(('http://', 'https://')):
        await message.answer(
            "Пожалуйста, введите корректный URL, начинающийся с http:// или https://"
        )
        return

    # Отправка сообщения о начале обработки
    processing_msg = await message.answer(MESSAGES['processing'])
    
    try:
        # Получаем текст статьи
        article = await web_analyzer.fetch_article(url)
        
        if "error" in article:
            await processing_msg.delete()
            await message.answer(
                f"❌ Не удалось получить информацию: {article['error']}"
            )
            # Предлагаем продолжить без статьи
            continue_keyboard = InlineKeyboardMarkup()
            continue_keyboard.add(
                InlineKeyboardButton("➡️ Продолжить без статьи", callback_data="continue_without_article")
            )
            await message.answer(
                "Хотите продолжить генерацию стратегии без статьи?",
                reply_markup=continue_keyboard
            )
            return
        
        # Сохраняем данные статьи в состоянии
        await state.update_data(
            article_title=article.get('title', ''),
            article_content=article.get('content', ''),
            article_url=url
        )
        
        await processing_msg.delete()
        await message.answer(
            f"✅ Статья успешно добавлена: *{article.get('title', 'Без названия')}*\n\n"
            f"Теперь генерирую стратегию с учетом всей собранной информации...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Начинаем генерацию стратегии
        await generate_strategy(message.chat.id, state)
        
    except Exception as e:
        logger.error(f"Ошибка при получении статьи: {e}")
        await processing_msg.delete()
        await message.answer(
            f"❌ Произошла ошибка при обработке статьи: {str(e)}\n"
            f"Продолжаю генерацию стратегии без статьи."
        )
        # Начинаем генерацию стратегии без статьи
        await generate_strategy(message.chat.id, state)


@retry_on_network_errors()
async def generate_strategy(chat_id: int, state: FSMContext):
    """Генерация стратегии на основе собранных данных"""
    # Получаем все данные из состояния
    data = await state.get_data()
    
    # Отправка сообщения о начале генерации
    processing_msg = await bot.send_message(chat_id, MESSAGES['processing'])
    
    # Создаем задачу для генерации в фоне
    generation_task = asyncio.create_task(_generate_strategy_task(chat_id, state, data))
    
    # Запускаем задачу обновления сообщения
    update_task = asyncio.create_task(_update_processing_message(processing_msg))
    
    try:
        # Ждем завершения генерации
        strategy_result = await generation_task
        # Отменяем обновление сообщения
        update_task.cancel()
        
    # Проверяем наличие ошибки в ответе
    if "error" in strategy_result:
        # Создаем клавиатуру для возврата в главное меню
        menu_keyboard = InlineKeyboardMarkup()
        menu_keyboard.add(
            InlineKeyboardButton("🏠 К главному меню", callback_data="goto_main_menu"),
            InlineKeyboardButton("🔄 Новая стратегия", callback_data="new_strategy")
        )
        
            await processing_msg.edit_text(
            f"Ошибка при генерации стратегии: {strategy_result['error']}",
            reply_markup=menu_keyboard
        )
        await state.finish()
        return

    # Сохранение результатов
        await state.update_data(strategy=strategy_result)
        
    # Формирование сообщения
    timeline_text = ""
    for period in strategy_result['timeline']:
        timeline_text += f"- {period['period']}\n"
        for action in period['actions']:
            timeline_text += f"  • {action}\n"
            
    resources_text = ""
    for resource in strategy_result['resources']:
        resources_text += f"- {resource}\n"

        strategy_text = f"📊 *Анализ ситуации:*\n{strategy_result.get('analysis', '')}\n\n🎯 *Стратегия:*\n{strategy_result['strategy']}\n\n⏱ *Временная линия:*\n{timeline_text}\n📋 *Необходимые ресурсы:*\n{resources_text}"
    
    # Если были использованы дополнительные данные, добавляем информацию
        if data.get('channel_title'):
            strategy_text += f"\n\n📱 *При генерации использовался Telegram-канал:*\n[{data['channel_title']}]({data.get('channel_url', '')})"
        
        if data.get('article_title'):
            strategy_text += f"\n\n📰 *При генерации использовалась статья:*\n[{data['article_title']}]({data.get('article_url', '')})"
    
    # Создаем клавиатуру с кнопками для действий со стратегией
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_strategy"),
        InlineKeyboardButton("🔄 Улучшить", callback_data="refine_strategy"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel_strategy")
    )

    try:
        await send_long_message(chat_id, strategy_text, reply_markup=keyboard)
        await UserState.waiting_strategy_confirmation.set()
    except Exception as e:
        logger.error(f"Ошибка при отправке стратегии: {e}")
        # Создаем клавиатуру для возврата в главное меню
        menu_keyboard = InlineKeyboardMarkup()
        menu_keyboard.add(
            InlineKeyboardButton("🏠 К главному меню", callback_data="goto_main_menu"),
            InlineKeyboardButton("🔄 Новая стратегия", callback_data="new_strategy")
        )
        
        try:
            await processing_msg.delete()
        except:
            pass
            
        await bot.send_message(
            chat_id,
            f"Произошла ошибка при генерации стратегии. Попробуйте еще раз.",
            reply_markup=menu_keyboard
        )
        await state.finish()

    except asyncio.CancelledError:
        # Если задача была отменена
        update_task.cancel()
        await processing_msg.edit_text("❌ Генерация стратегии была отменена")
        await state.finish()
    except Exception as e:
        # В случае других ошибок
        update_task.cancel()
        logger.error(f"Ошибка при генерации стратегии: {e}")
        await processing_msg.edit_text(f"❌ Произошла ошибка при генерации стратегии: {str(e)}")
        await state.finish()

async def _generate_strategy_task(chat_id: int, state: FSMContext, data: dict) -> Dict[str, Any]:
    """Фоновая задача для генерации стратегии"""
    try:
        # Анализ ситуации
        situation_analysis = await ai_manager.analyze_situation(data['point_a'])
        
        # Проверяем, есть ли данные канала и статьи
        channel_content = data.get('channel_content', '')
        channel_title = data.get('channel_title', '')
        article_content = data.get('article_content', '')
        article_title = data.get('article_title', '')
        
        # Генерация стратегии в зависимости от наличия данных
        if channel_content and article_content:
            # Если есть и канал и статья, передаем оба в генерацию
            strategy_result = await ai_manager.generate_strategy_with_channel(
                data['point_a'],
                data['point_b'],
                data['timeframe'],
                data['target_audience'],
                channel_title,
                channel_content,
                article_title,
                article_content
            )
        elif channel_content:
            # Если есть только канал
            strategy_result = await ai_manager.generate_strategy_with_channel(
                data['point_a'],
                data['point_b'],
                data['timeframe'],
                data['target_audience'],
                channel_title,
                channel_content
            )
        elif article_content:
            # Если есть только статья
            strategy_result = await ai_manager.generate_strategy_with_article(
                data['point_a'],
                data['point_b'],
                data['timeframe'],
                data['target_audience'],
                article_title,
                article_content
            )
        else:
            # Если ни канала, ни статьи нет, используем обычную генерацию
            strategy_result = await ai_manager.generate_strategy(
                data['point_a'],
                data['point_b'],
                data['timeframe'],
                data['target_audience']
            )
            
        # Добавляем результаты анализа
        strategy_result['analysis'] = situation_analysis.get('analysis', '')
        return strategy_result
        
    except Exception as e:
        logger.error(f"Ошибка в фоновой задаче генерации: {e}")
        return {"error": str(e)}

async def _update_processing_message(message: types.Message):
    """Обновление сообщения о генерации"""
    dots = 0
    try:
        while True:
            dots = (dots + 1) % 4
            await message.edit_text(f"{MESSAGES['processing']}{'.' * dots}")
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        # Нормальное завершение при отмене
        pass
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения: {e}")

@dp.callback_query_handler(lambda c: c.data == 'search_internet', state='*')
async def search_internet_start(callback_query: types.CallbackQuery, state: FSMContext):
    """Начало поиска в интернете"""
    await bot.answer_callback_query(callback_query.id)

    # Получаем данные из состояния
    data = await state.get_data()
    strategy = data.get('strategy', {}).get('strategy', '')
    point_a = data.get('point_a', '')
    point_b = data.get('point_b', '')
    target_audience = data.get('target_audience', '')
    
    # Сгенерируем предлагаемый поисковый запрос на основе данных стратегии
    try:
        suggested_query = await ai_manager.generate_search_query(
            strategy=strategy,
            point_a=point_a,
            point_b=point_b,
            target_audience=target_audience
        )
    except Exception as e:
        logger.error(f"Ошибка при генерации поискового запроса: {e}")
        suggested_query = f"Стратегия {point_b} для {target_audience}"
    
    # Сохраняем предложенный запрос
    await state.update_data(suggested_query=suggested_query)
    
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Использовать предложенный", callback_data="use_suggested_query"),
        InlineKeyboardButton("✏️ Ввести свой запрос", callback_data="enter_custom_query"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")
    )

    await bot.send_message(
        callback_query.from_user.id,
        f"Предлагаемый поисковый запрос:\n\n*{suggested_query}*\n\nЧто хотите сделать?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
            
    await UserState.waiting_search_confirmation.set()


@dp.callback_query_handler(lambda c: c.data == "finish_strategy", state="*")
async def finish_strategy(callback_query: types.CallbackQuery, state: FSMContext):
    """Завершение работы со стратегией"""
    await bot.answer_callback_query(callback_query.id)
    
    # Создаем клавиатуру для возврата в главное меню
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("🏠 К главному меню", callback_data="goto_main_menu"),
        InlineKeyboardButton("🔄 Новая стратегия", callback_data="new_strategy")
    )

    await bot.send_message(
        callback_query.from_user.id,
        "Работа со стратегией завершена. Вы можете вернуться в главное меню или начать новую стратегию.",
        reply_markup=keyboard
    )

    await state.finish()
    
@dp.callback_query_handler(lambda c: c.data == "use_suggested_query", state=UserState.waiting_search_confirmation)
async def use_suggested_query(callback_query: types.CallbackQuery, state: FSMContext):
    """Использование предложенного поискового запроса"""
    await bot.answer_callback_query(callback_query.id)

    # Получаем предложенный запрос
    data = await state.get_data()
    query = data.get('suggested_query', '')

    if not query:
        await bot.send_message(
            callback_query.from_user.id,
            "Ошибка: не удалось найти предложенный запрос. Пожалуйста, введите запрос вручную."
        )
        await UserState.waiting_search_query.set()
        return
    
    # Отправка сообщения о начале поиска
    processing_msg = await bot.send_message(
            callback_query.from_user.id,
        MESSAGES['processing']
    )

    try:
        # Ищем новости по запросу
        search_results = await web_analyzer.search_news(query, max_results=5)
        
        await processing_msg.delete()
        
        if not search_results:
            await bot.send_message(
                callback_query.from_user.id,
                "По вашему запросу ничего не найдено. Попробуйте изменить запрос."
            )
            return

        # Формируем сообщение с результатами
        results_text = f"🔍 Результаты поиска по запросу: *{query}*\n\n"
        
        for i, result in enumerate(search_results[:5], 1):
            results_text += f"{i}. [{result['title']}]({result['link']})\n"
            results_text += f"   {result['snippet'][:100]}...\n\n"
        
        # Сохраняем результаты в состояние
        await state.update_data(search_results=search_results)
        
        # Отправляем результаты
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Новый поиск", callback_data="search_internet"),
            InlineKeyboardButton("✅ Вернуться к стратегии", callback_data="back_to_strategy")
        )
        
        await send_long_message(
            callback_query.from_user.id,
            results_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await processing_msg.delete()
        await bot.send_message(
            callback_query.from_user.id,
            f"Произошла ошибка при поиске: {str(e)}"
        )


@dp.callback_query_handler(lambda c: c.data == "enter_custom_query", state=UserState.waiting_search_confirmation)
async def enter_custom_query(callback_query: types.CallbackQuery, state: FSMContext):
    """Ввод пользовательского поискового запроса"""
    await bot.answer_callback_query(callback_query.id)
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = InlineKeyboardMarkup()
    cancel_keyboard.add(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")
    )

    await bot.send_message(
        callback_query.from_user.id,
        "Введите поисковый запрос:",
        reply_markup=cancel_keyboard
    )
    
    await UserState.waiting_search_query.set()


@dp.message_handler(state=UserState.waiting_search_query)
async def process_custom_query(message: types.Message, state: FSMContext):
    """Обработка пользовательского поискового запроса"""
    query = message.text.strip()
    
    if not query:
        await message.answer("Пожалуйста, введите корректный поисковый запрос.")
        return
    
    # Отправка сообщения о начале поиска
    processing_msg = await message.answer(MESSAGES['processing'])
    
    try:
        # Ищем новости по запросу
        search_results = await web_analyzer.search_news(query, max_results=5)
        
        await processing_msg.delete()
        
        if not search_results:
            await message.answer(
                "По вашему запросу ничего не найдено. Попробуйте изменить запрос."
            )
        return

        # Формируем сообщение с результатами
        results_text = f"🔍 Результаты поиска по запросу: *{query}*\n\n"
        
        for i, result in enumerate(search_results[:5], 1):
            results_text += f"{i}. [{result['title']}]({result['link']})\n"
            results_text += f"   {result['snippet'][:100]}...\n\n"
        
        # Сохраняем результаты в состояние
        await state.update_data(search_results=search_results)
        
        # Отправляем результаты
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Новый поиск", callback_data="search_internet"),
            InlineKeyboardButton("✅ Вернуться к стратегии", callback_data="back_to_strategy")
        )
        
        await send_long_message(
            message.chat.id,
            results_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await processing_msg.delete()
        await message.answer(f"Произошла ошибка при поиске: {str(e)}")


@dp.callback_query_handler(lambda c: c.data == "cancel_search", state=[UserState.waiting_search_confirmation, UserState.waiting_search_query])
async def cancel_search(callback_query: types.CallbackQuery, state: FSMContext):
    """Отмена поиска в интернете"""
    await bot.answer_callback_query(callback_query.id)
    
    # Создаем клавиатуру для возврата к опциям стратегии
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📢 Сгенерировать лозунги", callback_data="generate_slogans"),
        InlineKeyboardButton("✅ Завершить работу", callback_data="finish_strategy")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Поиск в интернете отменен. Что хотите сделать дальше?",
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda c: c.data == "back_to_strategy", state="*")
async def back_to_strategy(callback_query: types.CallbackQuery, state: FSMContext):
    """Возврат к стратегии"""
    await bot.answer_callback_query(callback_query.id)
    
    # Создаем клавиатуру для опций стратегии
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🔍 Искать информацию в интернете", callback_data="search_internet"),
        InlineKeyboardButton("📢 Сгенерировать лозунги", callback_data="generate_slogans"),
        InlineKeyboardButton("✅ Завершить работу", callback_data="finish_strategy")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Вы вернулись к работе со стратегией. Что хотите сделать дальше?",
        reply_markup=keyboard
    )

@dp.message_handler(commands=['folders'])
async def cmd_folders(message: types.Message):
    """Обработчик команды /folders"""
    try:
        # Получаем список папок
        folders = await web_analyzer.get_folders()
        
        if not folders:
            await message.answer("У вас пока нет папок. Создайте новую папку с помощью команды /create_folder")
            return
        
        # Создаем клавиатуру с папками
        keyboard = InlineKeyboardMarkup(row_width=1)
        for folder in folders:
            keyboard.add(
                InlineKeyboardButton(
                    f"📁 {folder['name']} ({folder['channel_count']} каналов)",
                    callback_data=f"folder:{folder['id']}"
                )
            )
        
        # Добавляем кнопку создания новой папки
        keyboard.add(
            InlineKeyboardButton("➕ Создать новую папку", callback_data="create_folder")
        )
        
        await message.answer("📂 Ваши папки:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при получении списка папок: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message_handler(commands=['add_channel'])
async def cmd_add_channel(message: types.Message):
    """Обработчик команды /add_channel"""
    try:
        # Получаем список папок
        folders = await web_analyzer.get_folders()
        
        if not folders:
            # Если нет папок, просим создать сначала папку
            keyboard = InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                InlineKeyboardButton("➕ Создать папку", callback_data="create_folder")
            )
            
            await message.answer(
                "У вас нет папок для каналов. Сначала нужно создать папку.",
                reply_markup=keyboard
            )
            return
        
        # Создаем клавиатуру с папками
        keyboard = InlineKeyboardMarkup(row_width=1)
        for folder in folders:
            keyboard.add(
                InlineKeyboardButton(
                    f"📁 {folder['name']}",
                    callback_data=f"add_to_folder:{folder['id']}"
                )
            )
        
        await message.answer("Выберите папку для нового канала:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при получении списка папок: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message_handler(commands=['channels'])
async def cmd_channels(message: types.Message):
    """Обработчик команды /channels"""
    try:
        # Получаем список каналов
        channels = await web_analyzer.get_channels()
        
        if not channels:
            await message.answer(
                "У вас пока нет добавленных каналов. Добавьте канал с помощью команды /add_channel"
            )
            return
        
        # Создаем клавиатуру с каналами
        keyboard = InlineKeyboardMarkup(row_width=1)
        for channel in channels:
            keyboard.add(
                InlineKeyboardButton(
                    f"📢 {channel['title']} (@{channel['username']})",
                    callback_data=f"channel:{channel['id']}"
                )
            )
        
        # Добавляем кнопку добавления нового канала
        keyboard.add(
            InlineKeyboardButton("➕ Добавить новый канал", callback_data="add_channel")
        )
        
        await message.answer("📢 Ваши каналы:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при получении списка каналов: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message_handler(commands=['analyze'])
async def cmd_analyze(message: types.Message):
    """Обработчик команды /analyze"""
    try:
        # Получаем список каналов
        channels = await web_analyzer.get_channels()
        
        if not channels:
            await message.answer(
                "У вас пока нет добавленных каналов. Добавьте канал с помощью команды /add_channel"
            )
            return
        
        # Создаем клавиатуру с каналами
        keyboard = InlineKeyboardMarkup(row_width=1)
        for channel in channels:
            keyboard.add(
                InlineKeyboardButton(
                    f"📢 {channel['title']} (@{channel['username']})",
                    callback_data=f"analyze_channel:{channel['id']}"
                )
            )
        
        await message.answer("Выберите канал для анализа:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при получении списка каналов: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message_handler(commands=['models'])
async def cmd_models(message: types.Message):
    """Обработчик команды /models"""
    try:
        # Получаем список доступных моделей
        models = await ai_manager.get_available_models()
        current_model = await ai_manager.get_current_model()
        
        # Создаем клавиатуру с моделями
        keyboard = InlineKeyboardMarkup(row_width=1)
        for model in models:
            # Добавляем отметку к текущей модели
            model_text = f"✅ {model}" if model == current_model else model
            keyboard.add(
                InlineKeyboardButton(
                    model_text,
                    callback_data=f"set_model:{model}"
                )
            )
        
        await message.answer(
            f"🤖 Текущая модель: *{current_model}*\n\nВыберите модель для использования:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message_handler(commands=['providers'])
async def cmd_providers(message: types.Message):
    """Обработчик команды /providers"""
    try:
        # Получаем список доступных провайдеров
        providers = await ai_manager.get_available_providers()
        current_providers = await ai_manager.get_current_providers()
        
        # Создаем клавиатуру с провайдерами
        keyboard = InlineKeyboardMarkup(row_width=1)
        for provider in providers:
            # Добавляем отметку к текущим провайдерам
            provider_text = f"✅ {provider}" if provider in current_providers else provider
            keyboard.add(
                InlineKeyboardButton(
                    provider_text,
                    callback_data=f"toggle_provider:{provider}"
                )
            )
        
        # Добавляем кнопку сохранения
        keyboard.add(
            InlineKeyboardButton("💾 Сохранить", callback_data="save_providers")
        )
        
        await message.answer(
            f"🔌 Текущие провайдеры: *{', '.join(current_providers)}*\n\nВыберите провайдеры для использования:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при получении списка провайдеров: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

async def on_startup(dp: Dispatcher):
    """Действия при запуске бота"""
    logger.info("Bot started")


async def on_shutdown(dp: Dispatcher):
    """Действия при остановке бота"""
    logger.info("Bot stopped")
    await dp.storage.close()
    await dp.storage.wait_closed()
    await bot.session.close()

@dp.callback_query_handler(lambda c: c.data == "create_folder", state="*")
async def create_folder_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик создания новой папки"""
    await bot.answer_callback_query(callback_query.id)
    
    await bot.send_message(
        callback_query.from_user.id,
        "Введите название для новой папки:"
    )
    
    # Устанавливаем состояние ожидания имени папки
    await UserState.waiting_folder_name.set()

@dp.message_handler(state=UserState.waiting_folder_name)
async def process_folder_name(message: types.Message, state: FSMContext):
    """Обработчик ввода имени папки"""
    folder_name = message.text.strip()
    
    if not folder_name:
        await message.answer("Название папки не может быть пустым. Попробуйте еще раз:")
        return
    
    # Создаем папку
    result = await web_analyzer.create_folder(folder_name)
    
    if result.get("status") == "success":
        await message.answer(f"✅ Папка '{folder_name}' успешно создана!")
    else:
        await message.answer(f"❌ Ошибка при создании папки: {result.get('message', 'Неизвестная ошибка')}")
    
    # Сбрасываем состояние
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("folder:"), state="*")
async def folder_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора папки"""
    await bot.answer_callback_query(callback_query.id)
    
    folder_id = int(callback_query.data.split(":")[1])
    
    # Получаем каналы в папке
    channels = await web_analyzer.get_channels(folder_id)
    
    # Создаем клавиатуру с каналами
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    if channels:
        for channel in channels:
            keyboard.add(
                InlineKeyboardButton(
                    f"📢 {channel['title']} (@{channel['username']})",
                    callback_data=f"channel:{channel['id']}"
                )
            )
    
    # Добавляем кнопки управления папкой
    keyboard.add(
        InlineKeyboardButton("➕ Добавить канал", callback_data=f"add_to_folder:{folder_id}"),
        InlineKeyboardButton("🗑️ Удалить папку", callback_data=f"delete_folder:{folder_id}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_folders")
    )
    
    # Получаем информацию о папке
    folders = await web_analyzer.get_folders()
    folder_name = next((f["name"] for f in folders if f["id"] == folder_id), "Неизвестная папка")
    
    await bot.send_message(
        callback_query.from_user.id,
        f"📁 Папка: *{folder_name}*\n\n" + 
        (f"Каналы в папке ({len(channels)}):" if channels else "В этой папке пока нет каналов."),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query_handler(lambda c: c.data.startswith("add_to_folder:"), state="*")
async def add_to_folder_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик добавления канала в папку"""
    await bot.answer_callback_query(callback_query.id)
    
    folder_id = int(callback_query.data.split(":")[1])
    
    # Сохраняем ID папки в состоянии
    await state.update_data(folder_id=folder_id)
    
    # Создаем клавиатуру для отмены
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add_channel")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "Введите @username канала, который хотите добавить:",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ожидания имени канала
    await UserState.waiting_channel_username.set()

@dp.message_handler(state=UserState.waiting_channel_username)
async def process_channel_username(message: types.Message, state: FSMContext):
    """Обработчик ввода имени канала"""
    channel_username = message.text.strip()
    
    if not channel_username:
        await message.answer("Имя канала не может быть пустым. Попробуйте еще раз:")
        return
    
    # Если пользователь ввел @ в начале, удаляем его
    if channel_username.startswith("@"):
        channel_username = channel_username[1:]
    
    # Получаем ID папки из состояния
    data = await state.get_data()
    folder_id = data.get("folder_id")
    
    if not folder_id:
        await message.answer("❌ Ошибка: не указана папка. Попробуйте снова.")
        await state.finish()
        return
    
    # Отправляем сообщение о процессе
    processing_msg = await message.answer(MESSAGES['processing'])
    
    # Добавляем канал
    result = await web_analyzer.add_channel(folder_id, channel_username)
    
    # Удаляем сообщение о процессе
    await processing_msg.delete()
    
    if result.get("status") == "success":
        channel_info = result.get("channel_info", {})
        await message.answer(
            f"✅ Канал *{channel_info.get('title', channel_username)}* успешно добавлен в папку!",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(
            f"❌ Ошибка при добавлении канала: {result.get('message', 'Неизвестная ошибка')}"
        )
    
    # Сбрасываем состояние
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "cancel_add_channel", state=UserState.waiting_channel_username)
async def cancel_add_channel(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик отмены добавления канала"""
    await bot.answer_callback_query(callback_query.id)
    
    await bot.send_message(
        callback_query.from_user.id,
        "❌ Добавление канала отменено."
    )
    
    # Сбрасываем состояние
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "back_to_folders", state="*")
async def back_to_folders(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик возврата к списку папок"""
    await bot.answer_callback_query(callback_query.id)
    
    # Вызываем обработчик команды /folders
    await cmd_folders(callback_query.message)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_folder:"), state="*")
async def delete_folder_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик удаления папки"""
    await bot.answer_callback_query(callback_query.id)
    
    folder_id = int(callback_query.data.split(":")[1])
    
    # Создаем клавиатуру для подтверждения
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Да", callback_data=f"confirm_delete_folder:{folder_id}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"folder:{folder_id}")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "⚠️ Вы уверены, что хотите удалить эту папку? Все каналы в ней также будут удалены.",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith("confirm_delete_folder:"), state="*")
async def confirm_delete_folder(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик подтверждения удаления папки"""
    await bot.answer_callback_query(callback_query.id)
    
    folder_id = int(callback_query.data.split(":")[1])
    
    # Удаляем папку
    result = await web_analyzer.delete_folder(folder_id)
    
    if result.get("status") == "success":
        await bot.send_message(
            callback_query.from_user.id,
            "✅ Папка успешно удалена!"
        )
        
        # Возвращаемся к списку папок
        await cmd_folders(callback_query.message)
    else:
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Ошибка при удалении папки: {result.get('message', 'Неизвестная ошибка')}"
        )

@dp.callback_query_handler(lambda c: c.data.startswith("channel:"), state="*")
async def channel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора канала"""
    await bot.answer_callback_query(callback_query.id)
    
    channel_id = int(callback_query.data.split(":")[1])
    
    # Получаем информацию о канале
    channels = await web_analyzer.get_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    
    if not channel:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Канал не найден."
        )
        return
    
    # Создаем клавиатуру с действиями
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📊 Анализировать", callback_data=f"analyze_channel:{channel_id}"),
        InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_channel:{channel_id}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_channels")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        f"📢 Канал: *{channel['title']}*\n" +
        f"Username: @{channel['username']}\n" +
        f"ID: `{channel['id']}`",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query_handler(lambda c: c.data == "back_to_channels", state="*")
async def back_to_channels(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик возврата к списку каналов"""
    await bot.answer_callback_query(callback_query.id)
    
    # Вызываем обработчик команды /channels
    await cmd_channels(callback_query.message)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_channel:"), state="*")
async def delete_channel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик удаления канала"""
    await bot.answer_callback_query(callback_query.id)
    
    channel_id = int(callback_query.data.split(":")[1])
    
    # Создаем клавиатуру для подтверждения
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Да", callback_data=f"confirm_delete_channel:{channel_id}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"channel:{channel_id}")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        "⚠️ Вы уверены, что хотите удалить этот канал?",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith("confirm_delete_channel:"), state="*")
async def confirm_delete_channel(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик подтверждения удаления канала"""
    await bot.answer_callback_query(callback_query.id)
    
    channel_id = int(callback_query.data.split(":")[1])
    
    # Удаляем канал
    result = await web_analyzer.delete_channel(channel_id)
    
    if result.get("status") == "success":
        await bot.send_message(
            callback_query.from_user.id,
            "✅ Канал успешно удален!"
        )
        
        # Возвращаемся к списку каналов
        await cmd_channels(callback_query.message)
    else:
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Ошибка при удалении канала: {result.get('message', 'Неизвестная ошибка')}"
        )

@dp.callback_query_handler(lambda c: c.data.startswith("analyze_channel:"), state="*")
async def analyze_channel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик анализа канала"""
    await bot.answer_callback_query(callback_query.id)
    
    channel_id = int(callback_query.data.split(":")[1])
    
    # Получаем информацию о канале
    channels = await web_analyzer.get_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    
    if not channel:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Канал не найден."
        )
        return
    
    # Создаем клавиатуру с периодами анализа
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("За 1 день", callback_data=f"analyze_period:{channel_id}:1"),
        InlineKeyboardButton("За 4 дня", callback_data=f"analyze_period:{channel_id}:4"),
        InlineKeyboardButton("За 7 дней", callback_data=f"analyze_period:{channel_id}:7"),
        InlineKeyboardButton("🔙 Назад", callback_data=f"channel:{channel_id}")
    )
    
    await bot.send_message(
        callback_query.from_user.id,
        f"📊 Выберите период для анализа канала *{channel['title']}*:",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query_handler(lambda c: c.data.startswith("analyze_period:"), state="*")
async def analyze_period_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора периода анализа"""
    await bot.answer_callback_query(callback_query.id)
    
    parts = callback_query.data.split(":")
    channel_id = int(parts[1])
    period_days = int(parts[2])
    
    # Получаем информацию о канале
    channels = await web_analyzer.get_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    
    if not channel:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Канал не найден."
        )
        return
    
    # Отправляем сообщение о процессе
    processing_msg = await bot.send_message(
        callback_query.from_user.id,
        MESSAGES['processing']
    )
    
    try:
        # Анализируем канал
        result = await web_analyzer.analyze_channel(channel['username'], period_days)
        
        # Удаляем сообщение о процессе
        await processing_msg.delete()
        
        if result.get("status") == "success":
            # Формируем отчет
            messages = result.get("messages", [])
            topics = result.get("topics", [])
            sentiment = result.get("sentiment", {})
            
            report = f"📊 *Анализ канала {channel['title']}*\n\n"
            report += f"📅 Период: последние {period_days} дней\n"
            report += f"📝 Проанализировано сообщений: {len(messages)}\n\n"
            
            if topics:
                report += "🔍 *Основные темы:*\n"
                for topic in topics[:5]:
                    report += f"• {topic}\n"
                report += "\n"
            
            if sentiment:
                report += "😊 *Тональность:*\n"
                report += f"• Позитивная: {sentiment.get('positive', 0):.1f}%\n"
                report += f"• Нейтральная: {sentiment.get('neutral', 0):.1f}%\n"
                report += f"• Негативная: {sentiment.get('negative', 0):.1f}%\n\n"
            
            # Создаем клавиатуру для возврата
            keyboard = InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                InlineKeyboardButton("🔙 Назад к каналу", callback_data=f"channel:{channel_id}")
            )
            
            # Отправляем отчет
            await send_long_message(
                callback_query.from_user.id,
                report,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                callback_query.from_user.id,
                f"❌ Ошибка при анализе канала: {result.get('message', 'Неизвестная ошибка')}"
            )
    except Exception as e:
        logger.error(f"Ошибка при анализе канала: {e}")
        await processing_msg.delete()
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Произошла ошибка при анализе канала: {str(e)}"
        )

@dp.callback_query_handler(lambda c: c.data.startswith("set_model:"), state="*")
async def set_model_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик установки модели"""
    await bot.answer_callback_query(callback_query.id)
    
    model_name = callback_query.data.split(":")[1]
    
    # Устанавливаем модель
    result = await ai_manager.set_model(model_name)
    
    if result:
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Модель *{model_name}* успешно установлена!",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Ошибка при установке модели {model_name}."
        )
    
    # Обновляем список моделей
    await cmd_models(callback_query.message)

@dp.callback_query_handler(lambda c: c.data.startswith("toggle_provider:"), state="*")
async def toggle_provider_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик переключения провайдера"""
    await bot.answer_callback_query(callback_query.id)
    
    provider = callback_query.data.split(":")[1]
    
    # Получаем текущие провайдеры
    current_providers = await ai_manager.get_current_providers()
    
    # Переключаем провайдер
    if provider in current_providers:
        current_providers.remove(provider)
    else:
        current_providers.append(provider)
    
    # Сохраняем выбранные провайдеры в состоянии
    await state.update_data(selected_providers=current_providers)
    
    # Создаем клавиатуру с провайдерами
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    # Получаем список доступных провайдеров
    providers = await ai_manager.get_available_providers()
    
    for p in providers:
        # Добавляем отметку к выбранным провайдерам
        provider_text = f"✅ {p}" if p in current_providers else p
        keyboard.add(
            InlineKeyboardButton(
                provider_text,
                callback_data=f"toggle_provider:{p}"
            )
        )
    
    # Добавляем кнопку сохранения
    keyboard.add(
        InlineKeyboardButton("💾 Сохранить", callback_data="save_providers")
    )
    
    # Обновляем сообщение
    await bot.edit_message_text(
        f"🔌 Выбранные провайдеры: *{', '.join(current_providers)}*\n\nВыберите провайдеры для использования:",
        callback_query.from_user.id,
        callback_query.message.message_id,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query_handler(lambda c: c.data == "save_providers", state="*")
async def save_providers_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик сохранения провайдеров"""
    await bot.answer_callback_query(callback_query.id)
    
    # Получаем выбранные провайдеры из состояния
    data = await state.get_data()
    selected_providers = data.get("selected_providers", [])
    
    if not selected_providers:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Необходимо выбрать хотя бы одного провайдера."
        )
        return
    
    # Устанавливаем провайдеры
    result = await ai_manager.set_providers(selected_providers)
    
    if result:
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Провайдеры успешно сохранены: *{', '.join(selected_providers)}*",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Ошибка при сохранении провайдеров."
        )
    
    # Очищаем состояние
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "add_channel", state="*")
async def add_channel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик добавления канала из списка каналов"""
    await bot.answer_callback_query(callback_query.id)
    
    # Вызываем обработчик команды /add_channel
    await cmd_add_channel(callback_query.message)

@dp.callback_query_handler(lambda c: c.data == "cancel_operation", state="*")
async def cancel_operation(callback_query: types.CallbackQuery, state: FSMContext):
    """Отмена текущей операции"""
    await state.finish()
    await callback_query.message.edit_text("❌ Операция отменена")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "generate_slogans", state="*")
async def generate_slogans_start(callback_query: types.CallbackQuery, state: FSMContext):
    """Начало генерации лозунгов"""
    await bot.answer_callback_query(callback_query.id)
    
    # Получаем данные стратегии
    data = await state.get_data()
    strategy = data.get('strategy', {}).get('strategy', '')
    
    if not strategy:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Не найдена стратегия для генерации лозунгов"
        )
        return
    
    # Отправляем сообщение о начале генерации
    processing_msg = await bot.send_message(
        callback_query.from_user.id,
        MESSAGES['processing']
    )
    
    # Создаем задачу для генерации в фоне
    generation_task = asyncio.create_task(_generate_slogans_task(data))
    
    # Запускаем задачу обновления сообщения
    update_task = asyncio.create_task(_update_processing_message(processing_msg))
    
    try:
        # Ждем завершения генерации
        slogans = await generation_task
        # Отменяем обновление сообщения
        update_task.cancel()
        
        if isinstance(slogans, str) and slogans.startswith("Ошибка"):
            await processing_msg.edit_text(
                f"❌ {slogans}",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Форматируем лозунги
        slogans_text = "📢 *Сгенерированные лозунги:*\n\n"
        for i, slogan in enumerate(slogans, 1):
            slogans_text += f"{i}. {slogan}\n"
            
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Сгенерировать еще", callback_data="generate_slogans"),
            InlineKeyboardButton("🔙 Вернуться к стратегии", callback_data="back_to_strategy"),
            InlineKeyboardButton("✅ Завершить работу", callback_data="finish_strategy")
        )
        
        # Отправляем результат
        await send_long_message(
            callback_query.from_user.id,
            slogans_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    except asyncio.CancelledError:
        # Если задача была отменена
        update_task.cancel()
        await processing_msg.edit_text("❌ Генерация лозунгов была отменена")
    except Exception as e:
        # В случае других ошибок
        update_task.cancel()
        logger.error(f"Ошибка при генерации лозунгов: {e}")
        await processing_msg.edit_text(f"❌ Произошла ошибка при генерации лозунгов: {str(e)}")

async def _generate_slogans_task(data: dict) -> List[str]:
    """Фоновая задача для генерации лозунгов"""
    try:
        strategy = data.get('strategy', {}).get('strategy', '')
        point_b = data.get('point_b', '')
        target_audience = data.get('target_audience', '')
        
        # Генерируем тему для лозунгов на основе стратегии и цели
        theme = f"{point_b}\n\nКонтекст стратегии:\n{strategy[:500]}..."
        
        # Генерируем лозунги
        slogans = await ai_manager.generate_slogans(
            theme=theme,
            target_audience=target_audience,
            count=5
        )
        
        return slogans
        
    except Exception as e:
        logger.error(f"Ошибка в фоновой задаче генерации лозунгов: {e}")
        return f"Ошибка при генерации лозунгов: {str(e)}"

if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown) 
