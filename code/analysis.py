# Autocorrelation, hour-of-day scan, best-window OOS test, day-of-week, volume-vs-return.  Run from project/: python3 code/analysis.py
import pandas as pd, numpy as np
df=pd.read_csv("data/btc_1h.csv",index_col=0,parse_dates=True)
r=np.log(df.close).diff().dropna()            # hourly log returns
FEE=0.0010  # taker in+out = 0.10%
IS=r[:"2022-12-31"]; OOS=r["2023-01-01":]
print(f"In-sample {IS.index[0].date()}..{IS.index[-1].date()} ({len(IS)} h) | Out-of-sample {OOS.index[0].date()}..{OOS.index[-1].date()} ({len(OOS)} h)\n")

# ---------- 1. Mean reversion / momentum test ----------
print("=== TEST 1: does a loss predict a win? (autocorrelation of returns) ===")
d=np.log(df.close.resample("1D").last()).diff().dropna()
for name,s in (("hourly",r),("daily (00:00 UTC)",d)):
    for lbl,x in (("in-sample",s[:"2022-12-31"]),("out-of-sample",s["2023-01-01":])):
        ac=x.autocorr(1); n=len(x); se=1/np.sqrt(n)
        prev=x.shift(1).dropna(); cur=x.loc[prev.index]
        p_up_after_down=(cur[prev<0]>0).mean(); p_up_after_up=(cur[prev>0]>0).mean()
        print(f"{name:18s} {lbl:14s} lag-1 autocorr {ac:+.3f} (2σ ≈ ±{2*se:.3f}) | P(up | prev down) {p_up_after_down:.1%} | P(up | prev up) {p_up_after_up:.1%}")
print()

# ---------- 2. Time-of-day scan ----------
print("=== TEST 2: hour-of-day scan (mean log return per hour, bp = 0.01%) ===")
tab=pd.DataFrame({"IS":IS.groupby(IS.index.hour).mean()*1e4,"OOS":OOS.groupby(OOS.index.hour).mean()*1e4})
tab["IS_t"]=IS.groupby(IS.index.hour).apply(lambda x: x.mean()/x.std()*np.sqrt(len(x)))
tab["OOS_t"]=OOS.groupby(OOS.index.hour).apply(lambda x: x.mean()/x.std()*np.sqrt(len(x)))
print(tab.round(2).to_string())
print("\ncorrelation of hourly means IS vs OOS:", round(tab.IS.corr(tab.OOS),2))
print("avg hourly return overall (bp): IS %.2f  OOS %.2f  | fee per round trip = %.0f bp" % (IS.mean()*1e4, OOS.mean()*1e4, FEE*1e4))

# ---------- 3. Best in-sample windows, tested out of sample ----------
print("\n=== TEST 3: pick best 2h and 4h windows in-sample, test them out-of-sample ===")
def window_ret(s,start,L):
    hrs=[(start+i)%24 for i in range(L)]; return s[s.index.hour.isin(hrs)]
def stats(x,L,fee):
    # one trade per day covering L hours; aggregate to daily
    daily=x.groupby(x.index.date).sum(); daily=daily[x.groupby(x.index.date).count()==L]
    net=daily-fee; return len(daily), daily.mean()*1e4, (daily>0).mean(), net.mean()*1e4, net.sum()*100, net.mean()/net.std()*np.sqrt(365)
for L in (2,4):
    best=max(range(24), key=lambda h: window_ret(IS,h,L).mean())
    worst=min(range(24), key=lambda h: window_ret(IS,h,L).mean())
    for tag,h in (("best",best),("worst",worst)):
        for lbl,s in (("IS",IS),("OOS",OOS)):
            n,gross,wr,net,cum,sh=stats(window_ret(s,h,L),L,FEE)
            print(f"{L}h window {tag:5s} {h:02d}:00-{(h+L)%24:02d}:00 UTC | {lbl:3s} n={n:4d} gross {gross:+6.1f} bp/day, win {wr:.1%}, net after fee {net:+6.1f} bp/day, cum net {cum:+7.1f}%, Sharpe {sh:+.2f}")
# Quantpedia window
for lbl,s in (("IS",IS),("OOS",OOS)):
    n,gross,wr,net,cum,sh=stats(window_ret(s,21,2),2,FEE)
    print(f"Quantpedia 21:00-23:00 UTC      | {lbl:3s} n={n:4d} gross {gross:+6.1f} bp/day, win {wr:.1%}, net after fee {net:+6.1f} bp/day, cum net {cum:+7.1f}%, Sharpe {sh:+.2f}")

# ---------- 4. Day-of-week ----------
print("\n=== TEST 4: day-of-week (daily log return, bp) ===")
dow=pd.DataFrame({"IS":d[:"2022-12-31"].groupby(d[:"2022-12-31"].index.dayofweek).mean()*1e4,"OOS":d["2023-01-01":].groupby(d["2023-01-01":].index.dayofweek).mean()*1e4}); dow.index=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]; print(dow.round(1).to_string())

# ---------- 5. Volume vs return ----------
print("\n=== TEST 5: do high-volume hours have higher returns? ===")
v=df.volume.loc[r.index]; vh=v.groupby(v.index.hour).mean(); vh=vh/vh.mean()
print("busiest hours UTC:", list(vh.sort_values(ascending=False).index[:5]), "| quietest:", list(vh.sort_values().index[:5]))
print("corr(hour avg volume, hour avg return): IS %.2f, OOS %.2f" % (vh.corr(tab.IS), vh.corr(tab.OOS)))
q=pd.qcut(v,4,labels=["low","mid-low","mid-high","high"]); print(r.groupby(q).agg(mean_bp=lambda x: x.mean()*1e4, win=lambda x:(x>0).mean()).round(2).to_string())

# ---------- 6. Strategy comparison (fees in, IS/OOS) ----------
print("\n=== TEST 6: candidate strategies, fees included ===")
c=df.close; daily=c.resample("1D").last(); dret=np.log(daily).diff()
ma50=daily.rolling(50).mean(); ma200=daily.rolling(200).mean(); vol=dret.rolling(30).std(); volmed=vol.expanding().median()
MAKER=0.0004; TAKER=0.0010
def per(x,lbl): return x[:"2022-12-31"] if lbl=="IS" else x["2023-01-01":]
def show(name,p):
    out=[]
    for lbl in ("IS","OOS"):
        seg=per(p,lbl); x=seg.dropna(); yrs=len(seg)/365; cum=np.exp(x.sum())-1; eq=np.exp(x.cumsum()); dd=(eq/eq.cummax()-1).min()
        out.append(f"{lbl}: {(1+cum)**(1/yrs)-1:+6.1%}/yr, maxDD {dd:6.1%}, Sharpe {x.mean()/x.std()*np.sqrt(365):+.2f}")
    print(f"{name:50s} | "+" | ".join(out))
show("Buy & hold", dret)
w=r[r.index.hour.isin([21,22])]; cnt=w.groupby(w.index.date).count(); wd=w.groupby(w.index.date).sum(); wd=wd[cnt==2]; wd.index=pd.to_datetime(wd.index,utc=True); wd=wd.reindex(daily.index)
show("A. 21-23 UTC long daily (maker)", wd-MAKER); show("A. 21-23 UTC long daily (taker)", wd-TAKER)
show("A2. 21-23 UTC only when > 50d MA (maker)", (wd-MAKER).where(daily>ma50)); show("A3. 21-23 UTC only when > 200d MA (maker)", (wd-MAKER).where(daily>ma200)); show("A4. 21-23 UTC only on high-vol days (maker)", (wd-MAKER).where(vol>volmed))
pos=(daily>ma200).astype(int).shift(1); show("B. Long if > 200d MA, else cash", (dret*pos-pos.diff().abs().fillna(0)*TAKER).where(ma200.shift(1).notna()))
pos50=(daily>ma50).astype(int).shift(1); show("B2. Long if > 50d MA, else cash", (dret*pos50-pos50.diff().abs().fillna(0)*TAKER).where(ma50.shift(1).notna()))
posls=np.sign(daily-ma200).shift(1); show("B3. Long > 200d MA, short below", (dret*posls-posls.diff().abs().fillna(0)/2*TAKER).where(ma200.shift(1).notna()))
contra=-np.sign(dret.shift(1)); show("C. Fade yesterday daily (taker)", (dret*contra-TAKER).where(contra.notna()))
show("C2. Buy after down day, only if > 200d MA (taker)", (dret-TAKER).where((dret.shift(1)<0)&(daily.shift(1)>ma200.shift(1))))
