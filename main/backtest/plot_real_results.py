"""Create presentation-quality PNG charts from outputs_real/equity_curve.csv."""

import csv
import os
import tempfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "outputs_real"
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "wheel_strategy_matplotlib"))
import matplotlib.dates as mdates
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_curve():
    with (OUT / "equity_curve.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def configure_axes(ax):
    ax.grid(True, axis="y", color="#d9dee5", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#8a949e")
    ax.spines["bottom"].set_color("#8a949e")
    ax.tick_params(colors="#4f5963", labelsize=9)


def main():
    rows = read_curve()
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in rows]
    series = {name: [float(r[name]) for r in rows]
              for name in ("wheel", "nifty_tr", "universe_bh")}
    labels = {"wheel": "Real-data wheel", "nifty_tr": "NIFTY 50 total return",
              "universe_bh": "12-stock universe buy-and-hold"}
    colours = {"wheel": "#1769aa", "nifty_tr": "#d97706", "universe_bh": "#238636"}

    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(13, 6.5), dpi=160)
    for name, values in series.items():
        ax.plot(dates, values, label=labels[name], color=colours[name], linewidth=1.6)
    ax.set_title("NSE Bhavcopy Backtest: Equity Curves", loc="left", fontsize=15, fontweight="bold", pad=14)
    ax.set_ylabel("Portfolio value (INR)")
    ax.yaxis.set_major_formatter(lambda value, _: f"INR {value / 1e6:.0f}M")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(loc="upper left", frameon=False, ncol=3)
    configure_axes(ax)
    fig.tight_layout()
    fig.savefig(OUT / "real_equity_curves.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    wheel = series["wheel"]
    high = wheel[0]
    drawdown = []
    for value in wheel:
        high = max(high, value)
        drawdown.append((value / high - 1) * 100)
    fig, ax = plt.subplots(figsize=(13, 5.2), dpi=160)
    ax.fill_between(dates, drawdown, 0, color="#b42318", alpha=0.18)
    ax.plot(dates, drawdown, color="#b42318", linewidth=1.4)
    ax.set_title("NSE Bhavcopy Backtest: Real-data Wheel Drawdown", loc="left", fontsize=15, fontweight="bold", pad=14)
    ax.set_ylabel("Drawdown (%)")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    configure_axes(ax)
    fig.tight_layout()
    fig.savefig(OUT / "real_drawdown.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(OUT / "real_equity_curves.png")
    print(OUT / "real_drawdown.png")


if __name__ == "__main__":
    main()
