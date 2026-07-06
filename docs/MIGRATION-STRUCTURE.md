# AlphaFlow 工程结构迁移计划

本文档描述将 AlphaFlow 从「扁平脚本 + 混杂包根目录」演进为「可安装包 + 分层子包 + 统一 CLI」的分阶段 PR 方案。

**Phase 0（PR #1）已完成：**

- `pyproject.toml` — 支持 `pip install -e ".[dev]"` 与 `alphaflow` 控制台命令
- `alphaflow/cli.py` — 统一 CLI 骨架（委托库函数或 legacy 脚本）
- 现有 `scripts/*.py` **保持不变**，向后兼容

**Phase 1（PR #2）已完成：**

- `alphaflow/core/config.py` — 统一配置、bootstrap（`setup_project`）
- `alphaflow/core/data/` — OHLCV 抽象、yfinance provider、CSV 缓存
- `alphaflow/core/persistence/` — 原子 JSON 状态 + JSONL journal
- `alphaflow/config.py`、`alphaflow/data.py` — 兼容 re-export
- `options/state.py`、`options/journal.py`、`hot_journal.py`、V8 实盘 — 委托 core.persistence
- `tests/test_core_*.py` — 核心层单元测试

---

## 目标架构

```
AlphaFlow/
├── pyproject.toml
├── config/                         # Phase 2：拆分配置
│   ├── default.yaml
│   ├── options.yaml
│   ├── equity.yaml
│   └── hot.yaml
├── alphaflow/
│   ├── cli.py                      # ✅ Phase 0
│   ├── core/                       # Phase 1–2
│   │   ├── config.py
│   │   ├── indicators.py
│   │   ├── data/
│   │   ├── persistence/
│   │   └── broker/
│   ├── equity/                     # Phase 2
│   ├── options/                    # 已有，Phase 2 微调 import
│   ├── hot/                        # Phase 2（archived）
│   └── research/                   # Phase 3
├── scripts/                        # Phase 3 后变为 thin wrapper
└── tests/
    ├── core/
    ├── equity/
    ├── options/
    └── integration/
```

---

## Phase 0 — 可安装包 + CLI 骨架 ✅

| 变更 | 文件 | 说明 |
|------|------|------|
| 新增 | `pyproject.toml` | 依赖、console script、`pip install -e .` |
| 新增 | `alphaflow/cli.py` | 统一入口，见下方命令表 |
| 更新 | `.github/workflows/ci.yml` | `pip install -e ".[dev]"` |
| 保留 | `requirements.txt` | 兼容旧文档；内容与 pyproject 同步 |

### CLI 命令映射

| 新命令 | 等价旧命令 | 实现方式 |
|--------|------------|----------|
| `alphaflow backtest run` | `python scripts/backtest_main.py` | legacy 脚本 |
| `alphaflow research walk-forward` | `python scripts/walk_forward.py` | 库函数 |
| `alphaflow research optimize` | `python scripts/optimize.py` | legacy 脚本 |
| `alphaflow research verify-indicators` | `python scripts/verify_indicators.py` | 库函数 |
| `alphaflow options scan` | `python scripts/options_daily_scan.py` | 库函数 |
| `alphaflow options run --live` | `python scripts/live/ibkr_options.py --live` | legacy 脚本 |
| `alphaflow options stats` | `python scripts/options_paper_stats.py` | 库函数 |
| `alphaflow legacy equity-run` | `python scripts/live/ibkr_trading_system_v8.py` | legacy + 警告 |
| `alphaflow legacy hot-stats` | `python scripts/hot_paper_stats.py` | legacy 脚本 |

---

## Phase 1 — 核心层抽取 ✅

**目标：** 消除重复、统一基础设施，不改变对外行为。

### 1.1 合并 bootstrap / env 加载 ✅

```
alphaflow/config.py          →  re-export shim
alphaflow/core/config.py       →  canonical implementation + setup_project()
scripts/_bootstrap.py          →  thin wrapper → setup_project()
```

### 1.2 数据层抽象 ✅

```
alphaflow/data.py              →  re-export shim
alphaflow/core/data/base.py    →  OHLCVProvider Protocol
alphaflow/core/data/yfinance.py
alphaflow/core/data/cache.py   →  CSV cache under output/cache/ohlcv/
```

### 1.3 持久化统一 ✅

```
alphaflow/core/persistence/state.py    →  load_json / save_json (atomic)
alphaflow/core/persistence/journal.py  →  append_event / load_events

options/state.py, options/journal.py, hot_journal.py, V8  →  delegate to core
```

### 1.4 仓库卫生 ✅

- `__pycache__/` 不在 git 跟踪中
- CI 使用 `pip install -e ".[dev]"` 完整依赖

**验收：** `pytest tests/test_core_*.py` 全绿；旧 import 路径仍可用。

---

## Phase 1 — 核心层抽取（原 PR #2 计划，已合并上方）<!-- legacy anchor -->

## Phase 2 — 策略子包化（PR #3，中风险）

**目标：** 目录反映策略生命周期；指数策略真正复用 `signals.py`。

### 2.1 移动文件（保留 re-export 兼容层）

| 现路径 | 新路径 |
|--------|--------|
| `alphaflow/signals.py` | `alphaflow/equity/signals.py` |
| `alphaflow/strategy.py` | `alphaflow/equity/backtest.py` |
| `alphaflow/backtest.py` | `alphaflow/equity/engine.py` |
| `alphaflow/hot_*.py` | `alphaflow/hot/` |
| `alphaflow/walkforward.py` | `alphaflow/research/walkforward.py` |
| `alphaflow/grid.py` | `alphaflow/research/grid.py` |
| `alphaflow/parity.py` | `alphaflow/research/parity.py` |

根目录 `alphaflow/signals.py` 等保留：

```python
# alphaflow/signals.py (compat shim, deprecated)
from alphaflow.equity.signals import *  # noqa: F403
```

### 2.2 回测复用共享信号

`AlphaFlowStrategy.next()` 改为调用 `equity.signals.check_entry/check_exit/calc_position_size`，删除 `_should_enter/_should_exit` 重复逻辑。

新增 `tests/equity/test_signal_parity.py`：同一 OHLCV 上 Backtrader 成交时点 vs 纯函数信号一致。

### 2.3 配置拆分

```
config/default.yaml    # backtest, live 连接
config/options.yaml    # options_trading（主 profile）
config/equity.yaml     # strategy, risk, index_tickers
config/hot.yaml        # hot_trading, archived: true
```

```python
load_config(profile="options")  # default for live
```

**验收：** 新旧 import 均可用；signal parity 测试通过；README 更新 Current Workflow。

---

## Phase 3 — CLI 完全内化 + 编排（PR #4）

**目标：** `scripts/` 只做 deprecated wrapper；实盘有互斥与重连。

### 3.1 脚本变薄

每个 `scripts/foo.py` 变为：

```python
from alphaflow.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["research", "walk-forward", *sys.argv[1:]]))
```

或一行：`# deprecated: use alphaflow research walk-forward`

### 3.2 编排层

```
alphaflow/app/orchestrator.py
  - 进程锁 state/.alphaflow.lock（防 v8 与 options 同时跑）
  - IBKR 连接池 / 重连（core/broker/connection.py）
  - 统一定时任务入口（替代 run_options_scheduled.ps1 的逻辑文档化）
```

### 3.3 CLI 扩展

```bash
alphaflow options run --profile paper
alphaflow config validate
alphaflow doctor          # 检查 TWS、API key、config 完整性
```

**验收：** 无 `sys.path.insert`；`pip install alphaflow` 后任意目录可运行 CLI。

---

## Phase 4 — 长期（独立 PR）

- `ib_insync` → `ib_async`（仅改 `core/broker/`）
- `mypy` / `ruff` 进 CI
- integration tests：mock IB + fixture CSV
- 可选：监控面板读取 `journal` + `stats`

---

## 依赖规则（写入 CONTRIBUTING）

```
scripts/           →  只 import alphaflow.*，不写业务逻辑
alphaflow/equity/  →  import core；禁止 import options/hot
alphaflow/options/ →  import core；禁止 import equity/hot
alphaflow/hot/     →  import core only（frozen，不扩展）
alphaflow/core/    →  不 import 任何策略子包
```

---

## 推荐合并顺序

```
PR-0  pyproject.toml + cli.py + CI          ← 当前
PR-1  core/config + core/persistence        ← 1–2 天
PR-2  equity/ 子包 + signals 复用 + 配置拆分  ← 3–5 天
PR-3  CLI 内化 + orchestrator + 进程锁       ← 1 周
PR-4  ib_async / typing / integration tests  ← 按需
```

每 PR 保持：**测试全绿 + 旧命令仍可用**。

---

## 本地验证（Phase 0）

```bash
cd AlphaFlow
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

alphaflow --help
alphaflow options scan
alphaflow research verify-indicators
pytest tests/ -v --ignore=scripts/debug/test_ibkr.py
```
