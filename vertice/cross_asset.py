"""Simple baseline vs incremental cross-asset prediction tests."""
from __future__ import annotations
import numpy as np
import pandas as pd
def chronological_split(df:pd.DataFrame,train_fraction:float=0.7):
    if not 0<train_fraction<1: raise ValueError("train_fraction must be between 0 and 1")
    x=df.sort_index(); cut=int(len(x)*train_fraction)
    if cut<3 or len(x)-cut<2: raise ValueError("not enough rows for chronological split")
    return x.iloc[:cut].copy(),x.iloc[cut:].copy()
def _fit_ols(x:np.ndarray,y:np.ndarray)->np.ndarray:
    return np.linalg.lstsq(np.column_stack([np.ones(len(x)),x]),y,rcond=None)[0]
def incremental_prediction_test(frame:pd.DataFrame,*,target:str,base_features:list[str],added_feature:str,train_fraction:float=0.7)->dict:
    """Compare out-of-sample MSE; caller must supply lagged predictors to prevent leakage."""
    cols=[target,*base_features,added_feature]; data=frame[cols].replace([np.inf,-np.inf],np.nan).dropna().sort_index()
    train,test=chronological_split(data,train_fraction); yt,ys=train[target].to_numpy(),test[target].to_numpy()
    xb,xbs=train[base_features].to_numpy(),test[base_features].to_numpy(); xa,xas=train[[*base_features,added_feature]].to_numpy(),test[[*base_features,added_feature]].to_numpy()
    b0,b1=_fit_ols(xb,yt),_fit_ols(xa,yt); p0=np.column_stack([np.ones(len(test)),xbs])@b0; p1=np.column_stack([np.ones(len(test)),xas])@b1
    m0,m1=float(np.mean((ys-p0)**2)),float(np.mean((ys-p1)**2))
    return {"n_train":len(train),"n_test":len(test),"mse_base":m0,"mse_augmented":m1,"relative_mse_improvement":(m0-m1)/m0 if m0 else np.nan,"interpretation":"predictive comparison only; not causality"}
