"""Small NumPy-only trainer. Runtime inference does not import NumPy."""
import numpy as np


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -35, 35)))


def fit(x, y, penalty):
    if x.ndim!=2 or y.shape!=(len(x),) or not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isin(y,[0,1]).all():
        raise ValueError('Finite nonempty feature matrix and aligned labels required')
    if not np.isfinite(penalty) or penalty<=0:raise ValueError('Positive finite regularization required')
    scale = np.maximum(np.sqrt(np.mean(x*x, axis=0)), .015)
    z = np.clip(x/scale, -8, 8)
    beta = np.zeros(z.shape[1])
    def objective(b):
        pred=np.einsum('ij,j->i',z,b,optimize=False)
        return np.sum(np.logaddexp(0,pred)-y*pred)+penalty*np.sum(b*b)/2
    for _ in range(45):
        # Explicit contractions avoid spurious matmul floating-point exceptions
        # on the bundled macOS BLAS. Do not suppress numerical warnings.
        p=sigmoid(np.einsum('ij,j->i',z,beta,optimize=False))
        grad=np.einsum('ij,i->j',z,p-y,optimize=False)+penalty*beta
        hessian=np.einsum('ni,nj->ij',z,(p*(1-p))[:,None]*z,optimize=False)+np.eye(len(beta))*penalty
        delta=np.linalg.solve(hessian,grad)
        step=1.; before=objective(beta)
        while step>1e-6 and objective(beta-step*delta)>before:
            step/=2
        beta-=step*delta
        if np.max(np.abs(step*delta))<1e-7:break
    if not np.isfinite(beta).all():raise ValueError('Non-finite fitted coefficients')
    return {'scale':scale.tolist(),'weights':beta.tolist()}


def probabilities(x, model):
    scaled=np.clip(x/np.asarray(model['scale']),-8,8)
    if not np.isfinite(scaled).all():raise ValueError('Non-finite prediction inputs')
    return sigmoid(np.einsum('ij,j->i',scaled,np.asarray(model['weights']),optimize=False)/model.get('temperature',1.))


def metrics(y,p):
    y=np.asarray(y);p=np.asarray(p)
    if y.ndim!=1 or y.shape!=p.shape or not len(y) or not np.isin(y,[0,1]).all() or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
        raise ValueError('Aligned nonempty binary labels and finite probabilities in [0,1] required')
    p=np.clip(p,1e-9,1-1e-9)
    bins=[]
    for i in range(10):
        mask=(p>=i/10)&(p<(i+1)/10 if i<9 else p<=1)
        if mask.any():bins.append({'lower':i/10,'n':int(mask.sum()),'prediction':float(p[mask].mean()),'observed':float(y[mask].mean())})
    return {'n':len(y),'accuracy':float(np.mean((p>=.5)==y)),
            'log_loss':float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),
            'brier':float(np.mean((p-y)**2)),
            'ece':float(sum(b['n']*abs(b['prediction']-b['observed']) for b in bins)/len(y)),
            'calibration_bins':bins}


def calibrate(x,y,model):
    # One parameter, no intercept: swapping players always complements probability.
    grid=np.exp(np.linspace(np.log(.5),np.log(2),201))
    candidates=[(metrics(y,probabilities(x,dict(model,temperature=float(t))))['log_loss'],float(t)) for t in grid]
    loss,temp=min(candidates)
    raw=metrics(y,probabilities(x,model))['log_loss']
    return temp if loss<raw else 1.
