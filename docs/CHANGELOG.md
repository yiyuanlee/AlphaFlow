# Changelog

All notable changes to AlphaFlow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [10.0.0] - 2026-06-06

### Added
- **`alphaflow/options/`** — 期权包：`options_config`, `chain`, `signals`, `regime`, `sizing`, `execution`, `state`, `journal`, `manager`, `underlying`, `replay_proxy`, `stats`
- **`alphaflow/options/strategies/`** — Covered Call、Cash-Secured Put、Bull Put / Bear Call 垂直价差
- **`scripts/live/ibkr_options.py`** — 期权主循环（regime 路由、底仓维护、限价下单、持仓管理）
- **`scripts/options_paper_stats.py`**, **`scripts/options_replay_proxy.py`** — 纸面统计与简化回放代理
- **`tests/test_options_*.py`** — 链选择、sizing、信号路由、状态持久化单元测试
- **`docs/Options-Strategy-Document.md`** — 期权策略说明
- **`config.yaml`** — `options_trading` 配置段（QQQ/VOO/AAPL/MSFT、stock_core、regime/chain/risk）

### Changed
- **`scripts/live/ibkr_hot_stocks.py`** — 停用，重定向至 `ibkr_options.py`；完整副本在 `archive/scripts/live/`
- **`scripts/live/ibkr_trading_system_v8.py`** — 标记为降级（动量入场），底仓由 `UnderlyingManager` 接管
- **`scripts/live/ibkr_trading_system_v9.py`** — 重定向至 `ibkr_options.py`
- **`README.md`** — 期权为主架构说明

### Deprecated
- 热门股短线模块（`hot_trading` 配置保留只读，不再推荐实盘）

## [9.2.1] - 2026-06-06

### Added
- **`alphaflow/hot_grid.py`** — 热门股回放参数敏感性网格（`min_adx` / `min_rel_volume` / `rsi_max` / `require_golden_cross`）
- **`scripts/hot_grid_search.py`** — 网格搜索 CLI，`--quick` / `--objective balanced`
- **`tests/test_hot_grid.py`** — 网格评分单元测试

### Changed
- **`hot_replay.py`** — 抽取 `ReplayContext`，网格搜索复用预加载行情，避免重复下载

## [9.2.0] - 2026-06-06

### Added
- **热门股合格化四项** — 事件型金叉、QQQ 200EMA 大盘过滤、ADX + 相对成交量过滤
- **`alphaflow/hot_market.py`**, **`hot_journal.py`**, **`hot_replay.py`**, **`hot_stats.py`**
- **`scripts/hot_paper_stats.py`** — 纸面交易 JSONL 统计（胜率、盈亏比、跳过原因）
- **`scripts/hot_replay_backtest.py`** — 日线扫描器回放（TOP_PERC_GAIN 代理）
- **`tests/test_hot_signals.py`** — 热门股入场过滤单元测试

### Changed
- **`hot_signals.py`** — `check_hot_entry` 返回 `(bool, reason)`，支持事件金叉与市场过滤
- **`hot_indicators.py`** — 对齐 Backtrader EMA/Wilder，新增 `golden_cross` / `adx` / `rel_volume`
- **`ibkr_hot_stocks.py`** — 集成大盘过滤、完整入场链、纸面日志
- **`config.yaml`** — `market_filter`、`entry` 扩展字段、`replay` 段
- **项目目录** — 脚本迁入 `scripts/`，文档迁入 `docs/`，输出/状态目录分离

## [9.0.0] - 2026-06-03

### Added
- **`ibkr_hot_stocks.py`** — 热门股短线策略：IBKR 扫描器动态标的、个股池 40%、最长持仓 5 天
- **`alphaflow/hot_config.py`**, **`hot_signals.py`**, **`hot_indicators.py`**, **`scanner.py`**
- **`config.yaml`** — `index_tickers`（V8）与 `hot_trading`（扫描/持仓/风控）配置段

### Changed
- **`ibkr_trading_system_v8.py`** — 仅交易 `index_tickers`（QQQ/VOO），专注指数资金池
- **`ibkr_trading_system_v9.py`** — 重定向至 `ibkr_hot_stocks.py`

## [8.3.1] - 2026-06-03

### Changed
- **`config.yaml`** — 回测初始资金从 $10,000 提升至 **$50,000**（量化路线基准）
- **`backtest_main.py`** — 单标的表格资金显示从 config 动态读取
- **`README.md`** — 同步 $50k 回测结果（组合 +71.57%，净值 $85,784）

## [8.3.0] - 2026-06-03

### Added
- **`walk_forward.py`** — Walk-Forward 样本外验证 CLI
- **`alphaflow/walkforward.py`** — holdout（训练/验证/测试）与 rolling 滚动窗口模式
- **`alphaflow/grid.py`** — 共享参数网格搜索与目标函数（sharpe/return/calmar）
- **`config.yaml`** — `walk_forward` 分段配置（默认 VOO/QQQ，2010–2020 训练 / 2021–2023 验证 / 2024–2026 测试）

### Changed
- **`alphaflow/backtest.py`** — 支持按日期切片回测（`run_period_single` / `run_period_portfolio`）
- **`alphaflow/data.py`** — 新增 `slice_ohlcv` 日期切片工具

## [8.2.0] - 2026-06-03

### Added
- **`alphaflow/`** shared strategy package — `config`, `indicators`, `signals`, `strategy`, `backtest`, `data`
  - Backtest, optimize, and live trading now share the same entry/exit/position-sizing logic
- **Per-ticker backtest table** in `backtest_main.py` for README-aligned reporting

### Changed
- **`backtest_main.py`** — thin entry point using `alphaflow.backtest`
- **`optimize.py`** — uses shared `AlphaFlowStrategy` with full strategy params from config
- **`ibkr_trading_system_v8.py`** — uses `alphaflow.indicators` + `alphaflow.signals`; golden-cross entry aligned with backtest; ATR dynamic trailing stop; 60/40 portfolio allocation in live mode
- **`README.md`** — updated backtest results ($10,000, 2010–2026) with portfolio + single-ticker tables
- **`config.yaml`** — added `index_multiplier`; replaced delisted `SQ` with `XYZ`

## [8.1.0] - 2026-05-11

### Added
- **`optimize.py`** — 参数优化框架（网格搜索 + 贝叶斯优化）
  - 支持多参数并行扫描
  - 自动保存最优参数组合到 `optimal_params.yaml`
  - 输出 Top-10 参数组合排行榜
  - 对单个或多个标的分别优化
- **`CHANGELOG.md`** — 版本变更日志（本文档）
- **`backtest_main.py`** — 统一回测入口（废弃旧版 `backtest_multi.py`/`backtest_pro.py`/`backtest_v4.0.py`）
- **`equity_curve.png`** — 回测权益曲线图（由 `backtest_main.py` 自动生成）

### Changed
- **`README.md`** — 统一中英文版本为 V8.1
  - 英文部分更新至 V8.1（此前为 V7.0）
  - 标注 `ib_insync` 已实现（非 Roadmap）
  - 新增文件结构说明
- **`requirements.txt`** — 新增依赖声明

### Deprecated
- `backtest_multi.py` — 使用 `backtest_main.py` 替代
- `backtest_pro.py` — 保留参考，已废弃
- `backtest_v4.0.py` — 保留参考，已废弃

---

## [8.0.0] - 2026-04-30

### Added
- **`ibkr_trading_system_v8.py`** — 完整实盘交易系统
  - IBKR API 连接（ib_insync）
  - 实时行情扫描 + 自动下单
  - 订单成交确认回调
  - 日志记录
- **`ibkr_trading_system_v9.py`** — 实盘系统 v9（experimental）

### Changed
- 策略风控逻辑完善：ATR 动态止损 + Trailing Stop 双保险
- README 添加"实盘交易"说明

---

## [7.0.0] - 2026-04-15

### Added
- RSI 确认信号（RSI < 65 避免追高）
- ADX 趋势强度过滤（ADX > 20）
- 多标的组合回测框架

### Changed
- 策略版本号升至 V7.0

---

## [6.0.0] - 2026-04-01

### Added
- **`config.yaml`** — 参数集中化管理
  - 所有策略参数可在此配置，无需改动代码

---

## [5.0.0] - 2026-03-15

### Added
- IBKR 模拟账户实盘测试（ib_insync）
- 数据源切换为 Yahoo Finance（yfinance）

---

## [4.0.0] - 2026-03-01

### Added
- 多标的组合回测引擎
- 指数权重加成（QQQ/VOO 获得 3x 风险预算）

---

## [3.0.0] - 2026-02-15

### Added
- ATR 动态止损
- 移动止盈（Trailing Stop）

---

## [2.0.0] - 2026-02-01

### Added
- SMA 200 趋势过滤
- 固定止损

---

## [1.0.0] - 2026-01-15

### Added
- 基础均线交叉策略（EMA 10 / EMA 25）
- Backtrader 回测框架搭建
- 初始项目结构

---

[Unreleased]: https://github.com/yiyuanlee/AlphaFlow/compare/v8.1.0...HEAD
[8.1.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v8.0.0...v8.1.0
[8.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v7.0.0...v8.0.0
[7.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v6.0.0...v7.0.0
[6.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v5.0.0...v6.0.0
[5.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v4.0.0...v5.0.0
[4.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v3.0.0...v4.0.0
[3.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/yiyuanlee/AlphaFlow/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/yiyuanlee/AlphaFlow/tree/v1.0.0