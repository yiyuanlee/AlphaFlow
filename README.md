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
* **实盘对接**: IBKR API (ib_async) ✅ 已实现
* **配置文件**: config.yaml（参数集中管理）

### 🧠 无人值守架构（V11：模拟盘安全试点）

| 策略 | 脚本 | client_id | 标的 | 说明 |
|------|------|-----------|------|------|
| **V11 无人值守模拟盘** | `alphaflow options run --profile paper_qqq_cc --daemon` | 3 | QQQ | 100 股人工底仓 + 最多 1 张 Covered Call |
| **V10 期权路由（降级）** | `scripts/live/ibkr_options.py` | 3 | QQQ / VOO / AAPL / MSFT | 默认强制 dry-run，不再作为自动下单入口 |
| **指数动量（降级）** | `scripts/live/ibkr_trading_system_v8.py` | 1 | QQQ / VOO | 仅保留回测对齐 |
| ~~热门股短线~~ | ~~`ibkr_hot_stocks.py`~~ | — | — | **已停用**，归档于 `archive/scripts/live/` |

V11 只允许连接环境变量 `IBKR_PAPER_ACCOUNT` 指定的 `DU...` 模拟账户，以 IB Gateway 持仓和订单为事实来源。系统使用 SQLite 事务状态、HALT 熔断、Telegram 告警和独立心跳 watchdog；不会自动买卖 QQQ 底仓。

```bash
alphaflow options doctor --profile paper_qqq_cc
alphaflow options run --profile paper_qqq_cc --daemon
alphaflow options status --profile paper_qqq_cc --json
alphaflow options halt --profile paper_qqq_cc --reason "manual maintenance"

# 期权链历史回放（需 POLYGON_API_KEY 或 CSV）
set POLYGON_API_KEY=your_key
python scripts/download_options_chain.py --symbol QQQ --start 2024-01-01 --end 2024-06-30
python scripts/options_chain_replay.py --start 2024-01-01 --end 2024-06-30
```

部署、影子运行和 60 日验收步骤详见 [`docs/V11-UNATTENDED-PAPER.md`](docs/V11-UNATTENDED-PAPER.md)。

### 📋 标的与资金池说明

| 配置项 | 用途 | 说明 |
|--------|------|------|
| `index_tickers` | **V8 实盘** | 固定 QQQ / VOO，占用 `alloc_index` 60% 资金池 |
| `unattended_paper` | **V11 主运行路径** | QQQ 单标的 Covered Call，模拟盘限定 |
| `options_trading` | V10 兼容 | 历史 CC/CSP/价差路由，默认 dry-run |
| `hot_trading` | ~~热门股实盘~~ | **已停用**（配置保留只读） |
| `tickers` | **历史回测** | 17 只固定名单，仅用于 `scripts/backtest_main.py` 组合/单标的回测 |
| `walk_forward.tickers` | **样本外验证** | 默认 VOO / QQQ，`python scripts/walk_forward.py` |

> 热门股策略无法在历史数据上用固定名单回测，上线前请在 **IBKR 模拟盘** 验证扫描器与信号逻辑。

### 🧠 指数策略逻辑 (V8.1)
采用多重过滤机制，应对高波动市场：
1. **趋势过滤**: 仅在价格高于 **200日 EMA** 的牛市环境下入场
2. **入场信号**: EMA 10 金叉 EMA 25，同时 **RSI < 65**、**ADX > 20**、**ATR > ATR均值 × 0.8**（波动率状态确认）
3. **风险管理 (核心)**:
   * **ATR 自适应止损**: 动态设置止损位，2.5 倍 ATR
   * **ATR 动态移动止盈**: 从最高点回撤 `min(3×ATR, 12%)` 时锁利离场
   * **60/40 资金池**: 指数类 (VOO/QQQ) 最多占 60%，个股最多占 40%
   * **指数权重加成**: QQQ/VOO 获得 3 倍风险预算

### 🔥 热门股策略逻辑 (V9.1)

1. **标的来源**: IBKR `TOP_PERC_GAIN` 扫描器（美股主板，价 ≥ $10，量 ≥ 100 万）
2. **大盘过滤**: `QQQ` 收盘价 > 200 日 EMA 时才允许开仓
3. **入场（事件型）**: **当根 K 线 EMA 9 金叉 EMA 21** + 价格 > VWAP + RSI < 70 + **ADX > 20** + **相对成交量 > 1.2×**
4. **离场**: 止盈 5% / 止损 4% / EMA 死叉 / 跌破 VWAP / **满 5 个日历日强制平仓**
5. **风控**: 最多 5 个仓位，单票不超过个股池 10%，个股池回撤 5% 暂停开仓
6. **验证工具**:
   - 纸面日志 → `output/hot_paper_trades.jsonl`，统计 `python scripts/hot_paper_stats.py`
   - 日线扫描器回放 → `python scripts/hot_replay_backtest.py`（用涨幅榜代理 TOP_PERC_GAIN）
   - 参数敏感性网格 → `python scripts/hot_grid_search.py --quick`（`output/hot_grid_results.yaml`）

### ✅ 指标对齐（回测 ↔ 实盘）

指数策略的实盘信号使用 `alphaflow.indicators`，算法与 Backtrader 默认一致（EMA / Wilder SMMA 均以首期 SMA 为种子）：

| 指标 | 对齐方式 |
|------|----------|
| EMA 10 / 25 / 200 | `ema_backtrader()`，α = 2/(period+1) |
| ATR / RSI / ADX | `wilder_smooth()`，α = 1/period |
| 金叉信号 | `golden_cross` 布尔值逐日比对 |

```bash
python scripts/verify_indicators.py  # QQQ / VOO 应 100% PASS
pytest tests/test_indicator_parity.py -v
```

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

> 📌 组合回测中 PLTR、QQQ、VOO 贡献最大利润；大盘指数 (VOO/QQQ) 在单标的独立回测中依然表现最稳定。运行 `python scripts/backtest_main.py` 可复现最新结果；图表与结果文件写入 `output/`。

### 📐 Walk-Forward 样本外验证（2024–2026 测试段）

Holdout 模式：训练 2010–2020 → 验证 2021–2023 → 测试 2024–2026（`python scripts/walk_forward.py --quick`）

| 标的 | 测试段收益 | 测试段 Sharpe | 测试段最大回撤 | 测试段交易数 | 结论 |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **QQQ** | **+20.41%** | **0.29** | 2.35% | 1 | ✅ 通过（Sharpe > 0） |
| VOO | +11.23% | -0.05 | 1.80% | 1 | ❌ 未通过 |

> Walk-forward 表明策略在 QQQ 上样本外表现尚可，VOO 与全组合 Sharpe 仍接近 0。实盘建议从 **模拟盘 + 小资金** 起步，勿直接 unattended 实盘。

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

# 3. 运行回测（输出汇总表格 + output/equity_curve.png）
python scripts/backtest_main.py

# 4. 参数优化（网格搜索，结果保存至 output/optimal_params.yaml）
python scripts/optimize.py

# 5. Walk-Forward 样本外验证（训练→验证→测试，避免过拟合）
python scripts/walk_forward.py --quick

# 6. 指标对齐验证（Backtrader 回测 vs alphaflow.indicators 实盘，QQQ/VOO 应 100% 通过）
python scripts/verify_indicators.py

# 7. 实盘交易（需先打开 IBKR TWS/Gateway 模拟盘 7497）
python scripts/live/ibkr_trading_system_v8.py   # 指数池：QQQ/VOO（client_id=1）
python scripts/live/ibkr_hot_stocks.py          # 个股池：每日热门股（client_id=2）
python scripts/hot_paper_stats.py               # 热门股纸面交易统计
python scripts/hot_replay_backtest.py           # 热门股日线扫描器回放
python scripts/hot_grid_search.py --quick      # 热门股参数敏感性网格

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
* **Live Trading**: IBKR API (ib_async) ✅
* **Config**: config.yaml (centralized parameters)

### 🧠 V11 Unattended Paper Architecture

| Strategy | Script | Capital Pool | Universe | Max Hold |
|----------|--------|--------------|----------|----------|
| **V11 unattended paper** | `alphaflow options run --profile paper_qqq_cc --daemon` | One covered lot | QQQ | 21–45 DTE |
| **V10 options router** | `scripts/live/ibkr_options.py` | Legacy dry-run | QQQ / VOO / AAPL / MSFT | Deprecated for orders |
| **V8 equity trend** | `scripts/live/ibkr_trading_system_v8.py` | Backtest compatibility | QQQ / VOO | Deprecated for orders |

V11 requires 100 QQQ shares to be placed manually in the exact configured IBKR paper account. It opens at most one covered call, persists broker-reconciled state in SQLite, and fails closed on account, collateral, order, quote, or position mismatches.

### 📋 Tickers & Capital Pools

| Config key | Used by | Notes |
|------------|---------|-------|
| `unattended_paper` | **V11 primary** | QQQ-only covered-call paper pilot |
| `options_trading` | V10 compatibility | Legacy router, forced dry-run by default |
| `index_tickers` | V8 compatibility | Historical equity trend configuration |
| `hot_trading` | Archived | Dynamic scanner retained for research only |
| `tickers` | **Historical backtest** | 17-name fixed list for `scripts/backtest_main.py` only |
| `walk_forward.tickers` | **Out-of-sample test** | Default VOO / QQQ via `scripts/walk_forward.py` |

> The hot-stock sleeve cannot be backtested on a fixed list; validate on **IBKR paper trading** first.

### 🧠 Index Strategy Logic (V8.1)
Multiple filters to navigate high-volatility markets:
1. **Trend Filter**: Long positions only when price is above the **200-day EMA**
2. **Entry Signal**: EMA 10 golden cross EMA 25, with **RSI < 65**, **ADX > 20**, and **ATR > ATR-SMA × 0.8**
3. **Risk Management (Core)**:
   * **ATR Adaptive Stop-Loss**: Dynamic stops at 2.5x ATR
   * **ATR Dynamic Trailing Stop**: Exit at `min(3×ATR, 12%)` drawdown from peak
   * **60/40 Capital Pool**: Indices (VOO/QQQ) capped at 60%, stocks at 40%
   * **Index Weight Boost**: QQQ/VOO receive 3x risk allocation

### 🔥 Hot-Stock Strategy Logic (V9.1)

1. **Universe**: IBKR `TOP_PERC_GAIN` scanner (US major, price ≥ $10, volume ≥ 1M)
2. **Regime**: Open new trades only when `QQQ` close > 200-day EMA
3. **Entry (event)**: **Golden cross on current bar** + price > VWAP + RSI < 70 + ADX > 20 + relative volume > 1.2×
4. **Exit**: 5% TP / 4% SL / EMA cross / VWAP break / **5-day max hold**
5. **Risk**: Max 5 positions, 10% per name, pool drawdown halt at 5%
6. **Validation**: paper journal + `scripts/hot_paper_stats.py`; daily scanner replay via `scripts/hot_replay_backtest.py`

### ✅ Indicator Parity (Backtest ↔ Live)

Live index signals use `alphaflow.indicators`, matched to Backtrader defaults (SMA-seeded EMA / Wilder SMMA):

```bash
python scripts/verify_indicators.py  # QQQ / VOO should show 100% PASS
pytest tests/test_indicator_parity.py -v
```

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

> 📌 In portfolio mode, PLTR, QQQ, and VOO contributed the most PnL. Run `python scripts/backtest_main.py` to reproduce; artifacts go to `output/`.

### 📐 Walk-Forward Out-of-Sample (2024–2026 test window)

Holdout: train 2010–2020 → validate 2021–2023 → test 2024–2026 (`python scripts/walk_forward.py --quick`)

| Ticker | Test Return | Test Sharpe | Test Max DD | Test Trades | Verdict |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **QQQ** | **+20.41%** | **0.29** | 2.35% | 1 | ✅ Pass (Sharpe > 0) |
| VOO | +11.23% | -0.05 | 1.80% | 1 | ❌ Fail |

> Walk-forward suggests modest edge on QQQ only; portfolio Sharpe remains near zero. Start with **paper trading** before live capital.

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

# 3. Run backtest (summary table + output/equity_curve.png)
python scripts/backtest_main.py

# 4. Parameter optimization (grid search, saves to output/optimal_params.yaml)
python scripts/optimize.py

# 5. Walk-forward out-of-sample validation (train → val → test)
python scripts/walk_forward.py --quick

# 6. Indicator parity check (Backtrader backtest vs alphaflow.indicators live; QQQ/VOO should pass 100%)
python scripts/verify_indicators.py

# 7. Live trading (IBKR TWS/Gateway paper port 7497)
python scripts/live/ibkr_trading_system_v8.py   # Index sleeve: QQQ/VOO
python scripts/live/ibkr_hot_stocks.py          # Stock sleeve: daily hot tickers
python scripts/hot_paper_stats.py               # Hot-stock paper trade stats
python scripts/hot_replay_backtest.py           # Daily scanner replay proxy
python scripts/hot_grid_search.py --quick      # Hot-stock parameter sensitivity grid

# 8. Customize parameters (config.yaml → index_tickers / hot_trading)
```

---

## 📂 文件结构

```
AlphaFlow/
├── alphaflow/                # ⭐ 共享策略库（回测/优化/实盘共用）
│   ├── config.py             # 配置加载、项目路径（output/ state/）
│   ├── indicators.py         # 指标计算（与 Backtrader 对齐）
│   ├── parity.py             # 指标对齐检查
│   ├── signals.py            # 指数策略入场/离场/仓位
│   ├── strategy.py           # Backtrader 策略实现
│   ├── backtest.py           # 回测引擎
│   ├── walkforward.py        # Walk-Forward 核心
│   ├── hot_*.py / scanner.py # 热门股策略模块
│   └── data.py               # 数据下载
├── scripts/                  # 可执行入口脚本
│   ├── backtest_main.py      # ⭐ 组合 + 单标的回测
│   ├── optimize.py           # 参数网格搜索
│   ├── walk_forward.py       # Walk-Forward 验证
│   ├── verify_indicators.py  # 指标对齐验证
│   ├── hot_paper_stats.py    # 热门股纸面统计
│   ├── hot_replay_backtest.py # 热门股扫描器日线回放
│   ├── hot_grid_search.py     # 热门股参数敏感性网格
│   ├── live/                 # IBKR 实盘
│   │   ├── ibkr_trading_system_v8.py  # 指数池 QQQ/VOO
│   │   ├── ibkr_hot_stocks.py         # 热门股池
│   │   └── ibkr_trading_system_v9.py  # V9 兼容入口
│   └── debug/                # 诊断与连接测试
│       ├── diagnose.py
│       ├── debug_signals.py
│       ├── check_data.py
│       └── test_ibkr.py
├── tests/                    # pytest（含 test_indicator_parity.py）
├── docs/                     # 文档
│   ├── CHANGELOG.md
│   └── AlphaFlow-Strategy-Document.md
├── output/                   # 生成物（回测图、CSV、YAML，已 gitignore）
├── state/                    # 实盘运行时状态 JSON（已 gitignore）
├── archive/                  # 历史废弃脚本
├── config.yaml               # 全局参数配置
├── requirements.txt
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
- [x] **V9.1**: 指标对齐验证（Backtrader ↔ alphaflow.indicators，QQQ/VOO 100%）/ Indicator Parity Checks
- [x] **V9.2**: 热门股合格化（事件金叉、QQQ 大盘过滤、ADX/RVOL、纸面日志、扫描器回放）/ Hot-Stock Validation Suite

## ⚠️ Disclaimer / 免责声明
This project is for academic and technical discussion only. It does NOT constitute investment advice. Trading involves significant risk. The author is not responsible for any financial losses incurred from using this software.
本项目仅供学术研究和技术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。使用本程序产生的任何盈亏由使用者自行承担。
