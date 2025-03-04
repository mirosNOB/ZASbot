from __future__ import annotations
import g4f
import asyncio
from typing import List, Dict, Any, Optional, Union
import logging
from g4f.Provider import (
    DDG,
    Blackbox,
    Liaobots,
    PollinationsAI
)
from g4f import Model, models

# Logger setup function
def setup_logger(name=None, level=logging.INFO):
    """Настройка цветного логирования для модулей бота"""
    import colorlog
    
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

# Proxy manager placeholder (if needed)
class ProxyManager:
    async def get_next_proxy(self):
        return None
        
    def format_proxy_for_g4f(self, proxy_url):
        return {}

proxy_manager = ProxyManager()

class AIModelManager:
    def __init__(self):
        self.current_model = models.gpt_4o
        self.current_providers = [DDG, Blackbox, Liaobots, PollinationsAI]
        self.available_models = {
            "gpt-4": models.gpt_4,
            "gpt-4o": models.gpt_4o,
            "gpt-4o-mini": models.gpt_4o_mini,
            "claude-3-opus": models.claude_3_opus,
            "claude-3-sonnet": models.claude_3_sonnet,
            "claude-3-haiku": models.claude_3_haiku,
            "gemini-pro": models.gemini_1_5_pro,
            "llama-3": models.llama_3,
            "mixtral-8x7b": models.mixtral_8x7b,
        }
        
    def set_model(self, model_name: str) -> bool:
        """Установка модели по имени"""
        if model_name in self.available_models:
            self.current_model = self.available_models[model_name]
            return True
        return False
        
    def get_current_model(self) -> Model:
        """Получение текущей модели"""
        return self.current_model
        
    def get_available_models(self) -> List[str]:
        """Получение списка доступных моделей"""
        return list(self.available_models.keys())
        
    def set_providers(self, providers: List[str]) -> bool:
        """Установка провайдеров"""
        available_providers = {
            "ddg": DDG,
            "blackbox": Blackbox,
            "liaobots": Liaobots,
            "pollinations": PollinationsAI
        }
        
        new_providers = []
        for provider in providers:
            if provider.lower() in available_providers:
                new_providers.append(available_providers[provider.lower()])
                
        if new_providers:
            self.current_providers = new_providers
            return True
        return False
        
    def get_current_providers(self) -> List[str]:
        """Получение списка текущих провайдеров"""
        provider_names = {
            DDG: "ddg",
            Blackbox: "blackbox",
            Liaobots: "liaobots",
            PollinationsAI: "pollinations"
        }
        return [provider_names.get(p, str(p)) for p in self.current_providers]
        
    def get_available_providers(self) -> List[str]:
        """Получение списка доступных провайдеров"""
        return ["ddg", "blackbox", "liaobots", "pollinations"]

class AIManager:
    def __init__(self):
        self.model_manager = AIModelManager()
        self.logger = setup_logger(__name__)

    async def _make_request(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """Отправка запроса к модели"""
        try:
            # Получаем модель и провайдеры
            model = self.model_manager.get_current_model()
            providers = self.model_manager.current_providers
            self.logger.info(f"Запрос к модели {model} через провайдеры {', '.join([p.__name__ for p in providers])}")
            
            # Получаем прокси из менеджера
            proxy_url = await proxy_manager.get_next_proxy()
            proxies = proxy_manager.format_proxy_for_g4f(proxy_url) if proxy_url else {}
            
            if proxies:
                self.logger.info(f"Используем прокси: {proxy_url}")
            else:
                self.logger.warning("Прокси не найдены, запрос будет отправлен напрямую")
            
            try:
                # Улучшенная обработка потокового режима с обработкой форматов ответов
                response_chunks = []
                async for chunk in g4f.ChatCompletion.create_async(
                    model=model,
                    messages=messages,
                    providers=providers,
                    temperature=temperature,
                    stream=True,
                    proxy=proxies,  # Передаем прокси в запрос
                ):
                    if chunk:
                        # Проверяем, не является ли чанк словарем с форматом data:{"content":"..."}
                        if isinstance(chunk, dict) and "content" in chunk:
                            chunk = chunk.get("content", "")
                        elif isinstance(chunk, str) and chunk.startswith('data:'):
                            # Удаляем префикс data: и пытаемся получить содержимое
                            try:
                                import json
                                json_str = chunk.replace('data:', '').strip()
                                if json_str:
                                    data = json.loads(json_str)
                                    if isinstance(data, dict) and "content" in data:
                                        chunk = data.get("content", "")
                            except Exception as json_error:
                                self.logger.warning(f"Не удалось разобрать JSON из потокового ответа: {json_error}")
                        
                        response_chunks.append(str(chunk))
                
                # Собираем полный ответ из частей
                complete_response = ''.join(response_chunks)
                self.logger.debug(f"Полный ответ от модели получен (потоковый режим), длина: {len(complete_response)}")
                
            except Exception as stream_error:
                # Если потоковый режим не работает, используем обычный запрос
                self.logger.warning(f"Ошибка при использовании потокового режима: {stream_error}. Переключаемся на обычный режим.")
                complete_response = await g4f.ChatCompletion.create_async(
                    model=model,
                    messages=messages,
                    providers=providers,
                    temperature=temperature,
                    stream=False,
                    proxy=proxies,  # Передаем прокси в запрос
                )
                
                # Если ответ пришел в формате словаря с полем content
                if isinstance(complete_response, dict) and "content" in complete_response:
                    complete_response = complete_response.get("content", "")
                
                self.logger.debug(f"Полный ответ от модели получен (обычный режим), длина: {len(complete_response) if complete_response else 0}")
            
            # Проверка на пустой ответ
            if not complete_response:
                self.logger.warning("Получен пустой ответ от модели")
                return "Не удалось получить ответ от модели. Пожалуйста, попробуйте еще раз или измените запрос."
                
            return complete_response
        except Exception as e:
            self.logger.error(f"Ошибка при запросе к модели: {e}")
            return "Ошибка при обработке запроса: " + str(e)

    async def analyze_situation(self, situation: str) -> Dict[str, Any]:
        """Анализ текущей ситуации"""
        messages = [
            {"role": "system", "content": "Вы - опытный политтехнолог. Проанализируйте текущую ситуацию."},
            {"role": "user", "content": situation}
        ]
        
        self.logger.info(f"Запрос на анализ ситуации, длина входных данных: {len(situation)}")
        response = await self._make_request(messages, temperature=0.7)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось выполнить анализ"
            self.logger.error(f"Ошибка анализа ситуации: {error_msg}")
            return {"error": error_msg, "analysis": "Не удалось выполнить анализ ситуации. Пожалуйста, уточните ваш запрос."}
            
        self.logger.info(f"Анализ ситуации успешно выполнен, длина ответа: {len(response)}")
        return {
            "analysis": response,
            "key_factors": self._extract_key_factors(response),
            "risks": self._extract_risks(response),
            "opportunities": self._extract_opportunities(response)
        }

    async def generate_strategy(self, 
                              point_a: str, 
                              point_b: str, 
                              timeframe: str, 
                              target_audience: str) -> Dict[str, Any]:
        """Генерация стратегии"""
        messages = [
            {"role": "system", "content": "Вы - опытный политтехнолог. Разработайте стратегию достижения цели."},
            {"role": "user", "content": f"Текущая ситуация: {point_a}\nЦель: {point_b}\nВременные рамки: {timeframe}\nЦелевая аудитория: {target_audience}"}
        ]
        
        self.logger.info(f"Запрос на генерацию стратегии, входные данные: точка А ({len(point_a)} символов), точка Б ({len(point_b)} символов)")
        response = await self._make_request(messages, temperature=0.8)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось сгенерировать стратегию"
            self.logger.error(f"Ошибка генерации стратегии: {error_msg}")
            return {"error": error_msg, "strategy": "Не удалось сгенерировать стратегию. Пожалуйста, уточните ваш запрос."}
            
        self.logger.info(f"Стратегия успешно сгенерирована, длина ответа: {len(response)}")
        return {
            "strategy": response,
            "steps": self._extract_steps(response),
            "timeline": self._extract_timeline(response),
            "resources": self._extract_resources(response)
        }

    async def generate_slogans(self, 
                             theme: str, 
                             target_audience: str, 
                             count: int = 5) -> List[str]:
        """Генерация лозунгов и тезисов"""
        messages = [
            {"role": "system", "content": "Вы - опытный копирайтер. Создайте эффективные лозунги."},
            {"role": "user", "content": f"Тема: {theme}\nЦелевая аудитория: {target_audience}\nКоличество лозунгов: {count}"}
        ]
        
        self.logger.info(f"Запрос на генерацию лозунгов по теме '{theme}' для аудитории '{target_audience}'")
        response = await self._make_request(messages, temperature=0.9)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось сгенерировать лозунги"
            self.logger.error(f"Ошибка генерации лозунгов: {error_msg}")
            return ["Не удалось сгенерировать лозунги. Пожалуйста, уточните запрос."]
            
        self.logger.info(f"Лозунги успешно сгенерированы, длина ответа: {len(response)}")
        slogans = self._extract_slogans(response)
        
        # Если не удалось извлечь лозунги, возвращаем весь ответ как один лозунг
        if not slogans:
            self.logger.warning("Не удалось извлечь лозунги из ответа, возвращаем весь ответ")
            return [response]
            
        return slogans

    async def refine_strategy(self, 
                            strategy: str, 
                            feedback: str) -> str:
        """Улучшение стратегии на основе обратной связи"""
        messages = [
            {"role": "system", "content": "Вы - опытный политтехнолог. Улучшите стратегию на основе обратной связи."},
            {"role": "user", "content": f"Стратегия:\n{strategy}\n\nОбратная связь:\n{feedback}"}
        ]
        
        self.logger.info(f"Запрос на улучшение стратегии на основе обратной связи, длина стратегии: {len(strategy)}, длина обратной связи: {len(feedback)}")
        response = await self._make_request(messages, temperature=0.7)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось улучшить стратегию"
            self.logger.error(f"Ошибка улучшения стратегии: {error_msg}")
            return f"Не удалось улучшить стратегию. Исходная стратегия:\n\n{strategy}"
            
        self.logger.info(f"Стратегия успешно улучшена, длина ответа: {len(response)}")
        return response

    def _extract_key_factors(self, text: str) -> List[str]:
        """Извлечение ключевых факторов из текста"""
        factors = []
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['фактор', 'ключевой', 'важный', 'основной']):
                factors.append(line.strip())
        return factors

    def _extract_risks(self, text: str) -> List[str]:
        """Извлечение рисков из текста"""
        risks = []
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['риск', 'угроза', 'опасность', 'проблема']):
                risks.append(line.strip())
        return risks

    def _extract_opportunities(self, text: str) -> List[str]:
        """Извлечение возможностей из текста"""
        opportunities = []
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['возможность', 'перспектива', 'потенциал']):
                opportunities.append(line.strip())
        return opportunities

    def _extract_steps(self, text: str) -> List[str]:
        """Извлечение шагов из текста"""
        steps = []
        lines = text.split('\n')
        current_step = ""
        for line in lines:
            if any(line.strip().lower().startswith(str(i)) for i in range(1, 10)):
                if current_step:
                    steps.append(current_step.strip())
                current_step = line.strip()
            elif current_step:
                current_step += " " + line.strip()
        if current_step:
            steps.append(current_step.strip())
        return steps

    def _extract_timeline(self, text: str) -> List[Dict[str, Any]]:
        """Извлечение временной линии из текста"""
        timeline = []
        lines = text.split('\n')
        current_period = {}
        for line in lines:
            if any(keyword in line.lower() for keyword in ['этап', 'период', 'фаза', 'месяц', 'неделя']):
                if current_period:
                    timeline.append(current_period)
                current_period = {'period': line.strip(), 'actions': []}
            elif current_period and line.strip():
                current_period['actions'].append(line.strip())
        if current_period:
            timeline.append(current_period)
        return timeline

    def _extract_resources(self, text: str) -> List[str]:
        """Извлечение необходимых ресурсов из текста"""
        resources = []
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['ресурс', 'требуется', 'необходимо', 'нужно']):
                resources.append(line.strip())
        return resources

    def _extract_slogans(self, text: str) -> List[str]:
        """Извлечение лозунгов из текста"""
        slogans = []
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith(('•', '-', '*', '1.', '2.', '3.', '4.', '5.')):
                slogans.append(line)
        return slogans

    # Методы для управления моделями и провайдерами
    async def set_model(self, model_name: str) -> bool:
        """Установка модели по имени"""
        return self.model_manager.set_model(model_name)

    async def get_current_model(self) -> str:
        """Получение имени текущей модели"""
        return self.model_manager.get_current_model().name

    async def get_available_models(self) -> List[str]:
        """Получение списка доступных моделей"""
        return self.model_manager.get_available_models()

    async def set_providers(self, providers: List[str]) -> bool:
        """Установка провайдеров"""
        return self.model_manager.set_providers(providers)

    async def get_current_providers(self) -> List[str]:
        """Получение списка текущих провайдеров"""
        return self.model_manager.get_current_providers()

    async def get_available_providers(self) -> List[str]:
        """Получение списка доступных провайдеров"""
        return self.model_manager.get_available_providers() 