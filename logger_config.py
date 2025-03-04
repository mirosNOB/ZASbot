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