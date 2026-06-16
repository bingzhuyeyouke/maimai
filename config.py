"""
配置管理模块 —— 从 .env 文件读取所有配置
所有配置项都在这里集中管理，其他模块不要直接读环境变量
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path

# 项目根目录（config.py 所在目录）
PROJECT_ROOT = Path(__file__).parent


class Settings(BaseSettings):
    """
    全局配置，自动从 .env 文件加载
    用法：from config import settings
    """

    # ---------- 热点抓取 ----------
    crawl_interval: int = Field(
        default=60,
        description="请求间隔（秒），避免被反爬",
    )

    # ---------- 数据库 ----------
    db_path: str = Field(
        default="media_assistant.db",
        description="SQLite 数据库文件名",
    )

    # ---------- AI 内容生成（第2步用，先占位） ----------
    ai_api_key: str = Field(default="", description="AI 接口密钥")
    ai_model: str = Field(default="gpt-4o-mini", description="AI 模型名称")
    ai_base_url: str = Field(default="https://api.openai.com/v1", description="AI 接口地址")

    # ---------- 日志 ----------
    log_level: str = Field(default="INFO", description="日志级别")

    # ---------- 飞书表格 ----------
    feishu_app_id: str = Field(default="", description="飞书应用 app_id")
    feishu_app_secret: str = Field(default="", description="飞书应用 app_secret")
    feishu_spreadsheet_token: str = Field(
        default="",
        description="飞书多维表格 token（bitable app_token，或 Wiki 节点 token 会自动解析）",
    )
    feishu_sheet_id: str = Field(
        default="",
        description="飞书多维表格 table_id（留空则自动获取第一个表）",
    )

    # ---------- 脉脉发帖 ----------
    maimai_post_interval: int = Field(
        default=180,
        description="脉脉发帖间隔（秒），默认3分钟",
    )

    @property
    def db_full_path(self) -> Path:
        """数据库完整路径（基于项目根目录）"""
        return PROJECT_ROOT / self.db_path

    class Config:
        # 从项目根目录的 .env 文件加载
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"


# 全局单例，其他模块直接 import 使用
settings = Settings()
