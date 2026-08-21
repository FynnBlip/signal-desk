# Signal Desk · 通话评测工作台

喂任意 wav，出真实 PQ 分。把「语料 → 声线 → TTS → 信道 → 降噪 → 评测 → 判定」
七步通话测试链路做成可交互的本地工作台，零 GPU、纯 CPU 可跑。

> 目标：开源的、任何人一条命令能跑起来的通话质量评测 Agent 工作台。

## 七步链路

```
语料(01) → 声线(02) → TTS(03) → 信道(04) → 降噪(05) → 评测(06) → 判定(07)
   ↑                                                                    │
   └──────────────────── 迭代回环（回滚 / 换版本 / 调参）────────────────┘
```

每个 part 独立可跑，也能串成 loop。闭环大脑根据评测结果做「归因 → 条件晋级判定
→ LLM/规则建议 → 人在环确认」，决定回滚还是进入下一版。

## 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 01 语料生成 | ready | 中文通话语料 + 易混音对覆盖自检 |
| 02 音色聚类 | wip | 声线特征 + KMeans 聚类 + 覆盖矩阵 |
| 03 TTS 合成 | wip | MiniMax 系统音色合成 exam wav（预留本地引擎插槽） |
| 04 信道仿真 | wip | Opus 编解码闭环 × 多噪声场景 |
| 05 降噪 DUT | wip | GTCRN / DeepFilterNet3 / noisereduce |
| 06 评测 | wip | audiobox PQ/PC/CE/CU + ΔPQ 对比 |
| 07 闭环大脑 | wip | 版本迭代：归因 → 条件晋级 → 建议 → 人在环 |

> ready = 达到当前验收标准；wip = 有可跑的最小闭环，仍在打磨验收。

## 最新进展

- **05 接入 noisereduce**：`prop_decrease` 作为真实、可引用的降噪强度旋钮（替代早期 wet/dry 混音演示），纯 CPU 谱门控降噪。
- **07 版本迭代**：版本空间 = 同一算法沿「降噪比例 100%→40%」扫描，判定器输出「整体晋级（N 场景回退）／全绿晋级／条件晋级／回滚」，前端回退场景标黄，诚实呈现「一个上一个下」的权衡。
- **双主题**：浅色 SaaS + 暗色霓虹，设计 token 见 `docs/design-tokens.md`。

## 目录结构

| 目录 | 用途 |
|---|---|
| `app/` | 前端工作台（HTML，总览 + 各模块下钻） |
| `server/` | 本地后端（FastAPI，把 modules 挂成 HTTP 接口） |
| `modules/` | 七块，编号 = 链路顺序，各自可独立运行 |
| `data/` | 数据资产，数字唯一来源（红线见 `data/README.md`） |
| `models/` | 模型权重下载指引（权重不入仓库） |
| `docs/` | ADR / 设计 token / 口径依据 |
| `tests/` | 模块验收测试 |

## 怎么跑

```bash
# 安装依赖（Windows + Python 3.12，CPU 优先）
pip install -r requirements.txt

# 启动服务
python server/main.py
# 浏览器打开 http://127.0.0.1:8090
```

降噪 DUT 的 ONNX 权重、TTS 的 MiniMax key、audiobox checkpoint 等本地资产
见 `models/` 与 `.env.example`，不入仓库。

## 数据红线

- 所有数字来自 `data/eval` 真实评测 CSV，缺测写 NaN + `not_tested`，禁止占位假数据。
- 一份数据一个唯一来源，`matrix/` 是源，降噪产物按 `denoised/<版本>/` 归位。
- 无解就写无解，不造晋级假象；历史 CSV 不改，新数据写新时间戳。

## 发心

这不是为了面试做的，是想做一个能帮到一部分人的开源作品。
面试机会是水到渠成的事，作品本身的价值才是目标。
