"""Shared body and spherical camera coordinate convention."""
import numpy as np

# Spirula ERP CV ray (right, down, forward) to exporter camera body ray.
BODY_FROM_CV = np.array([[0., 0., -1.], [1., 0., 0.], [0., -1., 0.]])
