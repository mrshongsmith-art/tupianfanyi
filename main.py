import hashlib
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Node, Nodes, Plain, Reply
from astrbot.api.message_components import Image as AstrImage
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.quoted_message import extract_quoted_message_images
from astrbot.core.utils.session_waiter import (
    SessionController,
    SessionFilter,
    session_waiter,
)

from .utils import MangaTranslator


class TranslationSessionFilter(SessionFilter):
    def __init__(self, event: AstrMessageEvent, allowed_sender_ids: set[str]):
        self.origin_sender_id = event.get_sender_id()
        self.allowed_sender_ids = allowed_sender_ids

    def filter(self, event: AstrMessageEvent) -> str:
        group_or_session = event.get_group_id() or event.get_session_id()
        sender_id = event.get_sender_id()
        session_sender_id = (
            self.origin_sender_id if sender_id in self.allowed_sender_ids else sender_id
        )
        return (
            f"{event.get_platform_id()}:{event.get_message_type()}:"
            f"{group_or_session}:{session_sender_id}"
        )


@register("图片翻译", "樱小路真寻 ", "图片翻译插件", "1.0.0")
class ImageTranslatorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.translator = MangaTranslator(self.config)

        # Create cache directory
        self.cache_dir = Path(__file__).resolve().parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_images_from_components(self, components: list) -> list[AstrImage]:
        images = []
        for component in components:
            if isinstance(component, AstrImage):
                images.append(component)
            elif isinstance(component, Reply):
                if component.chain:
                    images.extend(self._get_images_from_components(component.chain))
            elif isinstance(component, Nodes):
                for node in component.nodes:
                    images.extend(self._get_images_from_components(node.content))
            elif isinstance(component, Node):
                images.extend(self._get_images_from_components(component.content))
        return images

    @staticmethod
    def _image_key(image: AstrImage) -> str:
        for attr in ("url", "file", "path"):
            value = getattr(image, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(id(image))

    @staticmethod
    def _normalize_command_text(text: str) -> str:
        return "".join(text.strip().lstrip("/#！!").split())

    def _is_translate_request(self, event: AstrMessageEvent) -> bool:
        plain_text = "".join(
            component.text
            for component in event.get_messages()
            if isinstance(component, Plain)
        )
        return self._normalize_command_text(plain_text) in {
            "图片翻译",
            "翻译图片",
        }

    def _get_allowed_sender_ids(self, event: AstrMessageEvent) -> set[str]:
        allowed = {event.get_sender_id()}
        self_id = str(event.get_self_id())

        for component in event.get_messages():
            if not isinstance(component, At):
                continue
            qq = str(component.qq).strip()
            if not qq or qq == "all" or qq == self_id:
                continue
            allowed.add(qq)

        return allowed

    async def _get_images_from_event(self, event: AstrMessageEvent) -> list[AstrImage]:
        images = self._get_images_from_components(event.get_messages())
        seen = {self._image_key(image) for image in images}

        try:
            quoted_image_refs = await extract_quoted_message_images(event)
        except Exception as e:
            logger.warning(f"Failed to extract quoted images: {e}")
            quoted_image_refs = []

        for image_ref in quoted_image_refs:
            if not isinstance(image_ref, str) or not image_ref.strip():
                continue
            image_ref = image_ref.strip()
            if image_ref in seen:
                continue
            images.append(AstrImage(file=image_ref))
            seen.add(image_ref)

        return images

    async def process_images(self, event: AstrMessageEvent, images: list):
        chain = []

        for img_component in images:
            try:
                file_path = Path(await img_component.convert_to_file_path())
                image_bytes = file_path.read_bytes()

                # Calculate MD5 for caching
                img_hash = hashlib.md5(image_bytes).hexdigest()

                # Check cache based on current priority
                priority = self.config.get("priority_api", "youdao")
                cache_file = self.cache_dir / f"{img_hash}_{priority}.jpg"

                result_bytes = None
                result_path = None
                api_name = ""
                failure_reason = "无可用API"

                if cache_file.exists():
                    result_bytes = cache_file.read_bytes()
                    if result_bytes:
                        result_path = cache_file
                        api_name = f"Cache-{priority}"
                else:
                    result_bytes, name = await self.translator.call_api(image_bytes)
                    if result_bytes:
                        # Determine suffix for saving
                        suffix = (
                            "youdao"
                            if name == "有道"
                            else "baidu"
                            if name == "百度"
                            else "unknown"
                        )
                        save_path = self.cache_dir / f"{img_hash}_{suffix}.jpg"

                        # Save to cache
                        save_path.write_bytes(result_bytes)
                        result_path = save_path
                        api_name = name
                    else:
                        failure_reason = name

                if result_path:
                    chain.append(Plain(f"翻译完成 ({api_name})\n"))
                    chain.append(AstrImage.fromFileSystem(str(result_path)))
                else:
                    chain.append(Plain(f"翻译失败: {failure_reason}\n"))
            except Exception as e:
                logger.error(f"Translation failed: {e}")
                chain.append(Plain(f"翻译出错: {e}\n"))

        if chain:
            yield event.chain_result(chain)

    async def _start_translation(self, event: AstrMessageEvent):
        allowed_sender_ids = self._get_allowed_sender_ids(event)
        images = await self._get_images_from_event(event)

        try:
            if images:
                async for res in self.process_images(event, images):
                    yield res
                return

            yield event.plain_result(
                "请发送要翻译的图片 (发送 '退出' 可取消，60 秒超时)"
            )

            @session_waiter(timeout=60, record_history_chains=False)
            async def wait_for_image(
                controller: SessionController,
                next_event: AstrMessageEvent,
            ):
                next_images = await self._get_images_from_event(next_event)
                msg_text = next_event.get_message_str().strip()

                if next_images:
                    async for res in self.process_images(next_event, next_images):
                        await next_event.send(res.derive(res.chain))
                    controller.stop()
                elif msg_text == "退出":
                    res = next_event.plain_result("已退出图片翻译模式")
                    await next_event.send(res.derive(res.chain))
                    controller.stop()
                else:
                    res = next_event.plain_result("请发送图片，或发送 '退出' 取消")
                    await next_event.send(res.derive(res.chain))
                    controller.keep(timeout=60, reset_timeout=True)

                next_event.stop_event()

            try:
                await wait_for_image(
                    event,
                    session_filter=TranslationSessionFilter(event, allowed_sender_ids),
                )
            except TimeoutError:
                yield event.plain_result("等待图片超时，已退出图片翻译模式")
        finally:
            event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def translate_image_keyword(self, event: AstrMessageEvent):
        """图片翻译 [图片]"""
        if not self._is_translate_request(event):
            return

        async for res in self._start_translation(event):
            yield res

    @filter.command("切换翻译api")
    async def switch_api(self, event: AstrMessageEvent, api_name: str = ""):
        """切换翻译api [api名称]"""
        if not api_name:
            api_names = ["youdao", "baidu"]
            current = self.config.get("priority_api", "youdao")
            yield event.plain_result(
                f"当前优先API: {current}\n可用API: {api_names}\n请使用 /切换翻译api [api名称] 进行切换"
            )
            return

        if api_name not in ["youdao", "baidu"]:
            yield event.plain_result("不支持的API名称。仅支持: youdao, baidu")
            return

        # Update config
        self.config["priority_api"] = api_name
        self.config.save_config()

        # Re-initialize translator to apply priority change
        self.translator = MangaTranslator(self.config)

        yield event.plain_result(f"已将 {api_name} 设为优先API并保存配置。")
