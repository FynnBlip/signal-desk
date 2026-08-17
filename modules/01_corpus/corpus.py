# -*- coding: utf-8 -*-
"""01 语料生成 —— 第一块蛋糕。

职责：生成中文通话考试语料 corpus.txt（编号|场景|正文），
并统计易混音对覆盖（z/zh、n/l、f/h、前后鼻音）。
支持默认模板与自定义条目（前端传入 items）。

本模块不碰音频；TTS/信道/降噪/评测由 02~07 各自负责。
可独立运行：python modules/01_corpus/corpus.py
"""

import copy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 每条语料：id 追踪编号 / scene 场景 / text 正文 / covers 覆盖的易混音对（自检用）
CORPUS_TEMPLATES = [
    {"id": "C001", "scene": "客服", "text": "喂，您好，请问有什么可以帮您？", "covers": ["前后鼻音"]},
    {"id": "C002", "scene": "数字", "text": "您记一下，我的手机号是一三八五二六零九七四三。", "covers": ["n/l", "前后鼻音"]},
    {"id": "C003", "scene": "快递", "text": "师傅您好，我的快递到了吗？麻烦帮我放快递柜里。", "covers": ["f/h", "n/l"]},
    {"id": "C004", "scene": "售后", "text": "这个充电器充不上电，怎么处理？", "covers": ["z/zh", "前后鼻音"]},
    {"id": "C005", "scene": "预约", "text": "你好，我想预约明天上午十点的检查，麻烦您了。", "covers": ["n/l"]},
    {"id": "C006", "scene": "家庭", "text": "妈，我下班了，晚上想喝点热汤。", "covers": ["前后鼻音"]},
    {"id": "C007", "scene": "唤醒", "text": "小艺小艺，怎么设置十点的闹钟？", "covers": ["z/zh", "前后鼻音"]},
    {"id": "C008", "scene": "账单", "text": "这个月的电费是一百二十三元四角五分，回头记得交。", "covers": ["f/h"]},
    {"id": "C009", "scene": "会议", "text": "各位同事，下午的评审会改到三点半了，你们别迟到。", "covers": ["前后鼻音", "n/l"]},
    {"id": "C010", "scene": "闲聊", "text": "外面风大，记得关好窗户，别感冒了。", "covers": ["f/h", "前后鼻音"]},
]


def get_templates():
    """返回语料模板，供前端展示推荐条目。"""
    return copy.deepcopy(CORPUS_TEMPLATES)


def generate_corpus(items=None, output_dir=None):
    """生成语料文件，返回结构化摘要（方便挂成 HTTP 接口 / function calling）。

    items 为 None 时用默认模板；否则用传入条目（自动补 id，缺 covers 视为自定义）。
    """
    target = Path(output_dir) if output_dir else PROJECT_ROOT / "data" / "corpus"
    target.mkdir(parents=True, exist_ok=True)
    out_file = target / "corpus.txt"

    if items is None:
        items = CORPUS_TEMPLATES
    else:
        normalized = []
        for i, it in enumerate(items, start=1):
            if not isinstance(it, dict) or not it.get("text", "").strip():
                continue
            normalized.append({
                "id": it.get("id") or f"C{i:03d}",
                "scene": it.get("scene") or "自定义",
                "text": it["text"].strip(),
                "covers": it.get("covers") or [],
            })
        items = normalized

    lines = [f"{t['id']}|{t['scene']}|{t['text']}" for t in items]
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "status": "ok",
        "file": str(out_file),
        "count": len(lines),
        "coverage": _count_coverage(items),
    }


def _count_coverage(templates):
    stats = {}
    for t in templates:
        for pair in t["covers"]:
            stats[pair] = stats.get(pair, 0) + 1
    return stats


if __name__ == "__main__":
    result = generate_corpus()
    print(f"语料已生成：{result['file']}")
    print(f"共 {result['count']} 条，易混音对覆盖：{result['coverage']}")
