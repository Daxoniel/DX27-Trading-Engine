"""Fixed logistic ablation research. No forecast or live-output authorization."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class FixedLogistic:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coefficient: tuple[float, ...]
    iterations: int

    def predict(self, x):
        a=np.asarray(x,dtype=float)
        if a.ndim!=2 or a.shape[1]!=len(self.mean) or not np.all(np.isfinite(a)):
            raise ValueError('finite fitted feature vector required')
        z=np.column_stack((np.ones(len(a)),(a-self.mean)/self.scale))@self.coefficient
        return np.exp(-np.logaddexp(0.,-z))


def fit_logistic(x, y):
    a=np.asarray(x,dtype=float);target=np.asarray(y,dtype=float)
    if a.ndim!=2 or len(a)<2 or target.shape!=(len(a),) or not np.all(np.isfinite(a)) or not np.all(np.isin(target,[0,1])) or len(np.unique(target))!=2:
        raise ValueError('finite binary two-class development sample required')
    mean=a.mean(axis=0);scale=a.std(axis=0);scale[scale==0]=1
    design=np.column_stack((np.ones(len(a)),(a-mean)/scale))
    coef=np.zeros(design.shape[1]);step=1/(.25*np.linalg.norm(design,2)**2/len(a)+1)
    for iteration in range(20000):
        z=design@coef;prob=np.exp(-np.logaddexp(0.,-z))
        grad=design.T@(prob-target)/len(a)+np.r_[0.,coef[1:]]
        if np.max(np.abs(grad))<=1e-8:
            return FixedLogistic(tuple(mean),tuple(scale),tuple(coef),iteration)
        coef-=step*grad
    raise ValueError('FAIL_INTEGRITY: fixed optimizer did not converge')


def drawdown_outcome(prices):
    a=np.asarray(prices,dtype=float)
    if a.shape!=(21,) or not np.all(np.isfinite(a)) or np.any(a<=0):
        raise ValueError('anchor and all 20 consecutive positive closes required')
    return int(np.max(1-a[1:]/np.maximum.accumulate(a)[1:])>=.05)


def auc(y, scores):
    y=np.asarray(y);s=np.asarray(scores,dtype=float)
    if y.shape!=s.shape or not np.all(np.isin(y,[0,1])) or not np.all(np.isfinite(s)):
        raise ValueError('finite paired binary outcomes/scores required')
    pos=s[y==1];neg=s[y==0]
    if not len(pos) or not len(neg):return None
    return float(np.mean((pos[:,None]>neg)+.5*(pos[:,None]==neg)))


def compare_arms(development_vector, development_sd, development_y, audit_vector, audit_sd, audit_y, anchor_indices, timeline_sessions):
    """Known-history audit only. Inputs already aligned to fixed 20-session grid.

    Temporal/source admission and split/purge happen at the typed tape boundary,
    not inferred from naked arrays. This routine can never issue production PASS.
    """
    dx=np.asarray(development_vector,dtype=float);ds=np.asarray(development_sd,dtype=float)
    ax=np.asarray(audit_vector,dtype=float);ass=np.asarray(audit_sd,dtype=float)
    y=np.asarray(audit_y);idx=np.asarray(anchor_indices)
    if ds.shape!=(len(dx),2) or ass.shape!=(len(ax),2) or ax.ndim!=2 or dx.ndim!=2 or ax.shape[1]!=dx.shape[1] or y.shape!=(len(ax),) or idx.shape!=y.shape:
        raise ValueError('paired complete four-arm dimensions required')
    if not np.all(np.isfinite(ds)) or not np.all(np.isfinite(ass)):
        raise ValueError('no missing-input imputation permitted')
    if len(idx) and (np.any(idx<0) or np.any(idx>=timeline_sessions) or np.any(np.diff(idx)<20) or np.any(idx%20)):
        raise ValueError('unshifted nonoverlapping 20-session anchors required')
    arms={'VECTOR':(), 'VECTOR_S':(0,), 'VECTOR_D':(1,), 'VECTOR_SD':(0,1)}
    models={};pred={};scores={}
    for name,cols in arms.items():
        train=np.column_stack((dx,ds[:,cols]));audit=np.column_stack((ax,ass[:,cols]))
        models[name]=fit_logistic(train,development_y)
        pred[name]=models[name].predict(audit);scores[name]=auc(y,pred[name])
    rng=np.random.default_rng(627);diff=[]
    if timeline_sessions<40:raise ValueError('40-session bootstrap chronology required')
    for _ in range(1000):
        # Paired rows are resampled through their ORIGINAL calendar blocks;
        # no artificial joins create fresh outcomes or targets.
        starts=rng.integers(0,timeline_sessions-40+1,size=int(np.ceil(timeline_sessions/40)))
        sampled=np.concatenate([np.arange(s,s+40) for s in starts])[:timeline_sessions]
        weights=np.bincount(sampled,minlength=timeline_sessions)[idx]
        rows=np.repeat(np.arange(len(y)),weights)
        a=auc(y[rows],pred['VECTOR'][rows]);b=auc(y[rows],pred['VECTOR_SD'][rows])
        if a is not None and b is not None:diff.append(b-a)
    interval=list(map(float,np.quantile(diff,[.025,.975],method='linear'))) if diff else None
    increment=None if scores['VECTOR'] is None else scores['VECTOR_SD']-scores['VECTOR']
    positives=int(np.sum(y==1));negatives=int(np.sum(y==0))
    sufficient=positives>=30 and negatives>=30 and len(diff)==1000
    numeric=None if not sufficient else increment>=.02 and interval[0]>0
    return {'role':'KNOWN_HISTORY_AUDIT_NOT_CONFIRMATION','market_effectiveness_result':'INSUFFICIENT_EVIDENCE' if not sufficient else ('AUDIT_NUMERIC_PASS_ONLY' if numeric else 'FAIL'),
            'auc':scores,'primary_auc_increment':increment,'primary_95pct_block_interval':interval,'valid_bootstrap_replicates':len(diff),
            'positive_outcomes':positives,'negative_outcomes':negatives,'confirmation_pass':False,'operational_enabled':False,
            'fitted_models':{name:vars(model) for name,model in models.items()}}


def audit_recorded_tape(calendar, states, spy_closes, protocol):
    """Typed-tape entry point with locked causal S/D, split/purge and grid rules.

    `spy_closes` maps session labels to complete positive closes; only the label
    builder consumes future outcomes. Runtime feature computation sees prior
    immutable snapshots only. This is development/audit, never fresh OOS.
    """
    from dx27.intelligence.sentinel.research.composite_reference import ReferenceBuilder
    from dx27.intelligence.sentinel.models import DataStatus
    from dx27.intelligence.sentinel.identity import stable_content_hash
    if not isinstance(states,tuple):raise TypeError('immutable recorded states required')
    by_day={s.snapshot.session_id:s for s in states}
    if len(by_day)!=len(states):raise ValueError('duplicate original-cutoff snapshots')
    builder=ReferenceBuilder(calendar)
    features=protocol['inputs']
    records=[]
    for state in sorted(states,key=lambda s:s.snapshot.session_id):
        builder._check(state)
        s,d=builder.build(state,states)
        vals=[state.measurement(name) for name in features]
        if any(m.data_status is not DataStatus.AVAILABLE for m in vals) or s.value is None or d.value is None:continue
        records.append((state.snapshot.session_id,[m.value for m in vals],[s.value,d.value],state.snapshot.snapshot_id))
    records={r[0]:r for r in records}
    sessions=calendar.sessions
    audit_start=next((i for i,s in enumerate(sessions) if s.session_id>='2020-01-01'),None)
    development_start=next((i for i,s in enumerate(sessions) if s.session_id>='2005-01-01' and s.session_id in records),None)
    if audit_start is None or development_start is None:
        return {'market_effectiveness_result':'BLOCKED_DATA','reason':'no paired admissible development/audit features','confirmation_pass':False}
    audit_end=max(i for i,s in enumerate(sessions) if s.session_id<='2026-09-30')
    train=[];audit=[];indices=[];missing_features=missing_outcomes=0
    for role,start,stop,dest in [('DEVELOPMENT',development_start,audit_start-40,train),('AUDIT',audit_start,audit_end+1,audit)]:
        for i in range(start,stop,20):
            if i+20>=len(sessions) or i+20>=stop:
                missing_outcomes+=1;continue # No target crosses purge/audit boundary.
            day=sessions[i].session_id
            if day not in records:missing_features+=1;continue
            path=[spy_closes.get(s.session_id) for s in sessions[i:i+21]]
            if any(v is None for v in path):missing_outcomes+=1;continue
            label=drawdown_outcome(path)
            dest.append((records[day],label))
            if role=='AUDIT':indices.append(i-audit_start)
    if not train or not audit:
        return {'market_effectiveness_result':'BLOCKED_DATA','reason':'no complete paired grid outcomes','confirmation_pass':False,'missing_features':missing_features,'missing_outcomes':missing_outcomes}
    result=compare_arms([r[1] for r,y in train],[r[2] for r,y in train],[y for r,y in train],
                        [r[1] for r,y in audit],[r[2] for r,y in audit],[y for r,y in audit],indices,audit_end-audit_start+1)
    result.update({'recorded_tape_digest':stable_content_hash(states),'missing_features':missing_features,'missing_outcomes':missing_outcomes,
                   'audit_snapshot_ids':[r[3] for r,y in audit],'development_rows':len(train),'audit_rows':len(audit)})
    return result
