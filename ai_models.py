from __future__ import annotations
from typing import List, Dict, Optional
from g4f.Provider import (
    DDG,
    Blackbox,
    Liaobots,
    PollinationsAI
)
from g4f import Model, models

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