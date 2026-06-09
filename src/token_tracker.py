"""Token消耗追踪模块 - 记录每次API调用的token用量，计算成本"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import List, Dict

import yaml

from .paths import get_path

logger = logging.getLogger(__name__)


class TokenRecord:
    """单次API调用的Token记录"""

    def __init__(
        self,
        step: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        elapsed_seconds: float = 0.0,
    ):
        self.step = step
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cached_tokens = cached_tokens
        self.elapsed_seconds = elapsed_seconds
        self.timestamp = None  # 由外部设置

    def to_dict(self) -> Dict:
        return {
            "step": self.step,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


class TokenTracker:
    """Token消耗追踪器"""

    def __init__(self, models_config_path: str = "config/models.yaml"):
        self.records: List[TokenRecord] = []
        self.pricing = self._load_pricing(models_config_path)

    def _load_pricing(self, config_path: str) -> Dict:
        """从配置文件加载计费信息"""
        try:
            path = get_path(config_path)
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return config.get("pricing", {})
        except Exception as e:
            logger.warning(f"Failed to load pricing config: {e}, using defaults")
            return {
                "input_per_million": 0.27,
                "cached_input_per_million": 0.07,
                "output_per_million": 1.10,
            }

    def record(
        self,
        step: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> TokenRecord:
        """记录一次API调用的Token消耗"""
        rec = TokenRecord(
            step=step,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            elapsed_seconds=elapsed_seconds,
        )
        self.records.append(rec)
        logger.info(
            f"Token recorded: step={step}, input={input_tokens}, "
            f"output={output_tokens}, cached={cached_tokens}"
        )
        return rec

    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    def total_cached_tokens(self) -> int:
        return sum(r.cached_tokens for r in self.records)

    def total_elapsed_seconds(self) -> float:
        return sum(r.elapsed_seconds for r in self.records)

    def compute_cost(self) -> Dict:
        """根据DeepSeek定价计算总成本"""
        pricing = self.pricing
        input_cost = self.total_input_tokens() * pricing.get("input_per_million", 0.27) / 1_000_000
        cached_cost = self.total_cached_tokens() * pricing.get("cached_input_per_million", 0.07) / 1_000_000
        output_cost = self.total_output_tokens() * pricing.get("output_per_million", 1.10) / 1_000_000
        total_cost = input_cost + cached_cost + output_cost

        return {
            "input_cost_usd": round(input_cost, 6),
            "cached_input_cost_usd": round(cached_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total_cost, 6),
        }

    def get_summary(self) -> Dict:
        """生成Token消耗汇总"""
        cost = self.compute_cost()
        return {
            "records": [r.to_dict() for r in self.records],
            "summary": {
                "total_input_tokens": self.total_input_tokens(),
                "total_output_tokens": self.total_output_tokens(),
                "total_cached_tokens": self.total_cached_tokens(),
                "total_elapsed_seconds": round(self.total_elapsed_seconds(), 2),
                **cost,
            },
        }

    def save(self, report_date: str, output_dir: str = "data/token_usage") -> str:
        """将Token消耗记录持久化到JSON文件"""
        dir_path = get_path(output_dir)
        os.makedirs(dir_path, exist_ok=True)
        filepath = dir_path / f"{report_date}.json"
        summary = self.get_summary()
        summary["date"] = report_date

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(f"Token usage saved to {filepath}")
        logger.info(
            f"Total cost: ${summary['summary']['total_cost_usd']} "
            f"(input={self.total_input_tokens()}, output={self.total_output_tokens()})"
        )
        return str(filepath)