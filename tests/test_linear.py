import unittest
import warnings
import numpy as np
from core.linear import fit,probabilities,metrics


class LinearNumericsTests(unittest.TestCase):
    def test_fitted_predictions_match_scalar_formula_without_numeric_warnings(self):
        rng=np.random.default_rng(12);x=rng.normal(size=(5000,40));y=(x[:,0]+rng.normal(size=5000)>0).astype(float)
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning)
            model=fit(x,y,10);actual=probabilities(x[:10],model)
        for vector,p in zip(x[:10],actual):
            logit=sum(max(-8,min(8,v/s))*w for v,s,w in zip(vector,model['scale'],model['weights']))
            self.assertAlmostEqual(p,1/(1+np.exp(-logit)),12)
        self.assertGreater(model['weights'][0],0)
        self.assertTrue(np.isfinite(model['weights']).all())

    def test_invalid_training_inputs_fail_instead_of_saving_corrupt_snapshot(self):
        for x,y in [(np.array([[float('nan')]]),np.array([1.])),(np.zeros((2,1)),np.array([1.])),(np.zeros((0,1)),np.array([]))]:
            with self.assertRaises(ValueError):fit(x,y,10)

    def test_invalid_metric_inputs_cannot_create_nan_or_fake_accuracy(self):
        for y,p in [([],[]),([1],[float('nan')]),([1],[1.1]),([0,1],[.2]),([2],[.8])]:
            with self.assertRaises(ValueError):metrics(y,p)
        with self.assertRaises(ValueError):fit(np.zeros((2,1)),np.array([0,2]),10)
        with self.assertRaises(ValueError):fit(np.zeros((2,1)),np.array([0,1]),-1)
