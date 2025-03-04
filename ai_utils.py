import g4f
import asyncio
from typing import List, Dict, Any, Optional
import logging
from logger_config import setup_logger
from ai_models import AIModelManager

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
            
            try:
                # Улучшенная обработка потокового режима с обработкой форматов ответов
                response_chunks = []
                async for chunk in g4f.ChatCompletion.create_async(
                    model=model,
                    messages=messages,
                    providers=providers,
                    temperature=temperature,
                    stream=True,
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

    async def generate_strategy_with_article(self,
                                           point_a: str,
                                           point_b: str,
                                           timeframe: str,
                                           target_audience: str,
                                           article_title: str,
                                           article_content: str) -> Dict[str, Any]:
        """
        Генерация стратегии с учетом информации из статьи
        
        Args:
            point_a: Текущая ситуация
            point_b: Желаемый результат
            timeframe: Временные рамки
            target_audience: Целевая аудитория
            article_title: Заголовок статьи
            article_content: Содержимое статьи
            
        Returns:
            Dict[str, Any]: Результат генерации стратегии
        """
        # Ограничиваем размер статьи, чтобы избежать превышения лимитов контекста
        max_content_length = 2000
        if len(article_content) > max_content_length:
            article_content = article_content[:max_content_length] + "..."
        
        messages = [
            {"role": "system", "content": "Вы - опытный политтехнолог. Разработайте стратегию достижения цели с учетом информации из статьи."},
            {"role": "user", "content": f"Текущая ситуация: {point_a}\n\nЦель: {point_b}\n\nВременные рамки: {timeframe}\n\nЦелевая аудитория: {target_audience}\n\nСтатья для контекста:\nЗаголовок: {article_title}\nСодержание: {article_content}\n\nРазработайте подробную стратегию, используя информацию из статьи, когда это уместно и может повысить эффективность стратегии. Обязательно укажите, как именно информация из статьи повлияла на стратегию."}
        ]
        
        self.logger.info(f"Запрос на генерацию стратегии с учетом статьи, входные данные: точка А ({len(point_a)} символов), точка Б ({len(point_b)} символов), статья ({len(article_content)} символов)")
        response = await self._make_request(messages, temperature=0.8)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось сгенерировать стратегию"
            self.logger.error(f"Ошибка генерации стратегии с учетом статьи: {error_msg}")
            return {"error": error_msg, "strategy": "Не удалось сгенерировать стратегию. Пожалуйста, уточните ваш запрос."}
            
        self.logger.info(f"Стратегия с учетом статьи успешно сгенерирована, длина ответа: {len(response)}")
        return {
            "strategy": response,
            "steps": self._extract_steps(response),
            "timeline": self._extract_timeline(response),
            "resources": self._extract_resources(response)
        }

    async def generate_strategy_with_channel(self,
                                          point_a: str,
                                          point_b: str,
                                          timeframe: str,
                                          target_audience: str,
                                          channel_title: str,
                                          channel_content: str,
                                          article_title: str = "",
                                          article_content: str = "") -> Dict[str, Any]:
        """
        Генерация стратегии с учетом данных из Telegram-канала и опционально статьи
        
        Args:
            point_a: Текущая ситуация
            point_b: Желаемый результат
            timeframe: Временные рамки
            target_audience: Целевая аудитория
            channel_title: Название канала
            channel_content: Содержимое канала (посты)
            article_title: Заголовок статьи (опционально)
            article_content: Содержимое статьи (опционально)
            
        Returns:
            Dict[str, Any]: Результат генерации стратегии
        """
        # Ограничиваем размер контента, чтобы избежать превышения лимитов контекста
        max_content_length = 2000
        if len(channel_content) > max_content_length:
            channel_content = channel_content[:max_content_length] + "..."
            
        article_text = ""
        if article_title and article_content:
            if len(article_content) > max_content_length:
                article_content = article_content[:max_content_length] + "..."
            article_text = f"\n\nСтатья для дополнительного контекста:\nЗаголовок: {article_title}\nСодержание: {article_content}"
        
        messages = [
            {"role": "system", "content": "Вы - опытный политтехнолог. Разработайте стратегию достижения цели с учетом информации из Telegram-канала."},
            {"role": "user", "content": f"Текущая ситуация: {point_a}\n\nЦель: {point_b}\n\nВременные рамки: {timeframe}\n\nЦелевая аудитория: {target_audience}\n\nДанные из Telegram-канала '{channel_title}':\n{channel_content}{article_text}\n\nРазработайте подробную стратегию, используя информацию из канала и статьи (если есть), когда это уместно и может повысить эффективность стратегии. Обязательно укажите, как именно информация из канала повлияла на стратегию."}
        ]
        
        self.logger.info(f"Запрос на генерацию стратегии с учетом данных канала, входные данные: точка А ({len(point_a)} символов), точка Б ({len(point_b)} символов), канал ({len(channel_content)} символов), статья ({len(article_content) if article_content else 0} символов)")
        response = await self._make_request(messages, temperature=0.8)
        
        # Проверяем, содержит ли ответ сообщение об ошибке
        if not response or response.startswith("Ошибка при обработке запроса") or response.startswith("Не удалось получить ответ"):
            error_msg = response if response else "Не удалось сгенерировать стратегию"
            self.logger.error(f"Ошибка генерации стратегии с учетом канала: {error_msg}")
            return {"error": error_msg, "strategy": "Не удалось сгенерировать стратегию. Пожалуйста, уточните ваш запрос."}
            
        self.logger.info(f"Стратегия с учетом канала успешно сгенерирована, длина ответа: {len(response)}")
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
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and len(line) < 100:
                # Удаляем цифры, звездочки и другие маркеры списков в начале
                clean_line = line.lstrip('0123456789.- *•>')
                if clean_line:
                    slogans.append(clean_line.strip())
        
        return slogans

    async def generate_search_query(self, strategy: str, point_a: str, point_b: str, target_audience: str) -> str:
        """
        Генерирует поисковый запрос на основе стратегии и других параметров
        
        Args:
            strategy: Текст стратегии
            point_a: Текущая ситуация
            point_b: Желаемый результат
            target_audience: Целевая аудитория
            
        Returns:
            str: Поисковый запрос
        """
        prompt = (
            f"На основе следующих данных сформулируй один короткий поисковый запрос "
            f"(до 10 слов) для поиска информации в интернете, которая может помочь "
            f"в реализации стратегии.\n\n"
            f"Текущая ситуация: {point_a}\n"
            f"Желаемый результат: {point_b}\n"
            f"Целевая аудитория: {target_audience}\n"
            f"Стратегия: {strategy[:500]}...\n\n"
            f"Поисковый запрос должен быть конкретным и содержать ключевые слова, "
            f"но при этом быть коротким. Не используй кавычки и специальные символы "
            f"в запросе. Верни только текст запроса без дополнительных пояснений."
        )
        
        messages = [
            {"role": "system", "content": "Ты - помощник, который формулирует поисковые запросы."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self._make_request(messages)
            # Очищаем от лишних символов и кавычек
            query = response.strip(' "\'\n')
            
            if len(query) > 150:
                query = query[:150]
                
            return query
        except Exception as e:
            self.logger.error(f"Ошибка при генерации поискового запроса: {e}")
            # Возвращаем запрос по умолчанию в случае ошибки
            return f"{point_b} для {target_audience}"

    async def analyze_article_for_channel(self, title: str, content: str, channel_info: Dict, channel_analysis: Dict) -> str:
        """
        Анализирует статью в контексте Telegram-канала
        
        Args:
            title: Заголовок статьи
            content: Содержимое статьи
            channel_info: Информация о канале
            channel_analysis: Результаты анализа канала
            
        Returns:
            str: Результаты анализа статьи в контексте канала
        """
        prompt = (
            f"Проанализируй статью в контексте Telegram-канала и дай рекомендации:\n\n"
            f"Канал: @{channel_info.get('username', '')}\n"
            f"Название канала: {channel_info.get('title', '')}\n"
            f"Статистика канала:\n"
            f"- Всего сообщений: {channel_analysis.get('total_messages', 0)}\n"
            f"- Среднее количество просмотров: {int(channel_analysis.get('avg_views', 0))}\n\n"
            f"Заголовок статьи: {title}\n\n"
            f"Содержание статьи (фрагмент):\n{content[:1500]}...\n\n"
            f"Дай анализ статьи, учитывая следующие аспекты:\n"
            f"1. Насколько тема статьи соответствует тематике канала\n"
            f"2. Потенциальный интерес аудитории канала к этой статье\n"
            f"3. Рекомендации по использованию информации из статьи в контексте канала\n"
            f"4. Ключевые моменты, которые стоит выделить при публикации\n"
            f"5. Возможные риски при публикации материала\n\n"
            f"Структурируй ответ по пунктам и дай конкретные рекомендации."
        )
        
        messages = [
            {"role": "system", "content": "Ты - аналитик контента для Telegram-каналов."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self._make_request(messages)
            return response
        except Exception as e:
            self.logger.error(f"Ошибка при анализе статьи: {e}")
            return "Произошла ошибка при анализе статьи. Пожалуйста, попробуйте еще раз."

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