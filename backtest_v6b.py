"""
backtest_v6b.py - V6 + closer target.

V6 base (all preserved):
  ATR_SL_MULT=2.0, PARTIAL=2.0, sector fixes, dup block, no RS

V6b single change:
  ATR_TGT_MULT: 3.0 -> 2.5 (closer target, more TARGET hits)
  MIN_RR:       1.5 -> 1.2 (accepts inherent RR=1.25)

Test cases: 31/31 passed before build.
"""

import sys, time, warnings
warnings.filterwarnings("ignore")
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    from datetime import date, datetime
    print("Libraries OK")
except ImportError as e:
    print(f"Missing: {e}"); sys.exit(1)

# ── Config ─────────────────────────────────────────────────
CAPITAL          = 600_000
RISK_PER_TRADE   = 6_000
MAX_POSITION     = 150_000
HOLD_DAYS        = 8
MIN_RR           = 1.2
ATR_SL_MULT      = 2.0
ATR_TGT_MULT     = 2.5
ATR_PARTIAL_MULT = 2.0
ADX_TREND_MIN    = 18
TREND_RSI_MIN    = 52
TREND_RSI_MAX    = 66
RSI_PULLBACK_MIN = 5
OVERSOLD_RSI_MAX = 38   # was 50
DIV_RSI_MAX      = 52
BP_MIN_DAYS      = 5
BP_MAX_DAYS      = 15
BP_PULLBACK_MIN  = 0.03
BP_PULLBACK_MAX  = 0.08
BP_VOL_THRESHOLD = 1.0
BP_VOL_BREAKOUT  = 2.0
START = "2015-01-01"
END   = date.today().isoformat()

WATCHLIST = [
    "HDFCBANK.NS","ICICIBANK.NS","AXISBANK.NS","SBIN.NS",
    "KOTAKBANK.NS","BAJFINANCE.NS","FEDERALBNK.NS",
    "INFY.NS","WIPRO.NS","HCLTECH.NS","LTIM.NS","COFORGE.NS","MPHASIS.NS",
    "SUNPHARMA.NS","DRREDDY.NS","DIVISLAB.NS",
    "MARUTI.NS","EICHERMOT.NS","HEROMOTOCO.NS","BAJAJ-AUTO.NS","M&M.NS",
    "HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","BRITANNIA.NS","DABUR.NS",
    "LT.NS","ABB.NS","SIEMENS.NS","HAVELLS.NS","POLYCAB.NS",
    "DEEPAKNTR.NS","PIDILITIND.NS","ASIANPAINT.NS",
    "HINDALCO.NS","TATASTEEL.NS","JSWSTEEL.NS","TATAPOWER.NS",
    "TITAN.NS","DMART.NS","TRENT.NS",
    "ADANIPORTS.NS","RELIANCE.NS","ULTRACEMCO.NS","APOLLOTYRE.NS",
]

SECTOR_MAP = {
    "HDFCBANK.NS":"BANKING","ICICIBANK.NS":"BANKING","AXISBANK.NS":"BANKING",
    "SBIN.NS":"BANKING","KOTAKBANK.NS":"BANKING","BAJFINANCE.NS":"BANKING",
    "FEDERALBNK.NS":"BANKING",
    "INFY.NS":"IT","WIPRO.NS":"IT","HCLTECH.NS":"IT",
    "LTIM.NS":"IT","COFORGE.NS":"IT","MPHASIS.NS":"IT",
    "SUNPHARMA.NS":"PHARMA","DRREDDY.NS":"PHARMA","DIVISLAB.NS":"PHARMA",
    "MARUTI.NS":"AUTO","EICHERMOT.NS":"AUTO","HEROMOTOCO.NS":"AUTO",
    "BAJAJ-AUTO.NS":"AUTO","M&M.NS":"AUTO",
    "HINDUNILVR.NS":"FMCG","ITC.NS":"FMCG","NESTLEIND.NS":"FMCG",
    "BRITANNIA.NS":"FMCG","DABUR.NS":"FMCG",
    "LT.NS":"CAPITAL","ABB.NS":"CAPITAL","SIEMENS.NS":"CAPITAL",
    "HAVELLS.NS":"CAPITAL","POLYCAB.NS":"CAPITAL",
    "DEEPAKNTR.NS":"CHEMICAL","PIDILITIND.NS":"CHEMICAL","ASIANPAINT.NS":"CHEMICAL",
    "HINDALCO.NS":"METAL","TATASTEEL.NS":"METAL","JSWSTEEL.NS":"METAL",
    "TATAPOWER.NS":"ENERGY",
    "TITAN.NS":"CONSUMER","DMART.NS":"CONSUMER","TRENT.NS":"CONSUMER",
    "ADANIPORTS.NS":"INFRA","RELIANCE.NS":"ENERGY",
    "ULTRACEMCO.NS":"CEMENT","APOLLOTYRE.NS":"AUTO",
}

SECTOR_PROXY = {
    "BANKING":"^NSEBANK","IT":"^CNXIT","PHARMA":"^CNXPHARMA",
    "AUTO":"^CNXAUTO","FMCG":"^CNXFMCG","METAL":"^CNXMETAL",
    "CAPITAL":"^CNXINFRA","CHEMICAL":"^CNXFMCG","CONSUMER":"^CNXCONSUMP",
    "ENERGY":"^CNXENERGY","INFRA":"^CNXINFRA","CEMENT":"^CNXINFRA",
}

SETUP_WIN_RATE = {
    "TREND_PULLBACK":0.55,"OVERSOLD_EXHAUSTION":0.52,
    "RSI_DIVERGENCE":0.54,"BREAKOUT_PULLBACK":0.56,
}

# ── Indicators ─────────────────────────────────────────────
def _rsi(c,p=14):
    d=c.diff(); ag=d.clip(lower=0).ewm(com=p-1,adjust=False,min_periods=p).mean()
    al=(-d.clip(upper=0)).ewm(com=p-1,adjust=False,min_periods=p).mean()
    return 100-100/(1+ag/al.replace(0,np.nan))

def _ema(c,p): return c.ewm(span=p,adjust=False).mean()

def _atr(df,p=14):
    hi=df["high"]; lo=df["low"]; cl=df["close"]
    tr=pd.concat([(hi-lo),(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=p,adjust=False).mean()

def _adx(df,p=14):
    hi=df["high"]; lo=df["low"]; cl=df["close"]
    tr=pd.concat([(hi-lo),(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    atr_=tr.ewm(span=p,adjust=False).mean()
    up=(hi-hi.shift()).clip(lower=0); dn=(lo.shift()-lo).clip(lower=0)
    up=up.where(up>dn,0); dn=dn.where(dn>up,0)
    pdi=up.ewm(span=p,adjust=False).mean()/atr_*100
    ndi=dn.ewm(span=p,adjust=False).mean()/atr_*100
    dx=(abs(pdi-ndi)/(pdi+ndi).replace(0,np.nan)*100).fillna(0)
    return dx.ewm(span=p,adjust=False).mean()

def _to_weekly(df):
    d=df.copy(); d.index=pd.to_datetime(d.index)
    return d.resample("W").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def _vol_ratio(v,w=20):
    avg=v.rolling(w).mean(); return v/avg.replace(0,np.nan)

# ── Sector check ───────────────────────────────────────────
def _sector_uptrend(sd,dt):
    if sd is None: return True
    s=sd[sd.index<=dt]
    if len(s)<25: return True
    return float(s["close"].iloc[-1])>float(_ema(s["close"],20).iloc[-1])

# ── Setup detection ────────────────────────────────────────
def _detect_weekly(wdf_full):
    wdf=wdf_full.iloc[:-1] if len(wdf_full)>14 else wdf_full
    if len(wdf)<14: return None,0
    rsi_s=_rsi(wdf["close"]); rv=float(rsi_s.iloc[-1])
    ema20=_ema(wdf["close"],20)

    if TREND_RSI_MIN<=rv<=TREND_RSI_MAX:
        if float(wdf["close"].iloc[-1])>float(ema20.iloc[-1]):
            rsi_max=float(rsi_s.iloc[-5:-1].max()) if len(rsi_s)>=5 else rv
            if rv<rsi_max-RSI_PULLBACK_MIN:
                try:
                    adxv=float(_adx(wdf).iloc[-1])
                    if adxv>=ADX_TREND_MIN: return "TREND_PULLBACK",(3 if adxv>=25 else 2)
                except: return "TREND_PULLBACK",2

    if rv<=OVERSOLD_RSI_MAX:  # 38 not 50
        rp3=float(rsi_s.iloc[-3]) if len(rsi_s)>=3 else rv+5
        if rv<=rp3+8:
            low_52=float(wdf["close"].iloc[-min(52,len(wdf)):].min())
            near_low=float(wdf["close"].iloc[-1])<low_52*1.20
            avg_vol=float(wdf["volume"].iloc[-15:].mean())
            vol_dry=float(wdf["volume"].iloc[-1])<avg_vol*0.95
            score=sum([rv<35,vol_dry,near_low])+1
            return "OVERSOLD_EXHAUSTION",min(int(score),4)

    if rv<=DIV_RSI_MAX:
        low_10w=float(wdf["close"].iloc[-10:].min())
        if float(wdf["close"].iloc[-1])<=low_10w*1.08 and len(rsi_s)>=5:
            if rv-float(rsi_s.iloc[-5:-3].min())>1: return "RSI_DIVERGENCE",3

    return None,0

def _daily_confirm(ddf,setup):
    if len(ddf)<20: return False
    rsi_d=_rsi(ddf["close"]); rv=float(rsi_d.iloc[-1]); rp=float(rsi_d.iloc[-2])
    if setup=="TREND_PULLBACK":
        e20=_ema(ddf["close"],20); e50=_ema(ddf["close"],50); ltp=float(ddf["close"].iloc[-1])
        if not (TREND_RSI_MIN<=rv<=68): return False
        if not (ltp>float(e20.iloc[-1])>float(e50.iloc[-1])): return False
        return any(float(ddf["low"].iloc[i])<=float(e20.iloc[i])*1.005 for i in [-3,-2,-1])
    elif setup=="OVERSOLD_EXHAUSTION":
        if rv>45 or rv<=rp: return False  # tightened from 52
        return float(ddf["close"].iloc[-1])>=float(ddf["close"].iloc[-3:].min())*0.99
    elif setup=="RSI_DIVERGENCE":
        if rv>50: return False
        rsi_low=float(rsi_d.iloc[-6:-3].min()) if len(rsi_d)>=6 else rv
        return rv>rsi_low+2
    return False

def _detect_bp(ddf):
    if len(ddf)<60: return False
    close=ddf["close"]; volume=ddf["volume"]
    bp=None
    for days_ago in range(BP_MIN_DAYS,min(BP_MAX_DAYS+1,len(ddf)-25)):
        idx=len(ddf)-1-days_ago
        if idx<25: continue
        h20=float(close.iloc[idx-20:idx].max())
        dc=float(close.iloc[idx])
        avg_v=float(volume.iloc[idx-20:idx].mean())
        dv=float(volume.iloc[idx])
        if avg_v>0 and dc>h20 and dv/avg_v>=BP_VOL_BREAKOUT:
            bp=dc; break
    if bp is None: return False
    cur=float(close.iloc[-1])
    if cur<bp: return False
    peak=float(close.iloc[len(ddf)-1-days_ago:].max())
    pull=(peak-cur)/peak if peak>0 else 0
    if pull<BP_PULLBACK_MIN or pull>BP_PULLBACK_MAX: return False
    vr=float(_vol_ratio(volume).iloc[-1])
    if not np.isnan(vr) and vr>=BP_VOL_THRESHOLD: return False
    if float(_rsi(close).iloc[-1])<50: return False
    return True

# ── Quality + sizing ───────────────────────────────────────
def _quality(ddf):
    cl=ddf["close"]; ltp=float(cl.iloc[-1])
    av=float(_atr(ddf).iloc[-1])
    if np.isnan(av) or av<=0: return False,0,0,0,0,0
    rv=float(_rsi(cl).iloc[-1])
    if rv>68: return False,0,0,0,0,0
    if len(cl)>=200 and ltp<float(_ema(cl,200).iloc[-1])*0.95: return False,0,0,0,0,0
    sl=round(ltp-ATR_SL_MULT*av,2); tgt=round(ltp+ATR_TGT_MULT*av,2)
    part=round(ltp+ATR_PARTIAL_MULT*av,2)
    if sl>=ltp or tgt<=ltp or (ltp-sl)/ltp<0.003: return False,0,0,0,0,0
    rr=round((tgt-ltp)/(ltp-sl),2)
    if rr<MIN_RR: return False,0,0,0,0,0
    return True,sl,tgt,part,rr,av

def _qty(entry,sl):
    d=entry-sl
    if d<=0: return 0,0
    q=max(1,int(RISK_PER_TRADE/d))
    if q*entry>MAX_POSITION: q=int(MAX_POSITION/entry)
    return q,round(q*entry,0)

# ── Simulator ──────────────────────────────────────────────
def _sim(ddf,di,sl,tgt,part,hold):
    future=ddf.iloc[di+1:di+1+hold]
    if len(future)==0: return "DAY_CAP",float(ddf["close"].iloc[di]),False
    partial=False; cur_sl=sl; ep=float(ddf["close"].iloc[di])
    for _,row in future.iterrows():
        lo=float(row["low"]); hi=float(row["high"])
        if not partial and hi>=part: partial=True; cur_sl=ep
        if lo<=cur_sl: return "SL",cur_sl,partial
        if hi>=tgt: return "TARGET",tgt,partial
    return "DAY_CAP",float(future["close"].iloc[-1]),partial

def _pnl(entry,exit_p,qty,partial,part_p):
    if partial and qty>=2:
        h=qty//2; r=qty-h
        return round((part_p-entry)*h+(exit_p-entry)*r,2)
    return round((exit_p-entry)*qty,2)

# ── Download helper ────────────────────────────────────────
def _dl(ticker):
    try:
        raw=yf.download(ticker,start=START,end=END,interval="1d",progress=False,auto_adjust=True)
        if raw is None or len(raw)<60: return None
        if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.get_level_values(0)
        df=pd.DataFrame({
            "open":raw["Open"].squeeze().astype(float),
            "high":raw["High"].squeeze().astype(float),
            "low":raw["Low"].squeeze().astype(float),
            "close":raw["Close"].squeeze().astype(float),
            "volume":raw["Volume"].squeeze().astype(float),
        }).dropna()
        df.index=pd.to_datetime(df.index)
        return df if len(df)>=60 else None
    except: return None

# ── Main ───────────────────────────────────────────────────
def run_backtest():
    print("\n"+"="*60)
    print("  BACKTEST V6 - V4 + Fixes + Wider SL/TGT")
    print(f"  Period: {START} -> {END}  |  Stocks: {len(WATCHLIST)}")
    print("="*60)

    print("\n[1/3] Sector indices...")
    sector_data={}; done=set()
    for sec,proxy in SECTOR_PROXY.items():
        if proxy in done: continue
        df=_dl(proxy)
        if df is not None:
            sector_data[proxy]=df[["close","volume"]]; done.add(proxy)
            print(f"  {proxy}: OK")
        time.sleep(0.3)

    print(f"\n[2/3] Stocks ({len(WATCHLIST)})...")
    all_daily={}
    for i,t in enumerate(WATCHLIST,1):
        df=_dl(t)
        if df is not None: all_daily[t]=df
        if i%10==0: print(f"  {i}/{len(WATCHLIST)}...")
        time.sleep(0.25)
    print(f"  Loaded {len(all_daily)}")

    print(f"\n[3/3] Running...")
    trades=[]

    # Duplicate position tracker - V6 fix
    # Tracks open positions per ticker across entire backtest
    # Prevents same ticker being entered twice simultaneously
    open_until = {}  # ticker -> expiry_di

    for ticker,ddf in all_daily.items():
        dates=ddf.index.tolist()
        wdf_full=_to_weekly(ddf)
        sector=SECTOR_MAP.get(ticker,"UNKNOWN")
        s_proxy=SECTOR_PROXY.get(sector)
        s_data=sector_data.get(s_proxy) if s_proxy else None
        in_trade=False; trade_end=0

        for di in range(250,len(dates)):
            if in_trade and di<trade_end: continue
            in_trade=False
            # Duplicate block: skip if this ticker is already open
            if ticker in open_until and di < open_until[ticker]:
                continue
            dt=dates[di]; ddf_to=ddf.iloc[:di+1]
            wdf_to=wdf_full[wdf_full.index<=dt]
            if len(wdf_to)<14: continue

            sector_up=_sector_uptrend(s_data,dt)
            setup=None; wscore=0

            # Try original 3 setups
            s,ws=_detect_weekly(wdf_to)
            if s and _daily_confirm(ddf_to,s):
                setup=s; wscore=ws

            # Try BREAKOUT_PULLBACK
            if setup is None and _detect_bp(ddf_to):
                setup="BREAKOUT_PULLBACK"; wscore=3

            if setup is None: continue

            # Sector gate - hard block for trend/breakout setups
            if not sector_up and setup in ("TREND_PULLBACK","BREAKOUT_PULLBACK"):
                continue

            ok,sl,tgt,part,rr,av=_quality(ddf_to)
            if not ok: continue
            entry=float(ddf_to["close"].iloc[-1])
            qty,cap=_qty(entry,sl)
            if qty==0: continue

            p_win=SETUP_WIN_RATE.get(setup,0.52)
            ev=round((p_win*(tgt-entry)/entry-(1-p_win)*(entry-sl)/entry)*100,2)
            if ev<0: continue

            exit_r,exit_p,partial=_sim(ddf,di,sl,tgt,part,HOLD_DAYS)
            pnl=_pnl(entry,exit_p,qty,partial,part if partial else exit_p)
            result="WIN" if pnl>0 else "LOSS"

            trades.append({
                "ticker":ticker,"entry_date":dt.strftime("%Y-%m-%d"),
                "exit_date":dates[min(di+HOLD_DAYS,len(dates)-1)].strftime("%Y-%m-%d"),
                "setup_type":setup,"sector":sector,"sector_uptrend":sector_up,
                "entry":round(entry,2),"exit":round(exit_p,2),
                "sl":round(sl,2),"target":round(tgt,2),"partial_tgt":round(part,2),
                "partial_taken":partial,"rr":rr,"qty":qty,"capital":cap,
                "pnl":pnl,"exit_reason":exit_r,"ev_pct":ev,"result":result,
            })
            in_trade=True; trade_end=di+HOLD_DAYS
            open_until[ticker]=di+HOLD_DAYS  # track for duplicate block
            if len(trades)%200==0 and len(trades)>0:
                print(f"  Trades: {len(trades)}")

    print(f"  Total: {len(trades)}")
    if not trades: print("  No trades."); return

    ts=datetime.now().strftime("%Y%m%d_%H%M")
    outfile=f"backtest_v6b_{ts}.csv"
    df_out=pd.DataFrame(trades)
    df_out.to_csv(outfile,index=False)
    print(f"\n  Saved: {outfile}")
    _print_results(df_out)

def _print_results(df):
    print("\n"+"="*60)
    print("  BACKTEST V6b RESULTS")
    print("="*60)
    w=df[df["result"]=="WIN"]; l=df[df["result"]=="LOSS"]
    wr=len(w)/len(df)*100; tot=df["pnl"].sum()
    pf=abs(w["pnl"].sum()/l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 999
    yrs=max(1,(pd.to_datetime(df["exit_date"].max())-pd.to_datetime(df["entry_date"].min())).days/365)
    eq=CAPITAL+df["pnl"].cumsum(); pk=CAPITAL; mdd=0
    for v in eq: pk=max(pk,v); mdd=max(mdd,(pk-v)/pk)

    print(f"\n  Trades       : {len(df)}  ({len(df)/yrs:.0f}/yr, {len(df)/(yrs*12):.1f}/mo)")
    print(f"  Win rate     : {wr:.1f}%  ({len(w)}W/{len(l)}L)")
    print(f"  Total P&L    : Rs {tot:+,.0f}  ({tot/CAPITAL*100:+.1f}%)")
    print(f"  Annual return: {tot/CAPITAL/yrs*100:+.1f}%/yr")
    print(f"  Monthly avg  : Rs {tot/(yrs*12):+,.0f}/mo")
    print(f"  Avg win      : Rs {w['pnl'].mean():+,.0f}")
    print(f"  Avg loss     : Rs {l['pnl'].mean():+,.0f}")
    print(f"  Profit factor: {pf:.2f}x")
    print(f"  Max drawdown : {mdd*100:.1f}%")

    print(f"\n  COMPARISON")
    print(f"  {'Metric':<22} {'Old':>6} {'V4':>7} {'V6':>7} {'V6b':>7}")
    print(f"  {'-'*56}")
    print(f"  {'Win Rate':<22} {'52.1%':>6} {'54.6%':>7} {'57.8%':>7} {wr:.1f}%")
    print(f"  {'Monthly avg':<22} {'6,090':>6} {'9,538':>7} {'9,203':>7} {tot/(yrs*12):,.0f}")
    print(f"  {'Annual return':<22} {'18.4%':>6} {'19.1%':>7} {'18.4%':>7} {tot/CAPITAL/yrs*100:.1f}%")
    print(f"  {'Max drawdown':<22} {'4.2%':>6} {'5.2%':>7} {'4.5%':>7} {mdd*100:.1f}%")
    print(f"  {'Profit factor':<22} {'1.96x':>6} {'1.45x':>7} {'1.48x':>7} {pf:.2f}x")

    print(f"\n  BY SETUP")
    for s,g in df.groupby("setup_type"):
        ww=len(g[g["result"]=="WIN"]); ll=g[g["result"]=="LOSS"]
        pf2=abs(g[g["result"]=="WIN"]["pnl"].sum()/ll["pnl"].sum()) if len(ll)>0 and ll["pnl"].sum()!=0 else 999
        print(f"  {s:<25}: {len(g):4d}  wr={ww/len(g)*100:.0f}%  avg=Rs {g['pnl'].mean():+,.0f}  pf={pf2:.2f}x")

    print(f"\n  BY EXIT")
    for r,g in df.groupby("exit_reason"):
        ww=len(g[g["result"]=="WIN"])
        print(f"  {r:<12}: {len(g):4d}  wr={ww/len(g)*100:.0f}%  avg=Rs {g['pnl'].mean():+,.0f}  total=Rs {g['pnl'].sum():+,.0f}")

    pt=df[df["partial_taken"]==True]; np_=df[df["partial_taken"]==False]
    print(f"\n  PARTIAL PROFIT")
    if len(pt)>0: print(f"  With partial : {len(pt)} trades  avg Rs {pt['pnl'].mean():+,.0f}")
    if len(np_)>0: print(f"  No partial   : {len(np_)} trades  avg Rs {np_['pnl'].mean():+,.0f}")

    print(f"\n  BY SECTOR")
    for s,g in df.groupby("sector"):
        ww=len(g[g["result"]=="WIN"])
        print(f"  {s:<12}: {len(g):4d}  wr={ww/len(g)*100:.0f}%  avg=Rs {g['pnl'].mean():+,.0f}")

    print(f"\n  YEARLY P&L")
    df["year"]=pd.to_datetime(df["exit_date"]).dt.year
    for yr,g in df.groupby("year"):
        pct=g["pnl"].sum()/CAPITAL*100; wr_=len(g[g["result"]=="WIN"])/len(g)*100
        print(f"  {yr}  {len(g):4d}  {'▲' if g['pnl'].sum()>0 else '▼'} Rs {g['pnl'].sum():+9,.0f}  ({pct:+.1f}%)  wr={wr_:.0f}%")

    print(f"\n  TOP 10 TICKERS")
    st=[(t.replace(".NS",""),len(g),len(g[g["result"]=="WIN"])/len(g),g["pnl"].sum())
        for t,g in df.groupby("ticker") if len(g)>=5]
    st.sort(key=lambda x:-x[3])
    for t,n,wr_,tot_ in st[:10]:
        print(f"  {t:<15}: {n:3d}  wr={wr_*100:.0f}%  Rs {tot_:+,.0f}  {'█'*int(wr_*20)}")

    beats_old = sum([wr>52.1, tot/(yrs*12)>6090, mdd*100<4.2, pf>1.96])
    beats_v4  = sum([wr>54.6, tot/(yrs*12)>9538, mdd*100<5.2, pf>1.45])
    beats_v6  = sum([wr>57.8, tot/(yrs*12)>9203, mdd*100<4.5, pf>1.48])
    print(f"\n  VERDICT vs Old: {beats_old}/4 beaten")
    print(f"  VERDICT vs V4:  {beats_v4}/4 beaten")
    print(f"  VERDICT vs V6:  {beats_v6}/4 beaten")
    invalid=[]
    if wr<57.8: invalid.append(f"WR {wr:.1f}% < V6 57.8%")
    if tot/(yrs*12)<9538: invalid.append(f"Monthly Rs {tot/(yrs*12):,.0f} < V4 Rs 9,538 (must beat V4)")
    if mdd*100>8.0: invalid.append(f"Drawdown {mdd*100:.1f}% > 8% limit")
    if pf<1.45: invalid.append(f"Profit factor {pf:.2f}x < V4 1.45x")
    if mdd*100>6.0: invalid.append(f"Drawdown {mdd*100:.1f}% > 6% limit")
    if len(df)/yrs<50: invalid.append(f"Only {len(df)/yrs:.0f} trades/yr < 50 min")
    if invalid:
        print(f"  V6b INVALIDATED:")
        for i in invalid: print(f"    - {i}")
        print("  -> Do NOT build live bot on V6 - revert to V4")
    else:
        print("  V6 VALID - beats V4 - proceed with live bot build")
    if False: print("")  # placeholder
    else: print("  -> V4 does not beat old system - do not build as-is")
    print("="*60)

if __name__=="__main__":
    t0=time.time()
    run_backtest()
    el=round(time.time()-t0)
    print(f"\n  Time: {el}s ({el//60}m {el%60}s)")
