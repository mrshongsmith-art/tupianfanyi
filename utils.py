import base64
import hashlib
import random
import time
import uuid
from io import BytesIO

import httpx
from PIL import Image

from astrbot.api import logger


class MangaTranslator:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.img_url = []
        self.api = []

        priority = self.config.get("priority_api", "youdao")

        # Add APIs based on priority
        if priority == "youdao":
            self._add_youdao()
            self._add_baidu()
        else:
            self._add_baidu()
            self._add_youdao()

        if not self.api:
            logger.warning("未检测到任何可用的翻译API配置 (有道/百度)")

    def _add_youdao(self):
        if self.config.get("youdao_app_key") and self.config.get("youdao_app_secret"):
            self.api.append(self.youdao)
            logger.info("检测到有道API")
        elif self.config.get("youdao_app_key") or self.config.get("youdao_app_secret"):
            logger.warning("有道API配置不完整，已跳过")

    def _add_baidu(self):
        if self.config.get("baidu_app_id") and self.config.get("baidu_app_key"):
            self.api.append(self.baidu)
            logger.info("检测到百度API")
        elif self.config.get("baidu_app_id") or self.config.get("baidu_app_key"):
            logger.warning("百度API配置不完整，已跳过")

    async def call_api(self, image_bytes: bytes) -> tuple[None | bytes, str]:
        for api in self.api:
            try:
                result = await api(image_bytes)
                return result
            except httpx.HTTPError as e:
                logger.warning(f"API[{api.__name__}]不可用：{e} 尝试切换下一个")
            except Exception as e:
                logger.error(f"API[{api.__name__}]出现未知错误：{e} 尝试切换下一个")
        return None, "无可用API"

    async def youdao(self, image_bytes) -> tuple[bytes, str]:
        """有道翻译"""
        # Compress if too large (Youdao limit 10MB usually, but safe to keep logic)
        if len(image_bytes) >= 2 * 1024 * 1024:
            image_bytes = self.compress_image(image_bytes)

        q = base64.b64encode(image_bytes).decode("utf-8")
        app_key = self.config.get("youdao_app_key", "")
        app_secret = self.config.get("youdao_app_secret", "")

        salt = str(uuid.uuid1())
        curtime = str(int(time.time()))

        def truncate(q):
            if q is None:
                return None
            size = len(q)
            return q if size <= 20 else q[0:10] + str(size) + q[size - 10 : size]

        signStr = app_key + truncate(q) + salt + curtime + app_secret
        sign = hashlib.sha256(signStr.encode("utf-8")).hexdigest()

        data = {
            "from": "auto",
            "to": "zh-CHS",
            "type": "1",
            "appKey": app_key,
            "salt": salt,
            "curtime": curtime,
            "sign": sign,
            "signType": "v3",
            "q": q,
            "render": 1,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient(timeout=30) as client:
            youdao_res = await client.post(
                url="https://openapi.youdao.com/ocrtransapi", data=data, headers=headers
            )
            youdao_res.raise_for_status()
            try:
                payload = youdao_res.json()
            except ValueError as e:
                raise ValueError("有道API返回了非JSON响应") from e
            if "render_image" not in payload:
                logger.error(payload)
                raise ValueError("有道API返回错误: " + str(payload))
            img_base64 = payload["render_image"]
            pic = base64.b64decode(img_base64)
        return pic, "有道"

    async def baidu(self, image_bytes: bytes) -> tuple[bytes, str]:
        """百度翻译"""
        app_id = str(self.config.get("baidu_app_id", ""))
        app_key = self.config.get("baidu_app_key", "")

        async with httpx.AsyncClient(timeout=30) as client:
            salt = random.randint(32768, 65536)
            image_data = image_bytes
            image_size = len(image_data)
            if image_size >= 4 * 1024 * 1024:
                logger.info("图片过大，进行压缩")
                image_data = self.compress_image(image_data)

            # Baidu uses MD5
            sign = hashlib.md5(
                (
                    app_id
                    + hashlib.md5(image_data).hexdigest()
                    + str(salt)
                    + "APICUID"
                    + "mac"
                    + app_key
                ).encode("utf-8")
            ).hexdigest()
            payload = {
                "from": "auto",
                "to": "zh",
                "appid": app_id,
                "salt": salt,
                "sign": sign,
                "cuid": "APICUID",
                "mac": "mac",
                "paste": 1,
                "version": 3,
            }
            image = {"image": ("image.jpg", image_data, "image/jpeg")}
            baidu_res = await client.post(
                url="http://api.fanyi.baidu.com/api/trans/sdk/picture",
                params=payload,
                files=image,
            )
            baidu_res.raise_for_status()
            try:
                payload = baidu_res.json()
            except ValueError as e:
                raise ValueError("百度API返回了非JSON响应") from e
            if "data" not in payload or "pasteImg" not in payload["data"]:
                logger.error(payload)
                raise ValueError("百度API返回错误: " + str(payload))
            img_base64 = payload["data"]["pasteImg"]
            pic = base64.b64decode(img_base64)
        return pic, "百度"

    @staticmethod
    def compress_image(image_data: bytes) -> bytes:
        with BytesIO(image_data) as input_buffer:
            with Image.open(input_buffer) as image:
                if image.mode == "RGBA":
                    image = image.convert("RGB")
                image = image.resize((int(image.width * 0.5), int(image.height * 0.5)))
                output_buffer = BytesIO()
                image.save(output_buffer, format="JPEG", optimize=True, quality=80)
                return output_buffer.getvalue()
