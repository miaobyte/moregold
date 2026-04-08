import re
import argparse
from pathlib import Path

import pandas as pd
import mplfinance as mpf


def parse_price(s):
    m = re.search(r"[0-9.]+", str(s))
    return float(m.group()) if m else None


def build_series(df, date):
    ts = pd.to_datetime(date + " " + df["时间"].astype(str))
    price = df["金价(USD/盎司)"].map(parse_price)
    s = pd.Series(price.to_numpy(), index=ts).sort_index().dropna()
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s})

def main(csv_path, out_dir="kline_jpg"):
    path = Path(csv_path)
    date = path.stem.replace("gold_", "")
    df = pd.read_csv(path)
    series = build_series(df, date)
    if series.empty:
        return
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    save_path = out / f"{date}.jpg"
    mpf.plot(series, type="line", style="yahoo", volume=False, savefig=dict(fname=save_path, dpi=160))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="kline_jpg")
    args = ap.parse_args()
    main(args.csv, args.out)
