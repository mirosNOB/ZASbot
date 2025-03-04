import aiohttp
import asyncio
import random
from typing import Optional, List, Dict
import logging
from logger_config import setup_logger
import g4f
from g4f.Provider import DDG, Blackbox, Liaobots, PollinationsAI

class ProxyManager:
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.proxy_list: List[Dict[str, str]] = []
        self.current_proxy: Optional[Dict[str, str]] = None
        self.proxy_sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
            "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt"
        ]
        self.test_url = "https://api.telegram.org"
        self.max_retries = 3
        self.timeout = 10

    async def fetch_proxies(self) -> List[Dict[str, str]]:
        """Получение списка прокси из различных источников"""
        proxies = set()
        async with aiohttp.ClientSession() as session:
            for source in self.proxy_sources:
                try:
                    async with session.get(source, timeout=10) as response:
                        if response.status == 200:
                            text = await response.text()
                            for line in text.splitlines():
                                if ':' in line:
                                    ip, port = line.strip().split(':')
                                    proxies.add(f"http://{ip}:{port}")
                except Exception as e:
                    self.logger.error(f"Ошибка при получении прокси из {source}: {e}")
        
        return [{"http": proxy, "https": proxy} for proxy in proxies]

    async def test_proxy(self, proxy: Dict[str, str]) -> bool:
        """Тестирование прокси на работоспособность"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.test_url,
                    proxy=proxy["http"],
                    timeout=self.timeout,
                    ssl=False
                ) as response:
                    return response.status == 200
        except Exception as e:
            self.logger.debug(f"Прокси {proxy['http']} не работает: {e}")
            return False

    async def get_working_proxy(self) -> Optional[Dict[str, str]]:
        """Получение рабочего прокси"""
        if not self.proxy_list:
            self.proxy_list = await self.fetch_proxies()
            self.logger.info(f"Получено {len(self.proxy_list)} прокси")

        # Перемешиваем список прокси
        random.shuffle(self.proxy_list)
        
        for proxy in self.proxy_list:
            if await self.test_proxy(proxy):
                self.logger.info(f"Найден рабочий прокси: {proxy['http']}")
                return proxy
        
        return None

    async def test_g4f_with_proxy(self, proxy: Dict[str, str]) -> bool:
        """Тестирование прокси с g4f"""
        try:
            # Настраиваем g4f для использования прокси
            g4f.debug.logging = False
            g4f.debug.version_check = False
            
            # Пробуем простой запрос
            response = await g4f.ChatCompletion.create_async(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "test"}],
                provider=DDG,
                proxy=proxy["http"]
            )
            return bool(response)
        except Exception as e:
            self.logger.debug(f"Ошибка при тестировании g4f с прокси {proxy['http']}: {e}")
            return False

    async def get_working_g4f_proxy(self) -> Optional[Dict[str, str]]:
        """Получение рабочего прокси для g4f"""
        for attempt in range(self.max_retries):
            proxy = await self.get_working_proxy()
            if proxy and await self.test_g4f_with_proxy(proxy):
                self.current_proxy = proxy
                return proxy
            self.logger.warning(f"Попытка {attempt + 1}/{self.max_retries} не удалась")
        
        return None

    def format_proxy_for_g4f(self, proxy_url: str) -> str:
        """Форматирование прокси для g4f"""
        return proxy_url.replace("http://", "").replace("https://", "")

    async def ensure_working_proxy(self) -> Optional[Dict[str, str]]:
        """Проверка и обновление текущего прокси при необходимости"""
        if not self.current_proxy or not await self.test_g4f_with_proxy(self.current_proxy):
            self.current_proxy = await self.get_working_g4f_proxy()
        return self.current_proxy 