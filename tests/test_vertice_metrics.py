import pandas as pd
from vertice.data_pipeline import quality_report, add_returns
from vertice.metrics import path_runs, lagged_corr

def sample():
 return pd.DataFrame({'timestamp':pd.date_range('2026-01-01 12:00',periods=4,freq='min',tz='UTC'),'symbol':['AAA']*4,'open':[10,10,11,10],'high':[10,11,11,10],'low':[9,10,10,9],'close':[10,11,10,10],'volume':[1,2,3,4]})
def test_quality_report_counts_clean_data():
 q=quality_report(sample()); assert q.rows==4 and q.symbols==1 and q.duplicate_symbol_timestamps==0
def test_returns_horizon_one():
 out=add_returns(sample(),horizons=(1,)); assert round(out.loc[1,'return_1'],6)==0.1
def test_run_lengths():
 r=path_runs(pd.Series([1,2,3,2,1,0])); assert r['up_run_max']==2 and r['down_run_max']==3
def test_lagged_corr_reports_requested_lags():
 r=pd.DataFrame({'A':[1,2,3,4,5,6],'B':[2,4,6,8,10,12]}); out=lagged_corr(r,'A','B',max_lag=2,min_periods=3); assert list(out.lag_bars)==[-2,-1,0,1,2]
