"""RH-OB Process Control and Digital Twin - backend package (Extractmet Private Limited).

Small dense linear algebra (150x150 BDF Newton matrices) is FASTER single-threaded; BLAS
thread oversubscription (multiple simulations / jobs on few cores) makes LU factorization
orders of magnitude slower. Pin BLAS threads before numpy/scipy are imported.
"""
import os as _os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")
