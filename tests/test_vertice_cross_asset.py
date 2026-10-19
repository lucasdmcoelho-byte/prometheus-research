import pandas as pd
import numpy as np
from vertice.cross_asset import chronological_split,incremental_prediction_test

def test_chronological_split_preserves_order():
 x=pd.DataFrame({'x':range(10)},index=pd.RangeIndex(10)); a,b=chronological_split(x,.7); assert a.index.max()<b.index.min()
def test_incremental_prediction_returns_oos_metrics():
 rng=np.random.default_rng(4); n=200; a=rng.normal(size=n); b=rng.normal(size=n); y=.3*a+.1*b+rng.normal(scale=.3,size=n); x=pd.DataFrame({'y':y,'base':b,'added':a},index=pd.RangeIndex(n)); out=incremental_prediction_test(x,target='y',base_features=['base'],added_feature='added'); assert out['n_test']>0 and 'relative_mse_improvement' in out
