import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

import yfinance as yf
import pandas as pd

from alphaflow.config import output_path

out_file = output_path('check_out.txt')
with open(out_file, 'w') as f:
    df = yf.download('VOO', start='2022-01-01', end='2026-03-20', progress=False, auto_adjust=True)
    f.write(f"COLUMNS_TYPE: {type(df.columns).__name__}\n")
    f.write(f"IS_MULTI: {isinstance(df.columns, pd.MultiIndex)}\n")
    f.write(f"COLUMNS: {list(df.columns)}\n")
    f.write(f"LEN: {len(df)}\n")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        f.write(f"FLAT_COLUMNS: {list(df.columns)}\n")

    f.write(f"HAS_DUPES: {df.columns.duplicated().any()}\n")
    dupe_list = list(df.columns[df.columns.duplicated()])
    if dupe_list:
        f.write(f"DUPE_COLS: {dupe_list}\n")

    f.write(f"TAIL:\n{df.tail(3).to_string()}\n")
    f.write(f"\nCOLUMN_VALUES: {[str(c) for c in df.columns]}\n")
    f.write(f"SHAPE: {df.shape}\n")
    f.write(f"DTYPES:\n{df.dtypes.to_string()}\n")

print(f"Wrote {out_file}")
