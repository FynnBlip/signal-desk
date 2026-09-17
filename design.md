# Design — Signal Desk

Signal Desk 的项目级视觉规范。它取代旧的 Aurora Glass 作为后续页面的唯一视觉依据；旧文档仅保留为历史记录。

## 当前实现入口（2026-09-10）

默认入口统一为 `app/lab.html`，只加载 `app/lab.css` 和 `app/lab.js`。七模块共用一套壳，禁止引入旧 index/workbench/insights 的布局或样式。此前章节提到的旧文件只作历史参考。当前结果必须按 experiment_id 隔离；缓存可以复用，历史结果不自动进入新实验。

## Genre

Editorial workbench（编辑型工程工作台）。界面首先是一套可信、可读、可追溯的实验工具，其次才是品牌展示。

## Macrostructure family

- 首页：Compact Thesis → Workbench Index → Action Rail。紧凑命题负责定调，七槽位链路必须成为首屏主体，三种进入方式随后承接操作。
- 工具页：Context Strip → Split Workbench → Result Ledger。页头只说明该槽位解决什么问题；输入、处理、输出先形成一条上下文摘要，再进入左侧配置与右侧运行观察，历史或批量结果沉到下方账本。
- 记录页：Long Document / Ledger。用分隔线、表格与展开详情表达 Trace，不用卡片墙。

## Theme

- `--color-paper` `#F2EFE7`
- `--color-paper-2` `#E7E0D3`
- `--color-paper-3` `#DCD3C3`
- `--color-ink` `#191917`
- `--color-ink-2` `#4F4C45`
- `--color-muted` `#746F65`
- `--color-rule` `#C9C1B4`
- `--color-success` `#267257`
- `--color-warning` `#9A5B16`
- `--color-danger` `#A23B32`

黑与暖纸色承担品牌表达。绿、琥珀、红只表达可用、进行中、失败等工程语义；蓝色不作为装饰性品牌色。

## Typography

版本验证工作台以 2026-09-07 的分层交互规则为准（`app/workbench.css`）：正文、导航、标题统一 Segoe UI / Microsoft YaHei UI；正文 14px，辅助文字 12–13px，区块标题 18–20px，页标题 28px，结论标题 26px，关键数字 28px。中文不使用负字距。下列旧 Display 大字号不适用于版本验证与首页任务标题。

- Display：Segoe UI Variable Display / Microsoft YaHei UI，700–750。
- Body：Segoe UI Variable Text / Microsoft YaHei UI，400–650。
- Editorial：Georgia / Noto Serif SC / Source Han Serif SC / STSong，只用于首页解释性文案和命题，不进入表格、表单或日志。
- 字号仅用六档：12 / 14 / 16 / 20 / 28 / 42–52px。64px 只允许用于独立品牌展示页，不用于工作台首页。
- 12px 仅用于状态、元数据和短标签；正文不得小于 14px，主要说明正文使用 16px。
- 数字使用 `font-variant-numeric: tabular-nums`。

## Spacing

4px 基准：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96。组件必须优先使用 CSS 中命名的 `--space-*`。

## Shape and hierarchy

- 应用卡片圆角上限 10px；表格、索引、Trace 默认不用圆角。
- 不使用玻璃、渐变背景、光晕、厚投影或卡片套卡片。
- 层级依次通过字号、字重、留白、明度差和细分隔线建立，阴影不承担结构。
- 三个进入方式在桌面端保持等宽、同高；主操作使用暖深纸色，并仅以小面积墨黑按钮建立优先级，次操作使用文本箭头。

## Task priority

- 工作台首屏先回答“当前可以做什么”，再解释“这个产品是什么”。
- 在 1366×768 下，核心任务区必须完整出现在首屏；标题与品牌叙事不得把它推到折叠线以下。
- 首页高度预算：项目栏约 10%，命题 15–20%，核心链路 35–40%，操作入口 25–30%。
- 高对比墨黑只用于导航与小面积主操作，不允许再用半屏黑色入口制造第二视觉中心。

## Tool workbench contract

- 工具页固定使用三层：上下文摘要、配置/运行双栏、结果账本。不得用一个大卡片包住所有表单、进度和结果。
- 配置栏回答“这次怎么跑”，运行栏回答“现在发生了什么”，结果栏回答“产出了什么、依据是什么”。三者不可混排。
- 空闲、运行、完成、失败必须使用语义文字与颜色共同表达；只有后端提供真实进度时才显示百分比，未知进度明确写为“运行中”，不得伪造进度。
- 结果首先呈现 Provider、输入、关键参数、输出路径和可试听产物；长表格允许容器内横向滚动，不得推动整页横向溢出。
- 桌面端配置/运行双栏，1100px 以下改为单栏；320px 起仍应保留完整表单宽度与可点击区域。

## Voice Cohort contract

- 声线聚类的样本单位是不同 `voice_id`，不是随机 WAV 文件；同一 `voice_id` 的重复文件不得被当成不同音色扩充样本量。
- Cohort 先规划后生成：规划阶段只读音色目录，必须显示去重后的调用数、总字符和预计音频时长；正式生成逐条落 manifest，可断点续跑。
- 中文通话实验默认只抽普通话系统音色；多语种音色必须由用户显式选择，避免口音与语速污染音色变量。
- 所有音色使用同一段目标 8–12 秒的音系覆盖探针。估算只用于成本预览，实际时长以 WAV 测量为准。
- 首次聚类的编号按簇中位 F0 从低到高稳定为 C1 / C2 / C3；锁为基线后，后续 Cohort 复用同一 scaler、中心和标签映射，只做归属，不重新洗牌。
- F0 与 F1 只作客观特征描述，使用“低 / 中 / 高基频”和“低 / 中 / 高 F1”等中性命名；不得仅凭均值推断性别、年龄或“声道粗细”。
- 版本回归账本固定比较 C1–C4 的样本数、占比、平均 F0/F1 与平均探针时长；版本必须带可读的 `version_label`，否则只能作为独立参考。
- 只有锚定当前基线的 Cohort 才进入“可比较”账本；独立重新拟合的结果保留展示，但不得伪装成同一组簇的变化。
- 固定簇可导出为独立评测目录；baseline / candidate 的 PQ、PC、CE、CU 必须复用同一套评测设置并并列展示均值、离散度与差值。客观评测完成后才进入人工听审，不自动替代人在环决策。

## Run, Trace and decision contract

- 第 07 槽使用分层视图：本轮结论、版本比较、配置与运行、实验历史分别展示。运行完成默认进入结论；场景证据与 A/B 试听从结论进入，保留返回入口和浏览器前进后退。详细数据不与结论争夺首屏。
- 暖白底参考 Anthropic 的克制气质，桌面工作区左右内边距 32px；不照搬官网的大留白。版本比较页默认展示六场景图表，原始数据与试听继续下钻。
- 六个噪声场景使用固定身份色，定义见 `app/scenes.css`：安静绿、办公室淡紫蓝、咖啡厅深紫、食堂粉、路口珊瑚、地铁红。场景选择卡可使用完整渐变；数据卡保持暖白，只在顶线、曲线、刻度与场景标签使用色彩。颜色负责识别场景，SNR 与长度刻度负责表达噪声强弱，两种语义不可混用。
- 音频播放互斥，切换视图停止播放；正式报告渲染为可读文档，按轮次展开，支持 Escape 关闭并恢复焦点。
- 一次运行只生成内存中的临时预览；只有人工确认晋级、回滚或无解后，才追加正式轮次、changelog 与报告。驳回只清除预览，不制造伪历史。
- Trace 只记录“配置锁定、模型加载、DUT、评测、建议生成、人工确认”等语义阶段；同一阶段的百分比就地更新，不逐条堆积轮询日志。
- 判定先显示方向（晋级 / 回滚 / 无解）与来源，再显示原因。证据固定使用“关键指标 + 逐场景差值 + 明文判读”，不得使用无坐标、无单位、无图例的装饰图。
- 正式历史只展示已确认轮次；临时预览必须始终标注“未写入历史”，重跑时明确说明会替换当前预览。

## Motion

- 常规反馈 150–220ms，使用 ease-out。
- hover 最多上移 1px；数据卡片和流程节点不缩放。
- `prefers-reduced-motion` 下关闭位移与动画。

## Microinteractions stance

- 成功、失败和运行态必须由文字 + 颜色共同表达。
- 焦点环使用 2px 墨黑轮廓，不能用发光效果。
- Trace 默认显示语义进度，技术 span 展开后查看。

## What every page must share

- 暖纸色、墨黑和语义色体系。
- 六档字号与三种字体角色的边界。
- 细线分层、低圆角、无装饰阴影的组件语言。
- 固定七槽位；槽内 Provider 可替换。

## What pages may differ on

- 首页可使用编辑型衬线说明，但留白必须服从核心任务的首屏可见性。
- 工具页允许更高信息密度，但仍遵守 14px 最小正文和单层容器。
- 噪声场景与图表可以使用数据本身需要的色彩，不得把数据色扩散为页面装饰。

## Exports

`tokens.css` 是运行时唯一 token 源；`tokens.json` 是同一系统的 DTCG 文件。以下映射用于
迁移到 Tailwind v4 或 shadcn/ui，不代表项目正在使用这些框架。

### tokens.css

```css
@import "tokens.css";
/* 完整定义见项目根目录 tokens.css；页面只消费 var(--token-name)。 */
```

### Tailwind v4 `@theme`

```css
@theme {
  --color-paper: #F2EFE7; --color-paper-2: #E7E0D3; --color-paper-3: #DCD3C3;
  --color-ink: #191917; --color-ink-2: #4F4C45; --color-muted: #746F65;
  --color-rule: #C9C1B4; --color-success: #267257;
  --color-warning: #9A5B16; --color-danger: #A23B32;
  --font-display: "Segoe UI Variable Display", "Microsoft YaHei UI", sans-serif;
  --font-body: "Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif;
  --font-outlier: "Cascadia Mono", Consolas, monospace;
  --spacing-1: 4px; --spacing-2: 8px; --spacing-3: 12px; --spacing-4: 16px;
  --spacing-6: 24px; --spacing-8: 32px; --spacing-12: 48px; --spacing-16: 64px;
  --text-meta: 12px; --text-small: 14px; --text-body: 16px;
  --text-heading: 20px; --text-section: 28px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --radius-card: 10px; --radius-input: 4px;
}
```

### DTCG `tokens.json`

```json
{
  "$schema": "https://design-tokens.github.io/community-group/format/",
  "color": {
    "paper": {"$value": "#F2EFE7", "$type": "color"},
    "paper-2": {"$value": "#E7E0D3", "$type": "color"},
    "paper-3": {"$value": "#DCD3C3", "$type": "color"},
    "ink": {"$value": "#191917", "$type": "color"},
    "ink-2": {"$value": "#4F4C45", "$type": "color"},
    "muted": {"$value": "#746F65", "$type": "color"},
    "rule": {"$value": "#C9C1B4", "$type": "color"},
    "success": {"$value": "#267257", "$type": "color"},
    "warning": {"$value": "#9A5B16", "$type": "color"},
    "danger": {"$value": "#A23B32", "$type": "color"}
  },
  "font": {
    "display": {"$value": "Segoe UI Variable Display, Microsoft YaHei UI, sans-serif", "$type": "fontFamily"},
    "body": {"$value": "Segoe UI Variable Text, Microsoft YaHei UI, sans-serif", "$type": "fontFamily"}
  },
  "space": {
    "1": {"$value": "4px", "$type": "dimension"},
    "2": {"$value": "8px", "$type": "dimension"},
    "4": {"$value": "16px", "$type": "dimension"},
    "8": {"$value": "32px", "$type": "dimension"}
  }
}
```

### shadcn/ui CSS variables

```css
:root {
  --background: 95.22% 0.0111 89.72; --foreground: 21.26% 0.0038 106.72;
  --card: 90.87% 0.0190 83.06; --card-foreground: 21.26% 0.0038 106.72;
  --popover: 95.22% 0.0111 89.72; --popover-foreground: 21.26% 0.0038 106.72;
  --primary: 21.26% 0.0038 106.72; --primary-foreground: 95.22% 0.0111 89.72;
  --secondary: 86.97% 0.0238 82.12; --secondary-foreground: 41.71% 0.0120 87.54;
  --muted: 81.38% 0.0200 80.10; --muted-foreground: 54.32% 0.0164 84.59;
  --destructive: 49.58% 0.1384 28.12; --destructive-foreground: 95.22% 0.0111 89.72;
  --border: 81.38% 0.0200 80.10; --input: 81.38% 0.0200 80.10;
  --ring: 21.26% 0.0038 106.72; --radius: 10px;
}
```

## Provenance

设计 DNA 来自对 Anthropic 公共首页截图与页面结构的研究：迁移的是非对称编辑版式、字体角色对比、暖纸色、黑色视觉锚点、细线索引与疏密节奏；不复制其品牌、文案、图像、字体文件或标志性插画。

## Notes

不要恢复 Aurora Glass、紫青渐变、漂浮光斑、毛玻璃侧栏、蓝色装饰描边、厚阴影、过量胶囊标签或卡片套卡片。
