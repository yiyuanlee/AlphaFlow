# AlphaFlow: IBKR Quant Trading System

[中文](#chinese) | [English](#english)

---

<a name="chinese"></a>
## 🇨🇳 中文说明

这是一个基于 Python 开发的自动化量化交易系统，专门针对 **Interactive Brokers (IBKR)** 小额账户（$3,000+）进行优化。

### 📈 项目概览
本项目旨在利用量化手段，在控制风险的前提下，实现美股市场的趋势跟踪交易。目前已完成 **V3.0 版本** 的回测系统开发，核心重点在于“风险控制”与“波动率自适应”。

### 🛠️ 技术栈
* **语言**: Python 3.10+
* **回测框架**: [Backtrader](https://www.backtrader.com/)
* **数据源**: Yahoo Finance (yfinance)
* **未来规划**: 对接 IBKR API (ib_insync)

### 🧠 策略逻辑 (V3.0)
该策略采用了多重过滤机制，以应对高波动市场：
1. **趋势过滤**: 仅在价格高于 **200日均线 (SMA 200)** 的牛市环境下入场。
2. **入场信号**: 10日快线金叉30日慢线，且 **RSI < 70** (避免追高)。
3. **风险管理 (核心)**: 
   * **ATR 自适应止损**: 基于平均真实波幅 (ATR) 的 2.5 倍动态设置止损位，自动适应市场波动。
   * **移动止损 (Trailing Stop)**: 股价从持仓最高点回撤 15% 时自动锁利离场。

### 📊 阶段性回测结果 (AMD 测试)
| 指标 | 结果 |
| :--- | :--- |
| **测试周期** | 2022-01-01 至 2026-03-20 |
| **总收益率** | 42.02% |
| **最大回撤** | 28.12% |
| **夏普比率** | 0.59 |

### 🚀 快速开始
1. **环境安装**: `pip install backtrader yfinance pandas matplotlib`
2. **运行回测**: `python backtest_pro.py`

---

<a name="english"></a>
## 🇺🇸 English Description

An automated quantitative trading system developed in Python, specifically optimized for **Interactive Brokers (IBKR)** small accounts ($3,000+).

### 📈 Project Overview
AlphaFlow aims to implement trend-following strategies in the US stock market while maintaining strict risk control. With **V3.0**, the backtesting engine is fully functional, focusing on "Risk Management" and "Volatility Adaptation."

### 🛠️ Tech Stack
* **Language**: Python 3.10+
* **Backtesting**: [Backtrader](https://www.backtrader.com/)
* **Data Source**: Yahoo Finance (yfinance)
* **Roadmap**: IBKR API Integration (ib_insync)

### 🧠 Strategy Logic (V3.0)
The strategy employs multiple filters to navigate high-volatility markets:
1. **Trend Filter**: Long positions are only taken when the price is above the **200-day SMA**.
2. **Entry Signal**: 10-day SMA crosses above 30-day SMA, with **RSI < 70** to avoid overbought conditions.
3. **Risk Management (Core)**: 
   * **ATR Adaptive Stop-Loss**: Dynamic stops set at 2.5x ATR to adjust for market volatility.
   * **Trailing Stop**: Automatic profit-taking if the price drops 15% from its peak.

### 📊 Backtesting Results (Case Study: AMD)
| Metric | Result |
| :--- | :--- |
| **Period** | 2022-01-01 to 2026-03-20 |
| **Total Return** | 42.02% |
| **Max Drawdown** | 28.12% |
| **Sharpe Ratio** | 0.59 |

### 🚀 Quick Start
1. **Installation**: `pip install backtrader yfinance pandas matplotlib`
2. **Run Backtest**: `python backtest_pro.py`

---

## 📅 Development Roadmap / 开发计划
- [x] **V1.0**: Basic Moving Average Crossover / 基础均线交叉策略
- [x] **V2.0**: SMA 200 Filter & Fixed Stop-loss / 引入200日线过滤与固定止损
- [x] **V3.0**: ATR Volatility & Trailing Stop / 引入ATR动态止损与移动止损
- [ ] **V4.0**: Multi-asset Portfolio Management / 多标的资产组合配置
- [ ] **V5.0**: IBKR Paper Trading Integration / 对接IBKR模拟账户实盘测试

## ⚠️ Disclaimer / 免责声明
This project is for academic and technical discussion only. It does NOT constitute investment advice. Trading involves significant risk. The author is not responsible for any financial losses incurred from using this software.
本项目仅供学术研究和技术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。使用本程序产生的任何盈亏由使用者自行承担。
