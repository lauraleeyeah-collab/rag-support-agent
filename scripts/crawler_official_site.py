# -*- coding: utf-8 -*-
"""官网知识爬虫（R1）：robots 预检 → 抓取 → 语义分块 → 去重入 ChromaDB。

合规三件套（架构 C4）：
- robots.txt 预检：禁抓路径自动跳过；
- UA 标识：请求头明确标识为客服知识库机器人；
- 请求间隔：同一域名相邻请求间隔 ≥1 秒。

语义分块策略（架构 D6，不机械按字数）：
1. 提取 <main>/<article> 正文，剔除 nav/footer/脚本；
2. 按 h2/h3 标题层级切成「主题单元」（标题 + 其下段落/列表/表格为一个单元）；
3. 表格整块保留为 markdown，不拆散；列表整块保留；
4. 单元超过 CHUNK_SIZE*2（1000 字）才按段落边界二次切分，切分点不跨句子；
5. 每条知识带 metadata：source_type=crawler / module / url / title。

去重（架构 D6）：
- doc_id = md5(url)，同 URL 重抓时先删后插（重抓 = 更新），保证不重复入库。

用法：
    pip install -r scripts/requirements-crawler.txt
    python scripts/crawler_official_site.py      # 抓取 crawl_targets.json 清单全部 URL
    python scripts/crawler_official_site.py --dry-run  # 只抓取与分块，不入库（调试用）

环境变量（与后端一致）：DASHSCOPE_API_KEY / CHROMA_HOST / CHROMA_PORT。
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

# 把 backend 目录加入 import 路径，复用后端的向量库与 embedding 能力
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# 爬虫在 Docker 之外运行，默认连本机映射端口（可用环境变量覆盖）
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8001")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawler_official_site")

# ── 常量 ────────────────────────────────────────────────────

# 合规 UA：明确标识用途与联系方式占位
USER_AGENT = "SiteKbBot/1.0 (+<contact-url-placeholder>; customer-service-knowledge-crawler)"

# 相邻请求最小间隔（秒）
REQUEST_INTERVAL = 1.0

# 请求超时（秒）
REQUEST_TIMEOUT = 20

# 分块上限：超过 CHUNK_SIZE*2 才二次切分（与后端默认 500 对齐）
MAX_CHUNK_CHARS = 1000

# 单条知识最小长度，过短的碎片直接丢弃
MIN_CHUNK_CHARS = 30

# 模块枚举（架构 §7.3）
MODULE_PRODUCT = "产品选型"
MODULE_TROUBLESHOOT = "故障排查"
MODULE_AFTER_SALE = "售后政策"



# 抓取目标从 scripts/crawl_targets.json 加载（示例见仓库，按目标官网替换 URL）
def _load_targets() -> List[Dict[str, str]]:
    targets_path = Path(__file__).resolve().parent / "crawl_targets.json"
    if not targets_path.exists():
        logger.warning("未找到 scripts/crawl_targets.json，使用空清单")
        return []
    data = json.loads(targets_path.read_text(encoding="utf-8"))
    return data.get("targets", [])


CRAWL_TARGETS: List[Dict[str, str]] = _load_targets()

# ── 数据结构 ────────────────────────────────────────────────

@dataclass
class KnowledgeItem:
    """一条待入库的知识单元。"""
    doc_id: str                      # md5(url) + 序号，全局唯一
    title: str                       # 来源页面标题（展示用）
    content: str                     # 知识正文
    url: str                         # 来源 URL
    module: str                      # 产品选型/故障排查/售后政策
    source_type: str = "crawler"
    extra: Dict[str, str] = field(default_factory=dict)


# ── 爬虫核心 ────────────────────────────────────────────────

class CrawlerOfficialSite:
    """官网知识爬虫：robots 预检 → 抓取 → 语义分块 → 入库。"""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # robots 解析器缓存：域名 → RobotFileParser
        self._robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
        # 上次请求时间：域名 → 时间戳（保证同域名间隔 ≥1s）
        self._last_fetch_at: Dict[str, float] = {}

    # ── robots 预检 ──

    def check_robots(self, url: str) -> bool:
        """检查目标 URL 是否允许被抓取（禁抓路径返回 False）。"""
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots_cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                # 用本爬虫的合规 UA 抓取 robots.txt（urllib 默认 UA 会被站点 403，导致预检静默全拒）
                resp = self._session.get(f"{base}/robots.txt", timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # robots 非 200 时按允许处理（站点未声明禁止），并记录日志
                    logger.warning("robots.txt 返回 %s %s（按允许处理）", resp.status_code, base)
                    rp.parse([])
            except Exception as e:
                # robots 不可达时按保守策略放行（站点未声明禁止），并记录日志
                logger.warning("robots.txt 读取失败 %s: %s（按允许处理）", base, e)
                rp.parse([])  # 空规则 = 全部允许
            self._robots_cache[base] = rp
        rp = self._robots_cache[base]
        allowed = rp.can_fetch(USER_AGENT, url)
        if not allowed:
            logger.info("robots.txt 禁止抓取，跳过：%s", url)
        return allowed

    # ── 抓取 ──

    def fetch(self, url: str) -> Optional[str]:
        """抓取页面 HTML；失败/超时记录日志返回 None（不中断整体流程）。"""
        domain = urlparse(url).netloc
        # 请求间隔控制：同域名相邻请求间隔 ≥ REQUEST_INTERVAL
        last = self._last_fetch_at.get(domain)
        if last is not None:
            elapsed = time.time() - last
            if elapsed < REQUEST_INTERVAL:
                time.sleep(REQUEST_INTERVAL - elapsed)
        try:
            resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
            self._last_fetch_at[domain] = time.time()
            if resp.status_code != 200:
                logger.warning("抓取失败 [%s] %s", resp.status_code, url)
                return None
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as e:
            logger.warning("抓取异常 %s: %s", url, e)
            self._last_fetch_at[domain] = time.time()
            return None

    # ── 语义分块 ──

    @staticmethod
    def _clean_soup(soup: BeautifulSoup) -> Optional[Tag]:
        """提取正文容器，剔除导航/页脚/脚本等噪音。"""
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "button"]):
            tag.decompose()
        for selector in ["nav", "footer", "header"]:
            for tag in soup.find_all(selector):
                tag.decompose()
        # 优先取语义化正文容器
        for selector in ["main", "article", '[role="main"]', ".content", "#content"]:
            node = soup.select_one(selector)
            if node is not None:
                return node
        return soup.body

    @staticmethod
    def _table_to_markdown(table: Tag) -> str:
        """把 HTML 表格整块转成 markdown（不拆散）。"""
        rows: List[List[str]] = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |",
                 "| " + " | ".join(["---"] * width) + " |"]
        for r in rows[1:]:
            lines.append("| " + " | ".join(r) + " |")
        return "\n".join(lines)

    @classmethod
    def _node_to_text(cls, node: Tag) -> str:
        """把正文节点转成文本（表格/列表整块保留结构）。"""
        if node.name == "table":
            return cls._table_to_markdown(node)
        if node.name in ("ul", "ol"):
            items = ["- " + li.get_text(" ", strip=True) for li in node.find_all("li", recursive=False)]
            return "\n".join(items)
        return node.get_text(" ", strip=True)

    @staticmethod
    def _split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
        """超长单元按段落边界二次切分，切分点不跨句子。"""
        if len(text) <= max_chars:
            return [text]
        paragraphs = [p for p in text.split("\n") if p.strip()]
        chunks: List[str] = []
        current = ""
        for para in paragraphs:
            if current and len(current) + len(para) + 1 > max_chars:
                chunks.append(current.strip())
                current = para
            else:
                current = f"{current}\n{para}" if current else para
        if current.strip():
            chunks.append(current.strip())
        # 单段仍超长时按句号/分号边界硬切
        final: List[str] = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final.append(chunk)
                continue
            sentences = re.split(r"(?<=[。！？；!?;])", chunk)
            buf = ""
            for s in sentences:
                if buf and len(buf) + len(s) > max_chars:
                    final.append(buf.strip())
                    buf = s
                else:
                    buf += s
            if buf.strip():
                final.append(buf.strip())
        return final

    def extract_knowledge(self, html: str, url: str, module: str) -> List[KnowledgeItem]:
        """语义分块：按 h2/h3 标题层级切「主题单元」，表格/列表整块保留。"""
        soup = BeautifulSoup(html, "lxml")
        page_title = soup.title.get_text(strip=True) if soup.title else url
        container = self._clean_soup(soup)
        if container is None:
            return []

        # 1. 按标题层级切主题单元
        units: List[str] = []
        current_title = ""
        current_parts: List[str] = []

        def flush() -> None:
            body = "\n".join(p for p in current_parts if p.strip()).strip()
            if body:
                header = f"【{current_title}】\n" if current_title else ""
                units.append(header + body)

        for node in container.find_all(
            ["h1", "h2", "h3", "p", "ul", "ol", "table", "li"], recursive=True
        ):
            # li 会被 ul/ol 整块处理，跳过避免重复
            if node.name == "li" and node.parent is not None and node.parent.name in ("ul", "ol"):
                continue
            if node.name in ("h1", "h2", "h3"):
                flush()
                current_title = node.get_text(" ", strip=True)
                current_parts = []
            else:
                text = self._node_to_text(node)
                if text:
                    current_parts.append(text)
        flush()

        # 无标题结构时退化为整页文本
        if not units:
            fallback = container.get_text("\n", strip=True)
            if fallback:
                units = [fallback]

        # 2. 超长单元二次切分 + 过滤过短碎片
        items: List[KnowledgeItem] = []
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        for unit in units:
            for chunk in self._split_long_text(unit):
                chunk = chunk.strip()
                if len(chunk) < MIN_CHUNK_CHARS:
                    continue
                items.append(KnowledgeItem(
                    doc_id=f"{url_hash}_{len(items)}",
                    title=page_title,
                    content=chunk,
                    url=url,
                    module=module,
                ))
        return items

    # ── 入库 ──

    def ingest(self, items: List[KnowledgeItem]) -> int:
        """去重入库：同 URL 先删后插（重抓 = 更新）。返回实际入库条数。"""
        if not items:
            return 0

        # 延迟导入：dry-run 模式下不需要后端依赖（dashscope/chromadb）
        from app.services.doc_service import get_collection, embed_texts

        collection = get_collection()
        urls = sorted({item.url for item in items})

        # 去重：删除同 URL 旧记录
        for url in urls:
            existing = collection.get(where={"url": url})
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])
                logger.info("同 URL 旧记录已清除：%s（%d 条）", url, len(existing["ids"]))

        # 批量向量化 + 入库
        documents = [item.content for item in items]
        embeddings = embed_texts(documents)
        ids = [item.doc_id for item in items]
        metadatas = [{
            "doc_id": item.doc_id,
            "source": item.title,          # 页面标题（展示用）
            "source_type": item.source_type,
            "module": item.module,
            "url": item.url,
        } for item in items]

        collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        return len(items)


# ── 主流程 ──────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="官网知识爬虫（目标清单见 crawl_targets.json）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取与分块，不入库（调试用）")
    args = parser.parse_args()

    crawler = CrawlerOfficialSite()
    stats: Dict[str, int] = {MODULE_PRODUCT: 0, MODULE_TROUBLESHOOT: 0, MODULE_AFTER_SALE: 0}
    total = 0

    for target in CRAWL_TARGETS:
        url, module = target["url"], target["module"]
        logger.info("=== 处理 %s [%s] ===", url, module)

        if not crawler.check_robots(url):
            continue
        html = crawler.fetch(url)
        if not html:
            continue

        items = crawler.extract_knowledge(html, url, module)
        logger.info("分块产出 %d 条知识", len(items))

        if args.dry_run:
            for it in items[:3]:
                logger.info("样例 | %s | %s...", it.title, it.content[:80].replace("\n", " "))
            stats[module] = stats.get(module, 0) + len(items)
            total += len(items)
            continue

        try:
            inserted = crawler.ingest(items)
            stats[module] = stats.get(module, 0) + inserted
            total += inserted
            logger.info("入库 %d 条", inserted)
        except Exception as e:
            # 单页失败不中断整体流程
            logger.error("入库失败 %s: %s", url, e)

    logger.info("========== 抓取完成 ==========")
    for module, count in stats.items():
        flag = "✅" if count >= 15 else "⚠️ 不足15条，需人工补录"
        logger.info("模块 %s：%d 条 %s", module, count, flag)
    logger.info("总计入库：%d 条", total)


if __name__ == "__main__":
    main()
