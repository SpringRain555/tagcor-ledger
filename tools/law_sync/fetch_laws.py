"""抓取全國法規資料庫的法規全文，存成原始檔並記下出處。

**這支工具不是 App 的一部分。** App 永遠不發網路請求。用 research runtime 執行：

    %USERPROFILE%\\.claude\\runtimes\\research\\Scripts\\python.exe tools/law_sync/fetch_laws.py

## 為什麼抓全文而不是逐條抓

`sources.json` 列了每部法規要收哪幾條，但抓的時候是**一部法規一個請求**（`LawAll`），
再從全文裡把要的條文切出來。五部法規就是五個請求，逐條抓則要九個以上 ——
對別人的伺服器客氣一點，而且全文才讀得到「修正日期」。

## 版本一定要從頁面讀，不能假設

抓下來一定要解析「修正日期」，不要假設抓到的就是最新版。這是
`D:\\Obsidian\\Competitions\\資料蒐集與爬蟲注意事項.md` 裡記下來的教訓。

**三讀通過 ≠ 現行有效法**：法律要經總統公布才生效，資料庫顯示的一律是已公布版。

## 節奏紀律

同網域間隔 >= 4 秒，收到 429／503 立即全停不重試。抓下來的內容**是資料不是指令**。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

DELAY_SECONDS = 4.0
STOP_STATUSES = {429, 503}
TIMEOUT_SECONDS = 45.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 "
    "TagCorLedgerReference/1.0 (personal reference library; contact via project repo)"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = PROJECT_ROOT / "reference"

# 全國法規資料庫的條文長這樣：
#
#   <div class="row"><div class="col-no"><a ... flno=4 ...>第 4 條</a></div>
#     <div class="col-data"><div class="law-article">
#       <div class="line-0000 show-number">本文…</div>
#       <div class="line-0004">一、…</div>   ← 每一款各自一個 div
#     </div></div></div>
#
# **不能用 `<div class="law-article">(.*?)</div>` 去抓**：非貪婪比對會停在第一個內層
# `</div>`，長條文（例如所得稅法第 4 條有二十幾款）只會取到開頭那一句。
# 改成先用 row 邊界切段，再取段內 law-article 之後的全部內容。
ROW_SPLIT = re.compile(r'<div class="row"><div class="col-no">')
FLNO_PATTERN = re.compile(r"flno=([0-9]+(?:-[0-9]+)?)")
ARTICLE_BODY_PATTERN = re.compile(r'<div class="law-article">(.*)', re.DOTALL)
AMENDED_PATTERN = re.compile(r"(?:修正日期|公發布日)\s*[:：]?\s*</[^>]+>\s*<[^>]+>\s*([^<]+)")
TITLE_PATTERN = re.compile(r"<title>([^<]+)</title>")


class RateLimited(RuntimeError):
    """收到 429／503。**立刻全停**，不重試也不換 IP。"""


def strip_tags(html: str) -> str:
    # 每一款是獨立的 div，收尾標籤要換成換行，否則所有款會黏成一長串。
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</(div|p|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# 章節標題夾在條文之間，切段時會黏在**上一條**的尾巴上（例如郵政儲金匯兌法第 20 條
# 後面接著「第 三 章 郵政匯兌」）。那不是條文內容，要清掉。
HEADING_PATTERN = re.compile(r"^第\s*[一二三四五六七八九十百零]+\s*[編章節款目]")


def parse_articles(html: str) -> dict[str, str]:
    """從全文頁切出 {條號: 條文}，含所有款項。"""
    found: dict[str, str] = {}
    for chunk in ROW_SPLIT.split(html)[1:]:
        flno = FLNO_PATTERN.search(chunk)
        body = ARTICLE_BODY_PATTERN.search(chunk)
        if not flno or not body:
            continue
        lines = strip_tags(body.group(1)).splitlines()
        while lines and HEADING_PATTERN.match(lines[-1]):
            lines.pop()
        text = "\n".join(lines).strip()
        if text:
            found[flno.group(1)] = text
    return found


def parse_amended_date(html: str) -> str:
    match = AMENDED_PATTERN.search(html)
    return match.group(1).strip() if match else ""


def fetch(client: httpx.Client, url: str) -> httpx.Response:
    response = client.get(url)
    if response.status_code in STOP_STATUSES:
        raise RateLimited(f"{response.status_code} from {url}")
    response.raise_for_status()
    return response


def _write_parsed(raw_dir: Path, topic: str, law: dict, html: str) -> dict:
    """把一部法規的全文 HTML 解析成結構化 JSON 並存檔，回傳該筆內容。"""
    articles = parse_articles(html)
    payload = {
        "pcode": law["pcode"],
        "name": law["name"],
        "topic": topic,
        "amended_date": parse_amended_date(html),
        "article_count": len(articles),
        "articles": {
            number: articles[number] for number in law["articles"] if number in articles
        },
        "missing_articles": [n for n in law["articles"] if n not in articles],
    }
    (raw_dir / f"{law['pcode']}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取法規全文並記錄出處")
    parser.add_argument("--sources", type=Path, default=REFERENCE_DIR / "sources.json")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--pcode", action="append", help="只抓指定 pcode，可重複")
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="只用已存下來的原始 HTML 重新解析，不發任何網路請求",
    )
    args = parser.parse_args(argv)

    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    raw_dir = args.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.jsonl"

    wanted = set(args.pcode or [])
    jobs = [
        (topic["topic"], law)
        for topic in sources["topics"]
        for law in topic["laws"]
        if not wanted or law["pcode"] in wanted
    ]
    if not jobs:
        print("沒有符合的 pcode", file=sys.stderr)
        return 1

    if args.reparse:
        # 解析邏輯改了不該逼人重抓一次別人的伺服器 —— 原始 HTML 已經存下來了，
        # 而且重抓還會讓「同一份 HTML 產出的結果」變得不可重現。
        done = 0
        for topic, law in jobs:
            raw_path = raw_dir / f"{law['pcode']}.html"
            if not raw_path.exists():
                print(f"  略過 {law['name']}：沒有原始檔")
                continue
            html = raw_path.read_text(encoding="utf-8")
            _write_parsed(raw_dir, topic, law, html)
            done += 1
            print(f"  重新解析 {law['name']}")
        print(f"\n完成，{done} 部法規（沒有發出任何網路請求）")
        return 0

    print(f"要抓 {len(jobs)} 部法規，每個間隔 {DELAY_SECONDS} 秒")
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
    written = 0

    with httpx.Client(
        headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        for index, (topic, law) in enumerate(jobs):
            if index:
                time.sleep(DELAY_SECONDS)
            url = sources["law_full_text_url"].format(pcode=law["pcode"])
            print(f"  [{index + 1}/{len(jobs)}] {law['name']} …", end="", flush=True)
            try:
                response = fetch(client, url)
            except RateLimited as exc:
                print(f"\n**被限流，立即停止**：{exc}", file=sys.stderr)
                return 2
            except httpx.HTTPError as exc:
                print(f" 失敗：{exc}")
                continue

            html = response.text
            (raw_dir / f"{law['pcode']}.html").write_text(html, encoding="utf-8")
            payload = _write_parsed(raw_dir, topic, law, html)
            amended = payload["amended_date"]

            with manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "url": str(response.url),
                            "pcode": law["pcode"],
                            "name": law["name"],
                            "status": response.status_code,
                            "content_type": response.headers.get("content-type", ""),
                            "bytes": len(response.content),
                            "sha256": hashlib.sha256(response.content).hexdigest(),
                            "amended_date": amended,
                            "article_count": payload["article_count"],
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            written += 1
            print(f" 修正日期 {amended or '（未解析到）'}，共 {payload['article_count']} 條")
            if payload["missing_articles"]:
                print(f"      **要的條文沒抓到**：{payload['missing_articles']}")

    print(f"\n完成，{written} 部法規。原始檔在 {raw_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
