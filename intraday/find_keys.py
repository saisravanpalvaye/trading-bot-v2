"""
intraday/find_keys.py — Look up current Upstox instrument keys for NSE stocks.

Stock splits/bonuses can change a company's ISIN, which makes the old key in
config.py invalid (Upstox error UDAPI100011). Run this to get the current keys.

Usage (from the intraday folder):
    python find_keys.py                        # checks the 3 that failed
    python find_keys.py KOTAKBANK SBIN TCS     # any symbols you want
"""

import gzip
import io
import json
import sys

import requests

MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
DEFAULT = ["KOTAKBANK", "BAJFINANCE", "DRREDDY"]


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or DEFAULT
    print(f"Downloading Upstox NSE instrument master ...")
    r = requests.get(MASTER_URL, timeout=60)
    r.raise_for_status()
    rows = json.load(gzip.GzipFile(fileobj=io.BytesIO(r.content)))

    found = {}
    for row in rows:
        if row.get("segment") == "NSE_EQ" and row.get("instrument_type") == "EQ":
            sym = row.get("trading_symbol")
            if sym in symbols:
                found[sym] = row

    print("\nPaste these lines into INSTRUMENTS in config.py:\n")
    for s in symbols:
        row = found.get(s)
        if row:
            pad = " " * max(1, 12 - len(s))
            print(f'    "{s}":{pad}"{row["instrument_key"]}",   # {row.get("name", "")}')
        else:
            print(f'    # {s}: NOT FOUND in NSE_EQ — check the symbol spelling')


if __name__ == "__main__":
    main()
