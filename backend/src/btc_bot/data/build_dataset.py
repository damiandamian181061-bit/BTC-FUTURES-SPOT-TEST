# Rebuilds data/btc_1h.csv from the raw Binance monthly zips (BTCUSDT-1h-YYYY-MM.zip, unzipped to CSV).
# Run from a folder containing the monthly CSVs, e.g. project/raw/. Source: https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/
import pandas as pd, glob
from ..config import DATA_DIR
cols=["open_time","open","high","low","close","volume","close_time","qav","trades","tbb","tbq","ignore"]
dfs=[]
for f in sorted(glob.glob("*.csv")):
    d=pd.read_csv(f,header=None,names=cols)
    if isinstance(d.iloc[0,0],str): d=d.iloc[1:].astype({c:float for c in cols[:11]})
    dfs.append(d)
df=pd.concat(dfs).sort_values("open_time").drop_duplicates("open_time")
t=df.open_time.astype("int64"); t=t.where(t<1e14, t//1000)  # handle micro/milliseconds
df["ts"]=pd.to_datetime(t,unit="ms",utc=True)
df=df.set_index("ts")[["open","high","low","close","volume"]].astype(float)
# check gaps
gaps=df.index.to_series().diff().dt.total_seconds().div(3600); print("rows",len(df),df.index[0],"->",df.index[-1]); print("months missing:", sorted(set(pd.period_range(df.index[0],df.index[-1],freq="M").astype(str))-set(df.index.to_period("M").astype(str).unique())))
print("gap hours >1:", int((gaps>1).sum()), "largest gap h:", gaps.max())
df.to_csv(DATA_DIR / "btc_1h.csv"); print(df.tail(2))
