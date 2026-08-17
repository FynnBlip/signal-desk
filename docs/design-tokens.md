# ATS Resume Analyzer Dashboard · Design Tokens

> 来源：Figma Community 文件 [ATS Resume Analyzer Dashboard](https://www.figma.com/community/file/1530261325896087183/ats-resume-analyzer-dashboard)
>
> - community id：`1530261325896087183`
> - design file key：`2244398949391261132`
> - 该文件由 **Figma Make** 生成（`viewer_mode=figmake_template`），底层是一套 React 组件代码
> - 技术栈映射：React + Tailwind CSS v4 + lucide-react（图标）+ Recharts（图表）
> - 主题：**浅色 + 毛玻璃（glassmorphism）**，全站无自定义 Web 字体

---

## 1. 颜色变量（Color）

### 1.1 品牌主色

| Token | HEX | 用途 |
| --- | --- | --- |
| `purple-500` | `#8B5CF6` | 主色，渐变起点、激活态、图表主色 |
| `purple-600` | `#7C3AED` | 标题渐变、hover |
| `teal-500` | `#14B8A6` | 辅色，渐变终点、图表辅色 |
| `teal-600` | `#0D9488` | 标题渐变终点 |

品牌渐变（核心视觉语言）：

```css
--gradient-brand: linear-gradient(to right, #8B5CF6, #14B8A6);      /* purple-500 → teal-500 */
--gradient-heading: linear-gradient(to right, #7C3AED, #0D9488);     /* purple-600 → teal-600，用于标题文字 */
```

### 1.2 强调色（KPI 图标 / 图表 / 状态）

| Token | HEX | 常见组合渐变 |
| --- | --- | --- |
| `blue-500` / `blue-600` | `#3B82F6` / `#2563EB` | `blue→teal`、`blue→purple` |
| `green-500` / `green-600` | `#22C55E` / `#16A34A` | `teal→green` |
| `emerald-500` | `#10B981` | — |
| `red-500` / `red-600` | `#EF4444` / `#DC2626` | `orange→red`（负向） |
| `orange-500` | `#F97316` | `orange→red` |
| `pink-500` | `#EC4899` | `purple→pink` |
| `amber-500` | `#F59E0B` | 图表序列色 |
| `cyan-500` | `#06B6D4` | 图表序列色 |

图表固定序列色（`skillsDistribution` / `topSkills`）：

```js
["#8B5CF6", "#14B8A6", "#3B82F6", "#F59E0B", "#EF4444", "#06B6D4"]
```

### 1.3 中性色（文字 / 边框）

| Token | HEX | 用途 |
| --- | --- | --- |
| `gray-800` | `#1F2937` | 标题、KPI 数值、正文强文字 |
| `gray-700` | `#374151` | 导航未激活、正文 |
| `gray-600` | `#4B5563` | 次级说明文字 |
| `gray-500` | `#6B7280` | 辅助文字 |
| `gray-400` | `#9CA3AF` | 弱文字 |
| `gray-200` | `#E5E7EB` | 边框、图表网格线 |
| `gray-100` | `#F3F4F6` | 浅底 |

### 1.4 语义色

| 语义 | Token | HEX |
| --- | --- | --- |
| 成功 / 上升 | `green-600` | `#16A34A` |
| 失败 / 下降 | `red-600` | `#DC2626` |
| 信息 / Demo | `blue-600` | `#2563EB` |
| Demo 徽章底 | `blue-100` | `#DBEAFE` |
| Demo 徽章边 | `blue-200` | `#BFDBFE` |

### 1.5 页面背景

| 用途 | 值 |
| --- | --- |
| 页面渐变底 | `linear-gradient(to bottom right, #FAF5FF, #EFF6FF, #F0FDFA)`（`purple-50 → blue-50 → teal-50`） |
| 装饰光斑 | `purple-300 #D8B4FE` / `teal-300 #5EEAD4` / `blue-300 #93C5FD`，`opacity: 0.3`、`blur-xl`、`mix-blend-multiply` |

### 1.6 毛玻璃（Glassmorphism）

| 元素 | background | blur | border | shadow |
| --- | --- | --- | --- | --- |
| 侧边栏 | `rgba(255,255,255,0.15)` | `20px` | `1px rgba(255,255,255,0.3)` | `0 12px 40px rgba(31,38,135,0.2)` |
| 卡片 | `rgba(255,255,255,0.1)` | `16px` | `1px rgba(255,255,255,0.2)` | `0 8px 32px rgba(31,38,135,0.15)` |

---

## 2. 文字样式（Typography）

### 2.1 字体族

| Token | 值 |
| --- | --- |
| `font-sans` | `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` |
| 说明 | 未加载自定义 Web 字体，使用系统 UI 无衬线字体 |
| 根字号 | `14px`（`--font-size: 14px`，Tailwind 默认基准仍按 `1rem=16px` 的 text-* 类使用） |

### 2.2 字号阶梯（实际使用）

| 类名 | px | 用途 |
| --- | --- | --- |
| `text-xs` | 12px | 标签、脚注、图例 |
| `text-sm` | 14px | 次级说明、KPI 标签、输入框 |
| `text-base` | 16px | 正文默认 |
| `text-lg` | 18px | 卡片标题、侧边栏 Logo |
| `text-xl` | 20px | 二级标题（如 Settings 分栏标题） |
| `text-2xl` | 24px | KPI 数值 |
| `text-3xl` | 30px | 页面主标题（h1） |

### 2.3 字重

| Token | 值 |
| --- | --- |
| `font-normal` | 400 |
| `font-medium` | 500 |
| `font-semibold` | 600 |

### 2.4 标题渐变字（全站 h1 统一）

```css
.page-title {
  background-image: linear-gradient(to right, #7C3AED, #0D9488);
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
}
```

---

## 3. 间距与圆角（Spacing & Radius）

### 3.1 圆角

| Token | 值 | 用途 |
| --- | --- | --- |
| `rounded-lg` | 8px | 小按钮、徽章 |
| `rounded-xl` | 12px | 按钮、输入框、导航项、图标容器 |
| `rounded-2xl` | 16px | 卡片 |
| `rounded-full` | 9999px | 头像、开关、圆点 |

### 3.2 间距（4px 基准）

| 类名 | 值 | 典型用途 |
| --- | --- | --- |
| `gap-2` / `p-2` | 8px | 按钮内图标间距 |
| `gap-3` / `px-3 py-2` | 12px | 导航项、徽章 |
| `gap-4` / `p-4` | 16px | 工具栏、侧边栏内边距 |
| `gap-6` / `p-6` | 24px | 卡片内边距、网格间距 |

### 3.3 阴影

| Token | 值 |
| --- | --- |
| `shadow-lg` | 图标容器、按钮 hover |
| `shadow-xl` | 卡片默认 |
| `shadow-2xl` | 卡片 hover |

---

## 4. 组件形态（Components）

### 4.1 侧边栏 Sidebar

- 宽度 `w-64`（256px），毛玻璃底 + `shadow-2xl`
- Logo 区：`w-10 h-10` 渐变方块（`purple-500 → teal-500`，`rounded-xl`）+ 标题 `ATS Analyzer`（`text-lg gray-800`）+ 副标题 `AI-Powered Recruitment`（`text-xs gray-600`）
- 导航项：`id / label / icon`，`px-4 py-3 rounded-xl`
  - 激活态：`bg-gradient-to-r from-purple-500 to-teal-500` + 白字 + `translate-x-1`
  - 未激活：`text-gray-700` + `hover:bg-white/20` + `hover:translate-x-1`
- 底部徽章：`bg-blue-100 text-blue-700 border-blue-200`，文案 `Demo Mode`
- 导航项 6 个：Dashboard / Resume Analyzer / Candidates / Job Postings / Analytics / Settings

### 4.2 主按钮 Button

```css
.btn-primary {
  padding: 8px 16px;
  background-image: linear-gradient(to right, #8B5CF6, #14B8A6);
  color: #fff;
  border-radius: 12px;
}
.btn-primary:hover { box-shadow: 0 10px 15px -3px rgb(0 0 0 / .1); }
```

- 图标按钮：`p-2 rounded-xl border border-white/30 hover:bg-white/30`
- 次要按钮：`px-3 py-1 bg-blue-600 text-white rounded-lg` / `bg-blue-100 text-blue-800`

### 4.3 KPI 统计卡 Stat Card

- 容器：`rounded-2xl p-6 shadow-xl` 毛玻璃，`hover:scale-105 hover:shadow-2xl`
- 顶部：`w-12 h-12` 渐变图标方块（`rounded-xl`）+ 趋势徽章（`+12%` 绿 / `-2 days` 红）
- 数值：`text-2xl gray-800`；标签：`text-sm gray-600 mt-1`

### 4.4 图表卡片 Chart Card

- 容器同 KPI 卡，标题 `text-lg gray-800`，右上角可选 `…` 图标按钮
- 图表网格线：`stroke #E5E7EB`，坐标轴字号 12px

### 4.5 输入 / 下拉 Input / Select

```css
.input {
  padding: 8px 16px;
  border-radius: 12px;
  border: 1px solid rgb(255 255 255 / .3);
  background: rgb(255 255 255 / .1);
  color: #374151;
}
.input:focus { outline: none; box-shadow: 0 0 0 2px #8B5CF6; }
```

### 4.6 开关 Toggle

- 轨道 `w-11 h-6 rounded-full`，关闭 `bg-gray-200`，开启 `bg-purple-500`
- 圆点 `after:w-5 after:h-5 after:bg-white`，开启时 `translate-x-full`

### 4.7 加载状态

- 转圈：`w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin`

### 4.8 动效 Token（Motion）

> 说明：全站动效以 **CSS transition + hover 反馈**为主，没有弹簧（spring）、没有拖拽、没有 stagger 入场。以下为从源码精确提取。

| Token | 值 | 说明 |
| --- | --- | --- |
| `duration-200` | `200ms` | 按钮、图标按钮 |
| `duration-300` | `300ms` | 卡片、导航项 |
| `easing` | `cubic-bezier(0.4, 0, 0.2, 1)` | Tailwind 默认 `ease-in-out`，全站统一 |
| `transform` | `scale` / `translateX` | 卡片缩放、导航位移 |

### 4.9 交互状态速查（Interaction States）

| 组件 | 触发 | 属性变化 | 时长 / 缓动 |
| --- | --- | --- | --- |
| KPI 统计卡 | `:hover` | `transform: scale(1.05)` + `box-shadow: shadow-2xl` | 300ms / ease-in-out |
| 导航项（未激活） | `:hover` | `transform: translateX(4px)` + `background: rgba(255,255,255,.2)` | 300ms / ease-in-out |
| 导航项（激活态） | 状态切换 | 瞬时，无 transition | — |
| 主按钮 | `:hover` | `box-shadow: shadow-lg` | 200ms / ease-in-out |
| 图标按钮 | `:hover` | `background: rgba(255,255,255,.3)` | 200ms / ease-in-out |
| 输入框 | `:focus` | `box-shadow: 0 0 0 2px #8B5CF6`（ring） | 瞬时 |
| 开关 Toggle | 状态切换 | 圆点 `translateX` 滑动 + 轨道变 `#8B5CF6` | `after:transition-all`（默认时长） |
| tab 内容切换 | 状态切换 | 内容整体替换 | 瞬时，无转场 |
| 图表 | 挂载后 | 无入场动画 | 静态渲染 |

### 4.10 关键帧动画（Keyframes）

背景光斑 `blob`（`animate-blob`，7s 无限循环）：

```css
@keyframes blob {
  0%   { transform: translate(0, 0)      scale(1);   }
  33%  { transform: translate(30px, -50px) scale(1.1); }
  66%  { transform: translate(-20px, 20px) scale(0.9); }
  100% { transform: translate(0, 0)      scale(1);   }
}
.animation-delay-2000 { animation-delay: 2s; }
.animation-delay-4000 { animation-delay: 4s; }
```

加载转圈 `spin`：

```css
.spinner { border: 2px solid #8B5CF6; border-top-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; }
```

### 4.11 已知缺口（原设计未包含）

- 无按压态（`:active`）反馈（按下变暗 / 缩放 0.98）
- 无弹簧 / 回弹动效，无拖拽、无手势
- tab 内容切换、图表均为瞬时 / 静态，无入场过渡
- 未实现 `prefers-reduced-motion` 降级
- 若需要更高阶「手感」（stagger、spring、转场），属于二次创作，非源文件既有

---

## 5. Analytics 页布局

页面结构（`Analytics & Reports`，单列容器 `space-y-6`）：

```
┌──────────────────────────────────────────────────────────────┐
│ 页头（flex，两端对齐）                                        │
│  ├─ 标题「Analytics & Reports」(h1 渐变字)                     │
│  │   └─ 副标题「Comprehensive insights …」(gray-600)           │
│  └─ 工具栏：时间范围 Select + 「Export Report」主按钮          │
├──────────────────────────────────────────────────────────────┤
│ KPI 四卡（grid lg:grid-cols-4，gap-6）                         │
│  Total Applications(+15.3%) · Average Score(+2.5%)            │
│  Excellent Candidates(+18%) · Avg. Processing Time(-0.5h)     │
├──────────────────────────────────────────────────────────────┤
│ 图表双列（grid lg:grid-cols-2）                                │
│  ├─ Score Trends（折线图，purple）                             │
│  └─ Most In-Demand Skills（横向条形图，purple→teal 渐变）       │
├──────────────────────────────────────────────────────────────┤
│ Application Volume（堆叠面积图，30 天）                         │
│  ├─ applications（purple 渐变填充）                            │
│  └─ completed（teal 渐变填充）                                  │
├──────────────────────────────────────────────────────────────┤
│ Performance Metrics（雷达/分组条，Current vs Benchmark）         │
│  ├─ Current（purple 实线）                                     │
│  └─ Benchmark（teal 虚线）                                     │
│  └─ 图例：Current Performance / Industry Benchmark            │
└──────────────────────────────────────────────────────────────┘
```

### Analytics 组件清单

| 区块 | 内容 | 关键样式 |
| --- | --- | --- |
| 页头 | 标题 + 时间筛选 + 导出按钮 | `text-3xl` 渐变标题、`rounded-xl` 控件 |
| KPI 卡 ×4 | Total Applications / Average Score / Excellent Candidates / Avg. Processing Time | 渐变图标 + 趋势徽章 |
| Score Trends | 7 日折线（avgScore） | `stroke #8B5CF6`，`strokeWidth 3` |
| Most In-Demand Skills | 前 6 技能横向条形 | 渐变 `#8B5CF6 → #14B8A6` |
| Application Volume | 30 日堆叠面积（applications + completed） | 双色渐变填充 |
| Performance Metrics | Current vs Benchmark 对比 | `#8B5CF6` vs `#14B8A6`（虚线） |

---

## 6. 全站信息架构

6 个一级视图（单页应用内 tab 切换，共享侧边栏 + `flex-1 p-6` 内容区）：

1. **Dashboard** — 欢迎页 + KPI 四卡 + Monthly Applications（面积图）+ Top Skills Detected（环形图）
2. **Resume Analyzer** — 简历上传 + 技能/经验/教育/关键词匹配评分
3. **Candidates** — 候选人列表 + 搜索筛选
4. **Job Postings** — 职位列表 + 搜索筛选
5. **Analytics** — 上述第 5 节布局
6. **Settings** — Profile / Notifications / Privacy / Data / Appearance 分栏

> 注：数据层为 Demo 模式（`http://localhost:5000/api` + mock 数据），图表由 Recharts 渲染。
