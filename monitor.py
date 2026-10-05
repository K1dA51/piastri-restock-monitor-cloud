#!/usr/bin/env python3
"""Piastri World Circuit 小码补货监控（云端版）。

设计用于 GitHub Actions 或任何常驻服务器。环境变量：
  BARK_ENDPOINT  例如 https://api.day.app
  BARK_DEVICE_KEY
可选：
  STORE_PRODUCTS_JSON  覆盖商品接口地址（默认官方 World Circuit 集合）

基线文件 world-circuit-stock.json 记录最近一次“相关状态”快照。
仅当被监控商品/尺码的可用状态发生变化时才重写基线，
因此仓库不会在每次无变化运行时产生提交。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

SOURCE = os.environ.get(
    "STORE_PRODUCTS_JSON",
    "https://store.oscarpiastri.com/collections/worldcircuit/products.json?limit=250",
)
BASELINE = os.environ.get("BASELINE_FILE", "world-circuit-stock.json")
BARK_ENDPOINT = os.environ.get("BARK_ENDPOINT", "").rstrip("/")
BARK_DEVICE_KEY = os.environ.get("BARK_DEVICE_KEY", "")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
PRODUCT_JSON_TEMPLATE = "https://store.oscarpiastri.com/products/{handle}.js"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://store.oscarpiastri.com/collections/worldcircuit",
}

WATCH = {
    "worldcircuit-t-shirt-off-white": {
        "title": "World Circuit T-Shirt - Off White",
        "url": "https://store.oscarpiastri.com/products/worldcircuit-t-shirt-off-white",
    },
    "worldcircuit-quarter-zip-burgundy": {
        "title": "World Circuit Quarter Zip - Burgundy",
        "url": "https://store.oscarpiastri.com/products/worldcircuit-quarter-zip-burgundy",
    },
    "worldcircuit-layered-t-shirt-blue": {
        "title": "World Circuit Layered T-Shirt - Blue",
        "url": "https://store.oscarpiastri.com/products/worldcircuit-layered-t-shirt-blue",
    },
}
SIZES = {"XS", "S", "M"}


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S%z")


def curl_json(url: str):
    """用系统 curl 抓取：Python 的 TLS 指纹会被商店风控判成机器人(429/403)。"""
    cmd = [
        "curl",
        "-sS",
        "--compressed",
        "-f",
        "--max-time",
        "30",
        "-A",
        UA,
        "-H",
        "Accept: application/json, text/plain, */*",
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        "-H",
        "Referer: https://store.oscarpiastri.com/collections/worldcircuit",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl 失败({proc.returncode}): {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


def urllib_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def http_json(url: str):
    try:
        return curl_json(url)
    except Exception as curl_err:  # noqa: BLE001
        try:
            return urllib_json(url)
        except Exception as ua_err:  # noqa: BLE001
            raise RuntimeError(f"请求失败: curl={curl_err}; urllib={ua_err}")


def fetch_collection() -> list:
    return http_json(SOURCE).get("products", [])


def fetch_per_product() -> list:
    return [
        http_json(PRODUCT_JSON_TEMPLATE.format(handle=handle))
        for handle in WATCH
    ]


def fetch_products(retries: int = 4) -> list:
    """集合接口失败时改用单品 .js 接口，并对 403/网络抖动做退避重试。"""
    last_err = None
    for attempt in range(retries):
        for fetch in (fetch_collection, fetch_per_product):
            try:
                products = fetch()
                if products:
                    return products
            except Exception as err:  # noqa: BLE001
                last_err = err
        if attempt < retries - 1:
            time.sleep(min(30, 5 * (2 ** attempt)))
    raise RuntimeError(f"抓取失败: {last_err}")


def snapshot_of(raw_products: list) -> dict:
    output = []
    for p in raw_products:
        output.append(
            {
                "id": p["id"],
                "handle": p["handle"],
                "title": p["title"],
                "url": "https://store.oscarpiastri.com/products/" + p["handle"],
                "variants": [
                    {"id": v["id"], "title": v["title"], "available": v["available"]}
                    for v in p["variants"]
                ],
            }
        )
    return {
        "checked_at": now_iso(),
        "source": SOURCE,
        "products": output,
    }


def small_size_status(snapshot: dict) -> dict:
    result = {}
    for p in snapshot.get("products", []):
        handle = p.get("handle")
        if handle not in WATCH:
            continue
        result[handle] = {}
        for v in p.get("variants", []):
            raw = v.get("title", "")
            size = raw.split("/")[-1].strip() if "/" in raw else raw.strip()
            if size in SIZES:
                result[handle][size] = bool(v.get("available"))
    return result


def load_baseline():
    try:
        with open(BASELINE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as err:
        print(f"[{now_iso()}] 基线文件损坏，将重新初始化: {err}", flush=True)
        return None


def save_baseline(snapshot: dict) -> None:
    tmp = BASELINE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, BASELINE)


def send_bark(items: list) -> None:
    if not BARK_ENDPOINT or not BARK_DEVICE_KEY:
        raise RuntimeError("缺少 BARK_ENDPOINT 或 BARK_DEVICE_KEY")
    lines = []
    for handle, size in items:
        meta = WATCH[handle]
        lines.append(f"{meta['title']}（{size}）\n{meta['url']}")
    payload = json.dumps(
        {"title": "OP商店补货", "body": "\n".join(lines)}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BARK_ENDPOINT}/{BARK_DEVICE_KEY}",
        data=payload,
        headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        code = resp.status
    if code < 200 or code >= 300:
        raise RuntimeError(f"Bark 返回 HTTP {code}")


def send_test_push() -> None:
    if not BARK_ENDPOINT or not BARK_DEVICE_KEY:
        raise RuntimeError("缺少 BARK_ENDPOINT 或 BARK_DEVICE_KEY")
    payload = json.dumps(
        {
            "title": "补货监控测试",
            "body": "云端监控与 Bark 推送通道正常，补货时会用这个通道通知你。",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BARK_ENDPOINT}/{BARK_DEVICE_KEY}",
        data=payload,
        headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        code = resp.status
    if code < 200 or code >= 300:
        raise RuntimeError(f"Bark 返回 HTTP {code}")


def main() -> int:
    if os.environ.get("BARK_TEST") == "1":
        send_test_push()
        print(f"[{now_iso()}] 已发送 Bark 测试推送。", flush=True)
        return 0

    baseline = load_baseline()
    try:
        products = fetch_products()
    except Exception as err:  # noqa: BLE001
        print(f"[{now_iso()}] {err}", flush=True)
        return 1

    new_snapshot = snapshot_of(products)
    if baseline is None:
        save_baseline(new_snapshot)
        print(f"[{now_iso()}] 首次运行：已保存当前库存作为基线，暂不提醒。", flush=True)
        return 0

    old = small_size_status(baseline)
    new = small_size_status(new_snapshot)

    restocked = []
    for handle in WATCH:
        old_sizes = old.get(handle, {})
        new_sizes = new.get(handle, {})
        for size in SIZES:
            if not old_sizes.get(size, False) and new_sizes.get(size, False):
                restocked.append((handle, size))

    relevant_changed = old != new
    if restocked:
        desc = ", ".join(f"{WATCH[h]['title']}（{s}）" for h, s in restocked)
        try:
            send_bark(restocked)
        except Exception as err:  # noqa: BLE001
            # 推送失败时保留旧基线，下一次运行会再次检测并重试
            print(f"[{now_iso()}] 检测到补货但 Bark 推送失败，将重试: {desc}；{err}", flush=True)
            return 1
        print(f"[{now_iso()}] 补货并已推送 Bark: {desc}", flush=True)
        save_baseline(new_snapshot)
        return 0

    if relevant_changed:
        # 售罄/减少等变化也更新基线，避免后续把旧状态误判成补货
        save_baseline(new_snapshot)
        print(f"[{now_iso()}] 库存状态有变化，已更新基线（无新增小码补货）。", flush=True)
    else:
        print(f"[{now_iso()}] 检查完成，无新增补货。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
