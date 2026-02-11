# 功能文档

股票舆情策略分析系统 —— 当前已实现功能的完整说明。

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────┐
│                   Electron 桌面客户端                      │
│  ┌──────────┐  ┌──────────────────────────────────────┐  │
│  │  侧边栏   │  │            主内容区                    │  │
│  │ 自选股配置 │  │  分析概览表 / K线图 / 舆情图 / 新闻    │  │
│  │ 权重调节  │  │                                      │  │
│  │ 开始分析  │  │                                      │  │
│  └──────────┘  └──────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP (127.0.0.1:8321)
                        ▼
┌─────────────────────────────────────────────────────────┐
│              FastAPI Python 后端 (server.py)              │
│                                                         │
│  新闻采集 → NLP 情感分析 → 技术指标 → 信号生成 → 仓位建议  │
└─────────────────────────────────────────────────────────┘
```

---

## 二、桌面客户端（Electron + React）

目录：`desktop/`

### 2.1 应用框架
- **Electron 主进程**：管理窗口、启动/停止 Python 后端、健康检查
- **React 前端**：Vite 构建，TailwindCSS 样式，TypeScript 类型安全
- **关键文件**：`desktop/electron/main.ts`、`desktop/src/App.tsx`

### 2.2 侧边栏（Sidebar）
- 美股代码输入（每行一个，如 AAPL、TSLA）
- A股代码输入（每行一个，如 600519、000858）
- 新闻回溯天数滑块（1-14 天）
- 策略权重调节：舆情权重、技术面权重、新闻量权重（自动归一化）
- 开始分析按钮（分析中显示加载状态）
- **关键文件**：`desktop/src/components/Sidebar.tsx`

### 2.3 分析概览表（SummaryTable）
- 显示所有股票的分析结果汇总
- 列：代码、市场（美股/A股）、舆情得分、技术面得分、新闻量得分、综合得分、信号、仓位、新闻数
- 点击行切换下方详情卡片
- **关键文件**：`desktop/src/components/SummaryTable.tsx`

### 2.4 股票详情卡片（StockCard）
- 顶部：股票代码、市场标签、信号徽章
- 指标行：舆情、技术面、新闻量、建议仓位
- 四个 Tab 页：
  - **K线图**：Plotly.js 交互式蜡烛图 + 成交量柱状图，标注信号
    - **红绿色调**：A股红涨绿跌（中国惯例），美股绿涨红跌（国际惯例）
    - **多周期切换**：分时（1分钟折线）、五日（5分钟K线）、日K、周K、月K、分钟（15分钟K线）
    - **中文化**：日期格式、悬浮提示、工具栏文字均为中文
    - **交互**：鼠标滚轮缩放、拖拽平移、工具栏快捷操作
  - **舆情走势**：情感得分时间线，标记正面/负面/中性阈值线
  - **新闻列表**：按时间排序，彩色情感标记 + 得分；点击可展开查看新闻摘要、情感标签、详细得分和原文链接
  - **评分明细**：RSI、MACD、均线趋势、技术面综合、舆情、新闻量各项得分
- **关键文件**：`desktop/src/components/StockCard.tsx`、`CandlestickChart.tsx`、`SentimentChart.tsx`、`NewsFeed.tsx`

### 2.5 自选股功能
- 分析结果表每行左侧有星标按钮，点击可添加/移除自选
- 侧边栏分为「分析配置」和「自选股」两个 Tab 页
- 自选股 Tab 按美股/A股分组展示，每项显示代码、市场标签和删除按钮
- 「分析自选股」按钮：使用当前策略参数一键分析所有自选股
- 「导入到分析配置」按钮：将自选股代码填入配置区输入框
- 数据通过 localStorage 持久化，应用重启后保留
- **关键文件**：`desktop/src/hooks/useWatchlist.ts`、`desktop/src/components/Sidebar.tsx`、`desktop/src/components/SummaryTable.tsx`

### 2.6 信号徽章（SignalBadge）
- 根据信号类型显示不同颜色背景
- 显示中文信号名称 + 数值得分
- 信号类型：强烈买入、买入、持有、卖出、强烈卖出
- **关键文件**：`desktop/src/components/SignalBadge.tsx`

### 2.6 加载与错误处理
- 启动时显示"正在启动 Python 后端"加载动画
- 分析中显示实时计时器和阶段提示（获取新闻 → NLP 分析 → 技术指标 → 模型下载）
- API 请求超时机制（普通 10 秒，分析 10 分钟）
- 连接失败、分析失败、空代码等场景均有中文错误提示
- **关键文件**：`desktop/src/App.tsx`、`desktop/src/api.ts`

### 2.7 应用菜单
- 编辑菜单：撤销、重做、剪切、复制、粘贴、全选
- 视图菜单：刷新、强制刷新、缩放控制、全屏
- 开发菜单：控制台开关（快捷键 Cmd+Option+I / Ctrl+Shift+I）
- 窗口菜单：最小化、缩放、关闭
- 启动时不再自动打开 DevTools，需通过「开发 → 控制台」手动打开
- **关键文件**：`desktop/electron/main.ts`

### 2.8 界面语言
- 全部界面文本已中文化（标题、标签、按钮、图表、错误提示、菜单等）

---

## 三、Python 后端（FastAPI）

文件：`server.py`

### 3.1 REST API 接口
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查，返回服务状态和模型加载状态 |
| `/api/config` | GET | 获取当前配置 |
| `/api/config` | POST | 更新配置 |
| `/api/analyze` | POST | 批量分析股票（传入股票列表和参数） |
| `/api/analyze/{ticker}` | POST | 分析单只股票 |
| `/api/price` | POST | 获取多周期行情数据（ticker/market/interval/period_days） |

### 3.2 模型预加载
- 服务启动后在后台线程预加载 FinBERT 和中文 NLP 模型
- 不阻塞健康检查接口
- **关键文件**：`server.py`

### 3.3 CORS 支持
- 允许所有来源跨域请求（开发模式下 Vite 和 Electron 使用不同端口）

---

## 四、策略引擎核心

目录：`src/`

### 4.1 新闻采集
- **美股**：Finnhub API（需 API Key）+ Yahoo Finance（免费，作为补充）
- **A股**：akshare 东方财富个股新闻
- 自动去重（按标题），按发布时间排序
- **关键文件**：`src/data/news_us.py`、`src/data/news_cn.py`

### 4.2 情感分析（NLP）
- **英文**：ProsusAI/finbert 金融领域预训练模型
- **中文**：uer/roberta-base-finetuned-chinanews-chinese
- 自动检测语言（CJK 字符占比 >30% 判定为中文）
- 输出得分范围 [-1, 1]：正面 >0.3，负面 <-0.3，中性居中
- 模型单例缓存，首次加载后复用
- **关键文件**：`src/analysis/sentiment.py`

### 4.3 行情数据
- **美股**：yfinance，支持 1m/5m/15m/日/周/月 多粒度，默认 120 天日线
- **A股**：akshare（stock_zh_a_hist / stock_zh_a_hist_min_em），前复权，支持分钟/日/周/月
- 列标准化为 open/high/low/close/volume
- **关键文件**：`src/data/price_us.py`、`src/data/price_cn.py`

### 4.4 技术指标
- RSI（14 周期）— 用于综合评分
- RSI（6 周期）— 用于口诀规则引擎
- MACD（12/26/9）+ 金叉/死叉自动检测 + 0 轴位置判断
- 均线（MA5/MA10/MA20/MA60 趋势判断）
- 布林带
- 各指标独立评分后加权合成技术面综合得分
- **关键文件**：`src/analysis/technical.py`

### 4.5 口诀规则引擎
- 基于经典短线技术分析口诀，结合 RSI6 和 MACD 状态生成操作建议
- 规则：
  - RSI6 <= 30 + MACD 金叉 → 短线买入
  - RSI6 >= 70 + MACD 死叉 → 短线卖出
  - 0 轴上金叉 → 大胆做；0 轴下金叉 → 少碰
  - RSI6 在 30-70 震荡区间且无交叉 → 观望不操作
- 输出结构：`[{action, rule, detail}]`，支持多条建议并行
- **关键文件**：`src/analysis/technical.py`（`generate_rule_advice` 函数）

### 4.5 信号生成
- 综合评分 = 舆情得分 × 舆情权重 + 技术面得分 × 技术权重 + 新闻量得分 × 新闻量权重
- 信号映射：>0.6 强烈买入，0.3~0.6 买入，-0.3~0.3 持有，-0.6~-0.3 卖出，<-0.6 强烈卖出
- 仓位建议：根据信号强度线性映射到最大仓位比例
- **关键文件**：`src/analysis/signal.py`、`src/strategy/strategy.py`

### 4.6 策略引擎（StrategyEngine）
- 编排整个分析流程：新闻采集 → 情感分析 → 行情获取 → 技术指标 → 信号生成 → 仓位计算
- 支持单只分析和批量分析
- 每只股票独立 try/catch，单只失败不影响其他
- **关键文件**：`src/strategy/strategy.py`

---

## 五、模拟交易系统

### 5.1 交易费用引擎
- **A 股**：佣金万 2.5（最低 5 元）+ 印花税 0.05%（仅卖出）+ 过户费 0.001%
- **美股**：零佣金（可配置为 $0.005/股）
- A 股涨跌停检查：主板 ±10%，创业板/科创板 ±20%
- A 股 T+1 规则：当日买入次日方可卖出
- **关键文件**：`src/trading/fees.py`

### 5.2 持仓管理
- 支持设置初始资金（默认 10 万）
- 跟踪现金余额、持仓字典、加权平均成本
- 计算总资产、浮动盈亏、已实现盈亏、胜率等
- 数据持久化至 `~/.stock-strategy/portfolio.json`
- **关键文件**：`src/trading/portfolio.py`

### 5.3 交易引擎
- **手动交易**：买入/卖出，执行前检查余额、持仓、T+1、涨跌停
- **信号驱动交易**：根据分析信号自动计算仓位比例，BUY/STRONG_BUY 买入、SELL/STRONG_SELL 卖出、HOLD 不操作
- **关键文件**：`src/trading/trade_engine.py`

### 5.4 策略回测
- 输入：股票代码、市场、起止日期、初始资金
- 流程：获取历史价格 → 逐日滚动计算技术指标 → 生成口诀规则信号 → 模拟交易 → 记录净值
- 输出：交易记录、净值曲线、买卖点、关键指标（总收益率、年化收益率、最大回撤、夏普比率、胜率、盈亏比）
- **关键文件**：`src/trading/backtest.py`

### 5.5 交易 API 接口
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/portfolio` | GET | 获取当前持仓和汇总（自动获取最新价格计算浮动盈亏）|
| `/api/portfolio/reset` | POST | 重置账户（设定初始资金）|
| `/api/trade` | POST | 执行手动买卖（ticker/market/action/shares/price）|
| `/api/trade/signal` | POST | 根据信号一键交易（ticker/market/signal/score/pct/price）|
| `/api/trades` | GET | 获取交易历史（按时间倒序）|
| `/api/backtest` | POST | 运行历史回测（ticker/market/start_date/end_date/capital）|

### 5.6 交易界面（前端）
- **交易弹窗**（TradeModal）：买入/卖出切换、价格和股数输入、实时费用预估、一键跟单模式
- **持仓总览面板**（PortfolioDashboard）：统计卡片 + 持仓表格 + 交易记录 + 重置账户
- **交易记录列表**（TradeHistory）：按时间倒序，支持按股票/方向/来源筛选
- **回测面板**（BacktestPanel）：配置表单 + 指标卡片 + 净值曲线 + K 线买卖点 + 交易记录
- **收益曲线图**（PnLChart）：Plotly 折线图，含基准线
- **关键文件**：`desktop/src/components/TradeModal.tsx`、`PortfolioDashboard.tsx`、`TradeHistory.tsx`、`BacktestPanel.tsx`、`PnLChart.tsx`

### 5.7 视图导航
- 侧边栏顶部新增三栏导航：分析 / 模拟交易 / 回测
- 主区域根据当前视图切换内容
- StockCard 标题栏新增「交易」和「回测」快捷按钮
- **关键文件**：`desktop/src/App.tsx`、`desktop/src/components/Sidebar.tsx`、`StockCard.tsx`

---

## 六、配置管理

- 配置文件：`config.yaml`（可选，不存在则使用默认值）
- 默认美股：AAPL、TSLA、NVDA、MSFT、GOOGL
- 默认A股：600519、000858、601318、000001、300750
- 可配置项：Finnhub API Key、自选股列表、策略权重、最大仓位、止损线、新闻回溯天数
- **关键文件**：`src/config.py`、`config.yaml`

---

## 七、Electron 启动管理

- 自动检测并清理占用 8321 端口的僵尸进程
- 支持复用已运行的 Python 后端实例
- 多路径 Python 查找：venv/bin/python3 → python → python3.12 等
- 启动失败时显示详细的 Python 错误信息
- 健康检查超时 60 秒
- 进程退出时自动清理 Python 后端（SIGTERM → SIGKILL）
- **关键文件**：`desktop/electron/main.ts`
