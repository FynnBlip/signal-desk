# 历史存档 · Aurora Glass · 可复用设计规范

> **已废弃，不再作为实现依据。** 当前系统为 `design.md` 中的 editorial workbench；
> 暖纸墨黑、细线账本、无渐变与无装饰阴影。本文仅作历史回溯。

> 风格名：**Aurora Glass（紫青毛玻璃）**。一次沉淀，任何新项目/新页面直接套用。
> 来源：ATS Resume Analyzer Dashboard（Figma Community，React+Tailwind v4 映射）+ 通话评测实验室 手感补充。
> 基调：浅色毛玻璃 + 紫→青品牌渐变 + 轻动效（干净、克制、不炫技）。

## 0. 怎么复用（三步）

1. 复制下面「全局 CSS 变量」块进新页面的 `:root`；
2. 按需复制「组件速查」里的类（`.card` / `.btn-primary` / `.nav-item` / `.badge` / `.input`）；
3. 打开「手感规范」，把 hover / press / 入场三类规则一起带上。

## 1. 全局 CSS 变量（直接抄）

```css
:root {
  /* 品牌渐变：全站按钮、激活态、图表主视觉 */
  --grad-brand: linear-gradient(to right, #8B5CF6, #14B8A6);
  --grad-heading: linear-gradient(to right, #7C3AED, #0D9488);

  /* 品牌与强调色 */
  --purple-500: #8B5CF6;
  --purple-600: #7C3AED;
  --teal-500: #14B8A6;
  --teal-600: #0D9488;
  --blue-500: #3B82F6;
  --green-500: #22C55E;
  --green-600: #16A34A;
  --red-500: #EF4444;
  --red-600: #DC2626;
  --orange-500: #F97316;
  --pink-500: #EC4899;
  --amber-500: #F59E0B;
  --cyan-500: #06B6D4;

  /* 中性色（文字/边框） */
  --gray-800: #1F2937; /* 标题、数值 */
  --gray-700: #374151; /* 导航未激活、正文 */
  --gray-600: #4B5563; /* 次级说明 */
  --gray-500: #6B7280; /* 辅助文字 */
  --gray-400: #9CA3AF; /* 弱文字 */
  --gray-200: #E5E7EB; /* 边框、网格线 */
  --gray-100: #F3F4F6; /* 浅底 */

  /* 语义色 */
  --ok: #16A34A;      /* 成功/上升 */
  --bad: #DC2626;     /* 失败/下降 */
  --info: #2563EB;    /* 信息/演示 */
  --ok-bg: #DCFCE7;
  --bad-bg: #FEE2E2;
  --info-bg: #DBEAFE;

  /* 页面背景：紫→蓝→青 的极浅渐变 */
  --bg-page: linear-gradient(to bottom right, #FAF5FF, #EFF6FF, #F0FDFA);

  /* 毛玻璃 */
  --glass: rgba(255, 255, 255, 0.58);
  --glass-border: rgba(255, 255, 255, 0.7);
  --glass-blur: 18px;

  /* 圆角 */
  --r-sm: 8px;   /* 小按钮、徽章 */
  --r-md: 12px;  /* 按钮、输入框、导航项 */
  --r-lg: 16px;  /* 卡片 */
  --r-full: 9999px;

  /* 阴影 */
  --shadow-card: 0 8px 32px rgba(31, 38, 135, 0.12);
  --shadow-hover: 0 16px 40px rgba(31, 38, 135, 0.2);

  /* 动效 */
  --t-fast: 150ms;  /* 微反馈 */
  --t-base: 250ms;  /* 常规 */
  --t-slow: 400ms;  /* 卡片浮现 */
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
  --ease-io: cubic-bezier(0.4, 0, 0.2, 1);

  /* 字体 */
  --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
  --fs-xs: 12px; --fs-sm: 14px; --fs-base: 16px;
  --fs-lg: 18px; --fs-xl: 20px; --fs-2xl: 24px; --fs-3xl: 30px;
}
```

## 2. 字体阶梯与圆角间距

| 用途 | 字号 |
|---|---|
| 标签 / 图例 | 12px |
| 次级说明 / KPI 标签 | 14px |
| 正文 | 16px |
| 卡片标题 / Logo | 18px |
| 二级标题 | 20px |
| KPI 数值 | 24px |
| 页面主标题（渐变字） | 30px |

- 字重只用三档：400 / 500 / 600。
- 圆角：小 8px、中 12px、卡片 16px、胶囊 9999px。
- 间距 4px 基准：8 / 12 / 16 / 24。
- 数字一律 `font-variant-numeric: tabular-nums`。

## 3. 组件速查

### 侧边栏 Sidebar
- 宽 256px，毛玻璃底 + 大阴影；Logo = 渐变方块（40px）+ 标题 + 一行小副标。
- 导航项：`padding 12px 16px; border-radius 12px`。
  - 激活态：紫青渐变底 + 白字；
  - 未激活：灰字，hover 时 `translateX(4px)` + 半透明白底。

### 主按钮 / 次按钮
```css
.btn-primary {
  padding: 8px 16px; border-radius: 12px; color: #fff;
  background-image: linear-gradient(to right, #8B5CF6, #14B8A6);
  transition: transform var(--t-fast) var(--ease-out), box-shadow var(--t-base) var(--ease-out);
}
.btn-primary:hover { box-shadow: 0 10px 20px rgba(124, 58, 237, .35); }
.btn-primary:active { transform: scale(.98); }
.btn-ghost { background: #fff; border: 1px solid var(--gray-200); color: var(--gray-700); border-radius: 12px; }
```

### KPI / 统计卡
- `border-radius 16px; padding 24px;` 毛玻璃 + `--shadow-card`。
- 顶部：40px 渐变图标方块 + 右侧趋势徽章（涨绿 / 跌红）。
- 数值 24px 深灰加粗；标签 14px 灰。

### 输入框 / 下拉 / 徽章 / 开关 / 加载
- 输入：`border 1px rgba(255,255,255,.3); background rgba(255,255,255,.55); border-radius 12px;` focus 时 `box-shadow 0 0 0 2px #8B5CF6`。
- 徽章：胶囊形，浅底 + 同色深字（语义色用上方 `--ok-bg` 等）。
- 开关：轨道 44×24 胶囊，开=紫，圆点白，切换时位移动画。
- 加载：2px 圆环 + 紫主色 + 透明顶边，1s 线性旋转。

## 4. 手感规范（Interaction Guide）

### 状态速查表
| 触发 | 属性变化 | 时长 / 缓动 |
|---|---|---|
| 卡片 :hover | `translateY(-3px)` + 阴影升为 `--shadow-hover` | 300ms / ease-in-out |
| 按钮 :hover | 阴影浮现（紫晕） | 250ms / ease-out |
| 按钮 :active | `scale(0.98)` | 150ms / ease-out |
| 导航 :hover | `translateX(4px)` + 半透明白底 | 300ms / ease-in-out |
| 输入 :focus | 2px 紫 ring | 瞬时 |
| 视图切换 | 内容 `fade + up(6px)` 淡入 | 300ms / ease-out |
| 卡片入场 | 逐卡 `fade + up(8px)`，相邻延迟 40ms（stagger） | 400ms / ease-out |
| 图表入场 | 折线描画 / 柱状上升 / 数字滚动 | 600ms / ease-out |

### 关键帧
```css
@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes blob {
  0%   { transform: translate(0, 0) scale(1); }
  33%  { transform: translate(30px, -50px) scale(1.1); }
  66%  { transform: translate(-20px, 20px) scale(0.9); }
  100% { transform: translate(0, 0) scale(1); }
}
@keyframes spin { to { transform: rotate(360deg); } }
```

### 铁律
1. 所有动效走 CSS transition/animation，无弹簧库也可以做到"干净手感"。
2. 必须实现 `prefers-reduced-motion: reduce` 降级：关闭位移/缩放，只留淡入。
3. 图表 Y 轴不截断、Δ 图带零线、单位与 seed 随图标注（数据诚实高于美观）。
4. 语义色全站唯一：绿=升/达标，红=降/回退，蓝=信息，紫青=品牌。

## 5. 与 通话评测实验室 的映射

| ATS 原设计 | 通话评测实验室 |
|---|---|
| 侧边栏 6 视图 | 总览 + 01~07 七模块导航 |
| KPI 四卡 | 语料条数 / 点亮模块数 / 数据规模 / 运行环境 |
| Score Trends 折线 | 迭代收敛五线图（后续 07 模块） |
| Export Report | 导出评测 CSV |
| Demo Mode 徽章 | 本地服务运行状态徽章 |
