#!/usr/bin/env python3
"""Export DingTalk 闪记 records into transcript and summary files."""
from __future__ import annotations

import os
import argparse
import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pymysql
import websockets

# LOCAL_SECRETS — 通过环境变量注入，见 .env。
# /reg 返回 401 ("device id or appkey is not equal" / "uid=null") 时需要从浏览器
# cookies 重新获取 DINGTALK_SHANJI_TOKEN / DINGTALK_SHANJI_DID。
TOKEN = os.getenv("DINGTALK_SHANJI_TOKEN")
DID = os.getenv("DINGTALK_SHANJI_DID")
UUID = "763275696439363334383838365f36373235315f30"

# Database config
DB_CONFIG = {
    "host": "rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com",
    "user": "root",
    "password": os.getenv("DB_PASSWORD_ZS"),
    "port": 3306,
    "database": "ai_insight",
    "charset": "utf8mb4",
}

_UUID_RE = re.compile(r"/transcribes/([A-Za-z0-9_]+)")

WS_URL = "wss://webalfa-cm3.dingtalk.com/long"
WEB_ORIGIN = "https://shanji.dingtalk.com"
DEFAULT_APP_KEY = os.getenv("DINGTALK_SHANJI_APP_KEY")
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 DingWeb/3.4.0 LANG/en_US"
)

log = logging.getLogger("shanji_export")

_mid_counter = 0

# 筛选条件常量
USER_FUNCTION_NAMES = (
    "产发体系",
    "产发轻资产体系",
    "粤浦产发体系",
    "项目总监产发体系",
)
MAY_START = "2026-05-01 00:00:00"
MAY_END = "2026-05-31 23:59:59"


def make_mid() -> str:
    global _mid_counter
    _mid_counter += 1
    return (
        f"{random.randint(100000, 999999)}{int(time.time() * 1000)}{_mid_counter:06d} 0"
    )


def referer_for(uuid: str) -> str:
    return f"{WEB_ORIGIN}/app/transcribes/{uuid}"


def build_transcript_body(uuid: str) -> list[dict[str, Any]]:
    return [
        {
            "taskUuid": uuid,
            "speaker": True,
            "timestamp": True,
            "exportFileType": "TXT",
            "targetLang": "source_lang",
            "exportContentType": "content",
            "supportBilingual": False,
        }
    ]


def build_summary_body(uuid: str) -> list[dict[str, Any]]:
    return [
        {
            "taskUuid": uuid,
            "speaker": False,
            "timestamp": False,
            "exportFileType": "Markdown",
            "targetLang": "source_lang",
            "exportContentType": "summary",
            "supportBilingual": False,
        }
    ]


async def lwp_call(
    ws: websockets.ClientConnection,
    lwp: str,
    uuid: str,
    body: list[dict[str, Any]] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    mid = make_mid()
    msg: dict[str, Any] = {
        "lwp": lwp,
        "headers": {
            "referer": referer_for(uuid),
            "TRANSCRIBE-PUBLISH-TYPE": "normal",
            "mid": mid,
        },
    }
    if body is not None:
        msg["body"] = body
    await ws.send(json.dumps(msg, separators=(",", ":"), ensure_ascii=False))
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"timeout waiting for response to {lwp} mid={mid}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(resp, dict) and resp.get("headers", {}).get("mid") == mid:
            return resp


async def register(
    ws: websockets.ClientConnection,
    *,
    uuid: str,
    token: str,
    app_key: str,
    ua: str,
    did: str | None = None,
) -> dict[str, Any]:
    mid = make_mid()
    headers: dict[str, Any] = {
        "referer": referer_for(uuid),
        "cache-header": "app-key token ua wv",
        "app-key": app_key,
        "token": token,
        "ua": ua,
        "dt": "j",
        "wv": "im:0,au:0,sy:6",
        "sync": "0,0;0;0;",
        "set-ver": "0",
        "reg-type": "1",
        "mid": mid,
    }
    if did:
        headers["did"] = did
    await ws.send(
        json.dumps({"lwp": "/reg", "headers": headers}, separators=(",", ":"))
    )
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("headers", {}).get("mid") == mid:
            if resp.get("code") != 200:
                raise RuntimeError(f"/reg rejected: {resp}")
            return resp


async def fetch_export_urls(
    *,
    uuid: str,
    token: str,
    app_key: str,
    ua: str,
    did: str | None = None,
) -> dict[str, str]:
    async with websockets.connect(
        WS_URL,
        origin=WEB_ORIGIN,
        user_agent_header=ua,
        compression="deflate",
        max_size=None,
    ) as ws:
        reg = await register(
            ws, uuid=uuid, token=token, app_key=app_key, ua=ua, did=did
        )
        sid = reg["headers"].get("sid", "")
        log.info("registered: uid=%s sid=%s…", reg["headers"].get("reg-uid"), sid[:16])

        plan: list[tuple[str, str, list[dict[str, Any]]]] = [
            (
                "transcript.txt",
                "/r/Adaptor/MinutesExportAppI/minutesExportLocal",
                build_transcript_body(uuid),
            ),
            (
                "summary.md",
                "/r/Adaptor/MinutesExportAppI/minutesExportLocal",
                build_summary_body(uuid),
            ),
        ]

        urls: dict[str, str] = {}
        for name, lwp, body in plan:
            try:
                resp = await lwp_call(ws, lwp, uuid, body)
                if resp.get("code") != 200:
                    log.warning("%s rpc failed (code %s), skipping this file", name, resp.get("code"))
                    continue
                url = resp["body"].get("exportUrl")
                if not url:
                    log.warning("%s response missing exportUrl, skipping this file", name)
                    continue
                urls[name] = url
                log.info("resolved %-16s -> %s", name, _shorten(url))
            except Exception:
                log.warning("%s failed, skipping this file", name, exc_info=True)
                continue
    return urls


def _query_db(cur) -> list[dict[str, str]]:
    cur.execute("SHOW COLUMNS FROM ts_task_user_info")
    existing_cols = {row["Field"] for row in cur.fetchall()}
    required_cols = {"id", "link_url", "user_function_name", "created_date"}
    missing_cols = required_cols - existing_cols
    if missing_cols:
        raise RuntimeError(f"ts_task_user_info missing required columns: {sorted(missing_cols)}")

    select_cols = ["DISTINCT id", "link_url", "user_function_name", "created_date"]
    sql = f"""
        SELECT {', '.join(select_cols)}
        FROM ts_task_user_info
        WHERE link_url IS NOT NULL
          AND link_url != ''
          AND user_function_name IN ({','.join(['%s'] * len(USER_FUNCTION_NAMES))})
          AND created_date BETWEEN %s AND %s
    """
    params: list[Any] = [*USER_FUNCTION_NAMES, MAY_START, MAY_END]

    if "delete_flag" in existing_cols:
        sql += " AND delete_flag = '0'"
    sql += " ORDER BY created_date DESC, id DESC"

    cur.execute(sql, params)
    rows = cur.fetchall()
    tasks = []
    for row in rows:
        m = _UUID_RE.search(row["link_url"])
        if not m:
            log.warning("skip: cannot extract uuid from link_url=%s", row["link_url"])
            continue
        tasks.append({
            "id": str(row["id"]),
            "uuid": m.group(1),
            "user_function_name": row["user_function_name"],
        })
    return tasks


def fetch_tasks_from_db(
    *, limit: int = 0,
) -> list[dict[str, str]]:
    """按 user_function_name 白名单和 5 月时间范围查询 ts_task_user_info。"""

    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            log.info("created_date: %s ~ %s", MAY_START, MAY_END)
            log.info("user_function_name: %s", ", ".join(USER_FUNCTION_NAMES))
            tasks = _query_db(cur)
            log.info("SQL 拉取: %d 条记录", len(tasks))
    finally:
        conn.close()

    if limit > 0:
        tasks = tasks[:limit]

    return tasks


async def download(urls: dict[str, str], out_dir: Path, ua: str, *, prefix: str = "") -> None:
    headers = {"Referer": f"{WEB_ORIGIN}/", "Origin": WEB_ORIGIN, "User-Agent": ua}
    # trust_env=False: bypass the shell's SOCKS proxy (downloads are direct HTTPS).
    async with httpx.AsyncClient(
        timeout=120.0, follow_redirects=True, headers=headers, trust_env=False
    ) as client:
        for name, url in urls.items():
            if prefix:
                if name == "transcript.txt":
                    dest = out_dir / f"{prefix}.txt"
                elif name == "summary.md":
                    dest = out_dir / f"{prefix}.md"
                else:
                    dest = out_dir / name
            else:
                dest = out_dir / name
            log.info("downloading %s", name)
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
            log.info("  wrote %s (%s bytes)", dest, f"{dest.stat().st_size:,}")


def _shorten(url: str, limit: int = 90) -> str:
    return url if len(url) <= limit else url[:limit] + "…"


async def run(args: argparse.Namespace) -> None:
    out_dir: Path = args.out_dir
    tasks = fetch_tasks_from_db(limit=args.limit)

    if not tasks:
        print("没有找到符合条件的记录")
        return

    skipped = done = 0
    for i, task in enumerate(tasks, 1):
        uuid = task["uuid"]
        prefix = task["id"]

        out_dir.mkdir(parents=True, exist_ok=True)

        # 检查是否已下载
        expected = [
            out_dir / f"{prefix}.txt",
            out_dir / f"{prefix}.md",
        ]
        if all(f.exists() and f.stat().st_size > 0 for f in expected):
            log.info("[%d/%d] skip (already exists) %s", i, len(tasks), prefix)
            skipped += 1
            continue

        log.info("[%d/%d] processing id=%s uuid=%s -> %s", i, len(tasks), prefix, uuid, out_dir)
        try:
            urls = await fetch_export_urls(
                uuid=uuid,
                token=TOKEN,
                app_key=DEFAULT_APP_KEY,
                ua=DEFAULT_UA,
                did=DID,
            )
        except Exception:
            log.exception("failed to fetch urls for uuid=%s, skipping", uuid)
            continue
        try:
            await download(urls, out_dir, DEFAULT_UA, prefix=prefix)
        except Exception:
            log.exception("failed to download for uuid=%s, skipping", uuid)
            continue
        done += 1

    print(f"done. exported: {done}, skipped: {skipped}, total: {len(tasks)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", default=0, type=int, help="限制导出条数，如 5")
    p.add_argument("--out-dir", default=Path(__file__).resolve().parent, type=Path, help="输出目录")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()


# ● nohup python3 /data/dingding/shanji_export.py > /data/dingding/export.log 2>&1 &

# 查看日志：
# tail -f /data/dingding/export.log
