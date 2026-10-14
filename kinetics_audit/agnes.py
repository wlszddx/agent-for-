import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.agnes-ai.cn/v1"
DEFAULT_MODEL = "agnes-2.5-flash"


class AgnesError(RuntimeError):
    pass


class AgnesClient:
    def __init__(self, api_key, model=DEFAULT_MODEL, base_url=DEFAULT_BASE):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls):
        api_key = os.environ.get("AGNES_API_KEY", "").strip()
        if not api_key:
            raise AgnesError("缺少 AGNES_API_KEY")
        return cls(
            api_key,
            os.environ.get("AGNES_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            os.environ.get("AGNES_BASE_URL", DEFAULT_BASE).strip() or DEFAULT_BASE,
        )

    def complete(self, messages, tools):
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 8192,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AgnesError(f"Agnes HTTP {exc.code}: {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise AgnesError(f"Agnes 连接失败: {exc.reason}") from exc
        message = body["choices"][0]["message"]
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                arguments = {"_malformed": raw}
            if not isinstance(arguments, dict):
                arguments = {"_malformed": arguments}
            calls.append(
                {
                    "id": call.get("id") or f"call_{index}",
                    "name": function.get("name") or "",
                    "arguments": arguments,
                }
            )
        return {"content": message.get("content"), "tool_calls": calls}
