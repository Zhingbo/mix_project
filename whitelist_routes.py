"""
白名单管理路由
提供白名单上传、下载、查询等功能
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Query, Form
from fastapi.responses import FileResponse
from typing import Any, Dict, List, Optional, Tuple
import base64
import json
import mimetypes
import os
import re
import tempfile
from auth_routes import get_current_user
from utils.logger import get_logger
import shutil

logger = get_logger(__name__)

router = APIRouter(prefix="/api/whitelist", tags=["whitelist"])

# 模板文件路径
TEMPLATE_FILE = "/root/mix_project/database/企业名录模版.xlsx"

# 临时上传目录
UPLOAD_DIR = "/root/mix_project/temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

VALID_POSITIONS = ['上游', '中游', '下游']
AUTO_POSITION = "自动识别"
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
MAX_IMAGE_SIZE = 15 * 1024 * 1024
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
IMAGE_MODEL_API_KEY = os.getenv("WHITELIST_IMAGE_API_KEY") or DASHSCOPE_API_KEY
IMAGE_MODEL_BASE_URL = os.getenv("WHITELIST_IMAGE_BASE_URL") or DASHSCOPE_BASE_URL
IMAGE_MODEL_NAME = os.getenv("WHITELIST_IMAGE_MODEL", "qwen-omni-4.0")
MAX_IMAGE_COMPANIES = int(os.getenv("WHITELIST_IMAGE_MAX_COMPANIES", "80"))
WHITELIST_IMAGE_MODEL_TOKENS = int(os.getenv("WHITELIST_IMAGE_MAX_TOKENS", "1400"))
WHITELIST_IMAGE_MODEL_TIMEOUT = float(os.getenv("WHITELIST_IMAGE_TIMEOUT", "55"))
LONG_IMAGE_MIN_HEIGHT = int(os.getenv("WHITELIST_LONG_IMAGE_MIN_HEIGHT", "1600"))
LONG_IMAGE_MIN_ASPECT_RATIO = float(os.getenv("WHITELIST_LONG_IMAGE_MIN_ASPECT_RATIO", "2.2"))
LONG_IMAGE_CHUNK_HEIGHT = int(os.getenv("WHITELIST_LONG_IMAGE_CHUNK_HEIGHT", "1200"))
LONG_IMAGE_CHUNK_OVERLAP = int(os.getenv("WHITELIST_LONG_IMAGE_CHUNK_OVERLAP", "140"))
LONG_IMAGE_MAX_CHUNKS = int(os.getenv("WHITELIST_LONG_IMAGE_MAX_CHUNKS", "8"))
LONG_IMAGE_CHUNK_WORKERS = int(os.getenv("WHITELIST_LONG_IMAGE_CHUNK_WORKERS", "3"))
LONG_IMAGE_COMPANIES_PER_CHUNK = int(os.getenv("WHITELIST_LONG_IMAGE_COMPANIES_PER_CHUNK", "45"))
LONG_IMAGE_CHUNK_TOKENS = int(os.getenv("WHITELIST_LONG_IMAGE_MAX_TOKENS", "1800"))


def _short_error(exc: Exception, limit: int = 260) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _is_supported_image(filename: Optional[str], content_type: Optional[str]) -> bool:
    suffix = os.path.splitext(filename or "")[1].lower()
    if suffix in IMAGE_SUFFIXES:
        return True
    return bool(content_type and content_type.startswith("image/") and content_type != "image/svg+xml")


def _strip_json_fences(content: str) -> str:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _recover_truncated_companies(content: str) -> Dict[str, Any]:
    marker = re.search(r'"companies"\s*:\s*\[', content, re.S)
    if not marker:
        raise ValueError("未找到 companies 数组")

    array_text = content[marker.end():]
    companies = []
    start = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(array_text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                raw_item = array_text[start:index + 1]
                try:
                    item = json.loads(raw_item)
                    if isinstance(item, dict):
                        companies.append(item)
                except Exception:
                    pass
                start = None

    if not companies:
        raise ValueError("未恢复到完整企业对象")
    logger.warning(f"模型 JSON 输出疑似截断，已恢复 {len(companies)} 个完整企业对象")
    return {"companies": companies}


def _extract_json_object(content: str) -> Dict[str, Any]:
    text = _strip_json_fences(content)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return _recover_truncated_companies(match.group(0))
        return _recover_truncated_companies(text)


def _call_openai_json(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 2000,
    timeout: float = 90
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
        )

    content = response.choices[0].message.content or "{}"
    return _extract_json_object(content)


def _image_to_data_url(image_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/png"
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _call_multimodal_json(
    image_path: str,
    prompt: str,
    max_tokens: int = WHITELIST_IMAGE_MODEL_TOKENS,
    timeout: float = WHITELIST_IMAGE_MODEL_TIMEOUT,
) -> Dict[str, Any]:
    image_url = _image_to_data_url(image_path)
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业信息抽取和工商全称标准化专家。"
                "请直接读取用户提供的图片，识别其中的企业名称，并只返回 JSON。"
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]
    return _call_openai_json(IMAGE_MODEL_API_KEY, IMAGE_MODEL_BASE_URL, IMAGE_MODEL_NAME, messages, max_tokens, timeout)


def _normalize_position(value: Any, default_position: str = "") -> str:
    text = str(value or "").strip()
    for position in VALID_POSITIONS:
        if text == position or position in text:
            return position
    return default_position if default_position in VALID_POSITIONS else ""


def _looks_like_company_name(name: str) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    company_markers = (
        "公司", "集团", "厂", "院", "所", "中心", "银行", "证券", "基金", "保险",
        "股份", "有限", "Co.", "CO.", "Inc", "Ltd", "LLC"
    )
    if any(marker in text for marker in company_markers):
        return True
    return bool(re.search(r"[A-Za-z0-9]{2,}", text))


def _is_industry_placeholder(company_name: str, source_name: str) -> bool:
    text = (company_name or "").strip()
    source = (source_name or "").strip()
    placeholders = ("企业", "公司", "厂商", "供应商", "服务商", "制造商", "机构")
    industry_terms = (
        "研发", "生产", "制造", "销售", "服务", "应用", "设备", "材料", "原料", "器械",
        "产业", "行业", "市场", "物流", "流通", "种植", "养殖", "加工", "检测", "认证"
    )
    if source and text == f"{source}企业":
        return True
    if any(text.endswith(term) for term in placeholders) and any(term in text for term in industry_terms):
        return True
    return False


def _normalize_company_items(items: Any, default_position: str = "") -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized = []
    seen = set()
    for item in items:
        if isinstance(item, str):
            source_name = item.strip()
            company_name = source_name
            confidence = "medium"
            evidence = ""
        elif isinstance(item, dict):
            source_name = str(item.get("source_name") or item.get("original") or item.get("name") or "").strip()
            company_name = str(item.get("company_name") or item.get("full_name") or source_name).strip()
            position = _normalize_position(
                item.get("position") or item.get("industry_position") or item.get("产业链环节"),
                default_position
            )
            confidence = str(item.get("confidence") or "medium").strip()
            evidence = str(item.get("evidence") or item.get("reason") or "").strip()
        else:
            continue

        if not isinstance(item, dict):
            position = default_position if default_position in VALID_POSITIONS else ""

        if not company_name:
            continue
        if not _looks_like_company_name(company_name) and not _looks_like_company_name(source_name):
            continue
        if _is_industry_placeholder(company_name, source_name):
            continue

        key = company_name
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "source_name": source_name or company_name,
            "company_name": company_name,
            "position": position,
            "confidence": confidence if confidence in {"high", "medium", "low"} else "medium",
            "evidence": evidence,
        })

    return normalized


def _merge_company_items(*groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    index_by_key = {}
    confidence_rank = {"low": 0, "medium": 1, "high": 2}

    for group in groups:
        for item in group or []:
            company_name = (item.get("company_name") or item.get("source_name") or "").strip()
            source_name = (item.get("source_name") or company_name).strip()
            if not company_name:
                continue
            key = re.sub(r"\s+", "", company_name)
            existing_index = index_by_key.get(key)
            if existing_index is None:
                index_by_key[key] = len(merged)
                merged.append({
                    "source_name": source_name,
                    "company_name": company_name,
                    "position": _normalize_position(item.get("position"), ""),
                    "confidence": item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "medium",
                    "evidence": item.get("evidence") or "",
                })
                continue

            existing = merged[existing_index]
            if not existing.get("position") and item.get("position"):
                existing["position"] = _normalize_position(item.get("position"), "")
            if confidence_rank.get(item.get("confidence"), 1) > confidence_rank.get(existing.get("confidence"), 1):
                existing["confidence"] = item.get("confidence")
            if not existing.get("evidence") and item.get("evidence"):
                existing["evidence"] = item.get("evidence")

    return merged


def _get_image_size(image_path: str) -> Tuple[int, int]:
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(f"图片分片依赖不可用: {exc}") from exc

    with Image.open(image_path) as image:
        return image.size


def _is_long_image(image_path: str) -> bool:
    try:
        width, height = _get_image_size(image_path)
    except Exception as exc:
        logger.warning(f"读取图片尺寸失败，跳过长图分片: {exc}")
        return False
    if width <= 0:
        return False
    return height >= LONG_IMAGE_MIN_HEIGHT and (height / width) >= LONG_IMAGE_MIN_ASPECT_RATIO


def _split_long_image(image_path: str) -> List[Tuple[str, int, int]]:
    from PIL import Image

    chunks: List[Tuple[str, int, int]] = []
    with Image.open(image_path) as image:
        width, height = image.size
        if height <= 0 or width <= 0:
            return chunks

        chunk_height = min(LONG_IMAGE_CHUNK_HEIGHT, height)
        overlap = min(max(LONG_IMAGE_CHUNK_OVERLAP, 0), max(chunk_height // 3, 1))
        step = max(chunk_height - overlap, 1)
        top = 0
        chunk_index = 0

        while top < height and chunk_index < LONG_IMAGE_MAX_CHUNKS:
            bottom = min(top + chunk_height, height)
            if height - bottom < max(overlap // 2, 40):
                bottom = height
            chunk = image.crop((0, top, width, bottom))
            suffix = os.path.splitext(image_path)[1].lower() or ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as temp_file:
                chunk.save(temp_file.name)
                chunks.append((temp_file.name, top, bottom))

            if bottom >= height:
                break
            top += step
            chunk_index += 1

    return chunks


def _build_image_extract_prompt(industry_name: str, position: str, image_label: str = "") -> str:
    fixed_position = position if position in VALID_POSITIONS else ""
    position_instruction = (
        f"用户已指定本张图片全部属于“{fixed_position}”，每个企业 position 都固定返回“{fixed_position}”。"
        if fixed_position
        else "请根据图片表格的分区、左侧合并单元格、标题或上下文自动判断每家企业属于“上游/中游/下游”。如果图片没有明确区分，position 返回空字符串，交给用户确认。"
    )
    return f"""请直接读取这张图片中的文字、表格或产业链图谱，抽取其中出现的企业名称，并尽量补齐为准确的工商注册全称。

产业链：{industry_name}
图片信息：{image_label}
位置处理：{position}
位置判断规则：{position_instruction}

要求：
1. 只抽取企业、集团、上市公司或明确经营主体，不要抽取行业、产品、城市、标题、说明文字。
2. 如果图片中是简称或品牌简称，请补齐为常见工商注册全称，例如“中国石化”补为“中国石油化工集团有限公司”。
3. position 只能是“上游”“中游”“下游”或空字符串。
4. 如果无法确定全称，company_name 可保留识别名称，但 confidence 必须为 low。
5. 不要把“化学制药”“生产制造”“医疗服务”等行业环节改写成“某某企业”。
6. 如果图片无法读取或没有企业名称，返回 companies 空数组。
7. 返回 JSON，不要输出解释文本。格式：
{{
  "companies": [
    {{
      "source_name": "图片中的名称",
      "company_name": "补齐后的企业全称",
      "position": "上游|中游|下游|",
      "confidence": "high|medium|low",
      "evidence": "来自图片的短证据"
    }}
  ]
}}
"""


def _extract_companies_from_image_direct(image_path: str, industry_name: str, position: str) -> Tuple[List[Dict[str, str]], str, str]:
    fixed_position = position if position in VALID_POSITIONS else ""
    prompt = _build_image_extract_prompt(industry_name, position, "完整图片")
    parsed = _call_multimodal_json(image_path, prompt)
    companies = _normalize_company_items(parsed.get("companies"), fixed_position)
    return companies[:MAX_IMAGE_COMPANIES], "multimodal_image", ""


def _extract_companies_from_image_chunk(
    image_path: str,
    industry_name: str,
    position: str,
    chunk_index: int,
    total_chunks: int,
    y_range: Tuple[int, int]
) -> Tuple[List[Dict[str, str]], str, str]:
    fixed_position = position if position in VALID_POSITIONS else ""
    chunk_label = f"长图切片 {chunk_index}/{total_chunks}，纵向范围 {y_range[0]}-{y_range[1]}"
    prompt = _build_image_extract_prompt(industry_name, position, chunk_label)
    parsed = _call_multimodal_json(
        image_path,
        prompt,
        max_tokens=LONG_IMAGE_CHUNK_TOKENS,
        timeout=WHITELIST_IMAGE_MODEL_TIMEOUT,
    )
    companies = _normalize_company_items(parsed.get("companies"), fixed_position)
    return companies[:LONG_IMAGE_COMPANIES_PER_CHUNK], "multimodal_image_chunk", chunk_label


def _extract_companies_from_long_image(image_path: str, industry_name: str, position: str) -> Tuple[List[Dict[str, str]], str, str]:
    chunks = _split_long_image(image_path)
    if len(chunks) <= 1:
        for chunk_path, _, _ in chunks:
            try:
                os.unlink(chunk_path)
            except OSError:
                pass
        raise RuntimeError("长图分片数量不足")

    logger.info(f"白名单长图分片识别: chunks={len(chunks)}")
    results: List[List[Dict[str, str]]] = []
    recognition_sections: List[Tuple[int, str]] = []
    errors = []
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        workers = max(1, min(LONG_IMAGE_CHUNK_WORKERS, len(chunks)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _extract_companies_from_image_chunk,
                    chunk_path,
                    industry_name,
                    position,
                    index,
                    len(chunks),
                    (top, bottom)
                ): (index, chunk_path)
                for index, (chunk_path, top, bottom) in enumerate(chunks, start=1)
            }
            for future in as_completed(futures):
                index, _ = futures[future]
                try:
                    companies, _, chunk_label = future.result()
                    results.append(companies)
                    recognition_sections.append((index, chunk_label))
                    logger.info(f"长图切片 {index}/{len(chunks)} 识别到 {len(companies)} 家企业")
                except Exception as exc:
                    errors.append(f"切片{index}: {_short_error(exc)}")
                    logger.warning(f"长图切片 {index}/{len(chunks)} 识别失败: {exc}")
    finally:
        for chunk_path, _, _ in chunks:
            try:
                os.unlink(chunk_path)
            except OSError:
                pass

    merged = _merge_company_items(*results)
    if merged:
        recognition_notes = "\n\n".join(text for _, text in sorted(recognition_sections, key=lambda item: item[0]))
        return merged[:MAX_IMAGE_COMPANIES], f"long_image_chunks_{len(chunks)}", recognition_notes
    raise RuntimeError("长图分片未识别到企业" + (f": {'; '.join(errors)}" if errors else ""))


@router.get("/template")
async def download_template(current_user: dict = Depends(get_current_user)):
    """
    下载白名单模板

    Returns:
        FileResponse: Excel模板文件
    """
    if not os.path.exists(TEMPLATE_FILE):
        raise HTTPException(status_code=404, detail="模板文件不存在")

    return FileResponse(
        path=TEMPLATE_FILE,
        filename="企业名录模版.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.post("/upload")
async def upload_whitelist(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    上传白名单Excel文件

    Args:
        file: 上传的Excel文件

    Returns:
        dict: 上传结果
    """
    # 检查文件类型
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件格式(.xlsx, .xls)")

    # 保存临时文件
    temp_file = None
    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx', dir=UPLOAD_DIR) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name

        logger.info(f"用户 {current_user.get('username')} 上传白名单文件: {file.filename}")

        # 导入数据
        from steps.step_upload_whitelist import import_whitelist
        result = import_whitelist(temp_path, current_user.get("user_id"))

        return result

    except Exception as e:
        logger.error(f"上传白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

    finally:
        # 清理临时文件
        if temp_file and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


@router.post("/recognize-image")
async def recognize_whitelist_image(
    file: UploadFile = File(...),
    industry_name: str = Form(...),
    position: str = Form(AUTO_POSITION),
    current_user: dict = Depends(get_current_user)
):
    """
    识别白名单图片中的企业名称，仅返回预览结果，不写入数据库。
    """
    industry_name = (industry_name or "").strip()
    position = (position or "").strip()

    if not industry_name:
        raise HTTPException(status_code=400, detail="请选择产业链")
    if position not in VALID_POSITIONS and position != AUTO_POSITION:
        raise HTTPException(status_code=400, detail=f"position值无效，允许的值: {', '.join(VALID_POSITIONS + [AUTO_POSITION])}")
    if not _is_supported_image(file.filename, file.content_type):
        raise HTTPException(status_code=400, detail="只支持图片文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片文件为空")
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="图片不能超过15MB")

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".png"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        logger.info(
            f"用户 {current_user.get('username')} 识别白名单图片: "
            f"{file.filename}, {industry_name}, {position}"
        )

        recognition_notes = ""
        recognize_method = "multimodal_image"
        errors = []
        try:
            if _is_long_image(temp_path):
                companies, recognize_method, recognition_notes = _extract_companies_from_long_image(temp_path, industry_name, position)
            else:
                companies, recognize_method, recognition_notes = _extract_companies_from_image_direct(temp_path, industry_name, position)
        except Exception as image_exc:
            errors.append(f"多模态图片识别失败: {_short_error(image_exc)}")
            detail = "；".join(errors)
            logger.error(f"白名单图片识别失败: {detail}")
            raise HTTPException(
                status_code=500,
                detail=f"图片识别失败：{detail}"
            )

        return {
            "success": True,
            "message": "识别完成" if companies else "未识别到企业名称",
            "data": {
                "industry_name": industry_name,
                "position": position,
                "recognize_method": recognize_method,
                "recognition_notes": recognition_notes[:8000],
                "ocr_text": "",
                "companies": companies,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"识别白名单图片失败: {e}")
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@router.get("/list")
async def get_whitelist_list(
    industry_name: Optional[str] = Query(None, description="产业链名称"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取白名单列表

    Args:
        industry_name: 产业链名称（可选）

    Returns:
        dict: 白名单列表
    """
    try:
        from steps.step_upload_whitelist import get_whitelist_list
        data = get_whitelist_list(industry_name)

        return {
            "success": True,
            "data": data,
            "count": len(data)
        }

    except Exception as e:
        logger.error(f"获取白名单列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.delete("/{industry_name}")
async def delete_whitelist(
    industry_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    删除指定产业链的白名单

    Args:
        industry_name: 产业链名称

    Returns:
        dict: 删除结果
    """
    try:
        from steps.step_upload_whitelist import delete_whitelist_by_industry
        count = delete_whitelist_by_industry(industry_name)

        return {
            "success": True,
            "message": f"已删除 {count} 条记录",
            "count": count
        }

    except Exception as e:
        logger.error(f"删除白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/stats")
async def get_whitelist_stats(current_user: dict = Depends(get_current_user)):
    """
    获取白名单统计信息

    Returns:
        dict: 统计信息
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        conn = await get_connection()
        cursor = conn.cursor()

        # 按产业链统计
        cursor.execute("""
            SELECT industry_name, position, COUNT(*) as count
            FROM whitelist_company
            GROUP BY industry_name, position
            ORDER BY industry_name, position
        """)
        by_industry = cursor.fetchall()

        # 总数统计
        cursor.execute("SELECT COUNT(*) as total FROM whitelist_company")
        total = cursor.fetchone()['total']

        # 按position统计
        cursor.execute("""
            SELECT position, COUNT(*) as count
            FROM whitelist_company
            GROUP BY position
        """)
        by_position = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "stats": {
                "total": total,
                "by_industry": by_industry,
                "by_position": by_position
            }
        }

    except Exception as e:
        logger.error(f"获取白名单统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.post("/item")
async def add_whitelist_item(
    industry_name: str,
    position: str,
    company_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    添加单个白名单企业

    Args:
        industry_name: 产业链名称
        position: 位置（上游/中游/下游）
        company_name: 企业名称

    Returns:
        dict: 添加结果
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        # 验证position
        VALID_POSITIONS = ['上游', '中游', '下游']
        if position not in VALID_POSITIONS:
            raise HTTPException(status_code=400, detail=f"position值无效，允许的值: {', '.join(VALID_POSITIONS)}")

        conn = await get_connection()
        cursor = conn.cursor()

        # 检查是否已存在
        cursor.execute("""
            SELECT id FROM whitelist_company
            WHERE industry_name = %s AND company_name = %s
        """, (industry_name, company_name))
        existing = cursor.fetchone()

        if existing:
            cursor.close()
            conn.close()
            return {
                "success": False,
                "message": "该企业已在白名单中"
            }

        # 插入新记录
        cursor.execute("""
            INSERT INTO whitelist_company (industry_name, position, company_name)
            VALUES (%s, %s, %s)
        """, (industry_name, position, company_name))

        conn.commit()
        new_id = cursor.lastrowid

        cursor.close()
        conn.close()

        logger.info(f"用户 {current_user.get('username')} 添加白名单: {industry_name} - {company_name}")

        return {
            "success": True,
            "message": "添加成功",
            "data": {
                "id": new_id,
                "industry_name": industry_name,
                "position": position,
                "company_name": company_name
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


@router.delete("/item/{item_id}")
async def delete_whitelist_item(
    item_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    删除单个白名单企业

    Args:
        item_id: 白名单项ID

    Returns:
        dict: 删除结果
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        conn = await get_connection()
        cursor = conn.cursor()

        # 先查询是否存在
        cursor.execute("""
            SELECT id, industry_name, company_name FROM whitelist_company WHERE id = %s
        """, (item_id,))
        item = cursor.fetchone()

        if not item:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="记录不存在")

        # 删除记录
        cursor.execute("""
            DELETE FROM whitelist_company WHERE id = %s
        """, (item_id,))

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"用户 {current_user.get('username')} 删除白名单: {item['industry_name']} - {item['company_name']}")

        return {
            "success": True,
            "message": "删除成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.put("/item/{item_id}")
async def update_whitelist_item(
    item_id: int,
    industry_name: str = None,
    position: str = None,
    company_name: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    编辑白名单企业信息

    Args:
        item_id: 白名单项ID
        industry_name: 新产业链名称（可选）
        position: 新位置（可选）
        company_name: 新企业名称（可选）

    Returns:
        dict: 更新结果
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        # 验证position
        if position:
            VALID_POSITIONS = ['上游', '中游', '下游']
            if position not in VALID_POSITIONS:
                raise HTTPException(status_code=400, detail=f"position值无效，允许的值: {', '.join(VALID_POSITIONS)}")

        conn = await get_connection()
        cursor = conn.cursor()

        # 先查询是否存在
        cursor.execute("""
            SELECT id FROM whitelist_company WHERE id = %s
        """, (item_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="记录不存在")

        # 构建更新语句
        update_fields = []
        params = []
        if industry_name is not None:
            update_fields.append("industry_name = %s")
            params.append(industry_name)
        if position is not None:
            update_fields.append("position = %s")
            params.append(position)
        if company_name is not None:
            update_fields.append("company_name = %s")
            params.append(company_name)

        if update_fields:
            update_fields.append("updated_at = NOW()")
            params.append(item_id)

            sql = f"""
                UPDATE whitelist_company
                SET {', '.join(update_fields)}
                WHERE id = %s
            """
            cursor.execute(sql, params)
            conn.commit()

        cursor.close()
        conn.close()

        logger.info(f"用户 {current_user.get('username')} 更新白名单 ID: {item_id}")

        return {
            "success": True,
            "message": "更新成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.get("/industries")
async def get_whitelist_industries(current_user: dict = Depends(get_current_user)):
    """
    获取所有产业链列表（用于筛选）

    Returns:
        dict: 产业链列表
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        conn = await get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT industry_name
            FROM whitelist_company
            ORDER BY industry_name
        """)
        industries = [row['industry_name'] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return {
            "success": True,
            "data": industries
        }

    except Exception as e:
        logger.error(f"获取产��链列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/items")
async def get_whitelist_items(
    industry_name: Optional[str] = Query(None, description="产业链名称"),
    position: Optional[str] = Query(None, description="位置"),
    search: Optional[str] = Query(None, description="企业名称搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取白名单企业列表（分页）

    Args:
        industry_name: 产业链名称（可选）
        position: 位置（可选）
        search: 企业名称搜索关键词（可选）
        page: 页码
        page_size: 每页数量

    Returns:
        dict: 分页数据
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        conn = await get_connection()
        cursor = conn.cursor()

        # 构建查询条件
        conditions = []
        params = []

        if industry_name:
            conditions.append("industry_name = %s")
            params.append(industry_name)

        if position:
            conditions.append("position = %s")
            params.append(position)

        if search:
            conditions.append("company_name LIKE %s")
            params.append(f"%{search}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 获取总数
        count_sql = f"SELECT COUNT(*) as total FROM whitelist_company {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()['total']

        # 获取分页数据
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT id, industry_name, position, company_name, created_at, updated_at
            FROM whitelist_company
            {where_clause}
            ORDER BY industry_name, position, id
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_sql, params + [page_size, offset])
        items = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
        }

    except Exception as e:
        logger.error(f"获取白名单列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/batch-delete")
async def batch_delete_whitelist(
    ids: list[int],
    current_user: dict = Depends(get_current_user)
):
    """
    批量删除白名单企业

    Args:
        ids: 要删除的ID列表

    Returns:
        dict: 删除结果
    """
    try:
        import pymysql
        from database.business_data.connection import get_connection

        if not ids:
            raise HTTPException(status_code=400, detail="请选择要删除的项")

        conn = await get_connection()
        cursor = conn.cursor()

        # 构建占位符
        placeholders = ','.join(['%s'] * len(ids))
        sql = f"DELETE FROM whitelist_company WHERE id IN ({placeholders})"
        cursor.execute(sql, ids)

        conn.commit()
        deleted_count = cursor.rowcount

        cursor.close()
        conn.close()

        logger.info(f"用户 {current_user.get('username')} 批量删除白名单: {deleted_count} 条")

        return {
            "success": True,
            "message": f"已删除 {deleted_count} 条记录",
            "count": deleted_count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除白名单失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
