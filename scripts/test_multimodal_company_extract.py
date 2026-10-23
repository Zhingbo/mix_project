#!/usr/bin/env python3
"""
Test project LLM endpoints for company extraction from a URL or an image.

This script is intentionally standalone. It discovers API keys already present
in the project, then tests whether each configured model can:
1. read a URL directly from the prompt;
2. extract companies from page text fetched by Jina Reader or direct HTML;
3. optionally read an image via OpenAI-compatible image_url messages.

Example:
    python scripts/test_multimodal_company_extract.py \
        --url "https://zhuanlan.zhihu.com/p/658421225"

    python scripts/test_multimodal_company_extract.py \
        --image /path/to/screenshot.png --only-image
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://zhuanlan.zhihu.com/p/658421225"

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

KNOWN_CONFIG_FILES = [
    PROJECT_ROOT / "settings.yaml",
    PROJECT_ROOT / "config/settings_show.yaml",
    PROJECT_ROOT / "test_final.py",
    PROJECT_ROOT / "test_models_precise.py",
    PROJECT_ROOT / "test_new_models.py",
    PROJECT_ROOT / "steps/step2_generate_definition.py",
    PROJECT_ROOT / "steps/step3_match_industryry.py",
    PROJECT_ROOT / "steps/step6_top_company_match.py",
    PROJECT_ROOT / "services/enhanced_ai_client.py",
    PROJECT_ROOT / "Industry_chain/test_doubao.py",
    PROJECT_ROOT / "Industry_chain/chain_generate_auto.py",
    PROJECT_ROOT / "Industry_chain/company_nodesmatch_top3.py",
]


@dataclass
class ModelSpec:
    provider: str
    model: str
    api_key: str
    base_url: str
    supports_image: bool = False
    source: str = ""

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def mask_key(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def scan_assignment_key(var_names: Iterable[str]) -> Optional[str]:
    joined_names = "|".join(re.escape(name) for name in var_names)
    pattern = re.compile(rf"\b(?:{joined_names})\s*=\s*['\"]([^'\"]+)['\"]")
    for path in KNOWN_CONFIG_FILES:
        text = read_text(path)
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def scan_key_near_base_url(base_url_marker: str) -> Optional[str]:
    for path in KNOWN_CONFIG_FILES:
        text = read_text(path)
        if base_url_marker not in text:
            continue

        # Common OpenAI constructor style:
        # OpenAI(api_key="...", base_url="...")
        for match in re.finditer(
            r"api_key\s*=\s*['\"]([^'\"]+)['\"][\s\S]{0,260}?"
            r"base_url\s*=\s*['\"]([^'\"]+)['\"]",
            text,
        ):
            key, base_url = match.groups()
            if base_url_marker in base_url:
                return key

        # LangChain style:
        # openai_api_key=..., openai_api_base=...
        for match in re.finditer(
            r"openai_api_key\s*=\s*['\"]([^'\"]+)['\"][\s\S]{0,260}?"
            r"openai_api_base\s*=\s*['\"]([^'\"]+)['\"]",
            text,
        ):
            key, base_url = match.groups()
            if base_url_marker in base_url:
                return key

    return None


def settings_deepseek_keys() -> List[str]:
    keys: List[str] = []
    for path in [PROJECT_ROOT / "settings.yaml", PROJECT_ROOT / "config/settings_show.yaml"]:
        data = load_yaml(path)
        system_settings = data.get("system_settings") or {}
        for name in ["deepseek_api_key", "deepseek_api_key1", "deepseek_api_key2", "deepseek_api_key3"]:
            value = system_settings.get(name)
            if value:
                keys.append(str(value))
    return unique_preserve_order(keys)


def discover_models(include_official_all_keys: bool = False) -> List[ModelSpec]:
    specs: List[ModelSpec] = []

    dashscope_key = (
        os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("ALI_API_KEY")
        or scan_assignment_key(["ALI_API_KEY"])
        or scan_key_near_base_url("dashscope.aliyuncs.com")
    )
    if dashscope_key:
        for model in [
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "vanchin/deepseek-v3.1-terminus",
            "vanchin/deepseek-r1",
        ]:
            specs.append(
                ModelSpec(
                    provider="dashscope",
                    model=model,
                    api_key=dashscope_key,
                    base_url=DASHSCOPE_BASE_URL,
                    supports_image=False,
                    source="project DashScope-compatible DeepSeek config",
                )
            )

        # Present in test_new_models.py and is the closest project-local
        # multimodal candidate exposed through DashScope-compatible API.
        specs.append(
            ModelSpec(
                provider="dashscope",
                model="qwen-omni-4.0",
                api_key=dashscope_key,
                base_url=DASHSCOPE_BASE_URL,
                supports_image=True,
                source="project qwen-omni candidate",
            )
        )

    official_keys = []
    env_deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if env_deepseek_key:
        official_keys.append(env_deepseek_key)
    official_keys.extend(settings_deepseek_keys())
    official_keys = unique_preserve_order(official_keys)

    if official_keys:
        keys_to_use = official_keys if include_official_all_keys else official_keys[:1]
        for idx, key in enumerate(keys_to_use, start=1):
            provider = "deepseek-official" if len(keys_to_use) == 1 else f"deepseek-official-{idx}"
            for model in ["deepseek-chat", "deepseek-v4-pro"]:
                specs.append(
                    ModelSpec(
                        provider=provider,
                        model=model,
                        api_key=key,
                        base_url=DEEPSEEK_BASE_URL,
                        supports_image=False,
                        source="settings.yaml DeepSeek config",
                    )
                )

    ark_key = (
        os.getenv("ARK_API_KEY")
        or scan_key_near_base_url("ark.cn-beijing.volces.com")
    )
    if ark_key:
        for model in [
            "ep-20250205154622-7gm5g",
            "ep-20250217153205-d7px5",
            "ep-20250217153421-8lrxj",
        ]:
            specs.append(
                ModelSpec(
                    provider="ark",
                    model=model,
                    api_key=ark_key,
                    base_url=ARK_BASE_URL,
                    supports_image=False,
                    source="project Ark/Doubao endpoint config",
                )
            )

    # Deduplicate provider/model/base_url while preserving order.
    unique_specs = []
    seen = set()
    for spec in specs:
        key = (spec.provider, spec.model, spec.base_url, spec.api_key)
        if key not in seen:
            seen.add(key)
            unique_specs.append(spec)
    return unique_specs


def load_jina_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Accept": "text/plain",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    for path in [PROJECT_ROOT / "settings.yaml", PROJECT_ROOT / "config/settings_show.yaml"]:
        data = load_yaml(path)
        system_settings = data.get("system_settings") or {}
        configured_headers = system_settings.get("jina_api_headers") or {}
        if configured_headers:
            headers.update({str(k): str(v) for k, v in configured_headers.items()})
            break

        keys = system_settings.get("jina_api_keys") or []
        if isinstance(keys, list) and keys:
            first = keys[0]
            if isinstance(first, dict):
                value = first.get("key") or first.get("api_key")
            else:
                value = first
            if value:
                headers["Authorization"] = f"Bearer {value}"
                break
    return headers


def request_kwargs(proxy: Optional[str], timeout: int) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"timeout": timeout}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    return kwargs


def fetch_with_jina(url: str, proxy: Optional[str], timeout: int) -> Tuple[Optional[str], Dict[str, Any]]:
    reader_url = f"https://r.jina.ai/{url}"
    headers = load_jina_headers()
    meta = {
        "method": "jina_reader",
        "url": reader_url,
        "authorization": mask_key(headers.get("Authorization", "").replace("Bearer ", "")),
    }
    try:
        response = requests.get(reader_url, headers=headers, **request_kwargs(proxy, timeout))
        meta["status_code"] = response.status_code
        meta["content_length"] = len(response.text or "")
        if response.status_code == 200 and response.text.strip():
            content = "\n".join(line.strip() for line in response.text.splitlines() if line.strip())
            return content, meta
        meta["error"] = response.text[:300]
        return None, meta
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta


def fetch_direct_html(url: str, proxy: Optional[str], timeout: int) -> Tuple[Optional[str], Dict[str, Any]]:
    meta = {"method": "direct_html", "url": url}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, **request_kwargs(proxy, timeout))
        response.encoding = response.apparent_encoding or response.encoding
        meta["status_code"] = response.status_code
        meta["content_length"] = len(response.text or "")
        if response.status_code != 200:
            meta["error"] = response.text[:300]
            return None, meta

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        content = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return content, meta
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta


def fetch_url_content(url: str, proxy: Optional[str], timeout: int) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    attempts = []
    content, meta = fetch_with_jina(url, proxy, timeout)
    attempts.append(meta)
    if content:
        return content, attempts

    content, meta = fetch_direct_html(url, proxy, timeout)
    attempts.append(meta)
    return content, attempts


def truncate_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    head = content[: int(max_chars * 0.72)]
    tail = content[-int(max_chars * 0.18) :]
    return f"{head}\n\n...[中间内容已截断，原始长度 {len(content)} 字符]...\n\n{tail}"


def image_to_data_url(image: str) -> str:
    if re.match(r"^https?://", image):
        return image
    path = Path(image).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {path}")
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def fetch_image_to_temp(image: str, proxy: Optional[str], timeout: int) -> Tuple[Optional[str], Dict[str, Any]]:
    meta = {"method": "download_image", "image": image}
    if not re.match(r"^https?://", image):
        path = Path(image).expanduser().resolve()
        if path.exists():
            meta["local_path"] = str(path)
            return str(path), meta
        meta["error"] = f"图片文件不存在: {path}"
        return None, meta

    try:
        response = requests.get(
            image,
            headers={"User-Agent": "Mozilla/5.0"},
            **request_kwargs(proxy, timeout),
        )
        meta["status_code"] = response.status_code
        meta["content_length"] = len(response.content or b"")
        if response.status_code != 200:
            meta["error"] = response.text[:300]
            return None, meta

        content_type = response.headers.get("content-type", "")
        suffix = ".png"
        if "jpeg" in content_type or "jpg" in content_type:
            suffix = ".jpg"
        elif "webp" in content_type:
            suffix = ".webp"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
            tmp.write(response.content)
            meta["temp_path"] = tmp.name
            return tmp.name, meta
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta


def flatten_ocr_result(result: Any) -> List[str]:
    texts: List[str] = []

    def visit(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for key in ("text", "rec_text", "transcription"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
            for value in node.values():
                visit(value)
            return
        if isinstance(node, (list, tuple)):
            if (
                len(node) >= 2
                and isinstance(node[1], (list, tuple))
                and len(node[1]) >= 1
                and isinstance(node[1][0], str)
            ):
                texts.append(node[1][0].strip())
                return
            if len(node) >= 2 and isinstance(node[0], str) and isinstance(node[1], (int, float)):
                texts.append(node[0].strip())
                return
            for item in node:
                visit(item)

    visit(result)
    return [text for text in unique_preserve_order(texts) if text]


def ocr_image(image: str, proxy: Optional[str], timeout: int) -> Tuple[Optional[str], Dict[str, Any]]:
    meta: Dict[str, Any] = {"method": "paddleocr", "image": image}
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        meta["error"] = f"PaddleOCR 不可用: {exc}"
        return None, meta

    image_path, image_meta = fetch_image_to_temp(image, proxy, timeout)
    meta["image_fetch"] = image_meta
    if not image_path:
        meta["error"] = image_meta.get("error", "图片读取失败")
        return None, meta

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        result = ocr.ocr(image_path, cls=True)
        texts = flatten_ocr_result(result)
        meta["line_count"] = len(texts)
        meta["text_length"] = sum(len(text) for text in texts)
        if texts:
            return "\n".join(texts), meta
        meta["error"] = "OCR 未识别到文本"
        return None, meta
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta
    finally:
        temp_path = image_meta.get("temp_path")
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


EXTRACTION_SYSTEM_PROMPT = """你是企业信息抽取和工商全称标准化专家。
你的任务是从给定网页正文、链接或图片中识别企业名称，并尽量转换为完整工商注册名称。

必须遵守：
1. 只返回资料中出现或可由资料明确指向的企业/机构，不要编造。
2. 尽量返回完整公司全称，包含“有限公司”“股份有限公司”“集团有限公司”等后缀。
3. 如果只能识别简称，把 source_name 写简称，full_name 写你能确认的最完整名称，confidence 标为 low 或 medium。
4. 如果你不能读取链接或图片内容，can_read 必须为 false，companies 返回空数组。
5. 只返回 JSON，不要使用 Markdown 代码块。

JSON 格式：
{
  "can_read": true,
  "companies": [
    {
      "source_name": "资料中的名称",
      "full_name": "补全后的企业全称",
      "confidence": "high|medium|low",
      "evidence": "来自资料的一小段依据"
    }
  ],
  "notes": "简短说明"
}
"""


def direct_url_prompt(url: str) -> str:
    return f"""请测试你是否能够直接读取下面这个网页链接的真实正文，并从正文中抽取企业名称、补成企业全称。

链接：{url}

如果你无法访问该网页的真实正文，请严格返回 can_read=false，不要根据链接标题或常识猜测。"""


def content_prompt(url: str, content: str) -> str:
    return f"""以下是脚本从网页链接抓取到的正文内容。请从正文中抽取企业名称，并尽量转换为完整工商注册名称。

来源链接：{url}

正文：
{content}
"""


def image_prompt(image_label: str) -> str:
    return f"""请读取这张图片中的文字或表格，抽取其中出现的企业名称，并尽量转换为完整工商注册名称。

图片来源：{image_label}

如果图片中没有企业名称，或你无法读取图片，请返回 can_read=false。"""


def ocr_prompt(image_label: str, ocr_text: str) -> str:
    return f"""以下是脚本使用 PaddleOCR 从图片中识别出的文字。请根据这些 OCR 文本抽取企业名称，并尽量转换为完整工商注册名称。

图片来源：{image_label}

OCR 文本：
{ocr_text}
"""


def call_model_json(
    spec: ModelSpec,
    messages: List[Dict[str, Any]],
    timeout: int,
    temperature: float = 0.1,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    started_at = time.time()
    meta = {
        "provider": spec.provider,
        "model": spec.model,
        "base_url": spec.base_url,
        "api_key": mask_key(spec.api_key),
    }
    try:
        client = OpenAI(api_key=spec.api_key, base_url=spec.base_url, timeout=timeout)
        try:
            response = client.chat.completions.create(
                model=spec.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception as json_exc:
            meta["json_mode_error"] = str(json_exc)[:300]
            response = client.chat.completions.create(
                model=spec.model,
                messages=messages,
                temperature=temperature,
            )

        text = (response.choices[0].message.content or "").strip()
        meta["elapsed_seconds"] = round(time.time() - started_at, 2)
        meta["raw"] = text
        try:
            cleaned = text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned), meta
        except json.JSONDecodeError as exc:
            meta["parse_error"] = str(exc)
            return None, meta
    except Exception as exc:
        meta["elapsed_seconds"] = round(time.time() - started_at, 2)
        meta["error"] = str(exc)
        return None, meta


def normalize_result(result: Optional[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    if not result:
        return {
            "can_read": False,
            "companies": [],
            "notes": "模型调用失败或返回非 JSON",
            "meta": meta,
        }

    companies = result.get("companies")
    if not isinstance(companies, list):
        companies = []

    normalized_companies = []
    for company in companies:
        if not isinstance(company, dict):
            continue
        source_name = str(company.get("source_name") or company.get("name") or "").strip()
        full_name = str(company.get("full_name") or company.get("企业全称") or source_name).strip()
        if not source_name and not full_name:
            continue
        normalized_companies.append(
            {
                "source_name": source_name or full_name,
                "full_name": full_name or source_name,
                "confidence": str(company.get("confidence") or "medium"),
                "evidence": str(company.get("evidence") or "")[:240],
            }
        )

    return {
        "can_read": bool(result.get("can_read", bool(normalized_companies))),
        "companies": normalized_companies,
        "notes": str(result.get("notes") or ""),
        "meta": meta,
    }


def run_text_test(spec: ModelSpec, mode: str, prompt: str, timeout: int) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    parsed, meta = call_model_json(spec, messages, timeout)
    result = normalize_result(parsed, meta)
    result["mode"] = mode
    result["model_label"] = spec.label
    return result


def run_image_test(spec: ModelSpec, image: str, timeout: int) -> Dict[str, Any]:
    try:
        image_url = image_to_data_url(image)
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": image_prompt(image)},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        parsed, meta = call_model_json(spec, messages, timeout)
        result = normalize_result(parsed, meta)
    except Exception as exc:
        result = {
            "can_read": False,
            "companies": [],
            "notes": f"图片准备失败: {exc}",
            "meta": {"error": str(exc)},
        }
    result["mode"] = "image"
    result["model_label"] = spec.label
    return result


def filter_models(specs: List[ModelSpec], requested: Optional[str]) -> List[ModelSpec]:
    if not requested:
        return specs
    tokens = [item.strip().lower() for item in requested.split(",") if item.strip()]
    if not tokens:
        return specs
    filtered = []
    for spec in specs:
        label = spec.label.lower()
        if any(token in label or token == spec.provider.lower() or token == spec.model.lower() for token in tokens):
            filtered.append(spec)
    return filtered


def summarize(results: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 96)
    print("测试摘要")
    print("=" * 96)
    print(f"{'模式':<14} {'模型':<42} {'可读':<6} {'企业数':<8} {'备注'}")
    print("-" * 96)
    for item in results:
        companies = item.get("companies") or []
        notes = (item.get("notes") or item.get("meta", {}).get("error") or "")[:28]
        print(
            f"{item.get('mode', ''):<14} "
            f"{item.get('model_label', ''):<42} "
            f"{str(item.get('can_read', False)):<6} "
            f"{len(companies):<8} "
            f"{notes}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test project models for company extraction from URL/image.")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL to test.")
    parser.add_argument("--image", help="Local image path or image URL to test.")
    parser.add_argument("--output", help="Output JSON path. Defaults to timestamped file in project root.")
    parser.add_argument("--models", help="Comma-separated provider/model filters, e.g. dashscope,deepseek-v4-pro,qwen-omni.")
    parser.add_argument("--proxy", help="Optional HTTP/SOCKS proxy, e.g. socks5://127.0.0.1:7891.")
    parser.add_argument("--timeout", type=int, default=90, help="HTTP/API timeout seconds.")
    parser.add_argument("--max-content-chars", type=int, default=24000, help="Max webpage text chars sent to each model.")
    parser.add_argument("--skip-direct-url", action="store_true", help="Skip direct URL reading prompt.")
    parser.add_argument("--skip-fetched-content", action="store_true", help="Skip Jina/direct fetched content prompt.")
    parser.add_argument("--only-image", action="store_true", help="Only run image tests. Requires --image.")
    parser.add_argument("--test-image-all", action="store_true", help="Try image payload on all models, not just image candidates.")
    parser.add_argument("--skip-image-ocr", action="store_true", help="Skip PaddleOCR image-to-text tests.")
    parser.add_argument("--all-official-keys", action="store_true", help="Use all DeepSeek keys found in settings.yaml.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.only_image and not args.image:
        print("--only-image 需要同时提供 --image", file=sys.stderr)
        return 2

    specs = filter_models(discover_models(args.all_official_keys), args.models)
    if not specs:
        print("没有发现可测试的模型配置。请检查 settings.yaml 或设置环境变量。", file=sys.stderr)
        return 1

    print("发现模型配置：")
    for spec in specs:
        image_flag = "image" if spec.supports_image else "text"
        print(f"  - {spec.label} [{image_flag}] key={mask_key(spec.api_key)} source={spec.source}")

    fetched_content = None
    fetch_attempts: List[Dict[str, Any]] = []
    if not args.only_image and not args.skip_fetched_content:
        print(f"\n抓取网页正文: {args.url}")
        fetched_content, fetch_attempts = fetch_url_content(args.url, args.proxy, args.timeout)
        if fetched_content:
            print(f"  抓取成功，正文长度: {len(fetched_content)}")
            fetched_content = truncate_content(fetched_content, args.max_content_chars)
            print(f"  发送给模型的正文长度: {len(fetched_content)}")
        else:
            print("  抓取失败，将只运行可用的直接 URL/图片测试。")

    results: List[Dict[str, Any]] = []

    for spec in specs:
        if not args.only_image and not args.skip_direct_url:
            print(f"\n[direct_url] {spec.label}")
            results.append(run_text_test(spec, "direct_url", direct_url_prompt(args.url), args.timeout))

        if not args.only_image and not args.skip_fetched_content and fetched_content:
            print(f"\n[fetched_content] {spec.label}")
            results.append(
                run_text_test(spec, "fetched_content", content_prompt(args.url, fetched_content), args.timeout)
            )

    image_ocr_text = None
    image_ocr_meta: Optional[Dict[str, Any]] = None
    if args.image and not args.skip_image_ocr:
        print(f"\n[image_ocr] PaddleOCR: {args.image}")
        image_ocr_text, image_ocr_meta = ocr_image(args.image, args.proxy, args.timeout)
        if image_ocr_text:
            print(f"  OCR 成功，文本长度: {len(image_ocr_text)}")
            for spec in specs:
                print(f"\n[image_ocr_text] {spec.label}")
                results.append(
                    run_text_test(spec, "image_ocr_text", ocr_prompt(args.image, image_ocr_text), args.timeout)
                )
        else:
            print(f"  OCR 失败: {(image_ocr_meta or {}).get('error', 'unknown')}")

    if args.image:
        image_specs = specs if args.test_image_all else [spec for spec in specs if spec.supports_image]
        if not image_specs:
            print("\n没有发现标记为支持图片的模型；如需强制测试，请加 --test-image-all。")
        for spec in image_specs:
            print(f"\n[image] {spec.label}")
            results.append(run_image_test(spec, args.image, args.timeout))

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "url": args.url,
        "image": args.image,
        "models": [
            {
                **asdict(spec),
                "api_key": mask_key(spec.api_key),
            }
            for spec in specs
        ],
        "fetch_attempts": fetch_attempts,
        "image_ocr": {
            "text": image_ocr_text,
            "meta": image_ocr_meta,
        },
        "results": results,
    }

    output_path = Path(args.output) if args.output else PROJECT_ROOT / (
        "model_company_extract_results_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    )
    output_path = output_path.expanduser().resolve()
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summarize(results)
    print(f"\n完整结果已写入: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
