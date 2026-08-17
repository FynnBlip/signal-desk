# 模型下载指引（权重不入仓库）

评测引擎：Meta Audiobox-Aesthetics

- 下载：HuggingFace `facebook/audiobox-aesthetics`（checkpoint 约 396MB）
- 放入 `models/audiobox-aesthetics/checkpoint.pt`
- 纯 CPU 即可推理，无需 GPU

TTS（可选）：MiniMax 商用 API，密钥写入 `.env`；**没有 key 也能用现成 wav 走 04~07**。
