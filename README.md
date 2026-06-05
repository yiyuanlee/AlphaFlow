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
* **回测框架**: [Backtrader](https://www.backtrader.com/)
* **共享策略模块**: `alphaflow/`（回测、优化、实盘共用同一套信号逻辑）
* **数据源**: Yahoo Finance (yfinance)
* **实盘对接**: IBKR API (ib_insync) ✅ 已实现
* **配置文件**: config.yaml（参数集中管理）

### 🧠 策略逻辑 (V8.1)
采用多重过滤机制，应对高波动市场：
1. **趋势过滤**: 仅在价格高于 **200日 EMA** 的牛市环境下入场
2. **入场信号**: EMA 10 金叉 EMA 25，同时 **RSI < 65**、**ADX > 20**、**ATR > ATR均值 × 0.8**（波动率状态确认）
3. **风险管理 (核心)**:
   * **ATR 自适应止损**: 动态设置止损位，2.5 倍 ATR
   * **ATR 动态移动止盈**: 从最高点回撤 `min(3×ATR, 12%)` 时锁利离场
   * **60/40 资金池**: 指数类 (VOO/QQQ) 最多占 60%，个股最多占 40%
   * **指数权重加成**: QQQ/VOO 获得 3 倍风险预算

### 📊 回测结果（2010-01-01 ~ 2026-06-03）
**初始资金: $10,000 | 佣金: 0.1% | 标的: config.yaml 中 16 只**

**真实组合回测（共享 $10,000 资金池，60/40 配置）**

| 指标 | 数值 |
|:---:|:---:|
| **总收益率** | **+70.07%** 🟢 |
| 结束净值 | $17,007 |
| 夏普比率 | -0.03 |
| 最大回撤 | 14.62% |

**单标的独立回测（各 $10,000 独立资金池，供横向对比）**

| 标的 | 收益率 | 夏普比率 | 最大回撤 | 交易数 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+39.21%** 🟢 | -0.29 | 14.05% | 19 | 47% |
| **PLTR** | **+30.50%** 🟢 | 0.03 | 8.33% | 4 | 50% |
| **QQQ** | **+25.07%** 🟢 | -0.26 | 25.23% | 20 | 30% |
| NVDA | +12.31% | -0.85 | 15.26% | 12 | 33% |
| TSLA | +12.07% | -0.90 | 15.95% | 11 | 45% |
| CVNA | +1.83% | -1.10 | 8.44% | 7 | 14% |
| NET | +1.80% | -6.36 | 7.31% | 2 | 50% |
| SMCI | +0.74% | -2.87 | 10.20% | 9 | 44% |
| MSTR | +0.34% | -2.63 | 5.86% | 4 | 50% |
| MARA | -1.42% | -4.24 | 6.31% | 3 | 33% |
| CRWD | -2.53% | -1.86 | 10.27% | 6 | 33% |
| APP | -4.25% | -3.87 | 4.59% | 2 | 0% |
| AMD | -5.48% | -6.41 | 8.79% | 5 | 0% |
| SHOP | -14.61% | -1.70 | 17.71% | 8 | 12% |
| **平均** | **+5.97%** | — | — | — | — |

> 📌 组合回测中 PLTR、QQQ、VOO 贡献最大利润；大盘指数 (VOO/QQQ) 在单标的独立回测中依然表现最稳定。运行 `python backtest_main.py` 可复现最新结果。

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

# 5. Walk-Forward 样本外验证（训练→验证→测试，避免过拟合）
python walk_forward.py --quick

# 6. 实盘交易（需先打开 IBKR TWS/Gateway，端口 7497）
python ibkr_trading_system_v8.py  # 稳定版（日线策略）
# python ibkr_trading_system_v9.py  # 实验版（日内高频）

# 7. 自定义参数（编辑 config.yaml、walk_forward 分段）
```

---

<a name="english"></a>
## 🇺🇸 English Description

An automated quantitative trading system developed in Python, specifically optimized for **Interactive Brokers (IBKR)** small accounts ($3,000+).

### 📈 Project Overview
AlphaFlow aims to implement trend-following strategies in the US stock market while maintaining strict risk control. V8.1 features a complete live trading system, focusing on "Risk Management" and "Volatility Adaptation."

### 🛠️ Tech Stack
* **Language**: Python 3.10+
* **Backtesting**: [Backtrader](https://www.backtrader.com/)
* **Shared Strategy Module**: `alphaflow/` (same signal logic for backtest, optimize, and live)
* **Data Source**: Yahoo Finance (yfinance)
* **Live Trading**: IBKR API (ib_insync) ✅
* **Config**: config.yaml (centralized parameters)

### 🧠 Strategy Logic (V8.1)
Multiple filters to navigate high-volatility markets:
1. **Trend Filter**: Long positions only when price is above the **200-day EMA**
2. **Entry Signal**: EMA 10 golden cross EMA 25, with **RSI < 65**, **ADX > 20**, and **ATR > ATR-SMA × 0.8**
3. **Risk Management (Core)**:
   * **ATR Adaptive Stop-Loss**: Dynamic stops at 2.5x ATR
   * **ATR Dynamic Trailing Stop**: Exit at `min(3×ATR, 12%)` drawdown from peak
   * **60/40 Capital Pool**: Indices (VOO/QQQ) capped at 60%, stocks at 40%
   * **Index Weight Boost**: QQQ/VOO receive 3x risk allocation

### 📊 Backtest Results (2010-01-01 ~ 2026-06-03)
**Initial Capital: $10,000 | Commission: 0.1% | Tickers: 16 from config.yaml**

**Portfolio Backtest (shared $10,000 pool, 60/40 allocation)**

| Metric | Value |
|:---:|:---:|
| **Total Return** | **+70.07%** 🟢 |
| Final Value | $17,007 |
| Sharpe Ratio | -0.03 |
| Max Drawdown | 14.62% |

**Single-Ticker Backtest (each $10,000 independent, for comparison)**

| Ticker | Return | Sharpe | Max DD | Trades | Win Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+39.21%** 🟢 | -0.29 | 14.05% | 19 | 47% |
| **PLTR** | **+30.50%** 🟢 | 0.03 | 8.33% | 4 | 50% |
| **QQQ** | **+25.07%** 🟢 | -0.26 | 25.23% | 20 | 30% |
| NVDA | +12.31% | -0.85 | 15.26% | 12 | 33% |
| TSLA | +12.07% | -0.90 | 15.95% | 11 | 45% |
| CVNA | +1.83% | -1.10 | 8.44% | 7 | 14% |
| NET | +1.80% | -6.36 | 7.31% | 2 | 50% |
| SMCI | +0.74% | -2.87 | 10.20% | 9 | 44% |
| MSTR | +0.34% | -2.63 | 5.86% | 4 | 50% |
| MARA | -1.42% | -4.24 | 6.31% | 3 | 33% |
| CRWD | -2.53% | -1.86 | 10.27% | 6 | 33% |
| APP | -4.25% | -3.87 | 4.59% | 2 | 0% |
| AMD | -5.48% | -6.41 | 8.79% | 5 | 0% |
| SHOP | -14.61% | -1.70 | 17.71% | 8 | 12% |
| **Average** | **+5.97%** | — | — | — | — |

> 📌 In portfolio mode, PLTR, QQQ, and VOO contributed the most PnL. Run `python backtest_main.py` to reproduce the latest results.

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

# 5. Walk-forward out-of-sample validation (train → val → test)
python walk_forward.py --quick

# 6. Live trading (requires IBKR TWS/Gateway on port 7497)
python ibkr_trading_system_v8.py  # Stable daily strategy
# python ibkr_trading_system_v9.py  # Experimental intraday

# 7. Customize parameters (edit config.yaml, walk_forward windows)
```

---

## 📂 文件结构

```
AlphaFlow/
├── alphaflow/                # ⭐ 共享策略模块（回测/优化/实盘共用）
│   ├── config.py             # 配置加载与类型化参数
│   ├── indicators.py         # 指标计算（EMA/RSI/ADX/ATR）
│   ├── signals.py            # 入场/离场/仓位计算逻辑
│   ├── strategy.py           # Backtrader 策略实现
│   ├── backtest.py           # 回测引擎
│   ├── grid.py               # 参数网格搜索
│   ├── walkforward.py        # Walk-Forward 验证核心
│   └── data.py               # 数据下载
├── backtest_main.py          # ⭐ 主回测入口（组合 + 单标的）
├── walk_forward.py           # ⭐ Walk-Forward 样本外验证
├── optimize.py               # 参数优化框架（网格搜索）
├── ibkr_trading_system_v8.py # ⭐ 实盘交易系统 V8.1（稳定版）
├── ibkr_trading_system_v9.py # 实盘 V9（日内高频，experimental）
├── diagnose.py               # 策略信号诊断工具
├── debug_signals.py          # 信号逐一扫描调试脚本
├── check_data.py             # 数据下载格式检查工具
├── test_ibkr.py              # IBKR 连接测试
├── config.yaml               # 全局参数配置
├── requirements.txt          # Python 依赖
├── AlphaFlow-Strategy-Document.md
├── CHANGELOG.md
├── archive/                  # 历史版本（已废弃）
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