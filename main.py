import datetime
import httpx
import astrbot.api.star as star
from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent, filter

# 已核对文档章节：[插件开发, 铁律 4 (系统可见性)]
@star.register("astrbot_plugin_web_search", "YEZI", "网页搜索", "v1.4.3", "https://github.com/zhyx111999/astrbot_plugin_web_search")
class Main(star.Star):
    def __init__(self, context: star.Context, config=None) -> None:
        super().__init__(context)
        self.config = config or {}
        self._rr_index = 0

    @filter.command("search")
    async def search_cmd(self, event: AstrMessageEvent, query: str):
        """手动网页搜索指令"""
        if not query:
            yield event.plain_result("请输入搜索内容。")
            return
        
        yield event.plain_result(f"🔍 正在执行网页搜索: {query}...")
        result = await self.gemini_search(event, query)
        yield event.plain_result(result)
        event.stop_event()

    @llm_tool("gemini_search")
    async def gemini_search(self, event: AstrMessageEvent, query: str) -> str:
        '''网页搜索工具。支持 2025 最新数据校对。

        Args:
            query(string): 用户希望检索的具体问题
        '''
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        
        time_prompt = (
            f"当前系统日期是 {current_date}。\\n"
            "请执行网页搜索，优先采纳 2025 年的最新动态，并剔除过时信息。"
        )

        # 铁律防御：读取配置并处理代理
        try:
            api_type = self.config.get("api_type", "google")
            proxy = self.context.get_config().get("proxy", "")
        except Exception:
            api_type = "google"
            proxy = ""

        try:
            if api_type == "openai":
                return await self._openai_style_search(query, time_prompt, proxy)
            else:
                return await self._google_sdk_search(query, time_prompt, proxy)
        except Exception as e:
            logger.error(f"[WebSearch] Error: {e}")
            return f"网页搜索暂时不可 available: {str(e)}"

    async def _openai_style_search(self, query: str, time_prompt: str, proxy: str) -> str:
        base = self.config.get("api_base_url", "https://generativelanguage.googleapis.com").rstrip("/")
        url = f"{base}/v1/chat/completions" if "/v1" not in base else f"{base}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self._get_key()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.config.get("model", "gemini-2.0-flash"),
            "messages": [
                {"role": "system", "content": time_prompt},
                {"role": "user", "content": f"请执行网页搜索并回答：{query}"}
            ]
        }

        # ✅ 铁律 1：处理 proxy 为空字符串转 None
        async with httpx.AsyncClient(proxy=proxy if proxy else None, timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data['choices'][0]['message']['content']

    async def _google_sdk_search(self, query: str, time_prompt: str, proxy: str) -> str:
        from google import genai
        from google.genai import types
        # SDK 模式下透传 API Base
        client = genai.Client(api_key=self._get_key(), http_options=types.HttpOptions(base_url=self.config.get("api_base_url"))).aio
        
        resp = await client.models.generate_content(
            model=self.config.get("model", "gemini-2.0-flash"),
            contents=f"{time_prompt}\\n\\n问题: {query}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        )
        return resp.text

    def _get_key(self):
        keys = self.config.get("api_key", [])
        if not keys: raise ValueError("未配置 API Key")
        key = keys[self._rr_index % len(keys)]
        self._rr_index += 1
        return key

    async def initialize(self):
        self.context.activate_llm_tool("gemini_search")