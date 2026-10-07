import numpy as np
import pytest
from dx27.intelligence.sentinel.research.reference_experiment import fit_logistic,auc,drawdown_outcome,compare_arms


def test_drawdown_running_peak_includes_anchor_and_followup():
    assert drawdown_outcome([100]+[101]*19+[94])==1
    assert drawdown_outcome([100]+[110]*19+[104])==1
    assert drawdown_outcome([100]+[101]*20)==0
    with pytest.raises(ValueError):drawdown_outcome([100]*20)


def test_fixed_optimizer_stationarity_scaling_and_prediction():
    x=np.arange(80,dtype=float).reshape(40,2)
    y=np.asarray([0]*20+[1]*20)
    model=fit_logistic(x,y)
    assert model==fit_logistic(x,y)
    design=np.column_stack((np.ones(len(x)),(x-model.mean)/model.scale))
    grad=design.T@(model.predict(x)-y)/len(x)+np.r_[0.,model.coefficient[1:]]
    assert np.max(abs(grad))<=1e-8
    assert auc(y,model.predict(x))==1
    with pytest.raises(ValueError):fit_logistic(x,np.zeros(40))
    with pytest.raises(ValueError):model.predict([[np.nan,np.nan]])


def test_auc_ties_and_missing_class():
    assert auc([1,0],[.5,.5])==.5
    assert auc([1,0],[1,0])==1
    assert auc([1,1],[1,0]) is None


def test_paired_audit_cannot_promote_or_shift_grid():
    rng=np.random.default_rng(627)
    train=rng.normal(size=(80,3));ds=rng.normal(size=(80,2));y=(train[:,0]>0).astype(int)
    audit=rng.normal(size=(10,3));sd=rng.normal(size=(10,2));ay=(audit[:,0]>0).astype(int)
    result=compare_arms(train,ds,y,audit,sd,ay,np.arange(0,200,20),200)
    assert set(result['auc'])=={'VECTOR','VECTOR_S','VECTOR_D','VECTOR_SD'}
    assert result['market_effectiveness_result']=='INSUFFICIENT_EVIDENCE'
    assert not result['confirmation_pass'] and not result['operational_enabled']
    with pytest.raises(ValueError,match='anchors'):compare_arms(train,ds,y,audit,sd,ay,[0,20,41,60,80,100,120,140,160,180],200)
