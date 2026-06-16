"""
飞书多维表格读取模块 —— 从飞书表格中读取待发帖内容

功能：
  1. 连接飞书 API（使用 app_id/app_secret）
  2. 自动解析 Wiki URL → bitable app_token（支持直接 bitable 和 wiki 嵌入两种方式）
  3. 读取多维表格中状态为"待发布"的行
  4. 下载行中附带的图片
  5. 更新行状态为"已发布"或"失败"

飞书表格结构（建议）：
  | 帖子内容 | 图片 | 状态 | 发布时间 | 备注 |
  状态值：待发布 / 已发布 / 失败

⚠️  前置条件：
  - 飞书开放平台创建应用：https://open.feishu.cn/app
  - 获取 app_id 和 app_secret
  - 应用权限：bitable:app, wiki:wiki:readonly（如通过 Wiki 访问）, drive:drive:readonly
  - 多维表格分享给应用（或应用添加为表格协作者）
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional, List
from pathlib import Path

from loguru import logger

from config import settings, PROJECT_ROOT


# 图片下载目录
IMAGE_DIR = PROJECT_ROOT / "downloads" / "feishu"

# 飞书 API 基础 URL
FEISHU_API = "https://open.feishu.cn/open-apis"


class FeishuReader:
    """
    飞书多维表格读取器（直接 HTTP API，不依赖 lark-oapi SDK 版本）

    用法：
        reader = FeishuReader()
        reader.connect()
        posts = reader.read_pending_posts()
        for post in posts:
            image_paths = reader.download_images(post["image_tokens"], post["row_id"])
            # 处理发帖...
            reader.mark_as_published(post["row_id"])
    """

    def __init__(self):
        self._token = ""           # tenant_access_token
        self._app_token = ""       # bitable app_token（自动解析）
        self._table_id = ""        # bitable table_id

    def connect(self) -> bool:
        """连接飞书 API：获取 tenant_access_token + 自动解析 Wiki URL"""
        logger.info("连接飞书 API...")

        if not settings.feishu_app_id or not settings.feishu_app_secret:
            logger.error("❌ 未配置飞书 app_id/app_secret，请在 .env 中设置")
            return False

        # 1. 获取 tenant_access_token
        try:
            self._token = self._get_tenant_token()
            logger.success("✓ 飞书 API 认证成功")
        except Exception as e:
            logger.error(f"❌ 飞书认证失败: {e}")
            return False

        # 2. 确定 bitable app_token
        self._app_token = settings.feishu_spreadsheet_token
        self._table_id = settings.feishu_sheet_id

        # 如果 app_token 看起来像 wiki token（非 bitable token），自动解析
        if self._app_token and not self._table_id:
            # 尝试直接当作 bitable token 使用
            if self._try_list_tables(self._app_token):
                logger.success(f"✓ bitable token 有效: {self._app_token}")
            else:
                logger.warning("  app_token 不是直接的 bitable token，尝试解析为 Wiki 节点...")
                resolved = self._resolve_wiki_token(self._app_token)
                if resolved:
                    self._app_token, self._table_id = resolved
                    logger.success(f"✓ Wiki 节点解析成功: app_token={self._app_token}")
                else:
                    logger.error("❌ 无法解析为 bitable 或 Wiki 节点")
                    return False

        # 3. 如果没有 table_id，自动获取第一个表
        if self._app_token and not self._table_id:
            self._table_id = self._get_first_table_id(self._app_token)
            if self._table_id:
                logger.success(f"✓ 自动获取 table_id: {self._table_id}")
            else:
                logger.error("❌ 未找到数据表")
                return False

        logger.success(f"✓ 飞书表格就绪: app_token={self._app_token}, table_id={self._table_id}")
        return True

    def read_pending_posts(self) -> List[dict]:
        """
        读取状态为"待发布"的行

        返回:
            [{"row_id": str, "content": str, "image_tokens": list, "fields": dict}, ...]
        """
        logger.info("读取飞书表格中待发布的帖子...")

        if not self._app_token or not self._table_id:
            logger.error("❌ 未配置飞书表格，请先 connect()")
            return []

        try:
            all_records = self._list_all_records()
            posts = []

            for item in all_records:
                fields = item.get("fields", {})
                record_id = item.get("record_id", "")

                # 检查状态列
                status = self._extract_text(fields.get("状态", ""))
                # 空状态也视为待发布（未设置状态的新行）
                if status and status not in ["待发布", "pending", ""]:
                    if status in ["已发布", "published", "失败", "failed", "跳过", "skipped"]:
                        continue

                # 提取内容
                content = self._extract_text(fields.get("帖子内容", ""))
                if not content:
                    # 空内容行跳过
                    continue

                # 提取图片 token
                image_tokens = self._extract_image_tokens(fields.get("图片", []))

                posts.append({
                    "row_id": record_id,
                    "content": content,
                    "image_tokens": image_tokens,
                    "fields": fields,
                })

            logger.success(f"✓ 读取到 {len(posts)} 篇待发布帖子（共 {len(all_records)} 行）")
            return posts

        except Exception as e:
            logger.error(f"❌ 读取表格异常: {e}")
            return []

    def download_images(self, image_tokens: List[str], post_id: str = "") -> List[str]:
        """
        下载飞书图片到本地

        参数:
            image_tokens: 图片 file_token 列表
            post_id:      帖子ID（用于创建子目录）

        返回:
            本地文件路径列表
        """
        if not image_tokens:
            return []

        logger.info(f"下载飞书图片: {len(image_tokens)} 张")

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        post_dir = IMAGE_DIR / post_id if post_id else IMAGE_DIR
        post_dir.mkdir(exist_ok=True)

        local_paths = []
        for i, token in enumerate(image_tokens, 1):
            filename = f"{i}.jpg"
            filepath = post_dir / filename

            if filepath.exists():
                local_paths.append(str(filepath))
                logger.debug(f"  图片 {i} 已存在，跳过下载")
                continue

            try:
                url = f"{FEISHU_API}/drive/v1/medias/{token}/download"
                req = urllib.request.Request(url, headers={
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": "media-assistant/1.0",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    if len(data) < 1000:
                        logger.warning(f"  图片 {i} 数据太小({len(data)}字节)，跳过")
                        continue
                    # 根据实际内容判断扩展名
                    ext = self._detect_image_ext(data)
                    if ext != "jpg":
                        filepath = post_dir / f"{i}.{ext}"
                    with open(filepath, "wb") as f:
                        f.write(data)
                local_paths.append(str(filepath))
                logger.debug(f"  ✓ 图片 {i} 已下载")
            except urllib.error.HTTPError as e:
                body = e.read().decode() if e.fp else ""
                logger.warning(f"  图片 {i} 下载失败(HTTP {e.code}): {body[:100]}")
            except Exception as e:
                logger.warning(f"  图片 {i} 下载失败: {e}")

        logger.info(f"图片下载完成: {len(local_paths)}/{len(image_tokens)} 张")
        return local_paths

    def mark_as_published(self, row_id: str, note: str = ""):
        """标记为已发布"""
        self._update_row_status(row_id, "已发布", note)

    def mark_as_failed(self, row_id: str, error: str = ""):
        """标记为失败"""
        self._update_row_status(row_id, "失败", error)

    # ==================== 内部方法 ====================

    def _api_request(self, method: str, path: str, body: dict = None) -> dict:
        """发送飞书 API 请求"""
        url = f"{FEISHU_API}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                if result.get("code", -1) != 0:
                    raise RuntimeError(f"API 错误: {result.get('code')} - {result.get('msg')}")
                return result
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            raise RuntimeError(f"HTTP {e.code}: {body_text[:200]}")

    def _get_tenant_token(self) -> str:
        """获取 tenant_access_token"""
        url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
        body = json.dumps({
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") != 0:
                raise RuntimeError(f"认证失败: {data.get('code')} - {data.get('msg')}")
            return data["tenant_access_token"]

    def _try_list_tables(self, app_token: str) -> bool:
        """尝试列出 bitable 的表，验证 app_token 是否有效"""
        try:
            url = f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("code") == 0
        except Exception:
            return False

    def _resolve_wiki_token(self, wiki_token: str) -> Optional[tuple]:
        """
        解析 Wiki 节点 token → 返回 (bitable_app_token, table_id)
        如果 Wiki 节点包含 bitable，返回其 obj_token 和第一个 table_id
        """
        try:
            url = f"{FEISHU_API}/wiki/v2/spaces/get_node?token={wiki_token}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") != 0:
                    logger.warning(f"  Wiki 解析失败: {data.get('msg')}")
                    return None

                node = data["data"]["node"]
                obj_type = node.get("obj_type", "")
                obj_token = node.get("obj_token", "")

                if obj_type != "bitable":
                    logger.warning(f"  Wiki 节点类型不是 bitable，而是: {obj_type}")
                    return None

                # 获取第一个 table_id
                table_id = self._get_first_table_id(obj_token)
                if not table_id:
                    logger.warning("  bitable 中没有数据表")
                    return None

                return (obj_token, table_id)

        except Exception as e:
            logger.warning(f"  Wiki 解析异常: {e}")
            return None

    def _get_first_table_id(self, app_token: str) -> Optional[str]:
        """获取 bitable 中的第一个 table_id"""
        try:
            url = f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") != 0 or not data.get("data", {}).get("items"):
                    return None
                return data["data"]["items"][0]["table_id"]
        except Exception:
            return None

    def _list_all_records(self) -> List[dict]:
        """分页获取所有记录"""
        all_items = []
        page_token = None

        while True:
            path = f"/bitable/v1/apps/{self._app_token}/tables/{self._table_id}/records?page_size=100"
            if page_token:
                path += f"&page_token={page_token}"

            result = self._api_request("GET", path)
            items = result.get("data", {}).get("items", [])
            all_items.extend(items)

            page_token = result.get("data", {}).get("page_token")
            if not page_token or not result.get("data", {}).get("has_more"):
                break

        return all_items

    def _update_row_status(self, row_id: str, status: str, note: str = ""):
        """更新行状态"""
        try:
            from datetime import datetime

            fields = {
                "状态": status,
                "发布时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            if note:
                fields["备注"] = note

            path = f"/bitable/v1/apps/{self._app_token}/tables/{self._table_id}/records/{row_id}"
            self._api_request("PUT", path, {"fields": fields})
            logger.info(f"  ✓ 行状态已更新: {status}")

        except Exception as e:
            logger.warning(f"  ⚠️ 更新行状态异常: {e}")

    # ==================== 辅助方法 ====================

    @staticmethod
    def _extract_text(field_value) -> str:
        """从飞书字段值中提取纯文本

        飞书多维表格文本字段格式：
          [[{"text": "xxx", "type": "text"}, ...]]
        """
        if isinstance(field_value, str):
            return field_value.strip()
        if isinstance(field_value, list):
            texts = []
            for item in field_value:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    # 单个 text 节点
                    texts.append(item.get("text", item.get("link", "")))
                elif isinstance(item, list):
                    # 嵌套列表 [[{"text": "xxx"}]]
                    for sub in item:
                        if isinstance(sub, dict):
                            texts.append(sub.get("text", sub.get("link", "")))
                        elif isinstance(sub, str):
                            texts.append(sub)
            return "".join(texts).strip()
        return str(field_value).strip() if field_value else ""

    @staticmethod
    def _extract_image_tokens(field_value) -> List[str]:
        """从飞书字段值中提取图片 file_token

        飞书附件字段格式：
          [{"file_token": "xxx", "name": "xxx.jpg", "size": 12345, "tmp_url": "xxx"}, ...]
        """
        tokens = []
        if isinstance(field_value, list):
            for item in field_value:
                if isinstance(item, dict):
                    token = item.get("file_token", "")
                    if token:
                        tokens.append(token)
                elif isinstance(item, str) and item.startswith("http"):
                    tokens.append(item)
        elif isinstance(field_value, str) and field_value.startswith("http"):
            tokens.append(field_value)
        return tokens

    @staticmethod
    def _detect_image_ext(data: bytes) -> str:
        """根据文件头检测图片格式"""
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "png"
        elif data[:2] == b'\xff\xd8':
            return "jpg"
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "webp"
        elif data[:4] == b'GIF8':
            return "gif"
        return "jpg"
