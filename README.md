# AlphaFlow: IBKR Quant Trading System

[中文](#chinese) | [English](#english)

---

<a name="chinese"></a>
## 🇨🇳 中文说明

这是一个基于 Python 开发的自动化量化交易系统，面向 **Interactive Brokers (IBKR)** 账户；当前回测与 Walk-forward 基准资金为 **$50,000**。

### 📈 项目概览
AlphaFlow 旨在利用量化手段，在控制风险的前提下，实现美股市场的趋势跟踪交易。V8.1 完成实盘交易系统，核心重点在于"风险控制"与"波动率自适应"。

### 🛠️ 技术栈
* **语言**: Python 3.10+
* **回测框架**: [Backtrader](https://www.backtrader.com/)
* **共享策略模块**: `alphaflow/`（回测、优化、实盘共用同一套信号逻辑）
* **数据源**: Yahoo Finance (yfinance)
* **实盘对接**: IBKR API (ib_insync) ✅ 已实现
* **配置文件**: config.yaml（参数集中管理）

### 🧠 双策略架构（指数 + 热门股）

| 策略 | 脚本 | 资金池 | 标的来源 | 持仓周期 |
|------|------|--------|---------|---------|
| **指数趋势** | `ibkr_trading_system_v8.py` | 60% (`alloc_index`) | 固定 QQQ / VOO | 数日~数月 |
| **热门股短线** | `ibkr_hot_stocks.py` | 40% (`alloc_stock`) | IBKR 扫描器每日涨幅榜 | **≤ 5 天** |

热门股策略不绑定固定个股名单，每 15 分钟扫描 `TOP_PERC_GAIN`，满足 EMA 金叉 + VWAP 上方 + RSI 过滤后入场，到期或止盈/止损离场。

### 🧠 指数策略逻辑 (V8.1)
采用多重过滤机制，应对高波动市场：
1. **趋势过滤**: 仅在价格高于 **200日 EMA** 的牛市环境下入场
2. **入场信号**: EMA 10 金叉 EMA 25，同时 **RSI < 65**、**ADX > 20**、**ATR > ATR均值 × 0.8**（波动率状态确认）
3. **风险管理 (核心)**:
   * **ATR 自适应止损**: 动态设置止损位，2.5 倍 ATR
   * **ATR 动态移动止盈**: 从最高点回撤 `min(3×ATR, 12%)` 时锁利离场
   * **60/40 资金池**: 指数类 (VOO/QQQ) 最多占 60%，个股最多占 40%
   * **指数权重加成**: QQQ/VOO 获得 3 倍风险预算

### 📊 回测结果（2010-01-01 ~ 2026-06-03）
**初始资金: $50,000 | 佣金: 0.1% | 标的: config.yaml 中 17 只**

**真实组合回测（共享 $50,000 资金池，60/40 配置）**

| 指标 | 数值 |
|:---:|:---:|
| **总收益率** | **+71.57%** 🟢 |
| 结束净值 | $85,784 |
| 夏普比率 | -0.02 |
| 最大回撤 | 14.68% |

**单标的独立回测（各 $50,000 独立资金池，供横向对比）**

| 标的 | 收益率 | 夏普比率 | 最大回撤 | 交易数 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+39.71%** 🟢 | -0.28 | 14.16% | 19 | 47% |
| **PLTR** | **+30.86%** 🟢 | 0.04 | 8.41% | 4 | 50% |
| **QQQ** | **+25.34%** 🟢 | -0.26 | 25.31% | 20 | 30% |
| NVDA | +12.25% | -0.85 | 15.40% | 12 | 33% |
| TSLA | +12.05% | -0.90 | 16.00% | 11 | 45% |
| XYZ | +2.26% | -8.55 | 7.29% | 4 | 50% |
| CVNA | +1.84% | -1.08 | 8.53% | 7 | 14% |
| NET | +1.84% | -6.21 | 7.43% | 2 | 50% |
| SMCI | +0.74% | -2.87 | 10.20% | 9 | 44% |
| MSTR | +0.17% | -2.61 | 6.04% | 4 | 50% |
| MARA | -1.38% | -4.04 | 6.57% | 3 | 33% |
| CRWD | -3.08% | -1.77 | 10.68% | 6 | 33% |
| APP | -4.97% | -3.31 | 5.36% | 2 | 0% |
| AMD | -5.55% | -6.35 | 8.85% | 5 | 0% |
| SHOP | -14.68% | -1.69 | 17.78% | 8 | 12% |
| **平均** | **+5.73%** | — | — | — | — |

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

# 6. 指标对齐验证（Backtrader 回测 vs alphaflow.indicators 实盘，QQQ/VOO 应 100% 通过）
python verify_indicators.py

# 7. 实盘交易（需先打开 IBKR TWS/Gateway 模拟盘 7497）
python ibkr_trading_system_v8.py   # 指数池：QQQ/VOO（client_id=1）
python ibkr_hot_stocks.py          # 个股池：每日热门股（client_id=2）

# 8. 自定义参数（config.yaml → index_tickers / hot_trading）
```

---

<a name="english"></a>
## 🇺🇸 English Description

An automated quantitative trading system developed in Python for **Interactive Brokers (IBKR)** accounts; backtest and walk-forward baseline capital is **$50,000**.

### 📈 Project Overview
AlphaFlow aims to implement trend-following strategies in the US stock market while maintaining strict risk control. V8.1 features a complete live trading system, focusing on "Risk Management" and "Volatility Adaptation."

### 🛠️ Tech Stack
* **Language**: Python 3.10+
* **Backtesting**: [Backtrader](https://www.backtrader.com/)
* **Shared Strategy Module**: `alphaflow/` (same signal logic for backtest, optimize, and live)
* **Data Source**: Yahoo Finance (yfinance)
* **Live Trading**: IBKR API (ib_insync) ✅
* **Config**: config.yaml (centralized parameters)

### 🧠 Dual-Strategy Architecture (Index + Hot Stocks)

| Strategy | Script | Capital Pool | Universe | Max Hold |
|----------|--------|--------------|----------|----------|
| **Index trend** | `ibkr_trading_system_v8.py` | 60% | QQQ / VOO | days–months |
| **Hot momentum** | `ibkr_hot_stocks.py` | 40% | IBKR daily scanner | **≤ 5 days** |

### 🧠 Index Strategy Logic (V8.1)
Multiple filters to navigate high-volatility markets:
1. **Trend Filter**: Long positions only when price is above the **200-day EMA**
2. **Entry Signal**: EMA 10 golden cross EMA 25, with **RSI < 65**, **ADX > 20**, and **ATR > ATR-SMA × 0.8**
3. **Risk Management (Core)**:
   * **ATR Adaptive Stop-Loss**: Dynamic stops at 2.5x ATR
   * **ATR Dynamic Trailing Stop**: Exit at `min(3×ATR, 12%)` drawdown from peak
   * **60/40 Capital Pool**: Indices (VOO/QQQ) capped at 60%, stocks at 40%
   * **Index Weight Boost**: QQQ/VOO receive 3x risk allocation

### 📊 Backtest Results (2010-01-01 ~ 2026-06-03)
**Initial Capital: $50,000 | Commission: 0.1% | Tickers: 17 from config.yaml**

**Portfolio Backtest (shared $50,000 pool, 60/40 allocation)**

| Metric | Value |
|:---:|:---:|
| **Total Return** | **+71.57%** 🟢 |
| Final Value | $85,784 |
| Sharpe Ratio | -0.02 |
| Max Drawdown | 14.68% |

**Single-Ticker Backtest (each $50,000 independent, for comparison)**

| Ticker | Return | Sharpe | Max DD | Trades | Win Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **VOO** | **+39.71%** 🟢 | -0.28 | 14.16% | 19 | 47% |
| **PLTR** | **+30.86%** 🟢 | 0.04 | 8.41% | 4 | 50% |
| **QQQ** | **+25.34%** 🟢 | -0.26 | 25.31% | 20 | 30% |
| NVDA | +12.25% | -0.85 | 15.40% | 12 | 33% |
| TSLA | +12.05% | -0.90 | 16.00% | 11 | 45% |
| XYZ | +2.26% | -8.55 | 7.29% | 4 | 50% |
| CVNA | +1.84% | -1.08 | 8.53% | 7 | 14% |
| NET | +1.84% | -6.21 | 7.43% | 2 | 50% |
| SMCI | +0.74% | -2.87 | 10.20% | 9 | 44% |
| MSTR | +0.17% | -2.61 | 6.04% | 4 | 50% |
| MARA | -1.38% | -4.04 | 6.57% | 3 | 33% |
| CRWD | -3.08% | -1.77 | 10.68% | 6 | 33% |
| APP | -4.97% | -3.31 | 5.36% | 2 | 0% |
| AMD | -5.55% | -6.35 | 8.85% | 5 | 0% |
| SHOP | -14.68% | -1.69 | 17.78% | 8 | 12% |
| **Average** | **+5.73%** | — | — | — | — |

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

# 6. Indicator parity check (Backtrader backtest vs alphaflow.indicators live; QQQ/VOO should pass 100%)
python verify_indicators.py

# 7. Live trading (IBKR TWS/Gateway paper port 7497)
python ibkr_trading_system_v8.py   # Index sleeve: QQQ/VOO
python ibkr_hot_stocks.py          # Stock sleeve: daily hot tickers

# 8. Customize parameters (config.yaml → index_tickers / hot_trading)
```

---

## 📂 文件结构

```
AlphaFlow/
├── alphaflow/                # ⭐ 共享策略模块（回测/优化/实盘共用）
│   ├── config.py             # 配置加载与类型化参数
│   ├── indicators.py         # 指标计算（与 Backtrader 对齐的 EMA/Wilder）
│   ├── parity.py             # Backtrader vs 实盘指标对齐检查
│   ├── signals.py            # 入场/离场/仓位计算逻辑
│   ├── strategy.py           # Backtrader 策略实现
│   ├── backtest.py           # 回测引擎
│   ├── grid.py               # 参数网格搜索
│   ├── walkforward.py        # Walk-Forward 验证核心
│   └── data.py               # 数据下载
├── backtest_main.py          # ⭐ 主回测入口（组合 + 单标的）
├── walk_forward.py           # ⭐ Walk-Forward 样本外验证
├── verify_indicators.py      # 指标对齐验证 CLI
├── tests/                    # pytest（含 test_indicator_parity.py）
├── optimize.py               # 参数优化框架（网格搜索）
├── ibkr_trading_system_v8.py # ⭐ 指数池实盘（QQQ/VOO，60%资金）
├── ibkr_hot_stocks.py        # ⭐ 热门股短线（扫描器，40%资金，≤5天）
├── ibkr_trading_system_v9.py # 兼容入口 → ibkr_hot_stocks.py
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
- [x] **V9.0**: 热门股短线策略（扫描器动态标的，≤5天持仓）/ Hot-Stock Momentum Sleeve

## ⚠️ Disclaimer / 免责声明
This project is for academic and technical discussion only. It does NOT constitute investment advice. Trading involves significant risk. The author is not responsible for any financial losses incurred from using this software.
本项目仅供学术研究和技术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。使用本程序产生的任何盈亏由使用者自行承担。