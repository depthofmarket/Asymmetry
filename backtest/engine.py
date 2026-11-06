import pandas as pd
import numpy as np
import ta
from datetime import datetime
import weakref

from backtest.auction_context import add_futures_auction_context
from backtest.cross_asset_context import (
    ALL_CROSS_ASSET_COLUMNS,
    DEFAULT_CROSS_ASSET_FEATURES_PATH,
    add_morning_cross_asset_features,
)
from backtest.event_sampling import add_cusum_event_features
from backtest.hawkes import add_hawkes_volatility_features
from backtest.market_structure import add_market_structure_features
from backtest.market_profile import add_market_profile_features
from backtest.market_memory import add_market_memory_features
from backtest.markov_regime import add_markov_regime_features
from backtest.objectives import bar_objective_metrics, execution_bar_objective_metrics
from backtest.options_flow import add_options_flow_features
from backtest.point_in_time import mask_columns_before_clock
from backtest.strategy_runtime import SignalEvent, extract_signal_events
from backtest.volume_spread import add_volume_spread_features
from backtest.execution import ExecutionMixin
from backtest.indicators import IndicatorMixin
from backtest.signals import SignalMixin

_EXECUTION_1M_CACHE: dict[tuple[int, int], tuple[weakref.ref, pd.DataFrame, np.ndarray, bool]] = {}


class BacktestEngine(ExecutionMixin, IndicatorMixin, SignalMixin):
    """Motas's Playground"""

    def __init__(self, data: pd.DataFrame, portfolio, futures_specs: dict, strategy_params: dict):
        if isinstance(data.index, pd.RangeIndex) and data.index.start == 0 and data.index.step == 1:
            self.data = data
        else:
            self.data = data.reset_index(drop=True)
        self.portfolio = portfolio
        self.futures_specs = futures_specs
        self.strategy_params = strategy_params
        self.equity_curve = []
        self._preprocessed_5m: pd.DataFrame | None = None
        self._execution_1m: pd.DataFrame | None = None
        self._execution_times: np.ndarray | None = None

    def get_directional_param(self, direction: str, key: str, default=None):
        directional_key = f'{direction}_{key}'
        if directional_key in self.strategy_params:
            return self.strategy_params[directional_key]
        return self.strategy_params.get(key, default)

    def get_signal_param(self, signal_type: str | None, direction: str, key: str, default=None):
        if signal_type:
            signal_directional_key = f'{signal_type}_{direction}_{key}'
            if signal_directional_key in self.strategy_params:
                return self.strategy_params[signal_directional_key]

            signal_key = f'{signal_type}_{key}'
            if signal_key in self.strategy_params:
                return self.strategy_params[signal_key]

        return self.get_directional_param(direction, key, default)

    def is_signal_direction_enabled(self, signal_type: str | None, direction: str) -> bool:
        return bool(self.get_signal_param(signal_type, direction, 'enabled', True))

    def _coerce_hour_map(self, value) -> dict[str, set[int]]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, set[int]] = {}
        for key, hours in value.items():
            if hours is None:
                continue
            if not isinstance(hours, (list, tuple, set)):
                hours = [hours]
            out[str(key)] = {int(hour) for hour in hours}
        return out

    def _coerce_context_filter_map(self, value) -> dict[str, dict[str, set]]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, dict[str, set]] = {}
        for key, filters in value.items():
            if not isinstance(filters, dict):
                continue
            coerced_filters: dict[str, set] = {}
            for column, allowed_values in filters.items():
                if allowed_values is None:
                    continue
                if not isinstance(allowed_values, (list, tuple, set)):
                    allowed_values = [allowed_values]
                coerced_filters[str(column)] = set(allowed_values)
            if coerced_filters:
                out[str(key)] = coerced_filters
        return out

    def _entry_offset_bars(self) -> int:
        entry_delay_bars = max(0, int(self.strategy_params.get('entry_delay_bars', 0) or 0))
        if self.strategy_params.get('entry_mode', 'same_bar_close') == 'next_bar_open':
            return 1 + entry_delay_bars
        return entry_delay_bars

    def _entry_context_offset_bars(self) -> int:
        entry_offset = self._entry_offset_bars()
        if entry_offset <= 0:
            return 0
        return entry_offset - 1

    def _coerce_markov_state_set(self, value) -> set[int]:
        if value is None:
            return set()
        if isinstance(value, str):
            values = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = [value]

        label_map = {
            "low": 0,
            "low_vol": 0,
            "mid": 1,
            "medium": 1,
            "mid_vol": 1,
            "high": 2,
            "high_vol": 2,
        }
        out: set[int] = set()
        for item in values:
            if item is None or item == "":
                continue
            key = str(item).strip().lower()
            if key in label_map:
                out.add(label_map[key])
            else:
                out.add(int(item))
        return out

    def _coerce_markov_state_map(self, value) -> dict[str, set[int]]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, set[int]] = {}
        for key, states in value.items():
            coerced = self._coerce_markov_state_set(states)
            if coerced:
                out[str(key)] = coerced
        return out

    def _coerce_market_memory_state_set(self, value) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            values = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = [value]

        aliases = {
            "neutral": "neutral_memory",
            "persistent": "persistent_memory",
            "trend": "persistent_memory",
            "mean_reverting": "mean_reverting_memory",
            "mr": "mean_reverting_memory",
            "chaotic": "chaotic_memory",
            "random": "chaotic_memory",
            "tail": "tail_risk_memory",
            "tail_risk": "tail_risk_memory",
            "unknown": "unknown",
        }
        out: set[str] = set()
        for item in values:
            if item is None or item == "":
                continue
            key = str(item).strip().lower()
            out.add(aliases.get(key, key))
        return out

    def _coerce_market_memory_state_map(self, value) -> dict[str, set[str]]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, set[str]] = {}
        for key, states in value.items():
            coerced = self._coerce_market_memory_state_set(states)
            if coerced:
                out[str(key)] = coerced
        return out

    def apply_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply optional research filters after signal generation.

        Filters are intentionally generic so we can test candidate variants
        without adding one-off strategy branches.
        """
        p = self.strategy_params
        has_filters = any(
            p.get(key)
            for key in (
                'blocked_setup_hours',
                'allowed_setup_hours',
                'blocked_setup_tags',
                'allowed_setup_tags',
                'allowed_entry_context',
                'blocked_entry_context',
            )
        )
        if not has_filters or 'signal' not in df.columns:
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        direction = pd.Series(np.where(signal > 0, 'long', np.where(signal < 0, 'short', '')), index=out.index)
        setup_tag = np.where(signal_type != '', signal_type + '_' + direction, direction)
        setup_tag = pd.Series(setup_tag, index=out.index)

        entry_offset = self._entry_offset_bars()
        effective_time = pd.to_datetime(out['time']).shift(-entry_offset) if entry_offset else pd.to_datetime(out['time'])
        effective_hour = effective_time.dt.hour.fillna(-1).astype(int)

        candidate_keys = {
            'setup_tag': setup_tag,
            'direction': direction,
            'signal_type': signal_type,
        }

        allowed_tags = {str(x) for x in p.get('allowed_setup_tags', [])}
        blocked_tags = {str(x) for x in p.get('blocked_setup_tags', [])}
        allowed_hours = self._coerce_hour_map(p.get('allowed_setup_hours', {}))
        blocked_hours = self._coerce_hour_map(p.get('blocked_setup_hours', {}))
        allowed_context = self._coerce_context_filter_map(p.get('allowed_entry_context', {}))
        blocked_context = self._coerce_context_filter_map(p.get('blocked_entry_context', {}))

        keep = pd.Series(True, index=out.index)

        if allowed_tags:
            tag_match = pd.Series(False, index=out.index)
            for series in candidate_keys.values():
                tag_match |= series.isin(allowed_tags)
            keep &= ~active | tag_match

        if blocked_tags:
            tag_match = pd.Series(False, index=out.index)
            for series in candidate_keys.values():
                tag_match |= series.isin(blocked_tags)
            keep &= ~(active & tag_match)

        if allowed_hours:
            hour_match = pd.Series(False, index=out.index)
            for key, hours in allowed_hours.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                hour_match |= key_match & effective_hour.isin(hours)
            keep &= ~active | hour_match

        if blocked_hours:
            hour_match = pd.Series(False, index=out.index)
            for key, hours in blocked_hours.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                hour_match |= key_match & effective_hour.isin(hours)
            keep &= ~(active & hour_match)

        context_offset = self._entry_context_offset_bars()
        entry_context = out.shift(-context_offset) if context_offset else out

        if allowed_context:
            context_match = pd.Series(False, index=out.index)
            context_scoped = pd.Series(False, index=out.index)
            for key, filters in allowed_context.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                if not key_match.any():
                    continue
                context_scoped |= key_match
                rule_match = key_match.copy()
                for column, allowed_values in filters.items():
                    if column not in entry_context.columns:
                        rule_match &= False
                        continue
                    rule_match &= entry_context[column].isin(allowed_values)
                context_match |= rule_match
            keep &= ~active | ~context_scoped | context_match

        if blocked_context:
            context_match = pd.Series(False, index=out.index)
            for key, filters in blocked_context.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                if not key_match.any():
                    continue
                rule_match = key_match.copy()
                for column, blocked_values in filters.items():
                    if column not in entry_context.columns:
                        rule_match &= False
                        continue
                    rule_match &= entry_context[column].isin(blocked_values)
                context_match |= rule_match
            keep &= ~(active & context_match)

        filtered = active & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_market_structure(self) -> bool:
        p = self.strategy_params
        return bool(
            p.get('market_structure_enabled', False)
            or str(p.get('market_structure_filter', 'off')).lower() not in ('off', 'none', 'false', '0')
            or p.get('market_structure_stop_enabled', False)
        )

    def add_market_structure(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_market_structure():
            return df

        p = self.strategy_params
        return add_market_structure_features(
            df,
            levels=int(p.get('market_structure_levels', 3)),
            atr_period=int(p.get('market_structure_atr_period', 78)),
            atr_multiplier=float(p.get('market_structure_atr_multiplier', 1.0)),
        )

    def apply_market_structure_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('market_structure_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df

        level = int(p.get('market_structure_filter_level', 1))
        prefix = f'ms_l{level}'
        required_cols = {
            f'{prefix}_last_type',
            f'{prefix}_swing_direction',
            f'{prefix}_bars_since_extreme',
            f'{prefix}_dist_to_support',
            f'{prefix}_dist_to_resistance',
        }
        if not required_cols.issubset(df.columns):
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        filter_signal_types = {str(x) for x in p.get('market_structure_filter_signal_types', [])}
        scoped = active & signal_type.isin(filter_signal_types) if filter_signal_types else active
        if not scoped.any():
            return out

        long_active = scoped & signal.eq(1)
        short_active = scoped & signal.eq(-1)
        last_type = out[f'{prefix}_last_type']
        swing_direction = out[f'{prefix}_swing_direction']
        bars_since = out[f'{prefix}_bars_since_extreme']

        keep = pd.Series(True, index=out.index)

        if mode in ('swing', 'swing_room'):
            aligned = pd.Series(False, index=out.index)
            aligned |= long_active & swing_direction.eq(1)
            aligned |= short_active & swing_direction.eq(-1)
            keep &= ~scoped | aligned

        elif mode in ('reversal', 'reversal_room'):
            max_bars = int(p.get('market_structure_max_bars_since_extreme', 12))
            recent_reversal = pd.Series(False, index=out.index)
            recent_reversal |= long_active & last_type.eq(-1) & bars_since.le(max_bars)
            recent_reversal |= short_active & last_type.eq(1) & bars_since.le(max_bars)
            keep &= ~scoped | recent_reversal

        elif mode not in ('room', 'room_only'):
            return out

        if mode in ('room', 'room_only', 'swing_room', 'reversal_room'):
            min_room = float(p.get('market_structure_min_room_to_opposite_points', 8.0))
            room_ok = pd.Series(False, index=out.index)
            room_ok |= long_active & out[f'{prefix}_dist_to_resistance'].ge(min_room)
            room_ok |= short_active & out[f'{prefix}_dist_to_support'].ge(min_room)
            keep &= ~scoped | room_ok

        filtered = scoped & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_market_profile(self) -> bool:
        p = self.strategy_params
        return bool(
            p.get('market_profile_enabled', False)
            or p.get('strategy_name') == 'market_profile_cross'
            or p.get('strategy_name') == 'hybrid_profile_regime_no_orb'
            or str(p.get('market_profile_filter', 'off')).lower() not in ('off', 'none', 'false', '0')
            or p.get('market_profile_target_enabled', False)
        )

    def add_market_profile(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_market_profile():
            return df

        p = self.strategy_params
        return add_market_profile_features(
            df,
            lookback_bars=int(p.get('market_profile_lookback_bars', 390)),
            atr_multiplier=float(p.get('market_profile_atr_multiplier', 3.0)),
            first_weight=float(p.get('market_profile_first_weight', 1.0)),
            prominence_threshold=float(p.get('market_profile_prominence_threshold', 0.25)),
            grid_size=int(p.get('market_profile_grid_size', 160)),
            recompute_every_bars=int(p.get('market_profile_recompute_every_bars', 12)),
            max_levels=int(p.get('market_profile_max_levels', 8)),
            min_level_distance_points=float(p.get('market_profile_min_level_distance_points', 4.0)),
            backend=str(p.get('market_profile_backend', 'histogram')),
        )

    def apply_market_profile_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('market_profile_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df

        required_cols = {
            'mp_nearest_support',
            'mp_nearest_resistance',
            'mp_dist_to_support',
            'mp_dist_to_resistance',
            'mp_crossed_up',
            'mp_crossed_down',
        }
        if not required_cols.issubset(df.columns):
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        filter_signal_types = {str(x) for x in p.get('market_profile_filter_signal_types', [])}
        scoped = active & signal_type.isin(filter_signal_types) if filter_signal_types else active
        if not scoped.any():
            return out

        long_active = scoped & signal.eq(1)
        short_active = scoped & signal.eq(-1)
        keep = pd.Series(True, index=out.index)

        def room_ok() -> pd.Series:
            min_room = float(p.get('market_profile_min_room_to_opposite_points', 8.0))
            ok = pd.Series(False, index=out.index)
            ok |= long_active & out['mp_dist_to_resistance'].ge(min_room)
            ok |= short_active & out['mp_dist_to_support'].ge(min_room)
            return ok

        def reversion_ok() -> pd.Series:
            tolerance = float(p.get('market_profile_near_level_tolerance_points', 5.0))
            ok = pd.Series(False, index=out.index)
            ok |= long_active & out['mp_dist_to_support'].between(0, tolerance, inclusive='both')
            ok |= short_active & out['mp_dist_to_resistance'].between(0, tolerance, inclusive='both')
            return ok

        def breakout_ok() -> pd.Series:
            ok = pd.Series(False, index=out.index)
            ok |= long_active & out['mp_crossed_up'].fillna(False)
            ok |= short_active & out['mp_crossed_down'].fillna(False)
            return ok

        if mode in ('room', 'room_only'):
            keep &= ~scoped | room_ok()
        elif mode == 'reversion':
            keep &= ~scoped | reversion_ok()
        elif mode == 'reversion_room':
            keep &= ~scoped | (reversion_ok() & room_ok())
        elif mode == 'breakout':
            keep &= ~scoped | breakout_ok()
        elif mode == 'breakout_room':
            keep &= ~scoped | (breakout_ok() & room_ok())
        elif mode == 'context':
            context_ok = pd.Series(False, index=out.index)
            mr_mask = signal_type.eq('mr')
            trend_mask = signal_type.eq('trend')
            context_ok |= mr_mask & reversion_ok()
            context_ok |= trend_mask & breakout_ok()
            context_ok |= ~(mr_mask | trend_mask) & room_ok()
            if bool(p.get('market_profile_context_requires_room', True)):
                context_ok &= room_ok()
            keep &= ~scoped | context_ok
        else:
            return out

        filtered = scoped & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def apply_vsa_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('vsa_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df

        required_cols = {'vsa_absorption', 'vsa_thin_move', 'vsa_score'}
        if not required_cols.issubset(df.columns):
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        filter_signal_types = {str(x) for x in p.get('vsa_filter_signal_types', [])}
        scoped = active & signal_type.isin(filter_signal_types) if filter_signal_types else active
        if not scoped.any():
            return out

        absorption = out['vsa_absorption'].fillna(False).astype(bool)
        thin_move = out['vsa_thin_move'].fillna(False).astype(bool)
        keep = pd.Series(True, index=out.index)

        if mode == 'require_absorption':
            keep &= ~scoped | absorption
        elif mode == 'require_thin_move':
            keep &= ~scoped | thin_move
        elif mode == 'avoid_absorption':
            keep &= ~(scoped & absorption)
        elif mode == 'avoid_thin_move':
            keep &= ~(scoped & thin_move)
        elif mode == 'context':
            mr_mask = signal_type.eq('mr')
            trend_mask = signal_type.eq('trend')
            mp_mask = signal_type.eq('mp')
            context_ok = pd.Series(True, index=out.index)
            context_ok.loc[mr_mask] = absorption.loc[mr_mask]
            context_ok.loc[trend_mask | mp_mask] = thin_move.loc[trend_mask | mp_mask]
            keep &= ~scoped | context_ok
        else:
            return out

        filtered = scoped & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_markov_regime(self) -> bool:
        p = self.strategy_params
        return bool(
            p.get('markov_regime_enabled', False)
            or str(p.get('markov_regime_filter', 'off')).lower() not in ('off', 'none', 'false', '0')
        )

    def add_markov_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_markov_regime():
            return df

        p = self.strategy_params
        return add_markov_regime_features(
            df,
            n_states=int(p.get('markov_n_states', 3)),
            calibration_bars=int(p.get('markov_calibration_bars', 78)),
            min_calibration_bars=int(p.get('markov_min_calibration_bars', 30)),
            refit_every_bars=int(p.get('markov_refit_every_bars', 12)),
            smoothing=float(p.get('markov_transition_smoothing', 0.1)),
            min_std=float(p.get('markov_min_std', 1e-8)),
            min_state_observations=int(p.get('markov_min_state_observations', 3)),
            volatility_method=str(p.get('markov_volatility_method', 'range_close')),
            initial_prob_mode=str(p.get('markov_initial_prob_mode', 'uniform')),
        )

    def apply_markov_regime_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('markov_regime_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df
        if 'markov_state' not in df.columns:
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        state = pd.to_numeric(out['markov_state'], errors='coerce')
        confidence = pd.to_numeric(out.get('markov_state_confidence', pd.Series(np.nan, index=out.index)), errors='coerce')
        min_confidence = float(p.get('markov_min_confidence', 0.0) or 0.0)

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        direction = pd.Series(np.where(signal > 0, 'long', np.where(signal < 0, 'short', '')), index=out.index)
        setup_tag = np.where(signal_type != '', signal_type + '_' + direction, direction)
        setup_tag = pd.Series(setup_tag, index=out.index)
        candidate_keys = {
            'setup_tag': setup_tag,
            'direction': direction,
            'signal_type': signal_type,
        }

        keep = pd.Series(True, index=out.index)
        keep &= ~active | state.notna()
        if min_confidence > 0:
            keep &= ~active | confidence.ge(min_confidence)

        n_states = int(p.get('markov_n_states', 3))
        high_state = max(0, n_states - 1)
        if mode == 'avoid_high':
            keep &= ~active | state.lt(high_state)
        elif mode == 'require_low':
            keep &= ~active | state.eq(0)
        elif mode == 'require_low_mid':
            keep &= ~active | state.isin({0, 1})
        elif mode == 'require_mid_high':
            keep &= ~active | state.isin({1, high_state})
        elif mode == 'require_high':
            keep &= ~active | state.eq(high_state)
        elif mode in ('context', 'map', 'custom'):
            allowed_states = self._coerce_markov_state_map(p.get('markov_allowed_states', {}))
            if mode == 'context' and not allowed_states and n_states == 3:
                allowed_states = {
                    'mr': {0, 1},
                    'trend': {1, 2},
                    'mp': {1, 2},
                }
            if allowed_states:
                state_match = pd.Series(False, index=out.index)
                for key, states in allowed_states.items():
                    key_match = pd.Series(False, index=out.index)
                    for series in candidate_keys.values():
                        key_match |= series.eq(key)
                    state_match |= key_match & state.isin(states)
                keep &= ~active | state_match
        else:
            return out

        blocked_states = self._coerce_markov_state_map(p.get('markov_blocked_states', {}))
        if blocked_states:
            state_match = pd.Series(False, index=out.index)
            for key, states in blocked_states.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                state_match |= key_match & state.isin(states)
            keep &= ~(active & state_match)

        filtered = active & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_market_memory(self) -> bool:
        p = self.strategy_params
        mode = str(p.get('market_memory_filter', 'off')).lower()
        return bool(p.get('market_memory_enabled', False) or mode not in ('off', 'none', 'false', '0'))

    def add_market_memory(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_market_memory():
            return df

        p = self.strategy_params
        return add_market_memory_features(
            df,
            hurst_window_bars=int(p.get('market_memory_hurst_window_bars', 156)),
            hurst_min_bars=int(p.get('market_memory_hurst_min_bars', 64)),
            entropy_window_bars=int(p.get('market_memory_entropy_window_bars', 156)),
            entropy_min_bars=int(p.get('market_memory_entropy_min_bars', 64)),
            entropy_bins=int(p.get('market_memory_entropy_bins', 10)),
            lz_window_bars=int(p.get('market_memory_lz_window_bars', 96)),
            lz_min_bars=int(p.get('market_memory_lz_min_bars', 48)),
            tail_window_bars=int(p.get('market_memory_tail_window_bars', 390)),
            tail_min_bars=int(p.get('market_memory_tail_min_bars', 120)),
            tail_fraction=float(p.get('market_memory_tail_fraction', 0.10)),
            tail_min_observations=int(p.get('market_memory_tail_min_observations', 8)),
            tail_event_quantile=float(p.get('market_memory_tail_event_quantile', 0.99)),
            recompute_every_bars=int(p.get('market_memory_recompute_every_bars', 6)),
            hurst_low_threshold=float(p.get('market_memory_hurst_low_threshold', 0.45)),
            hurst_high_threshold=float(p.get('market_memory_hurst_high_threshold', 0.55)),
            entropy_low_threshold=float(p.get('market_memory_entropy_low_threshold', 0.55)),
            entropy_high_threshold=float(p.get('market_memory_entropy_high_threshold', 0.85)),
            lz_low_threshold=float(p.get('market_memory_lz_low_threshold', 0.75)),
            lz_high_threshold=float(p.get('market_memory_lz_high_threshold', 1.05)),
            tail_alpha_fat_threshold=float(p.get('market_memory_tail_alpha_fat_threshold', 3.0)),
            tail_alpha_thin_threshold=float(p.get('market_memory_tail_alpha_thin_threshold', 5.0)),
        )

    def apply_market_memory_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('market_memory_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df
        if 'market_memory_state' not in df.columns:
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        direction = pd.Series(np.where(signal > 0, 'long', np.where(signal < 0, 'short', '')), index=out.index)
        setup_tag = np.where(signal_type != '', signal_type + '_' + direction, direction)
        setup_tag = pd.Series(setup_tag, index=out.index)
        candidate_keys = {
            'setup_tag': setup_tag,
            'direction': direction,
            'signal_type': signal_type,
        }

        scoped = active.copy()
        filter_signal_types = {str(x) for x in p.get('market_memory_filter_signal_types', [])}
        if filter_signal_types:
            scoped &= signal_type.isin(filter_signal_types) | setup_tag.isin(filter_signal_types) | direction.isin(filter_signal_types)

        state = out['market_memory_state'].fillna('unknown').astype(str)
        has_memory = state.ne('unknown')
        allow_missing = bool(p.get('market_memory_allow_missing', True))
        keep = pd.Series(True, index=out.index)
        if allow_missing:
            scoped &= has_memory
        else:
            keep &= ~scoped | has_memory
            scoped &= has_memory

        if mode in ('avoid_chaotic', 'avoid_random'):
            keep &= ~(scoped & state.eq('chaotic_memory'))
        elif mode in ('avoid_tail_risk', 'avoid_tail'):
            keep &= ~(scoped & state.eq('tail_risk_memory'))
        elif mode == 'avoid_fragile':
            keep &= ~(scoped & state.isin(['chaotic_memory', 'tail_risk_memory']))
        elif mode == 'require_persistent':
            keep &= ~scoped | state.eq('persistent_memory')
        elif mode in ('require_mean_reverting', 'require_mr'):
            keep &= ~scoped | state.eq('mean_reverting_memory')
        elif mode == 'context':
            mr_allowed = self._coerce_market_memory_state_set(
                p.get('market_memory_mr_allowed_states', ['mean_reverting_memory', 'neutral_memory'])
            )
            trend_allowed = self._coerce_market_memory_state_set(
                p.get('market_memory_trend_allowed_states', ['persistent_memory', 'neutral_memory'])
            )
            mp_allowed = self._coerce_market_memory_state_set(
                p.get('market_memory_mp_allowed_states', ['persistent_memory', 'neutral_memory'])
            )
            context_ok = pd.Series(True, index=out.index)
            context_ok &= ~(scoped & signal_type.eq('mr')) | state.isin(mr_allowed)
            context_ok &= ~(scoped & signal_type.eq('trend')) | state.isin(trend_allowed)
            context_ok &= ~(scoped & signal_type.eq('mp')) | state.isin(mp_allowed)
            if bool(p.get('market_memory_context_avoid_fragile', True)):
                context_ok &= ~(scoped & state.isin(['chaotic_memory', 'tail_risk_memory']))
            keep &= context_ok
        elif mode in ('map', 'custom'):
            allowed_states = self._coerce_market_memory_state_map(p.get('market_memory_allowed_states', {}))
            if allowed_states:
                state_match = pd.Series(False, index=out.index)
                for key, states in allowed_states.items():
                    key_match = pd.Series(False, index=out.index)
                    for series in candidate_keys.values():
                        key_match |= series.eq(key)
                    state_match |= key_match & state.isin(states)
                keep &= ~scoped | state_match
        else:
            return out

        blocked_states = self._coerce_market_memory_state_map(p.get('market_memory_blocked_states', {}))
        if blocked_states:
            state_match = pd.Series(False, index=out.index)
            for key, states in blocked_states.items():
                key_match = pd.Series(False, index=out.index)
                for series in candidate_keys.values():
                    key_match |= series.eq(key)
                state_match |= key_match & state.isin(states)
            keep &= ~(scoped & state_match)

        filtered = active & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_options_flow(self) -> bool:
        p = self.strategy_params
        mode = str(p.get('options_flow_filter', 'off')).lower()
        return bool(p.get('options_flow_enabled', False) or mode not in ('off', 'none', 'false', '0'))

    def add_options_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_options_flow():
            return df
        path = self.strategy_params.get('options_flow_features_path')
        if not path:
            return df
        return add_options_flow_features(df, path)

    def apply_options_flow_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('options_flow_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df
        if 'options_net_gex' not in df.columns:
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        allow_missing = bool(p.get('options_flow_allow_missing', True))
        net_gex = pd.to_numeric(out['options_net_gex'], errors='coerce')
        abs_gex = pd.to_numeric(out.get('options_abs_gex', pd.Series(np.nan, index=out.index)), errors='coerce')
        min_abs_gex = float(p.get('options_flow_min_abs_gex', 0.0) or 0.0)
        has_flow = net_gex.notna() & abs_gex.fillna(0.0).ge(min_abs_gex)

        signal_type = out['signal_type'].fillna('').astype(str) if 'signal_type' in out.columns else pd.Series('', index=out.index)
        keep = pd.Series(True, index=out.index)
        if allow_missing:
            scoped = active & has_flow
        else:
            keep &= ~active | has_flow
            scoped = active & has_flow

        if mode == 'require_positive_gex':
            keep &= ~scoped | net_gex.ge(0)
        elif mode == 'require_negative_gex':
            keep &= ~scoped | net_gex.le(0)
        elif mode == 'avoid_negative_gex':
            keep &= ~scoped | net_gex.ge(0)
        elif mode == 'context':
            mr = signal_type.eq('mr')
            trend_or_breakout = signal_type.isin(['trend', 'mp'])
            context_ok = pd.Series(True, index=out.index)
            # Positive dealer gamma is usually a mean-reversion context; negative
            # gamma is usually a trend/expansion context. This is a hypothesis,
            # not a conclusion, so it stays behind a candidate flag.
            context_ok &= ~(scoped & mr) | net_gex.ge(0)
            context_ok &= ~(scoped & trend_or_breakout) | net_gex.le(0)
            keep &= context_ok
        elif mode in ('gamma_environment', 'dealer_gamma_environment'):
            mr = signal_type.eq('mr')
            trend_or_breakout = signal_type.isin(['trend', 'mp'])
            threshold = float(p.get('options_flow_gex_neutral_threshold', 0.0) or 0.0)
            positive_gamma = net_gex.gt(threshold)
            negative_gamma = net_gex.lt(-threshold)
            neutral_gamma = scoped & ~positive_gamma & ~negative_gamma

            env_ok = pd.Series(True, index=out.index)
            env_ok &= ~(scoped & mr) | positive_gamma | neutral_gamma
            env_ok &= ~(scoped & trend_or_breakout) | negative_gamma | neutral_gamma

            room = float(p.get('options_flow_wall_room_points', 12.0) or 0.0)
            amp_trigger = float(p.get('options_flow_amplifier_trigger_points', room) or 0.0)
            require_amp = bool(p.get('options_flow_require_negative_gamma_amplifier', True))
            gamma_above = pd.to_numeric(out.get('options_gamma_wall_above_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            gamma_below = pd.to_numeric(out.get('options_gamma_wall_below_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            call_dist = pd.to_numeric(out.get('options_call_wall_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            put_dist = pd.to_numeric(out.get('options_put_wall_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            long_signal = scoped & signal.gt(0)
            short_signal = scoped & signal.lt(0)

            # In positive gamma, walls are treated as pinning/S-R: do not buy
            # futures into nearby call/gamma resistance or sell into nearby
            # put/gamma support.
            into_call_resistance = call_dist.notna() & call_dist.ge(0) & call_dist.le(room)
            into_put_support = put_dist.notna() & put_dist.ge(0) & put_dist.le(room)
            near_gamma_above = gamma_above.notna() & gamma_above.ge(0) & gamma_above.le(room)
            near_gamma_below = gamma_below.notna() & gamma_below.ge(0) & gamma_below.le(room)
            env_ok &= ~(positive_gamma & long_signal & (into_call_resistance | near_gamma_above))
            env_ok &= ~(positive_gamma & short_signal & (into_put_support | near_gamma_below))

            # In negative gamma, call/put walls are treated as amplifier
            # triggers. If configured, require long trend/breakout trades to be
            # near/through the call-side trigger and short trend/breakout trades
            # to be near/through the put-side trigger.
            if require_amp:
                call_amplifier = (call_dist.abs().le(amp_trigger)) | (gamma_above.notna() & gamma_above.le(amp_trigger))
                put_amplifier = (put_dist.abs().le(amp_trigger)) | (gamma_below.notna() & gamma_below.le(amp_trigger))
                env_ok &= ~(negative_gamma & trend_or_breakout & long_signal) | call_amplifier
                env_ok &= ~(negative_gamma & trend_or_breakout & short_signal) | put_amplifier

            keep &= env_ok
        elif mode == 'gex_wall_room':
            room = float(p.get('options_flow_wall_room_points', 12.0) or 0.0)
            above_dist = pd.to_numeric(out.get('options_gamma_wall_above_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            below_dist = pd.to_numeric(out.get('options_gamma_wall_below_distance', pd.Series(np.nan, index=out.index)), errors='coerce')
            long_signal = scoped & signal.gt(0)
            short_signal = scoped & signal.lt(0)
            keep &= ~(long_signal & above_dist.notna() & above_dist.ge(0) & above_dist.le(room))
            keep &= ~(short_signal & below_dist.notna() & below_dist.ge(0) & below_dist.le(room))
        else:
            return out

        filtered = active & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def should_compute_cross_asset_context(self) -> bool:
        p = self.strategy_params
        mode = str(p.get('cross_asset_filter', 'off')).lower()
        return bool(
            p.get('cross_asset_context_enabled', False)
            or p.get('cross_asset_features_path')
            or mode not in ('off', 'none', 'false', '0')
        )

    def add_cross_asset_context(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.should_compute_cross_asset_context():
            return df
        p = self.strategy_params
        path = p.get('cross_asset_features_path', DEFAULT_CROSS_ASSET_FEATURES_PATH)
        return add_morning_cross_asset_features(
            df,
            path,
            rth_start=str(p.get('rth_start', '09:30')),
            or15_available_at=str(p.get('or15_signal_bar_5m', '09:40')),
        )

    def apply_cross_asset_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        mode = str(p.get('cross_asset_filter', 'off')).lower()
        if mode in ('off', 'none', 'false', '0') or 'signal' not in df.columns:
            return df

        out = df.copy()
        signal = out['signal'].fillna(0).astype(int)
        active = signal != 0
        if not active.any():
            return out

        allow_missing = bool(p.get('cross_asset_allow_missing', True))
        keep = pd.Series(True, index=out.index)
        long_signal = active & signal.gt(0)
        short_signal = active & signal.lt(0)

        vx_close = pd.to_numeric(out.get('vx_close_945', pd.Series(np.nan, index=out.index)), errors='coerce')
        vx_chg = pd.to_numeric(out.get('vx_or15_change', pd.Series(np.nan, index=out.index)), errors='coerce')
        spx_iv = pd.to_numeric(out.get('spx_iv_close_945', pd.Series(np.nan, index=out.index)), errors='coerce')
        spx_ret = pd.to_numeric(out.get('spx_or15_return_pct', pd.Series(np.nan, index=out.index)), errors='coerce')
        tick_mean = pd.to_numeric(out.get('tick_or15_mean', pd.Series(np.nan, index=out.index)), errors='coerce')
        term_spread = pd.to_numeric(out.get('vx_minus_vix_spot_945', pd.Series(np.nan, index=out.index)), errors='coerce')

        if mode == 'vx_min_level':
            min_vx = float(p.get('cross_asset_min_vx_close_945', 16.0))
            cond = vx_close.ge(min_vx)
            keep &= ~active | (cond | (allow_missing & vx_close.isna()))
        elif mode == 'vx_compressing_on_long':
            max_vx_chg = float(p.get('cross_asset_max_vx_or15_change_long', 0.0))
            cond = vx_chg.le(max_vx_chg)
            keep &= ~long_signal | (cond | (allow_missing & vx_chg.isna()))
        elif mode == 'spx_iv_min_level':
            min_iv = float(p.get('cross_asset_min_spx_iv_945', 0.14))
            cond = spx_iv.ge(min_iv)
            keep &= ~active | (cond | (allow_missing & spx_iv.isna()))
        elif mode == 'spx_direction_confirm':
            long_ok = spx_ret.gt(0.0) | (allow_missing & spx_ret.isna())
            short_ok = spx_ret.lt(0.0) | (allow_missing & spx_ret.isna())
            keep &= (~long_signal | long_ok) & (~short_signal | short_ok)
        elif mode == 'tick_not_exhausted':
            max_tick_long = float(p.get('cross_asset_max_tick_or15_mean_long', 100.0))
            cond = tick_mean.le(max_tick_long)
            keep &= ~long_signal | (cond | (allow_missing & tick_mean.isna()))
        elif mode == 'vix_contango':
            cond = term_spread.ge(0.0)
            keep &= ~active | (cond | (allow_missing & term_spread.isna()))
        else:
            return out

        filtered = active & ~keep
        out.loc[filtered, 'signal'] = 0
        if 'signal_type' in out.columns:
            out.loc[filtered, 'signal_type'] = ''
        return out

    def execution_timeframe(self) -> str:
        return str(self.strategy_params.get('execution_timeframe', '5min')).lower()

    def _get_execution_1m(self) -> pd.DataFrame:
        if self._execution_1m is not None:
            return self._execution_1m

        required_cols = {'time', 'open', 'high', 'low', 'close'}
        if not required_cols.issubset(self.data.columns):
            self._execution_1m = pd.DataFrame()
            self._execution_times = np.array([], dtype='datetime64[ns]')
            return self._execution_1m

        cache_key = (id(self.data), len(self.data))
        cached = _EXECUTION_1M_CACHE.get(cache_key)
        if cached is not None and cached[0]() is self.data:
            _, base_df, base_times, _ = cached
        else:
            cols = ['time', 'open', 'high', 'low', 'close']
            base_df = self.data[cols].copy()
            base_df['volume'] = self.data['volume'].to_numpy() if 'volume' in self.data.columns else 0.0
            base_df['time'] = pd.to_datetime(base_df['time'])
            base_df = base_df.sort_values('time').drop_duplicates(subset='time', keep='first').reset_index(drop=True)
            base_times = base_df['time'].to_numpy(dtype='datetime64[ns]')
            is_1m = False
            if len(base_df) >= 2:
                diffs = base_df['time'].diff().dropna()
                if not diffs.empty:
                    is_1m = bool(diffs.mode().iloc[0] <= pd.Timedelta(minutes=1))
            if len(_EXECUTION_1M_CACHE) >= 4:
                _EXECUTION_1M_CACHE.clear()
            try:
                ref_obj = weakref.ref(self.data)
            except TypeError:
                ref_obj = lambda: None
            _EXECUTION_1M_CACHE[cache_key] = (ref_obj, base_df, base_times, is_1m)

        df = base_df
        times_arr = base_times
        if self._preprocessed_5m is not None and 'time' in self._preprocessed_5m.columns and not self._preprocessed_5m.empty:
            pre_times = pd.to_datetime(self._preprocessed_5m['time'], errors='coerce').dropna()
            if not pre_times.empty:
                start_time = np.datetime64(pre_times.min())
                end_time = np.datetime64(pre_times.max() + pd.Timedelta(minutes=5))
                s_idx = int(base_times.searchsorted(start_time, side='left'))
                e_idx = int(base_times.searchsorted(end_time, side='left'))
                if s_idx > 0 or e_idx < len(base_df):
                    df = base_df.iloc[s_idx:e_idx].reset_index(drop=True)
                    times_arr = base_times[s_idx:e_idx]
        self._execution_1m = df
        self._execution_times = times_arr
        return self._execution_1m

    def can_use_1min_execution(self) -> bool:
        if self.execution_timeframe() != '1min':
            return False

        exec_df = self._get_execution_1m()
        if len(exec_df) < 2:
            return False

        cache_key = (id(self.data), len(self.data))
        cached = _EXECUTION_1M_CACHE.get(cache_key)
        if cached is not None and cached[0]() is self.data:
            return cached[3]

        diffs = exec_df['time'].diff().dropna()
        if diffs.empty:
            return False

        return diffs.mode().iloc[0] <= pd.Timedelta(minutes=1)

    def use_volume_profile_mr_target(self) -> bool:
        p = self.strategy_params
        target_reference = str(p.get('mr_target_reference', '')).lower()
        return bool(
            target_reference == 'vp_poc'
            or p.get('strategy_name') in ('volume_profile_regime', 'hybrid_profile_regime_no_orb')
        )

    def entry_delay_bars(self) -> int:
        return max(0, int(self.strategy_params.get('entry_delay_bars', 0) or 0))

    def _prepare_signal_frame(self, pre_df: pd.DataFrame) -> pd.DataFrame:
        df = pre_df.copy()
        if {'orb_high', 'orb_low', 'orb_range'}.issubset(df.columns) and self.strategy_params.get('strategy_name') not in ('morning_va_breakout', 'morning_or15_fade'):
            df = self.classify_day_regime(df)
        df = self.generate_signals(df)
        df = self.apply_market_profile_signal_filters(df)
        df = self.apply_market_structure_signal_filters(df)
        df = self.apply_vsa_signal_filters(df)
        df = self.apply_markov_regime_signal_filters(df)
        df = self.apply_market_memory_signal_filters(df)
        df = self.apply_options_flow_signal_filters(df)
        df = self.apply_cross_asset_signal_filters(df)
        df = self.apply_signal_filters(df)

        # Guard: zero out signals on bars where VWAP is missing.  Pre-RTH bars
        # (when vwap_session='rth') get NaN VWAP; comparisons like
        # `close > vwap` silently produce False/NaN and can leak bad signals.
        if 'vwap' in df.columns and 'signal' in df.columns:
            vwap_missing = df['vwap'].isna()
            has_signal = df['signal'].fillna(0).astype(int) != 0
            bad = vwap_missing & has_signal
            if bad.any():
                df.loc[bad, 'signal'] = 0
                if 'signal_type' in df.columns:
                    df.loc[bad, 'signal_type'] = ''

        return df.reset_index(drop=True)

    def build_signal_frame(self, pre_df: pd.DataFrame | None = None) -> pd.DataFrame:
        """
        Public strategy-brain seam: prepare signals without executing orders.

        This lets research scripts, paper trading, and eventual live routing
        consume the same signal dataframe without depending on portfolio state.
        """
        if pre_df is None:
            pre_df = self.preprocess()
        return self._prepare_signal_frame(pre_df)

    def signal_events(self, pre_df: pd.DataFrame | None = None) -> list[SignalEvent]:
        signal_frame = self.build_signal_frame(pre_df)
        return extract_signal_events(
            signal_frame,
            entry_mode=str(self.strategy_params.get('entry_mode', 'same_bar_close')),
            entry_delay_bars=self.entry_delay_bars(),
        )

    def entry_context_metadata(self, entry_row: pd.Series | None) -> dict:
        if entry_row is None:
            return {}
        context_cols = [
            'day_regime',
            'open_context',
            'gap_points',
            'gap_atr',
            'gap_prior_range_pct',
            'open_location_prior_range',
            'overnight_inventory_points',
            'overnight_inventory_atr',
            'overnight_inventory_direction',
            'overnight_range_atr',
            'gap_inventory_alignment',
            'prior_rth_range_atr',
            'rth_range_so_far_atr',
            'ib_range_atr',
            'above_ib_high',
            'below_ib_low',
            'inside_ib',
            'vp_poc',
            'vp_val',
            'vp_vah',
            'prior_rth_poc',
            'prior_rth_vah',
            'prior_rth_val',
            'prior_rth_close_1m',
            'or15_open',
            'or15_high',
            'or15_low',
            'or15_close',
            'or15_range_points',
            'or15_close_location',
            'first15_return_points',
            'first15_return_pct',
            'vwap',
            'vwap_side',
            'vwap_side_prev',
            'vwap_dev',
            'vwap_dev_prev_points',
            'vwap_z',
            'vwap_cross_direction',
            'vwap_side_age_bars',
            'vsa_residual',
            'vsa_score',
            'vsa_model_r2',
            'vsa_model_slope',
            'vsa_absorption',
            'vsa_thin_move',
            'vsa_rel_range',
            'vsa_rel_volume',
            'hawkes_norm_range',
            'hawkes_vol',
            'hawkes_q_low',
            'hawkes_q_high',
            'hawkes_vol_above_high',
            'hawkes_vol_below_low',
            'hawkes_vol_cross_above_high',
            'hawkes_vol_cross_below_low',
            'hawkes_momentum_signal',
            'cusum_event',
            'cusum_event_up',
            'cusum_event_down',
            'cusum_event_direction',
            'cusum_event_move_points',
            'cusum_event_move_atr',
            'cusum_threshold_points',
            'cusum_bars_since_event',
            'markov_volatility',
            'markov_state',
            'markov_state_label',
            'markov_state_confidence',
            'markov_fit_age_bars',
            'markov_prob_low_vol',
            'markov_prob_mid_vol',
            'markov_prob_high_vol',
            'market_memory_hurst',
            'market_memory_hurst_regime',
            'market_memory_entropy',
            'market_memory_entropy_regime',
            'market_memory_lz_complexity',
            'market_memory_lz_regime',
            'market_memory_tail_alpha',
            'market_memory_tail_alpha_regime',
            'market_memory_tail_threshold_points',
            'market_memory_tail_event',
            'market_memory_state',
            'options_trade_date',
            'options_available_time',
            'options_underlying_price',
            'options_contracts',
            'options_total_oi',
            'options_call_oi',
            'options_put_oi',
            'options_put_call_oi_ratio',
            'options_cleared_volume',
            'options_call_volume',
            'options_put_volume',
            'options_net_gex',
            'options_abs_gex',
            'options_call_gex',
            'options_put_gex',
            'options_net_dex',
            'options_call_dex',
            'options_put_dex',
            'options_vega_exposure',
            'options_avg_iv',
            'options_gex_regime',
            'options_gamma_environment',
            'options_gamma_wall_strike',
            'options_gamma_wall_role',
            'options_gamma_wall_above',
            'options_gamma_wall_below',
            'options_gamma_wall_distance',
            'options_gamma_wall_above_distance',
            'options_gamma_wall_below_distance',
            'options_call_wall_strike',
            'options_put_wall_strike',
            'options_call_wall_role',
            'options_put_wall_role',
            'options_call_wall_distance',
            'options_put_wall_distance',
            *ALL_CROSS_ASSET_COLUMNS,
        ]
        metadata = {}
        for col in context_cols:
            if col not in entry_row.index:
                continue
            value = entry_row[col]
            is_missing = False if isinstance(value, (bool, np.bool_)) else pd.isna(value)
            if is_missing:
                continue
            if isinstance(value, np.generic):
                value = value.item()
            metadata[col] = value
        return metadata

    def preprocess(self, force: bool = False) -> pd.DataFrame:
        """
        Build a 5-min dataframe with indicators + ORB columns.

        VWAP is computed from 1-min bars for accuracy, then merged into the
        5-min frame.  This is reusable for repeated runs (param sweeps /
        walk-forward) as long as indicator-related params are unchanged.
        """
        if self._preprocessed_5m is not None and not force:
            return self._preprocessed_5m

        # Compute VWAP from 1-min data before resampling
        vwap_5m = self.compute_1min_vwap(self.data)
        opening_profile = self.compute_opening_volume_profile(self.data)
        prior_rth_or15 = self.compute_prior_rth_and_or15_features(self.data)

        df = self.resample_to_5min(self.data)

        # Merge accurate VWAP into the 5-min frame
        df = df.merge(vwap_5m, on='time', how='left')

        df = self.calculate_indicators(df)
        df = self.add_market_structure(df)
        df = self.add_market_profile(df)
        if not opening_profile.empty:
            df = df.merge(opening_profile, on='date_str', how='left')
            df = mask_columns_before_clock(
                df,
                ('vp_poc', 'vp_val', 'vp_vah', 'vp_width'),
                available_at=str(self.strategy_params.get('vp_profile_end', self.strategy_params.get('orb_end', '10:00'))),
            )
        if not prior_rth_or15.empty:
            df = df.merge(prior_rth_or15, on='date_str', how='left')
            df = mask_columns_before_clock(
                df,
                (
                    'or15_open',
                    'or15_high',
                    'or15_low',
                    'or15_close',
                    'or15_range_points',
                    'or15_close_location',
                    'first15_return_points',
                    'first15_return_pct',
                ),
                available_at=str(self.strategy_params.get('or15_signal_bar_5m', '09:40')),
            )
        df = self.calculate_opening_ranges(df)
        df = self.add_options_flow(df)
        df = self.add_cross_asset_context(df)
        df = df.reset_index(drop=True)
        self._preprocessed_5m = df
        return df

    def run_on_preprocessed(self, pre_df: pd.DataFrame) -> dict:
        self._preprocessed_5m = pre_df
        if self.can_use_1min_execution():
            return self._run_on_preprocessed_1min_execution(pre_df)
        return self._run_on_preprocessed_bar_level(pre_df)

    def _run_on_preprocessed_1min_execution(self, pre_df: pd.DataFrame) -> dict:
        self.equity_curve = []
        df = self._prepare_signal_frame(pre_df)
        p = self.strategy_params
        times_5m = pd.to_datetime(df['time']).to_numpy(dtype='datetime64[ns]')
        daily_trade_count: dict[str, int] = {}
        max_hold_minutes = int(p.get('max_hold_bars', 0)) * 5
        entry_delay_bars = self.entry_delay_bars()

        i = 1
        signal_arr = pd.to_numeric(df['signal'], errors='coerce').fillna(0).to_numpy(dtype=int) if 'signal' in df.columns else np.zeros(len(df), dtype=int)
        atr_arr = pd.to_numeric(df['atr'], errors='coerce').to_numpy(dtype=float) if 'atr' in df.columns else np.full(len(df), np.nan)
        while i < len(df):
            if signal_arr[i] == 0 or np.isnan(atr_arr[i]):
                i += 1
                continue
            signal_row = df.iloc[i]

            if p.get('entry_mode', 'same_bar_close') == 'next_bar_open':
                entry_i = i + 1 + entry_delay_bars
                if entry_i >= len(df):
                    break
                entry_row = df.iloc[entry_i]
                context_row = df.iloc[max(i, entry_i - 1)]
                direction = 'long' if int(signal_row['signal']) == 1 else 'short'
                signal_type = signal_row['signal_type'] if 'signal_type' in df.columns else None
                entry_price = float(entry_row['open'])
            else:
                direction = 'long' if int(signal_row['signal']) == 1 else 'short'
                signal_type = signal_row['signal_type'] if 'signal_type' in df.columns else None
                if entry_delay_bars > 0:
                    entry_i = i + entry_delay_bars
                    if entry_i >= len(df):
                        break
                    entry_row = df.iloc[entry_i]
                    context_row = df.iloc[max(i, entry_i - 1)]
                    entry_price = float(entry_row['open'])
                else:
                    entry_i = i
                    entry_row = signal_row
                    context_row = signal_row
                    entry_price = float(entry_row['close'])

            if pd.isna(context_row['atr']):
                i += 1
                continue

            if p.get('entry_mode', 'same_bar_close') == 'same_bar_close' and entry_delay_bars == 0:
                entry_time = pd.Timestamp(entry_row['time']) + pd.Timedelta(minutes=5)
            else:
                entry_time = pd.Timestamp(entry_row['time'])
            trade_date = entry_time.strftime('%Y-%m-%d')
            daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0)
            if daily_trade_count[trade_date] >= p['max_trades_per_day']:
                i += 1
                continue

            context_atr = float(context_row['atr'])
            contracts = self.calculate_contracts(context_atr, direction, signal_type)
            if contracts <= 0:
                i += 1
                continue

            setup_tag = f"{signal_type}_{direction}" if signal_type else direction
            open_position = self.portfolio.enter_position(
                entry_price,
                contracts,
                entry_time,
                direction,
                signal_type=signal_type or "",
                setup_tag=setup_tag,
                metadata=self.entry_context_metadata(context_row),
            )
            if open_position is None:
                i += 1
                continue

            vwap_target = None
            target_price = None
            if signal_type == 'mr':
                if self.use_volume_profile_mr_target() and 'vp_poc' in df.columns:
                    target_price = context_row['vp_poc']
                else:
                    vwap_target = context_row['vwap']

            exit_levels = self.build_exit_levels(
                direction,
                entry_price,
                contracts,
                context_atr,
                vwap_target=vwap_target,
                target_price=target_price,
                signal_type=signal_type,
                entry_row=context_row,
            )
            daily_trade_count[trade_date] += 1

            trade_max_hold = max_hold_minutes
            if signal_type == 'va_continuation' and 'continuation_max_hold_bars' in p:
                trade_max_hold = int(p['continuation_max_hold_bars']) * 5

            exit_time, exit_price, exit_reason = self._simulate_trade_on_1m(
                open_position,
                exit_levels,
                entry_time=entry_time,
                max_hold_minutes=trade_max_hold,
                hawkes_exit_time=self.next_hawkes_exit_time(df, entry_i, open_position),
            )
            open_position.reason = exit_reason
            self.portfolio.exit_position(exit_price, exit_time, 0, exit_reason=exit_reason)

            next_signal_time = pd.Timestamp(exit_time).floor('5min')
            i = max(i + 1, int(times_5m.searchsorted(np.datetime64(next_signal_time), side='left')))

        return self.get_results()

    def _run_on_preprocessed_bar_level(self, pre_df: pd.DataFrame) -> dict:
        """
        Execute the backtest on a preprocessed 5-min dataframe.

        Signals are generated using current `strategy_params`.
        """
        # Reset equity curve to prevent leakage across sweep/WF runs
        self.equity_curve = []

        df = self._prepare_signal_frame(pre_df)

        open_position = None
        entry_bar = None
        exit_levels = {}
        pending_signal = None
        pending_signal_type = None
        pending_context_i = None
        pending_entry_delay_remaining = 0
        daily_trade_count = {}
        p = self.strategy_params
        entry_delay_bars = self.entry_delay_bars()

        opens = df['open'].to_numpy(dtype=float)
        closes = df['close'].to_numpy(dtype=float)
        highs = df['high'].to_numpy(dtype=float)
        lows = df['low'].to_numpy(dtype=float)
        timestamps = df['time'].to_numpy()
        atrs = pd.to_numeric(df['atr'], errors='coerce').to_numpy(dtype=float)
        signals = pd.to_numeric(df['signal'], errors='coerce').fillna(0).to_numpy(dtype=int) if 'signal' in df.columns else np.zeros(len(df), dtype=int)
        signal_types = df['signal_type'].to_numpy() if 'signal_type' in df.columns else np.array([None] * len(df))

        for i in range(1, len(df)):
            atr = atrs[i]
            if np.isnan(atr):
                self.equity_curve.append(self.portfolio.get_equity())
                continue

            open_price  = opens[i]
            close_price = closes[i]
            high_price  = highs[i]
            low_price   = lows[i]
            timestamp   = timestamps[i]
            sig         = signals[i]
            sig_type    = signal_types[i]

            if open_position is not None:
                exit_flag = False
                exit_reason = ""
                exit_price = close_price
                use_current_bar_excursion = self.managed_stop_uses_current_bar_excursion()
                if use_current_bar_excursion:
                    self.update_trade_excursions(open_position, high_price, low_price)
                active_exit_levels = self.apply_trade_management(
                    open_position,
                    exit_levels,
                    bars_held=i - entry_bar,
                )

                exit_flag, exit_reason, resolved_exit_price = self.resolve_intrabar_exit(
                    open_position.direction,
                    open_price,
                    high_price,
                    low_price,
                    active_exit_levels,
                )
                if exit_flag:
                    exit_price = resolved_exit_price

                if not exit_flag and not use_current_bar_excursion:
                    self.update_trade_excursions(open_position, high_price, low_price)

                active_hold_bars = int(p.get('continuation_max_hold_bars', p.get('max_hold_bars', 0))) if getattr(open_position, 'signal_type', '') == 'va_continuation' else int(p.get('max_hold_bars', 0))
                if not exit_flag and active_hold_bars > 0 and i - entry_bar >= active_hold_bars:
                    exit_flag, exit_reason, exit_price = True, "time_exit", close_price

                if (
                    not exit_flag
                    and self.should_hawkes_exit(open_position, df.loc[i], bars_held=i - entry_bar)
                ):
                    exit_flag, exit_reason, exit_price = True, "hawkes_vol_exit", close_price

                if exit_flag:
                    open_position.reason = exit_reason
                    self.portfolio.exit_position(exit_price, timestamp, 0, exit_reason=exit_reason)
                    open_position = None
                    exit_levels = {}

            if open_position is None and pending_signal is not None:
                if pending_entry_delay_remaining > 0:
                    pending_entry_delay_remaining -= 1
                    pending_context_i = i
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue

                trade_date = str(timestamp)[:10]
                daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0)
                direction = 'long' if pending_signal == 1 else 'short'
                setup_tag = f"{pending_signal_type}_{direction}" if pending_signal_type else direction
                context_i = pending_context_i if pending_context_i is not None else max(0, i - 1)
                context_row = df.loc[context_i]
                if pd.isna(context_row['atr']):
                    pending_signal = None
                    pending_signal_type = None
                    pending_context_i = None
                    pending_entry_delay_remaining = 0
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue
                context_atr = float(context_row['atr'])
                contracts = self.calculate_contracts(context_atr, direction, pending_signal_type)

                if daily_trade_count[trade_date] < p['max_trades_per_day'] and contracts > 0:
                    open_position = self.portfolio.enter_position(
                        open_price,
                        contracts,
                        timestamp,
                        direction,
                        signal_type=pending_signal_type or "",
                        setup_tag=setup_tag,
                        metadata=self.entry_context_metadata(context_row),
                    )
                    # Circuit breaker: enter_position returns None when equity too low
                    if open_position is not None:
                        entry_bar = i
                        vwap_target = None
                        target_price = None
                        if pending_signal_type == 'mr':
                            if self.use_volume_profile_mr_target() and 'vp_poc' in df.columns:
                                target_price = context_row['vp_poc']
                            else:
                                vwap_target = context_row['vwap']
                        exit_levels = self.build_exit_levels(
                            direction,
                            open_price,
                            contracts,
                            context_atr,
                            vwap_target=vwap_target,
                            target_price=target_price,
                            signal_type=pending_signal_type,
                            entry_row=context_row,
                        )
                        daily_trade_count[trade_date] += 1
                        self.update_trade_excursions(open_position, high_price, low_price)

                        exit_flag, exit_reason, resolved_exit_price = self.resolve_intrabar_exit(
                            direction,
                            open_price,
                            high_price,
                            low_price,
                            exit_levels,
                        )
                        if exit_flag:
                            open_position.reason = exit_reason
                            self.portfolio.exit_position(resolved_exit_price, timestamp, 0, exit_reason=exit_reason)
                            open_position = None
                            exit_levels = {}

                pending_signal = None
                pending_signal_type = None
                pending_context_i = None
                pending_entry_delay_remaining = 0

            if open_position is None and pending_signal is None and sig != 0:
                if p.get('entry_mode', 'same_bar_close') == 'next_bar_open':
                    pending_signal = sig
                    pending_signal_type = sig_type
                    pending_context_i = i
                    pending_entry_delay_remaining = entry_delay_bars
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue

                if entry_delay_bars > 0:
                    pending_signal = sig
                    pending_signal_type = sig_type
                    pending_context_i = i
                    pending_entry_delay_remaining = max(0, entry_delay_bars - 1)
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue

                trade_date = str(timestamp)[:10]
                daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0)
                if daily_trade_count[trade_date] >= p['max_trades_per_day']:
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue

                signal_type = sig_type
                direction = 'long' if sig == 1 else 'short'
                setup_tag = f"{signal_type}_{direction}" if signal_type else direction
                contracts = self.calculate_contracts(atr, direction, signal_type)
                if contracts == 0:
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue

                open_position = self.portfolio.enter_position(
                    close_price,
                    contracts,
                    timestamp,
                    direction,
                    signal_type=signal_type or "",
                    setup_tag=setup_tag,
                    metadata=self.entry_context_metadata(df.loc[i]),
                )
                # Circuit breaker: enter_position returns None when equity too low
                if open_position is None:
                    self.equity_curve.append(self.portfolio.get_equity())
                    continue
                daily_trade_count[trade_date] += 1
                vwap_target = None
                target_price = None
                if signal_type == 'mr':
                    if self.use_volume_profile_mr_target() and 'vp_poc' in df.columns:
                        target_price = df.loc[i, 'vp_poc']
                    else:
                        vwap_target = df.loc[i, 'vwap']
                exit_levels = self.build_exit_levels(
                    direction,
                    close_price,
                    contracts,
                    atr,
                    vwap_target=vwap_target,
                    target_price=target_price,
                    signal_type=signal_type,
                    entry_row=df.loc[i],
                )
                entry_bar = i

        self.equity_curve.append(self.portfolio.get_equity())

        if open_position is not None:
            open_position.reason = "end_of_data"
            self.portfolio.exit_position(df.loc[len(df)-1, 'close'], df.loc[len(df)-1, 'time'], 0, exit_reason="end_of_data")

        return self.get_results()

    def run(self) -> dict:
        print("  Preprocessing 5-min bars + indicators...")
        pre_df = self.preprocess()
        print(f"  {len(pre_df):,} bars ready")
        print("  Running execution loop...")
        return self.run_on_preprocessed(pre_df)

    def get_results(self) -> dict:
        trades_df = self.portfolio.get_trade_log()

        if len(trades_df) == 0:
            return {'error': 'No trades generated'}

        trades_df = trades_df.sort_values('exit_time').reset_index(drop=True)
        trades_df['cumulative_pnl'] = trades_df['pnl'].cumsum()
        trades_df['equity'] = self.portfolio.initial_capital + trades_df['cumulative_pnl']
        bar_metrics = bar_objective_metrics(
            self._preprocessed_5m if self._preprocessed_5m is not None else self.resample_to_5min(self.data),
            trades_df,
            self.futures_specs,
            self.portfolio.initial_capital,
        )
        execution_bar_metrics = execution_bar_objective_metrics(
            self._get_execution_1m(),
            trades_df,
            self.futures_specs,
            self.portfolio.initial_capital,
        )

        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['pnl'] > 0])
        losing_trades = len(trades_df[trades_df['pnl'] <= 0])
        total_pnl = trades_df['pnl'].sum()
        avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['pnl'] <= 0]['pnl'].mean() if losing_trades > 0 else 0
        win_sum = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        loss_sum = abs(trades_df[trades_df['pnl'] <= 0]['pnl'].sum())
        profit_factor = win_sum / loss_sum if loss_sum > 0 else (float("inf") if win_sum > 0 else 0)

        max_dd = 0
        equity_array = np.concatenate((
            [self.portfolio.initial_capital],
            trades_df['equity'].to_numpy()
        ))
        peak = equity_array[0]
        for val in equity_array:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            if dd > max_dd:
                max_dd = dd

        long_trades = trades_df[trades_df['direction'] == 'long']
        short_trades = trades_df[trades_df['direction'] == 'short']
        long_pnl = long_trades['pnl'].sum() if len(long_trades) > 0 else 0
        short_pnl = short_trades['pnl'].sum() if len(short_trades) > 0 else 0
        long_loss_sum = abs(long_trades[long_trades['pnl'] <= 0]['pnl'].sum())
        short_loss_sum = abs(short_trades[short_trades['pnl'] <= 0]['pnl'].sum())
        long_profit_factor = (
            long_trades[long_trades['pnl'] > 0]['pnl'].sum() / long_loss_sum
            if long_loss_sum > 0
            else (float("inf") if long_trades[long_trades['pnl'] > 0]['pnl'].sum() > 0 else 0)
        )
        short_profit_factor = (
            short_trades[short_trades['pnl'] > 0]['pnl'].sum() / short_loss_sum
            if short_loss_sum > 0
            else (float("inf") if short_trades[short_trades['pnl'] > 0]['pnl'].sum() > 0 else 0)
        )

        consecutive_wins = 0
        consecutive_losses = 0
        max_consec_wins = 0
        max_consec_losses = 0
        for pnl in trades_df['pnl']:
            if pnl > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consec_wins = max(max_consec_wins, consecutive_wins)
            else:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consec_losses = max(max_consec_losses, consecutive_losses)

        trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
        trades_df['hold_minutes'] = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
        avg_hold = trades_df['hold_minutes'].mean()

        daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.normalize())['pnl'].sum()
        active_trade_days = len(daily_pnl)
        source_df = self._preprocessed_5m if self._preprocessed_5m is not None else self.data
        if active_trade_days > 1 and source_df is not None and 'time' in source_df.columns and not source_df.empty:
            src_times = pd.to_datetime(source_df['time'], errors='coerce').dropna()
            rth_s_parts = str(self.strategy_params.get('rth_start', '09:30')).split(':')
            rth_e_parts = str(self.strategy_params.get('rth_end', '16:00')).split(':')
            rth_s_min = int(rth_s_parts[0]) * 60 + int(rth_s_parts[1])
            rth_e_min = int(rth_e_parts[0]) * 60 + int(rth_e_parts[1])
            hm_min = src_times.dt.hour * 60 + src_times.dt.minute
            rth_dates = src_times.loc[(hm_min >= rth_s_min) & (hm_min <= rth_e_min)].dt.normalize().unique()
            session_dates = pd.DatetimeIndex(sorted(rth_dates if len(rth_dates) >= 2 else src_times.dt.normalize().unique()))
            if len(session_dates) >= 2:
                daily_pnl = daily_pnl.reindex(session_dates.union(daily_pnl.index)).fillna(0.0).sort_index()
        daily_equity = daily_pnl.cumsum() + self.portfolio.initial_capital
        daily_returns = daily_equity.pct_change().dropna()
        sharpe = (
            daily_returns.mean() / daily_returns.std() * np.sqrt(252)
            if active_trade_days > 1 and len(daily_returns) > 1 and daily_returns.std() > 0
            else 0
        )

        return_pct = (self.portfolio.get_equity() - self.portfolio.initial_capital) / self.portfolio.initial_capital * 100
        expectancy = (winning_trades / total_trades * avg_win) + (losing_trades / total_trades * avg_loss)
        calmar = return_pct / max_dd if max_dd > 0 else 0

        results_out = {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': (winning_trades / total_trades * 100),
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'sharpe_ratio': sharpe,
            'calmar_ratio': calmar,
            'max_drawdown': max_dd,
            'max_consec_wins': max_consec_wins,
            'max_consec_losses': max_consec_losses,
            'avg_hold_minutes': avg_hold,
            'best_trade': trades_df['pnl'].max(),
            'worst_trade': trades_df['pnl'].min(),
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'long_total_pnl': long_pnl,
            'short_total_pnl': short_pnl,
            'long_profit_factor': long_profit_factor,
            'short_profit_factor': short_profit_factor,
            'long_win_rate': (len(long_trades[long_trades['pnl'] > 0]) / len(long_trades) * 100) if len(long_trades) > 0 else 0,
            'short_win_rate': (len(short_trades[short_trades['pnl'] > 0]) / len(short_trades) * 100) if len(short_trades) > 0 else 0,
            'final_equity': self.portfolio.get_equity(),
            'return_pct': return_pct,
            'circuit_breaker_triggered': self.portfolio.circuit_breaker_triggered,
            'equity_curve': equity_array.tolist(),
            'trades': trades_df,
            **bar_metrics,
            **execution_bar_metrics,
        }

        # Rule 5: Automatic fail-safe recording into provenance store
        if self.strategy_params.get("auto_record_provenance", False):
            try:
                import math
                from backtest.provenance import default_store
                strat_name = str(self.strategy_params.get("name", "Custom Backtest"))
                strat_id = str(self.strategy_params.get("strategy_id", strat_name.lower().replace(" ", "_")))
                data_path = str(self.strategy_params.get("data_path", "data/raw/data.parquet"))
                d_start = str(trades_df['entry_time'].min())[:10] if not trades_df.empty else "N/A"
                d_end = str(trades_df['exit_time'].max())[:10] if not trades_df.empty else "N/A"
                default_store.record_run(
                    strategy_id=strat_id,
                    strategy_name=strat_name,
                    methodology=str(self.strategy_params.get("methodology", "historical_simulation")),
                    date_start=d_start,
                    date_end=d_end,
                    data_path=data_path,
                    total_trades=total_trades,
                    win_rate=(winning_trades / total_trades * 100) if total_trades > 0 else 0.0,
                    profit_factor=profit_factor,
                    gross_profit=win_sum,
                    net_profit=total_pnl,
                    max_drawdown=max_dd,
                    sharpe_ratio=sharpe if sharpe is not None and not math.isnan(sharpe) else 0.0,
                    largest_win=float(trades_df['pnl'].max()) if not trades_df.empty else 0.0,
                    slippage_model=str(self.strategy_params.get("slippage_model", "CQG Realism")),
                    commission_model=str(self.strategy_params.get("commission_model", "$1.40 RT micro")),
                    is_net=True,
                    params=self.strategy_params,
                )
            except Exception:
                pass

        return results_out
