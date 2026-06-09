"""DeepSeek API分析模块 - 三步调用架构：摘要 → 市场影响 → 个股关联"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional

import yaml
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .paths import get_path
from .token_tracker import TokenTracker

logger = logging.getLogger(__name__)


class DeepSeekAnalyzer:
    """DeepSeek API新闻分析器"""

    def __init__(
        self,
        tracker: TokenTracker,
        config_path: str = "config/models.yaml",
    ):
        self.tracker = tracker
        self.config = self._load_config(config_path)

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

        model_cfg = self.config["deepseek"]
        self.client = OpenAI(
            api_key=api_key,
            base_url=model_cfg["base_url"],
        )
        self.model = model_cfg["model"]
        self.max_tokens = model_cfg.get("max_tokens", 4096)
        self.temperature = model_cfg.get("temperature", 0.3)

    def _load_config(self, config_path: str) -> Dict:
        """加载模型配置"""
        path = get_path(config_path)
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _get_prompt(self, prompt_name: str) -> str:
        """获取指定 prompt 模板"""
        prompts = self.config.get("prompts", {})
        prompt = prompts.get(prompt_name, "")
        if not prompt:
            raise ValueError(f"Prompt '{prompt_name}' not found in config")
        return prompt

    def _extract_json(self, text: str) -> Dict:
        """从LLM响应中提取JSON（兼容非JSON模式或markdown包裹）"""
        logger.info(f"_extract_json input: {repr(text[:200])}")

        # 先尝试直接解析
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试提取 markdown code block 中的 JSON
        try:
            pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    parsed = json.loads(match.strip())
                    logger.info(f"Found JSON in code block: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
                    return parsed
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception:
            logger.warning("Error processing markdown code blocks")

        # 使用括号匹配找到完整的JSON对象
        try:
            start = text.find("{")
            logger.info(f"First '{{' found at position: {start}")
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    ch = text[i]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start : i + 1]
                            logger.info(f"Found candidate JSON with depth matching: {repr(candidate[:100])}")
                            try:
                                parsed = json.loads(candidate)
                                logger.info(f"Successfully parsed candidate: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
                                return parsed
                            except (json.JSONDecodeError, TypeError) as e:
                                logger.info(f"Depth-matched candidate failed JSON parse: {e}")
                                # Continue looking for other candidates
                            break

            # If no valid JSON found, return safe error dict
            logger.warning("Failed to extract valid JSON from response: %s", text[:200])
            return {"raw_output": text, "parse_error": True, "error_type": "no_valid_json"}

        except Exception as e:
            logger.error(f"Unexpected error in JSON extraction: {e}")
            return {"raw_output": text, "parse_error": True, "error_type": "extraction_error", "exception": str(e)}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(
            (Exception,)
        ),  # catches API errors, rate limits, etc.
        reraise=True,
    )
    def _call_api(
        self, step: str, system_prompt: str, user_content: str
    ) -> Dict:
        """调用DeepSeek API，带重试和Token记录"""
        logger.info(f"[{step}] DEBUG: _call_api started")
        logger.info(f"[{step}] Calling DeepSeek API...")
        logger.info(f"[{step}] DEBUG: system_prompt length: {len(system_prompt)}")
        logger.info(f"[{step}] DEBUG: user_content length: {len(user_content)}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(f"[{step}] DEBUG: messages created: {len(messages)} messages")
        start_time = time.time()

        try:
            logger.info(f"[{step}] DEBUG: About to call client.chat.completions.create")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            logger.info(f"[{step}] DEBUG: client.chat.completions.create returned")

            elapsed = time.time() - start_time
            logger.info(f"[{step}] DEBUG: elapsed time: {elapsed}")

            # Check if response exists and has the expected structure
            logger.info(f"[{step}] DEBUG: Checking response structure")
            if not response:
                logger.error(f"[{step}] DEBUG: Response is None or falsy")
                raise ValueError("Invalid API response structure")

            if not hasattr(response, 'choices'):
                logger.error(f"[{step}] DEBUG: Response has no 'choices' attribute")
                raise ValueError("Invalid API response structure")

            logger.info(f"[{step}] DEBUG: Response has choices, count: {len(response.choices)}")

            choice = response.choices[0]
            if not hasattr(choice, 'message'):
                logger.error(f"[{step}] DEBUG: Choice has no 'message' attribute")
                raise ValueError("Invalid choice structure in API response")

            if not hasattr(choice.message, 'content'):
                logger.error(f"[{step}] DEBUG: Message has no 'content' attribute")
                raise ValueError("Invalid choice structure in API response")

            raw_content = choice.message.content
            logger.info(f"[{step}] DEBUG: Got raw_content, type: {type(raw_content)}, length: {len(raw_content) if raw_content else 'None'}")
            logger.info(f"[{step}] Raw API response: {repr(raw_content[:200])}")

            # Handle the specific problematic case
            if raw_content and raw_content.strip().startswith('"summaries"'):
                logger.error(f"[{step}] DEBUG: Detected problematic response starting with 'summaries'")
                # Return error structure instead of raising exception
                return {
                    "raw_output": raw_content,
                    "parse_error": True,
                    "error_type": "schema_echo",
                    "summaries": []
                }

            # Process token usage
            usage = getattr(response, 'usage', None)
            logger.info(f"[{step}] DEBUG: usage: {usage}")
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            cached_tokens = getattr(usage, "prompt_tokens_details", None)
            cached_count = (
                cached_tokens.cached_tokens
                if cached_tokens and hasattr(cached_tokens, "cached_tokens")
                else 0
            )

            logger.info(f"[{step}] DEBUG: Tokens - input: {input_tokens}, output: {output_tokens}, cached: {cached_count}")

            # 记录Token消耗
            logger.info(f"[{step}] DEBUG: About to record token usage")
            self.tracker.record(
                step=step,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_count,
                elapsed_seconds=elapsed,
            )
            logger.info(f"[{step}] DEBUG: Token usage recorded")

            # Extract JSON
            logger.info(f"[{step}] DEBUG: About to extract JSON from raw_content")
            result = self._extract_json(raw_content)
            logger.info(f"[{step}] DEBUG: _extract_json returned, type: {type(result)}")

            # Make sure result is always a dict with expected structure
            if not isinstance(result, dict):
                logger.error(f"[{step}] DEBUG: _extract_json returned non-dict: {type(result)}, value: {result}")
                result = {"raw_output": str(raw_content) if raw_content else "", "parse_error": True}

            logger.info(f"[{step}] Parsed result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
            logger.info(f"[{step}] API call completed in {elapsed:.1f}s")

            return result

        except Exception as e:
            elapsed = time.time() - start_time
            error_str = str(e)
            logger.error(f"[{step}] DEBUG: Exception occurred in _call_api")
            logger.error(f"[{step}] DEBUG: Exception type: {type(e).__name__}")
            logger.error(f"[{step}] DEBUG: Exception message: {error_str}")
            logger.error(f"[{step}] DEBUG: Exception repr: {repr(e)}")
            logger.error(f"[{step}] DEBUG: Exception args: {e.args if hasattr(e, 'args') else 'No args'}")
            logger.warning(f"[{step}] API call failed after {elapsed:.1f}s: {error_str} (type: {type(e).__name__})")

            # Handle the specific problematic string case
            if error_str == '"\n  "summaries"' or error_str.startswith('summaries'):
                logger.error(f"[{step}] DEBUG: Caught the specific problematic response: {error_str}")
                return {
                    "raw_output": error_str,
                    "parse_error": True,
                    "error_type": "schema_echo",
                    "summaries": []
                }

            # Re-raise the exception so retry logic works
            logger.error(f"[{step}] DEBUG: About to re-raise exception")
            raise

    def analyze_news(self, news_text: str) -> Dict:
        """三步分析流程：摘要 → 市场影响 → 个股关联"""
        logger.info("=" * 60)
        logger.info("Starting three-step news analysis")
        logger.info("=" * 60)
        logger.info(f"DEBUG: analyze_news called with news_text length: {len(news_text)}")

        # Step 1: 新闻摘要提炼
        logger.info("DEBUG: About to get summary prompt")
        summary_prompt = self._get_prompt("summary")
        logger.info("DEBUG: Got summary prompt, setting system prompt")
        system_prompt = "你是一位资深财经分析师。严格按照JSON格式输出分析结果，严禁输出提示词、JSON格式示例或任何其他文字解释。只输出纯净的JSON数据。"

        logger.info("DEBUG: About to call _call_api for summary step")
        logger.info(f"DEBUG: summary_prompt type: {type(summary_prompt)}, length: {len(summary_prompt)}")
        try:
            logger.info("DEBUG: About to format summary_prompt")
            formatted_content = summary_prompt.format(news_content=news_text)
            logger.info(f"DEBUG: Formatted content length: {len(formatted_content)}")
        except Exception as e:
            logger.error(f"DEBUG: Exception during prompt formatting: {type(e).__name__}, message: {str(e)}")
            raise

        try:
            logger.info("Step 1/3: Generating news summaries...")
            summary_result = self._call_api(
                step="summary",
                system_prompt=system_prompt,
                user_content=formatted_content,
            )
            logger.info(f"DEBUG: _call_api returned successfully. Type: {type(summary_result)}, Value preview: {str(summary_result)[:100]}")
        except Exception as e:
            logger.error(f"DEBUG: Exception in _call_api call: {type(e).__name__}, message: {str(e)}")
            raise

        # Validate summary_result is a dict before processing
        logger.info(f"DEBUG: About to validate summary_result type")
        if not isinstance(summary_result, dict):
            logger.error(f"DEBUG: Summary result is not a dict: {type(summary_result)}, value: {summary_result}")
            return {
                "summaries": [],
                "us_market": {},
                "cn_market": {},
                "bullish_sectors": [],
                "bearish_sectors": [],
                "us_stocks": [],
                "cn_stocks": []
            }
        logger.info(f"DEBUG: summary_result is a dict with keys: {list(summary_result.keys())}")

        # Step 2: 市场影响判断
        logger.info("DEBUG: About to format summaries as JSON")
        try:
            summaries_json = json.dumps(summary_result, ensure_ascii=False)
            logger.info(f"DEBUG: Successfully formatted summaries_json: {summaries_json[:100]}")
        except Exception as e:
            logger.error(f"DEBUG: Failed to JSON serialize summary_result: {type(e).__name__}, message: {str(e)}")
            raise

        logger.info("DEBUG: Getting market prompt")
        market_prompt = self._get_prompt("market_impact")
        system_prompt = "你是一位资深市场分析师。严格按照JSON格式输出分析结果，严禁输出提示词、JSON格式示例或任何其他文字解释。只输出纯净的JSON数据。"

        logger.info("DEBUG: About to call _call_api for market step")
        try:
            logger.info("Step 2/3: Analyzing market impact...")
            market_result = self._call_api(
                step="market_impact",
                system_prompt=system_prompt,
                user_content=market_prompt.format(summaries=summaries_json),
            )
            logger.info(f"DEBUG: Market _call_api returned successfully. Type: {type(market_result)}")
        except Exception as e:
            logger.error(f"DEBUG: Exception in market _call_api: {type(e).__name__}, message: {str(e)}")
            raise

        # Validate market_result is a dict before processing
        if not isinstance(market_result, dict):
            logger.error(f"DEBUG: Market result is not a dict: {type(market_result)}, value: {market_result}")
            market_result = {}

        # Step 3: 个股关联
        logger.info("DEBUG: About to format market as JSON")
        market_json = json.dumps(market_result, ensure_ascii=False)
        stock_prompt = self._get_prompt("stock_pick")
        system_prompt = "你一位资深投资顾问。严格按照JSON格式输出分析结果，严禁输出提示词、JSON格式示例或任何其他文字解释。只输出纯净的JSON数据。"

        logger.info("DEBUG: About to call _call_api for stock step")
        try:
            logger.info("Step 3/3: Identifying related stocks...")
            stock_result = self._call_api(
                step="stock_pick",
                system_prompt=system_prompt,
                user_content=stock_prompt.format(
                    summaries=summaries_json,
                    market_impact=market_json,
                ),
            )
            logger.info(f"DEBUG: Stock _call_api returned successfully. Type: {type(stock_result)}")
        except Exception as e:
            logger.error(f"DEBUG: Exception in stock _call_api: {type(e).__name__}, message: {str(e)}")
            raise

        # Validate stock_result is a dict before processing
        if not isinstance(stock_result, dict):
            logger.error(f"DEBUG: Stock result is not a dict: {type(stock_result)}, value: {stock_result}")
            stock_result = {}

        # 整合全部结果
        logger.info("DEBUG: About to create final result dict")
        try:
            full_result = {
                "summaries": summary_result.get("summaries", []),
                "us_market": market_result.get("us_market", {}),
                "cn_market": market_result.get("cn_market", {}),
                "bullish_sectors": market_result.get("bullish_sectors", []),
                "bearish_sectors": market_result.get("bearish_sectors", []),
                "us_stocks": stock_result.get("us_stocks", []),
                "cn_stocks": stock_result.get("cn_stocks", []),
            }
            logger.info(f"DEBUG: Created full_result successfully with keys: {list(full_result.keys())}")
        except Exception as e:
            logger.error(f"DEBUG: Exception creating full_result: {type(e).__name__}, message: {str(e)}")
            raise

        logger.info("=" * 60)
        logger.info("Three-step analysis completed")
        logger.info("=" * 60)

        return full_result