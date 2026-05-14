from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


REGIME_LABELS = ("low_vol", "mid_vol", "high_vol")


@dataclass(frozen=True)
class MarkovCalibration:
    transition_matrix: np.ndarray
    emission_means: np.ndarray
    emission_stds: np.ndarray
    thresholds: np.ndarray


class GaussianMarkovRegimeModel:
    """
    Small Gaussian-emission Markov volatility model.

    The implementation follows the transcript's structure, with two deliberate
    research-safety changes:
    - calibration consumes only data supplied by the caller, so rolling feature
      builders can enforce point-in-time windows;
    - likelihood updates use log space and smoothing to avoid brittle zero
      probabilities from tiny calibration samples.
    """

    def __init__(
        self,
        *,
        n_states: int = 3,
        smoothing: float = 0.1,
        min_std: float = 1e-8,
        min_state_observations: int = 3,
        initial_prob_mode: str = "uniform",
    ) -> None:
        if int(n_states) < 2:
            raise ValueError("n_states must be at least 2")

        self.n_states = int(n_states)
        self.smoothing = max(float(smoothing), 0.0)
        self.min_std = max(float(min_std), 1e-12)
        self.min_state_observations = max(1, int(min_state_observations))
        self.initial_prob_mode = str(initial_prob_mode or "uniform").lower()
        self.state_probabilities = np.full(self.n_states, 1.0 / self.n_states, dtype=float)
        self.current_state = 0
        self.calibration: MarkovCalibration | None = None

    def calibrate(self, observations: Sequence[float]) -> bool:
        values = np.asarray(observations, dtype=float)
        values = values[np.isfinite(values) & (values > 0)]
        min_observations = max(self.n_states * self.min_state_observations, 2 * self.n_states)
        if len(values) < min_observations:
            return False

        percentiles = np.linspace(0, 100, self.n_states + 1)[1:-1]
        thresholds = np.percentile(values, percentiles) if len(percentiles) else np.array([])
        assignments = np.searchsorted(thresholds, values, side="right").astype(int)

        emission_means = np.full(self.n_states, np.nan, dtype=float)
        emission_stds = np.full(self.n_states, np.nan, dtype=float)
        for state in range(self.n_states):
            state_values = values[assignments == state]
            if len(state_values) >= self.min_state_observations:
                emission_means[state] = float(np.mean(state_values))
                emission_stds[state] = max(float(np.std(state_values)), self.min_std)

        if np.isnan(emission_means).any():
            return False

        transition_counts = np.zeros((self.n_states, self.n_states), dtype=float)
        for prior_state, next_state in zip(assignments[:-1], assignments[1:]):
            transition_counts[int(prior_state), int(next_state)] += 1.0

        transition_matrix = transition_counts + self.smoothing
        row_sums = transition_matrix.sum(axis=1, keepdims=True)
        transition_matrix = transition_matrix / np.where(row_sums > 0, row_sums, 1.0)

        order = np.argsort(emission_means)
        if not np.array_equal(order, np.arange(self.n_states)):
            emission_means = emission_means[order]
            emission_stds = emission_stds[order]
            transition_matrix = transition_matrix[order][:, order]
            inverse_order = np.empty_like(order)
            inverse_order[order] = np.arange(self.n_states)
            assignments = inverse_order[assignments]

        self.calibration = MarkovCalibration(
            transition_matrix=transition_matrix,
            emission_means=emission_means,
            emission_stds=emission_stds,
            thresholds=thresholds,
        )
        self.state_probabilities = self._initial_probabilities(assignments)
        self.current_state = int(np.argmax(self.state_probabilities))
        return True

    def _initial_probabilities(self, assignments: np.ndarray) -> np.ndarray:
        if self.initial_prob_mode == "empirical":
            counts = np.bincount(assignments, minlength=self.n_states).astype(float)
            probs = counts + self.smoothing
            total = probs.sum()
            if total > 0:
                return probs / total
        return np.full(self.n_states, 1.0 / self.n_states, dtype=float)

    def update(self, observation: float) -> tuple[int, np.ndarray]:
        if self.calibration is None:
            return self.current_state, self.state_probabilities.copy()

        value = float(observation)
        if not np.isfinite(value) or value <= 0:
            return self.current_state, self.state_probabilities.copy()

        priors = self.calibration.transition_matrix.T @ self.state_probabilities
        priors = np.clip(priors, 1e-12, 1.0)
        means = self.calibration.emission_means
        stds = np.maximum(self.calibration.emission_stds, self.min_std)
        log_likelihoods = (
            -np.log(stds)
            - 0.5 * np.log(2.0 * np.pi)
            - 0.5 * ((value - means) / stds) ** 2
        )
        log_posteriors = np.log(priors) + log_likelihoods
        log_posteriors -= np.nanmax(log_posteriors)
        posteriors = np.exp(log_posteriors)
        total = float(np.nansum(posteriors))
        if not np.isfinite(total) or total <= 0:
            posteriors = priors / priors.sum()
        else:
            posteriors = posteriors / total

        self.state_probabilities = posteriors
        self.current_state = int(np.argmax(posteriors))
        return self.current_state, posteriors.copy()


def ohlc_volatility(data: pd.DataFrame, method: str = "range_close") -> pd.Series:
    required = {"high", "low", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"markov regime requires columns: {sorted(missing)}")

    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")
    method = str(method or "range_close").lower()

    if method == "log_range":
        out = np.log(high.replace(0, np.nan) / low.replace(0, np.nan)).abs()
    elif method == "abs_return":
        out = np.log(close.replace(0, np.nan)).diff().abs()
    else:
        out = (high - low).abs() / close.replace(0, np.nan).abs()

    return pd.Series(out, index=data.index, dtype=float).replace([np.inf, -np.inf], np.nan)


def _state_label(state: int, n_states: int) -> str:
    if n_states == 3 and 0 <= state < len(REGIME_LABELS):
        return REGIME_LABELS[state]
    return f"state_{state}"


def add_markov_regime_features(
    data: pd.DataFrame,
    *,
    n_states: int = 3,
    calibration_bars: int = 78,
    min_calibration_bars: int = 30,
    refit_every_bars: int = 12,
    smoothing: float = 0.1,
    min_std: float = 1e-8,
    min_state_observations: int = 3,
    volatility_method: str = "range_close",
    initial_prob_mode: str = "uniform",
) -> pd.DataFrame:
    """
    Append point-in-time Markov volatility-regime features.

    For row i, the model is calibrated using rows strictly before i, then row i's
    completed bar volatility is scored. A signal produced on row i can therefore
    enter on the next bar without seeing future volatility.
    """

    df = data.reset_index(drop=True).copy()
    n_states = max(2, int(n_states))
    min_calibration_bars = max(n_states * min_state_observations, int(min_calibration_bars))
    calibration_bars = max(min_calibration_bars, n_states * min_state_observations, int(calibration_bars))
    refit_every_bars = max(1, int(refit_every_bars))

    vol = ohlc_volatility(df, method=volatility_method).to_numpy(dtype=float)
    n = len(df)
    states = np.full(n, np.nan, dtype=float)
    confidence = np.full(n, np.nan, dtype=float)
    fit_age = np.full(n, np.nan, dtype=float)
    calibrated = np.zeros(n, dtype=bool)
    probs = np.full((n, n_states), np.nan, dtype=float)
    means = np.full((n, n_states), np.nan, dtype=float)
    stds = np.full((n, n_states), np.nan, dtype=float)

    model: GaussianMarkovRegimeModel | None = None
    last_fit_idx = -10**9
    for idx in range(n):
        if idx < min_calibration_bars:
            continue

        should_refit = model is None or (idx - last_fit_idx) >= refit_every_bars
        if should_refit:
            start_idx = max(0, idx - calibration_bars)
            candidate = GaussianMarkovRegimeModel(
                n_states=n_states,
                smoothing=smoothing,
                min_std=min_std,
                min_state_observations=min_state_observations,
                initial_prob_mode=initial_prob_mode,
            )
            if candidate.calibrate(vol[start_idx:idx]):
                model = candidate
                last_fit_idx = idx

        if model is None or model.calibration is None:
            continue

        state, posterior = model.update(vol[idx])
        states[idx] = float(state)
        probs[idx] = posterior
        confidence[idx] = float(np.nanmax(posterior))
        fit_age[idx] = float(idx - last_fit_idx)
        calibrated[idx] = True
        means[idx] = model.calibration.emission_means
        stds[idx] = model.calibration.emission_stds

    df["markov_volatility"] = vol
    df["markov_state"] = states
    df["markov_state_label"] = [
        _state_label(int(state), n_states) if np.isfinite(state) else ""
        for state in states
    ]
    df["markov_state_confidence"] = confidence
    df["markov_fit_age_bars"] = fit_age
    df["markov_calibrated"] = calibrated
    for state in range(n_states):
        label = _state_label(state, n_states)
        df[f"markov_prob_{label}"] = probs[:, state]
        df[f"markov_emission_mean_{label}"] = means[:, state]
        df[f"markov_emission_std_{label}"] = stds[:, state]

    return df
