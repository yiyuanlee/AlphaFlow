# AlphaFlow: IBKR Quant Trading System

[中文](#chinese) | [English](#english)

---

<a name="chinese"></a>
## 🇨🇳 中文说明

这是一个基于 Python 开发的自动化量化交易系统，专门针对 **Interactive Brokers (IBKR)** 小额账户（$3,000+）进行优化。

### 📈 项目概览
AlphaFlow 旨在利用量化手段，在控制风险的前提下，实现美股市场的趋势跟踪交易。V8.1 完成实盘交易系统，核心重点在于"风险控制"与"波动率自适应"。

### 🛠️ 技术栈
* **语言**: Python 3.10+
* **回测框架**: [Backtrader](https://www.backtrader.com/) + 自定义 V8 引擎
* **数据源**: Yahoo Finance (yfinance)
* **实盘对接**: IBKR API (ib_insync) ✅ 已实现
* **配置文件**: config.yaml（参数集中管理）

### 🧠 策略逻辑 (V8.1)
采用多重过滤机制，应对高波动市场：
1. **趋势过滤**: 仅在价格高于 **200日均线** 的牛市环境下入场
2. **入场信号**: EMA 10 日线上穿 EMA 25 日线，同时 **RSI < 65** 且 **ADX > 20**（趋势强度确认）
3. **风险管理 (核心)**:
   * **ATR 自适应止损**: 动态设置止损位，2.5 倍 ATR 自动适应市场波动
   * **移动止盈 (Trailing Stop)**: 从持仓最高点回撤 12% 时自动锁利离场
   * **指数权重加成**: QQQ/VOO 获得 3 倍风险预算

### 📊 多标的回测结果（2022-01-01 ~ 2026-03-20）
**初始资金: $3,000 | 佣金: 0.1%**

| 标的 | 收益率 | 夏普比率 | 最大回撤 | 交易数 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+28.33%** 🟢 | **0.59** | 5.32% | 3 | 100% |
| **QQQ** | **+9.34%** 🟢 | **0.26** | 6.68% | 2 | 50% |
| GOOGL | +4.18% | -0.10 | 2.63% | 2 | 100% |
| TSLA | +0.12% | -3.71 | 0.79% | 1 | 100% |
| NVDA | -0.70% | -1.86 | 2.53% | 3 | 33% |
| AMD | -1.63% | -2.03 | 2.35% | 2 | 0% |
| AAPL | -6.00% | -1.46 | 6.19% | 4 | 0% |
| MSFT | 0.00% | 0.0 | 0.00% | 0 | — |
| **平均** | **+4.21%** | **-1.04** | **3.31%** | **17** | — |

> 📌 **策略更适合大盘指数**（VOO/QQQ）：趋势跟踪策略在具有明确趋势的大盘指数上表现更稳定，个股受突发新闻影响大，信号频繁失效。

### 🚀 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/yiyuanlee/AlphaFlow.git
cd AlphaFlow

# 2. 安装依赖（推荐创建虚拟环境）
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt

# 3. 运行回测（输出汇总表格 + Equity Curve）
python backtest_main.py

# 4. 参数优化（网格搜索，自动保存最优参数到 optimal_params.yaml）
python optimize.py

# 5. 实盘交易（需先打开 IBKR TWS/Gateway，端口 7497）
python ibkr_trading_system_v8.py  # 稳定版（日线策略）
# python ibkr_trading_system_v9.py  # 实验版（日内高频）

# 6. 自定义参数（编辑 config.yaml）
```

---

<a name="english"></a>
## 🇺🇸 English Description

An automated quantitative trading system developed in Python, specifically optimized for **Interactive Brokers (IBKR)** small accounts ($3,000+).

### 📈 Project Overview
AlphaFlow aims to implement trend-following strategies in the US stock market while maintaining strict risk control. V8.1 features a complete live trading system, focusing on "Risk Management" and "Volatility Adaptation."

### 🛠️ Tech Stack
* **Language**: Python 3.10+
* **Backtesting**: [Backtrader](https://www.backtrader.com/) + custom V8 engine
* **Data Source**: Yahoo Finance (yfinance)
* **Live Trading**: IBKR API (ib_insync) ✅
* **Config**: config.yaml (centralized parameters)

### 🧠 Strategy Logic (V8.1)
Multiple filters to navigate high-volatility markets:
1. **Trend Filter**: Long positions only when price is above the **200-day EMA**
2. **Entry Signal**: EMA 10 crosses above EMA 25, with **RSI < 65** and **ADX > 20** (trend strength confirmation)
3. **Risk Management (Core)**:
   * **ATR Adaptive Stop-Loss**: Dynamic stops at 2.5x ATR
   * **Trailing Stop**: Auto-exit when price drops 12% from peak
   * **Index Weight Boost**: QQQ/VOO receive 3x risk allocation

### 📊 Multi-Asset Backtest Results (2022-01-01 ~ 2026-03-20)
**Initial Capital: $3,000 | Commission: 0.1%**

| Ticker | Return | Sharpe | Max DD | Trades | Win Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+28.33%** 🟢 | **0.59** | 5.32% | 3 | 100% |
| **QQQ** | **+9.34%** 🟢 | **0.26** | 6.68% | 2 | 50% |
| GOOGL | +4.18% | -0.10 | 2.63% | 2 | 100% |
| TSLA | +0.12% | -3.71 | 0.79% | 1 | 100% |
| NVDA | -0.70% | -1.86 | 2.53% | 3 | 33% |
| AMD | -1.63% | -2.03 | 2.35% | 2 | 0% |
| AAPL | -6.00% | -1.46 | 6.19% | 4 | 0% |
| MSFT | 0.00% | 0.0 | 0.00% | 0 | — |
| **Average** | **+4.21%** | **-1.04** | **3.31%** | **17** | — |

> 📌 **Strategy is better suited for broad-market indices** (VOO/QQQ): Trend-following strategies perform more consistently on indices with clear trends, while individual stocks are more vulnerable to news-driven volatility.

### 🚀 Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/yiyuanlee/AlphaFlow.git
cd AlphaFlow

# 2. Install dependencies (recommended: create a venv)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt

# 3. Run backtest (summary table + equity curve)
python backtest_main.py

# 4. Parameter optimization (grid search, saves to optimal_params.yaml)
python optimize.py

# 5. Live trading (requires IBKR TWS/Gateway on port 7497)
python ibkr_trading_system_v8.py  # Stable daily strategy
# python ibkr_trading_system_v9.py  # Experimental intraday

# 6. Customize parameters (edit config.yaml)
```

---

## 📂 文件结构

```
AlphaFlow/
├── backtest_main.py          # ⭐ 主回测入口（真实组合回测，60/40 配置）
├── optimize.py               # 参数优化框架（网格搜索，自动保存最优参数）
├── ibkr_trading_system_v8.py # ⭐ 实盘交易系统 V8.1（稳定版，推荐使用）
├── ibkr_trading_system_v9.py # 实盘交易系统 V9（日内高频，experimental）
├── diagnose.py               # 策略信号诊断工具（排查为什么没有交易信号）
├── debug_signals.py          # 信号逐一扫描调试脚本
├── check_data.py             # 数据下载格式检查工具
├── test_ibkr.py              # IBKR 连接测试
├── config.yaml               # 全局参数配置（回测与实盘共用）
├── requirements.txt          # Python 依赖
├── AlphaFlow-Strategy-Document.md  # 策略详细文档
├── CHANGELOG.md              # 版本变更日志
├── archive/                  # 历史版本（已废弃，仅供参考）
│   ├── backtest_multi.py
│   ├── backtest_pro.py
│   └── backtest_v4.0.py
└── README.md
```

---

## 📅 开发路线图 / Development Roadmap
- [x] **V1.0**: 基础均线交叉策略 / Basic Moving Average Crossover
- [x] **V2.0**: SMA 200 过滤 + 固定止损 / SMA 200 Filter & Fixed Stop-loss
- [x] **V3.0**: ATR 动态止损 + 移动止盈 / ATR Volatility & Trailing Stop
- [x] **V4.0**: 多标的组合回测 / Multi-asset Portfolio Backtest
- [x] **V5.0**: IBKR 模拟账户实盘测试 / IBKR Paper Trading
- [x] **V6.0**: 参数配置化管理 / Parameter Optimization via config.yaml
- [x] **V7.0**: 策略优化（RSI确认 + ADX趋势强度）/ Strategy Optimization
- [x] **V8.0**: 实盘交易系统 / Live Trading System
- [x] **V8.1**: 参数优化框架 + 自动化参数搜索 / Auto Parameter Tuning
- [x] **V9.0**: 日内交易模式 + 高频扫描（experimental）/ Intraday Mode (experimental)

## ⚠️ Disclaimer / 免责声明
This project is for academic and technical discussion only. It does NOT constitute investment advice. Trading involves significant risk. The author is not responsible for any financial losses incurred from using this software.
本项目仅供学术研究和技术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。使用本程序产生的任何盈亏由使用者自行承担。