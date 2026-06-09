"""路径辅助模块 - 提供基于项目根目录的绝对路径"""

from pathlib import Path

# 项目根目录（main.py 所在目录）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def get_path(relative_path: str) -> Path:
    """获取相对于项目根目录的绝对路径"""
    return PROJECT_ROOT / relative_path