{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": 4,
   "id": "2acec73c-1927-4f1a-8a17-f35768b04db1",
   "metadata": {},
   "outputs": [],
   "source": [
    "import multiprocessing\n",
    "import warnings\n",
    "from math import ceil\n",
    "from math import floor\n",
    "from pathlib import Path\n",
    "from typing import List\n",
    "from typing import Literal\n",
    "from typing import Optional\n",
    "from typing import Tuple\n",
    "from typing import Union\n",
    "from typing import cast\n",
    "\n",
    "import numpy as np\n",
    "import pandas as pd\n",
    "from matplotlib import pyplot as plt\n",
    "from scipy.linalg import solve  # type: ignore\n",
    "from scipy.optimize import minimize  # type: ignore\n",
    "from scipy.special import gammaln  # type: ignore\n",
    "from scipy.special import polygamma  # type: ignore\n",
    "from scipy.stats import norm  # type: ignore\n",
    "from sklearn.linear_model import LinearRegression  # type: ignore"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 9,
   "id": "a2dc20d0-0ebf-471f-aebb-44ecc8d2cc37",
   "metadata": {},
   "outputs": [],
   "source": [
    "import pydeseq2\n",
    "import pydeseq2.utils\n",
    "from pydeseq2.grid_search import grid_fit_alpha\n",
    "from pydeseq2.grid_search import grid_fit_shrink_beta"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "4a6487e3-764e-4422-aa3b-63762794114c",
   "metadata": {},
   "outputs": [],
   "source": [
    "def irls_glm(\n",
    "    counts: np.ndarray,\n",
    "    size_factors: np.ndarray,\n",
    "    design_matrix: np.ndarray,\n",
    "    cnv: np.ndarray,\n",
    "    disp: float,\n",
    "    min_mu: float = 0.5,\n",
    "    beta_tol: float = 1e-8,\n",
    "    min_beta: float = -30,\n",
    "    max_beta: float = 30,\n",
    "    optimizer: Literal[\"BFGS\", \"L-BFGS-B\"] = \"L-BFGS-B\",\n",
    "    maxiter: int = 250,\n",
    ") -> Tuple[np.ndarray, np.ndarray, np.ndarray, bool]:\n",
    "\n",
    "    assert optimizer in [\"BFGS\", \"L-BFGS-B\"]\n",
    "    \n",
    "    X = design_matrix\n",
    "    num_vars = design_matrix.shape[1]\n",
    "    \n",
    "    # if full rank, estimate initial betas for IRLS below\n",
    "    if np.linalg.matrix_rank(X) == num_vars:\n",
    "        Q, R = np.linalg.qr(X)\n",
    "        y = np.log((counts/cnv)/size_factors + 0.1)\n",
    "        beta_init = solve(R, Q.T @ y)\n",
    "        beta = beta_init\n",
    "\n",
    "    else:  # Initialise intercept with log base mean\n",
    "        beta_init = np.zeros(num_vars)\n",
    "        beta_init[0] = np.log((counts / cnv) / size_factors).mean()\n",
    "        beta = beta_init\n",
    "        \n",
    "    dev = 1000.0\n",
    "    dev_ratio = 1.0\n",
    "\n",
    "    ridge_factor = np.diag(np.repeat(1e-6, num_vars))\n",
    "    mu = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "    \n",
    "    converged = True\n",
    "    i = 0\n",
    "    while dev_ratio > beta_tol:\n",
    "        W = mu / (1.0 + mu * disp)\n",
    "        z = np.log((mu / cnv)/size_factors) + (counts - mu) / mu\n",
    "        H = (X.T * W) @ X + ridge_factor\n",
    "        beta_hat = solve(H, X.T @ (W * z), assume_a=\"pos\")\n",
    "        i += 1\n",
    "\n",
    "        if sum(np.abs(beta_hat) > max_beta) > 0 or i >= maxiter:\n",
    "            # If IRLS starts diverging, use L-BFGS-B\n",
    "            def f(beta: np.ndarray) -> float:\n",
    "                # closure to minimize\n",
    "                mu_ = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "                \n",
    "                return nb_nll(counts, mu_, disp) + 0.5 * (ridge_factor @ beta**2).sum()\n",
    "\n",
    "            def df(beta: np.ndarray) -> np.ndarray:\n",
    "                mu_ = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "                #mu_ = np.maximum(size_factors * np.exp(X @ beta), min_mu)\n",
    "                return (\n",
    "                    -X.T @ counts\n",
    "                    + ((1 / disp + counts) * mu_ / (1 / disp + mu_)) @ X\n",
    "                    + ridge_factor @ beta\n",
    "                )\n",
    "\n",
    "            res = minimize(\n",
    "                f,\n",
    "                beta_init,\n",
    "                jac=df,\n",
    "                method=optimizer,\n",
    "                bounds=(\n",
    "                    [(min_beta, max_beta)] * num_vars\n",
    "                    if optimizer == \"L-BFGS-B\"\n",
    "                    else None\n",
    "                ),\n",
    "            )\n",
    "            beta = res.x\n",
    "            mu = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "            converged = res.success\n",
    "\n",
    "            if not res.success and num_vars <= 2:\n",
    "                beta = grid_fit_beta(\n",
    "                    counts,\n",
    "                    size_factors,\n",
    "                    cnv,\n",
    "                    X,\n",
    "                    disp,\n",
    "                )\n",
    "                mu = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "            break\n",
    "\n",
    "        beta = beta_hat\n",
    "        mu = np.maximum(cnv * size_factors * np.exp(X @ beta), min_mu)\n",
    "        \n",
    "        # Compute deviation\n",
    "        old_dev = dev\n",
    "        # Replaced deviation with -2 * nll, as in the R code\n",
    "        dev = -2 * nb_nll(counts, mu, disp)\n",
    "        dev_ratio = np.abs(dev - old_dev) / (np.abs(dev) + 0.1)\n",
    "\n",
    "    # Compute H diagonal (useful for Cook distance outlier filtering)\n",
    "    W = mu / (1.0 + mu * disp)\n",
    "    W_sq = np.sqrt(W)\n",
    "    XtWX = (X.T * W) @ X + ridge_factor\n",
    "    H = W_sq * np.diag(X @ np.linalg.inv(XtWX) @ X.T) * W_sq\n",
    "    \n",
    "    # Return an UNthresholded mu (as in the R code)\n",
    "    # Previous quantities are estimated with a threshold though\n",
    "    \n",
    "    return beta, mu, H, converged\n"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "59c73150-882f-4bb5-8661-13be067616d6",
   "metadata": {},
   "outputs": [],
   "source": [
    "def fit_moments_dispersions(\n",
    "    normed_counts: np.ndarray, size_factors: np.ndarray, cnv: np.ndarray\n",
    ") -> np.ndarray:\n",
    "    \"\"\"Dispersion estimates based on moments, as per the R code.\n",
    "\n",
    "    Used as initial estimates in :meth:`DeseqDataSet.fit_genewise_dispersions()\n",
    "    <pydeseq2.dds.DeseqDataSet.fit_genewise_dispersions>`.\n",
    "\n",
    "    Parameters\n",
    "    ----------\n",
    "    normed_counts : ndarray\n",
    "        Array of deseq2-normalized read counts. Rows: samples, columns: genes.\n",
    "\n",
    "    size_factors : ndarray\n",
    "        DESeq2 normalization factors.\n",
    "\n",
    "    Returns\n",
    "    -------\n",
    "    ndarray\n",
    "        Estimated dispersion parameter for each gene.\n",
    "    \"\"\"\n",
    "    # Exclude genes with all zeroes\n",
    "    normed_counts = normed_counts[:, ~(normed_counts == 0).all(axis=0)]\n",
    "    # mean inverse size factor\n",
    "    s_mean_inv = ((1 / cnv)/size_factors).mean()\n",
    "    mu = normed_counts.mean(0)\n",
    "    sigma = normed_counts.var(0, ddof=1)\n",
    "    # ddof=1 is to use an unbiased estimator, as in R\n",
    "    # NaN (variance = 0) are replaced with 0s\n",
    "    return np.nan_to_num((sigma - s_mean_inv * mu) / mu**2)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "16cdb05f-2c37-4cd8-a286-73665f207a24",
   "metadata": {},
   "outputs": [],
   "source": [
    "def grid_fit_beta(\n",
    "    counts: np.ndarray,\n",
    "    size_factors: np.ndarray,\n",
    "    design_matrix: np.ndarray,\n",
    "    disp: float,\n",
    "    cnv: np.ndarray,\n",
    "    min_mu: float = 0.5,\n",
    "    grid_length: int = 60,\n",
    "    min_beta: float = -30,\n",
    "    max_beta: float = 30,\n",
    ") -> np.ndarray:\n",
    "    \n",
    "    x_grid = np.linspace(min_beta, max_beta, grid_length)\n",
    "    y_grid = np.linspace(min_beta, max_beta, grid_length)\n",
    "    ll_grid = np.zeros((grid_length, grid_length))\n",
    "\n",
    "    def loss(beta: np.ndarray) -> np.ndarray:\n",
    "        # closure to minimize\n",
    "\n",
    "        mu = np.maximum(cnv[:, None] * size_factors[:, None] * np.exp(design_matrix @ beta.T), min_mu)\n",
    "        return vec_nb_nll(counts, mu, disp) + 0.5 * (1e-6 * beta**2).sum(1)\n",
    "\n",
    "    for i, x in enumerate(x_grid):\n",
    "        ll_grid[i, :] = loss(np.array([[x, y] for y in y_grid]))\n",
    "\n",
    "    min_idxs = np.unravel_index(np.argmin(ll_grid, axis=None), ll_grid.shape)\n",
    "    delta = x_grid[1] - x_grid[0]\n",
    "\n",
    "    fine_x_grid = np.linspace(\n",
    "        x_grid[min_idxs[0]] - delta, x_grid[min_idxs[0]] + delta, grid_length\n",
    "    )\n",
    "\n",
    "    fine_y_grid = np.linspace(\n",
    "        y_grid[min_idxs[1]] - delta,\n",
    "        y_grid[min_idxs[1]] + delta,\n",
    "        grid_length,\n",
    "    )\n",
    "\n",
    "    for i, x in enumerate(fine_x_grid):\n",
    "        ll_grid[i, :] = loss(np.array([[x, y] for y in fine_y_grid]))\n",
    "\n",
    "    min_idxs = np.unravel_index(np.argmin(ll_grid, axis=None), ll_grid.shape)\n",
    "    beta = np.array([fine_x_grid[min_idxs[0]], fine_y_grid[min_idxs[1]]])\n",
    "    return beta"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (ipykernel)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.11.7"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}