# StockEmotion Agent Teams 配置

## 项目概述

StockEmotion 是一个基于新闻情感分析的股票策略系统，包含 Python 后端和 Electron + React 前端。

## 团队角色定义

### Lead Agent（主导 Agent）
- 负责任务分解、分配和最终汇总
- 理解整体架构：Python 后端 + Electron/React 前端
- 协调各 Teammate 之间的工作

### Teammate: Backend（后端开发）
- 负责 `stock-sentiment-strategy/src/` 下的 Python 代码
- 涵盖：数据采集（data/）、情感分析（analysis/）、策略引擎（strategy/）、模拟交易（trading/）
- 相关入口：`server.py`（FastAPI）、`main.py`（CLI）、`app.py`（Streamlit）
- 技术栈：FastAPI, transformers, pandas, yfinance, akshare

### Teammate: Frontend（前端开发）
- 负责 `stock-sentiment-strategy/desktop/` 下的前端代码
- 涵盖：React 组件（src/components/）、hooks、样式、API 调用
- 技术栈：Electron, React, TypeScript, Vite, TailwindCSS, Plotly.js

### Teammate: Testing & Review（测试与审查）
- 负责代码审查、测试编写、bug 排查
- 覆盖前后端的测试用例
- 关注 API 接口一致性（前后端联调）

## 项目结构

```
stock-sentiment-strategy/
├── app.py                  # Streamlit Web 入口
├── main.py                 # CLI 入口
├── server.py               # FastAPI 后端服务（端口 8321）
├── config.yaml             # 主配置文件
├── requirements.txt        # Python 依赖
├── desktop/                # Electron 桌面客户端
│   ├── electron/           # Electron 主进程
│   ├── src/                # React 前端源码
│   │   ├── components/     # React 组件
│   │   ├── hooks/          # 自定义 hooks
│   │   └── styles/         # 样式文件
│   └── package.json
└── src/                    # Python 策略引擎
    ├── analysis/           # 情感分析、技术指标、信号
    ├── data/               # 新闻与行情数据采集
    ├── output/             # CLI 报告、Web 输出
    ├── strategy/           # 策略引擎
    └── trading/            # 模拟交易、回测
```

## 使用示例

在 Claude Code 中可以这样使用 Agent Teams：

1. **跨层功能开发**：
   "创建一个 agent team，一个 teammate 负责后端新增 API 接口，一个负责前端对接该接口"

2. **并行代码审查**：
   "创建 agent team 审查最近的代码变更，一个 teammate 审查 Python 后端，一个审查 React 前端"

3. **Bug 调试**：
   "创建 agent team 调试数据获取问题，一个 teammate 检查后端 API，一个检查前端请求"

4. **新功能开发**：
   "创建 agent team 开发实时推送功能，后端 teammate 用 WebSocket，前端 teammate 做 UI 展示"
