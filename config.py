import os
from dotenv import load_dotenv

load_dotenv()

# Базовые настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Настройки Telethon
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

def get_admin_ids():
    admin_ids_str = os.getenv('ADMIN_IDS', '')
    if not admin_ids_str:
        return []
    try:
        return list(map(int, admin_ids_str.split(',')))
    except ValueError:
        return []

ADMIN_IDS = get_admin_ids()

# Настройки G4F
G4F_PROVIDER = os.getenv('G4F_PROVIDER', 'gpt-3.5-turbo')
G4F_MODEL = os.getenv('G4F_MODEL', 'gpt-3.5-turbo')

# Настройки базы данных
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot.db')

# Константы для работы бота
MAX_MESSAGE_LENGTH = 4096
MAX_ANALYSIS_TIME = 600  # 10 минут
DEFAULT_TIMEOUT = 60

# Системные промпты
SYSTEM_PROMPTS = {
    'situation_analysis': """Вы - опытный политтехнолог. Проанализируйте текущую ситуацию:
    1. Определите ключевые факторы
    2. Выявите сильные и слабые стороны
    3. Оцените риски и возможности
    Текущая ситуация: {situation}""",
    
    'strategy_generation': """На основе анализа ситуации разработайте стратегию:
    1. Определите основные направления работы
    2. Предложите конкретные тактические шаги
    3. Укажите необходимые ресурсы
    4. Определите временные рамки
    Цель: {goal}
    Временной период: {timeframe}
    Целевая аудитория: {target_audience}""",
    
    'slogan_generation': """Создайте эффективные лозунги и тезисы для кампании:
    1. Краткие и запоминающиеся
    2. Эмоционально заряженные
    3. Соответствующие целевой аудитории
    Тема: {theme}
    Целевая аудитория: {target_audience}""",
}

# Шаблоны сообщений
MESSAGES = {
    'start': "👋 Добро пожаловать в ПолитТехПро!\nЯ помогу вам разработать эффективную политическую стратегию.",
    'help': """🔍 Основные команды:
    /start - Начать работу
    /new_strategy - Создать новую стратегию
    /analyze - Анализ канала
    /generate_slogans - Генерация лозунгов
    /folders - Управление папками
    /add_channel - Добавить канал
    /channels - Список каналов
    /help - Помощь""",
    'error': "❌ Произошла ошибка: {error}",
    'timeout': "⏳ Превышено время ожидания. Попробуйте еще раз.",
    'processing': "⚙️ Обрабатываю ваш запрос...",
    'success': "✅ Готово!",
}

# Состояния FSM
class States:
    START = 'start'
    WAITING_POINT_A = 'waiting_point_a'
    WAITING_POINT_B = 'waiting_point_b'
    WAITING_TIMEFRAME = 'waiting_timeframe'
    WAITING_TARGET_AUDIENCE = 'waiting_target_audience'
    GENERATING_STRATEGY = 'generating_strategy'
    WAITING_CONFIRMATION = 'waiting_confirmation'
    EDITING_STRATEGY = 'editing_strategy'
    GENERATING_SLOGANS = 'generating_slogans'
    ANALYZING_SITUATION = 'analyzing_situation'
    WAITING_FOLDER_NAME = 'waiting_folder_name'
    WAITING_CHANNEL_USERNAME = 'waiting_channel_username'
    WAITING_FOLDER_SELECTION = 'waiting_folder_selection' 