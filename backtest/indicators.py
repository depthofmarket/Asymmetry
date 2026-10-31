"""Data preprocessing, indicator computation, regime classification."""


import numpy as np
import pandas as pd
import ta

from backtest.auction_context import add_futures_auction_context
from backtest.event_sampling import add_cusum_event_features
from backtest.hawkes import add_hawkes_volatility_features
from backtest.market_memory import add_market_memory_features
from backtest.markov_regime import add_markov_regime_features
from backtest.point_in_time import mask_columns_before_clock
from backtest.volume_spread import add_volume_spread_features

_HM_LOOKUP = np.array([f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)], dtype=object)


def _hm_to_minutes(hm: str) -> int:
    h, m = str(hm).split(":", 1)
    return int(h) * 60 + int(m)


def _fast_hour_min(dt: pd.Series) -> pd.Series:
    idx = (dt.dt.hour.to_numpy(dtype=int) * 60 + dt.dt.minute.to_numpy(dtype=int)) % 1440
    return pd.Series(_HM_LOOKUP[idx], index=dt.index, dtype=object)


def _fast_date_str(dt: pd.Series) -> pd.Series:
    norm = dt.dt.normalize()
    uniq = pd.Index(norm.dropna().unique())
    mapping = pd.Series(uniq.strftime("%Y-%m-%d"), index=uniq)
    return norm.map(mapping)


class IndicatorMixin:
    """Mixin extracted from BacktestEngine — Data preprocessing, indicator computation, regime classification."""

    def _session_confirm(self, mask: pd.Series, session_key: pd.Series, bars: int) -> pd.Series:
        if bars <= 1:
            return mask.fillna(False).astype(bool)
        return (
            mask.fillna(False)
            .astype(int)
            .groupby(session_key)
            .transform(lambda s: s.rolling(window=bars, min_periods=bars).sum())
            .ge(bars)
        )

    def _vwap_reversion_context(self, df: pd.DataFrame, signal_type: str) -> tuple[pd.Series, pd.Series]:
        index = df.index
        false = pd.Series(False, index=index)
        required = {'close', 'vwap', 'vwap_z'}
        if not required.issubset(df.columns):
            return false, false

        p = self.strategy_params
        z = pd.to_numeric(df['vwap_z'], errors='coerce')
        session_key = df.get('_vwap_session', df.get('date_str', pd.Series(0, index=index)))

        def rolling_extreme(window: int, mode: str) -> pd.Series:
            grouped = z.groupby(session_key, dropna=False)
            if mode == 'min':
                return grouped.transform(lambda s: s.rolling(window=window, min_periods=1).min())
            return grouped.transform(lambda s: s.rolling(window=window, min_periods=1).max())

        long_lookback = max(
            1,
            int(
                self.get_signal_param(
                    signal_type,
                    'long',
                    'vwap_reversion_lookback_bars',
                    p.get('vwap_reversion_lookback_bars', 4),
                )
                or 4
            ),
        )
        short_lookback = max(
            1,
            int(
                self.get_signal_param(
                    signal_type,
                    'short',
                    'vwap_reversion_lookback_bars',
                    p.get('vwap_reversion_lookback_bars', 4),
                )
                or 4
            ),
        )
        long_extreme = rolling_extreme(long_lookback, 'min')
        short_extreme = rolling_extreme(short_lookback, 'max')

        long_entry_z = float(
            self.get_signal_param(
                signal_type,
                'long',
                'vwap_reversion_entry_z',
                p.get('vwap_reversion_entry_z', 1.5),
            )
        )
        short_entry_z = float(
            self.get_signal_param(
                signal_type,
                'short',
                'vwap_reversion_entry_z',
                p.get('vwap_reversion_entry_z', 1.5),
            )
        )
        long_reclaim_z = float(
            self.get_signal_param(
                signal_type,
                'long',
                'vwap_reversion_reclaim_z',
                p.get('vwap_reversion_reclaim_z', 0.35),
            )
        )
        short_reclaim_z = float(
            self.get_signal_param(
                signal_type,
                'short',
                'vwap_reversion_reclaim_z',
                p.get('vwap_reversion_reclaim_z', 0.35),
            )
        )

        long_ctx = (
            z.notna()
            & long_extreme.le(-long_entry_z)
            & (z - long_extreme).ge(long_reclaim_z)
        )
        short_ctx = (
            z.notna()
            & short_extreme.ge(short_entry_z)
            & (short_extreme - z).ge(short_reclaim_z)
        )

        long_max_z = float(
            self.get_signal_param(
                signal_type,
                'long',
                'vwap_reversion_max_z',
                p.get('vwap_reversion_max_z', 3.5),
            )
        )
        short_max_z = float(
            self.get_signal_param(
                signal_type,
                'short',
                'vwap_reversion_max_z',
                p.get('vwap_reversion_max_z', 3.5),
            )
        )
        if long_max_z > 0:
            long_ctx &= long_extreme.ge(-long_max_z)
        if short_max_z > 0:
            short_ctx &= short_extreme.le(short_max_z)

        require_counter_side = bool(
            p.get(
                f'{signal_type}_vwap_reversion_require_still_counter_vwap',
                p.get('vwap_reversion_require_still_counter_vwap', True),
            )
        )
        if require_counter_side:
            long_ctx &= df['close'].lt(df['vwap'])
            short_ctx &= df['close'].gt(df['vwap'])

        if 'close_strength' in df.columns:
            long_strength_min = self.get_signal_param(
                signal_type,
                'long',
                'vwap_reversion_close_strength_min',
                p.get('vwap_reversion_long_close_strength_min'),
            )
            short_strength_max = self.get_signal_param(
                signal_type,
                'short',
                'vwap_reversion_close_strength_max',
                p.get('vwap_reversion_short_close_strength_max'),
            )
            if long_strength_min is not None:
                long_ctx &= df['close_strength'].ge(float(long_strength_min))
            if short_strength_max is not None:
                short_ctx &= df['close_strength'].le(float(short_strength_max))

        return long_ctx.fillna(False), short_ctx.fillna(False)


    def resample_to_5min(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time')
        resampled = df.resample('5min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        resampled = resampled.reset_index()
        return resampled

    def _time_mask(self, times: pd.Series, start: str, end: str) -> pd.Series:
        dt = pd.to_datetime(times)
        hm_min = dt.dt.hour * 60 + dt.dt.minute
        s_min = _hm_to_minutes(start)
        e_min = _hm_to_minutes(end)
        if s_min <= e_min:
            return hm_min.ge(s_min) & hm_min.lt(e_min)
        return hm_min.ge(s_min) | hm_min.lt(e_min)

    def _vwap_session_key(self, times: pd.Series, session_mode: str) -> pd.Series:
        dt = pd.to_datetime(times)
        session = dt.dt.normalize()
        if session_mode in ("globex", "futures", "eth"):
            after_18 = (dt.dt.hour > 18) | ((dt.dt.hour == 18) & (dt.dt.minute >= 0))
            session = session.mask(after_18, session + pd.Timedelta(days=1))
        return session

    def compute_1min_vwap(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """
        Compute VWAP on 1-min bars (per session), then resample to 5-min by
        taking the last VWAP value in each 5-min window.

        Returns a 5-min dataframe with a 'vwap' column.
        """
        df = df_1m.copy()
        df['time'] = pd.to_datetime(df['time'])
        session_mode = str(self.strategy_params.get('vwap_session', 'rth')).lower()
        df['_vwap_session'] = self._vwap_session_key(df['time'], session_mode)

        active = pd.Series(True, index=df.index)
        if session_mode == "rth":
            active = self._time_mask(
                df['time'],
                str(self.strategy_params.get('rth_start', '09:30')),
                str(self.strategy_params.get('rth_end', '16:00')),
            )

        # Cumulative typical-price * volume, per session
        df['vwap_1m'] = np.nan
        typical_price = (df['high'] + df['low'] + df['close']) / 3.0
        work = df.loc[active].copy()
        if work.empty:
            return pd.DataFrame(columns=['time', 'vwap'])
        work['_tp_vol'] = typical_price.loc[work.index] * work['volume']
        work['_cum_tp_vol'] = work.groupby('_vwap_session')['_tp_vol'].cumsum()
        work['_cum_vol'] = work.groupby('_vwap_session')['volume'].cumsum()
        df.loc[work.index, 'vwap_1m'] = work['_cum_tp_vol'] / work['_cum_vol'].replace(0, np.nan)

        # Resample: take the last 1-min VWAP within each 5-min window
        df = df.set_index('time')
        vwap_5m = df['vwap_1m'].resample('5min').last().dropna().reset_index()
        vwap_5m.columns = ['time', 'vwap']
        return vwap_5m

    def build_value_area(self, volume_by_price: pd.Series, value_area_pct: float) -> tuple[float, float, float]:
        """
        Approximate a session volume profile by assigning each 1-min bar's full
        volume to its typical price bin, then expand outward from POC until the
        requested value-area percentage is covered.
        """
        if volume_by_price.empty:
            return np.nan, np.nan, np.nan

        volume_by_price = volume_by_price.sort_index()
        prices = volume_by_price.index.to_numpy(dtype=float)
        volumes = volume_by_price.to_numpy(dtype=float)

        poc_idx = int(np.argmax(volumes))
        low_idx = poc_idx
        high_idx = poc_idx
        cumulative_volume = float(volumes[poc_idx])
        target_volume = float(volumes.sum()) * float(value_area_pct)

        while cumulative_volume < target_volume and (low_idx > 0 or high_idx < len(volumes) - 1):
            down_volume = volumes[low_idx - 1] if low_idx > 0 else -1.0
            up_volume = volumes[high_idx + 1] if high_idx < len(volumes) - 1 else -1.0

            if up_volume > down_volume:
                high_idx += 1
                cumulative_volume += float(volumes[high_idx])
            elif down_volume > up_volume:
                low_idx -= 1
                cumulative_volume += float(volumes[low_idx])
            else:
                if low_idx > 0:
                    low_idx -= 1
                    cumulative_volume += float(volumes[low_idx])
                if cumulative_volume >= target_volume:
                    break
                if high_idx < len(volumes) - 1:
                    high_idx += 1
                    cumulative_volume += float(volumes[high_idx])

        return float(prices[poc_idx]), float(prices[low_idx]), float(prices[high_idx])

    def compute_opening_volume_profile(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        tick_size = float(p.get('vp_tick_size', 0.25))
        value_area_pct = float(p.get('vp_value_area_pct', 0.70))
        profile_start = p.get('vp_profile_start', p.get('orb_start', '09:30'))
        profile_end = p.get('vp_profile_end', p.get('orb_end', '10:00'))

        t_series = pd.to_datetime(df_1m['time'])
        hm_min = t_series.dt.hour * 60 + t_series.dt.minute
        s_min = _hm_to_minutes(profile_start)
        e_min = _hm_to_minutes(profile_end)
        profile_mask = (hm_min >= s_min) & (hm_min < e_min)
        profile_df = df_1m.loc[profile_mask, ['high', 'low', 'close', 'volume']].copy()
        if profile_df.empty:
            return pd.DataFrame(columns=['date_str', 'vp_poc', 'vp_val', 'vp_vah', 'vp_width'])
        profile_df['date_str'] = _fast_date_str(t_series.loc[profile_mask])

        typical_price = (profile_df['high'] + profile_df['low'] + profile_df['close']) / 3.0
        profile_df['price_bin'] = np.round((typical_price / tick_size)) * tick_size
        profile_df['price_bin'] = profile_df['price_bin'].round(6)

        profile_rows = []
        for date_str, day_df in profile_df.groupby('date_str', sort=False):
            volume_by_price = day_df.groupby('price_bin')['volume'].sum()
            vp_poc, vp_val, vp_vah = self.build_value_area(volume_by_price, value_area_pct)
            profile_rows.append({
                'date_str': date_str,
                'vp_poc': vp_poc,
                'vp_val': vp_val,
                'vp_vah': vp_vah,
                'vp_width': vp_vah - vp_val if np.isfinite(vp_vah) and np.isfinite(vp_val) else np.nan,
            })

        return pd.DataFrame(profile_rows)

    def compute_prior_rth_and_or15_features(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        bin_size = float(p.get('prior_rth_profile_bin_size', 1.0))
        value_area_pct = float(p.get('prior_rth_value_area_pct', p.get('vp_value_area_pct', 0.70)))
        rth_start = str(p.get('rth_start', '09:30'))
        rth_end = str(p.get('rth_end', '16:00'))
        or15_end_1m = str(p.get('or15_end_1m', '09:44'))

        df = df_1m[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
        df['time'] = pd.to_datetime(df['time'])
        if not df['time'].is_monotonic_increasing or df['time'].isna().any():
            df = df.dropna(subset=['time']).sort_values('time', kind='stable').reset_index(drop=True)
        hm_min = df['time'].dt.hour * 60 + df['time'].dt.minute
        rth_s_min = _hm_to_minutes(rth_start)
        rth_e_min = _hm_to_minutes(rth_end)
        or15_e_min = _hm_to_minutes(or15_end_1m)

        rth_mask = (hm_min >= rth_s_min) & (hm_min <= rth_e_min)
        rth = df.loc[rth_mask].copy()
        if rth.empty:
            return pd.DataFrame(
                columns=[
                    'date_str',
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
                ]
            )
        rth['date_str'] = _fast_date_str(rth['time'])

        from backtest.poc_rejection_signal import _compute_prior_session_profiles

        prior_profiles = _compute_prior_session_profiles(
            rth,
            bin_size=bin_size,
            value_area_pct=value_area_pct,
        )
        prior_profiles['date_str'] = pd.to_datetime(prior_profiles['session']).dt.strftime('%Y-%m-%d')
        prior_close_by_date = rth.groupby('date_str', sort=True)['close'].last().shift(1)
        prior_profiles['prior_rth_close_1m'] = prior_profiles['date_str'].map(prior_close_by_date)
        prior_profiles = prior_profiles.rename(
            columns={
                'prior_poc': 'prior_rth_poc',
                'prior_vah': 'prior_rth_vah',
                'prior_val': 'prior_rth_val',
            }
        )[['date_str', 'prior_rth_poc', 'prior_rth_vah', 'prior_rth_val', 'prior_rth_close_1m']]

        or15_mask = (hm_min >= rth_s_min) & (hm_min <= or15_e_min)
        or15_bars = df.loc[or15_mask].copy()
        if not or15_bars.empty:
            or15_bars['date_str'] = _fast_date_str(or15_bars['time'])
        if or15_bars.empty:
            for col in (
                'or15_open',
                'or15_high',
                'or15_low',
                'or15_close',
                'or15_range_points',
                'or15_close_location',
                'first15_return_points',
                'first15_return_pct',
            ):
                prior_profiles[col] = np.nan
            return prior_profiles

        or15_stats = (
            or15_bars.groupby('date_str', sort=True)
            .agg(
                or15_open=('open', 'first'),
                or15_high=('high', 'max'),
                or15_low=('low', 'min'),
                or15_close=('close', 'last'),
            )
            .reset_index()
        )
        or15_range = (or15_stats['or15_high'] - or15_stats['or15_low']).replace(0.0, np.nan)
        or15_stats['or15_range_points'] = or15_range
        or15_stats['or15_close_location'] = (or15_stats['or15_close'] - or15_stats['or15_low']) / or15_range
        or15_stats['first15_return_points'] = or15_stats['or15_close'] - or15_stats['or15_open']
        or15_stats['first15_return_pct'] = (
            or15_stats['first15_return_points'] / or15_stats['or15_open'].replace(0.0, np.nan)
        )

        return prior_profiles.merge(or15_stats, on='date_str', how='left')


    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.strategy_params

        df['trend_ema'] = ta.trend.EMAIndicator(df['close'], window=p['trend_ema_period']).ema_indicator()
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=p.get('rsi_period', 14)).rsi()
        df['atr'] = ta.volatility.AverageTrueRange(
            df['high'], df['low'], df['close'], window=p['atr_period']
        ).average_true_range()
        df['atr_avg'] = df['atr'].rolling(window=50).mean()
        df['atr_normal'] = df['atr'] < (df['atr_avg'] * p['atr_max_multiplier'])

        df['date'] = pd.to_datetime(df['time']).dt.date
        vwap_session = str(p.get('vwap_session', 'rth')).lower()
        df['_vwap_session'] = self._vwap_session_key(df['time'], vwap_session)
        # VWAP is already computed from 1-min data and merged in preprocess().
        # If missing (e.g. run_on_preprocessed called directly), fall back to 5-min approx.
        if 'vwap' not in df.columns:
            df['vwap'] = np.nan
            active = pd.Series(True, index=df.index)
            if vwap_session == "rth":
                active = self._time_mask(
                    df['time'],
                    str(p.get('rth_start', '09:30')),
                    str(p.get('rth_end', '16:00')),
                )
            work = df.loc[active].copy()
            if not work.empty:
                tp_vol = work['close'] * work['volume']
                df.loc[work.index, 'vwap'] = (
                    tp_vol.groupby(work['_vwap_session']).transform('cumsum') /
                    work['volume'].groupby(work['_vwap_session']).transform('cumsum')
                )

        # VWAP distance & z-score (for mean reversion logic)
        vwap_dev = df['close'] - df['vwap']
        df['vwap_dev'] = vwap_dev
        vwap_std = vwap_dev.groupby(df['_vwap_session']).transform(lambda s: s.rolling(window=p.get('vwap_z_window', 20)).std())
        df['vwap_z'] = (vwap_dev / vwap_std).replace([np.inf, -np.inf], np.nan)

        vwap_valid = df['vwap'].notna() & df['close'].notna()
        vwap_side = pd.Series('unknown', index=df.index, dtype='object')
        vwap_side.loc[vwap_valid & df['close'].gt(df['vwap'])] = 'above_vwap'
        vwap_side.loc[vwap_valid & df['close'].lt(df['vwap'])] = 'below_vwap'
        vwap_side.loc[vwap_valid & df['close'].eq(df['vwap'])] = 'at_vwap'
        df['vwap_side'] = vwap_side

        prev_side = vwap_side.groupby(df['_vwap_session']).shift(1).fillna('unknown')
        df['vwap_side_prev'] = prev_side
        df['vwap_dev_prev_points'] = vwap_dev.groupby(df['_vwap_session']).shift(1)
        df['vwap_cross_direction'] = 'none'
        df.loc[vwap_side.eq('above_vwap') & prev_side.isin(['below_vwap', 'at_vwap']), 'vwap_cross_direction'] = 'cross_up'
        df.loc[vwap_side.eq('below_vwap') & prev_side.isin(['above_vwap', 'at_vwap']), 'vwap_cross_direction'] = 'cross_down'

        directional_side = vwap_side.where(vwap_side.isin(['above_vwap', 'below_vwap']))
        side_changed = (
            directional_side.ne(directional_side.shift(1))
            | df['_vwap_session'].ne(df['_vwap_session'].shift(1))
            | directional_side.isna()
        )
        side_run = side_changed.cumsum()
        side_age = directional_side.groupby([df['_vwap_session'], side_run], dropna=False).cumcount() + 1
        df['vwap_side_age_bars'] = side_age.where(directional_side.notna(), 0).astype(int)

        # Trend strength proxy (EMA slope, in points per bar)
        slope_n = int(p.get('trend_slope_bars', 6))
        if slope_n < 1:
            slope_n = 1
        df['trend_ema_slope'] = (df['trend_ema'] - df['trend_ema'].shift(slope_n)) / slope_n

        df['volume_sma'] = df['volume'].rolling(window=p['volume_sma_period']).mean()
        df['volume_spike'] = df['volume'] > (df['volume_sma'] * p['volume_spike_multiplier'])

        if bool(p.get('vsa_enabled', True)):
            df = add_volume_spread_features(
                df,
                lookback_bars=int(p.get('vsa_lookback_bars', 390)),
                min_r2=float(p.get('vsa_min_r2', 0.10)),
                min_slope=float(p.get('vsa_min_slope', 0.0)),
                score_scale=float(p.get('vsa_score_scale', 1.0)),
                extreme_threshold=float(p.get('vsa_extreme_threshold', 0.65)),
            )

        if bool(p.get('hawkes_enabled', True)):
            df = add_hawkes_volatility_features(
                df,
                norm_lookback_bars=int(p.get('hawkes_norm_lookback_bars', 390)),
                threshold_lookback_bars=int(p.get('hawkes_threshold_lookback_bars', 390)),
                kappa=float(p.get('hawkes_kappa', 0.10)),
                low_quantile=float(p.get('hawkes_low_quantile', 0.05)),
                high_quantile=float(p.get('hawkes_high_quantile', 0.95)),
            )

        if bool(p.get('cusum_event_enabled', True)):
            df = add_cusum_event_features(
                df,
                threshold_atr_multiple=float(p.get('cusum_event_atr_multiple', 1.0)),
                min_threshold_points=float(p.get('cusum_event_min_threshold_points', 0.25)),
            )

        df = self.add_markov_regime(df)
        df = self.add_market_memory(df)

        df['time_dt'] = pd.to_datetime(df['time'])
        df['hour_min'] = _fast_hour_min(df['time_dt'])
        df['date_str'] = _fast_date_str(df['time_dt'])
        df = add_futures_auction_context(
            df,
            rth_start=str(p.get('rth_start', '09:30')),
            rth_end=str(p.get('rth_end', '16:00')),
            initial_balance_end=str(p.get('initial_balance_end', '10:30')),
        )

        return df

    def calculate_opening_ranges(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        orb_mask = (df['hour_min'] >= p['orb_start']) & (df['hour_min'] < p['orb_end'])
        orb_data = df[orb_mask].groupby('date_str').agg(
            orb_high=('high', 'max'),
            orb_low=('low', 'min')
        ).reset_index()
        orb_data['orb_range'] = orb_data['orb_high'] - orb_data['orb_low']
        orb_data = orb_data[
            (orb_data['orb_range'] >= p['orb_min_points']) &
            (orb_data['orb_range'] <= p['orb_max_points'])
        ]
        df = df.merge(orb_data[['date_str', 'orb_high', 'orb_low', 'orb_range']], on='date_str', how='left')
        df = mask_columns_before_clock(
            df,
            ('orb_high', 'orb_low', 'orb_range'),
            available_at=str(p.get('orb_end', '10:00')),
        )
        df = self.classify_day_regime(df)
        return df

    def classify_day_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify each session into:
        - neutral: no strong evidence yet
        - range: balanced / mean-reverting structure
        - trend_up / trend_down: directional day confirmed and locked
        """
        df = df.copy()
        p = self.strategy_params

        df['day_regime'] = 'neutral'

        orb_valid = df['orb_range'].notna()
        df['session_high_so_far'] = df.groupby('date_str')['high'].cummax()
        df['session_low_so_far'] = df.groupby('date_str')['low'].cummin()
        df['session_range_so_far'] = df['session_high_so_far'] - df['session_low_so_far']
        df['orb_mid'] = (df['orb_high'] + df['orb_low']) / 2.0
        df['orb_range_multiple'] = df['session_range_so_far'] / df['orb_range'].replace(0, np.nan)
        bar_range = (df['high'] - df['low']).replace(0, np.nan)
        df['close_strength'] = ((df['close'] - df['low']) / bar_range).fillna(0.5)
        df['session_extension_from_mid'] = df['close'] - df['orb_mid']
        df['session_extension_abs'] = df['session_extension_from_mid'].abs()
        df['vwap_distance_abs'] = (df['close'] - df['vwap']).abs()

        eval_start = p.get('regime_eval_start', p.get('orb_end', '10:00'))
        after_eval = df['hour_min'] >= eval_start

        long_accept_buffer_pts = float(self.get_signal_param('trend', 'long', 'acceptance_buffer_points', p.get('trend_acceptance_buffer_points', 2.0)))
        short_accept_buffer_pts = float(self.get_signal_param('trend', 'short', 'acceptance_buffer_points', p.get('trend_acceptance_buffer_points', 2.0)))
        long_range_mult = float(self.get_signal_param('trend', 'long', 'min_range_multiple', p.get('regime_trend_min_range_multiple', p.get('trend_min_range_multiple', 1.8))))
        short_range_mult = float(self.get_signal_param('trend', 'short', 'min_range_multiple', p.get('regime_trend_min_range_multiple', p.get('trend_min_range_multiple', 1.8))))
        range_max_mult = float(p.get('regime_range_max_range_multiple', p.get('mr_balance_max_range_multiple', 1.35)))
        range_max_slope = float(p.get('regime_range_max_slope', 0.18))
        trend_min_slope = float(p.get('regime_trend_min_slope', 0.20))
        trend_confirm_bars = int(p.get('regime_trend_confirm_bars', 2))
        range_confirm_bars = int(p.get('regime_range_confirm_bars', 2))
        trend_min_extension_factor = float(p.get('regime_trend_min_extension_factor', 0.35))
        trend_min_extension_points = float(p.get('regime_trend_min_extension_points', 4.0))
        range_max_extension_factor = float(p.get('regime_range_max_extension_factor', 0.22))
        range_max_extension_points = float(p.get('regime_range_max_extension_points', 4.0))
        trend_min_vwap_distance = float(p.get('regime_trend_min_vwap_distance_points', 3.0))
        range_max_vwap_distance = float(p.get('regime_range_max_vwap_distance_points', 4.0))
        range_value_buffer = float(p.get('regime_range_value_area_buffer_points', 1.0))

        vp_upper = df['vp_vah'] if 'vp_vah' in df.columns else df['orb_high']
        vp_lower = df['vp_val'] if 'vp_val' in df.columns else df['orb_low']
        vp_mid = df['vp_poc'] if 'vp_poc' in df.columns else df['orb_mid']
        upper_accept = np.maximum(df['orb_high'], vp_upper.fillna(df['orb_high'])) + long_accept_buffer_pts
        lower_accept = np.minimum(df['orb_low'], vp_lower.fillna(df['orb_low'])) - short_accept_buffer_pts

        trend_extension_threshold = np.maximum(
            trend_min_extension_points,
            df['orb_range'].fillna(0.0) * trend_min_extension_factor,
        )
        range_extension_threshold = np.maximum(
            range_max_extension_points,
            df['orb_range'].fillna(0.0) * range_max_extension_factor,
        )

        up_raw = (
            after_eval
            & orb_valid
            & (df['orb_range_multiple'] >= long_range_mult)
            & (df['close'] > upper_accept)
            & (df['close'].shift(1) > upper_accept.shift(1).fillna(df['orb_high'].shift(1)))
            & (df['close'] > df['vwap'])
            & (df['trend_ema_slope'] >= trend_min_slope)
            & (df['session_extension_from_mid'] >= trend_extension_threshold)
            & (df['vwap_distance_abs'] >= trend_min_vwap_distance)
        )
        down_raw = (
            after_eval
            & orb_valid
            & (df['orb_range_multiple'] >= short_range_mult)
            & (df['close'] < lower_accept)
            & (df['close'].shift(1) < lower_accept.shift(1).fillna(df['orb_low'].shift(1)))
            & (df['close'] < df['vwap'])
            & (df['trend_ema_slope'] <= -trend_min_slope)
            & (-df['session_extension_from_mid'] >= trend_extension_threshold)
            & (df['vwap_distance_abs'] >= trend_min_vwap_distance)
        )

        in_value_area = (
            (df['close'] >= (vp_lower.fillna(df['orb_low']) - range_value_buffer))
            & (df['close'] <= (vp_upper.fillna(df['orb_high']) + range_value_buffer))
        )
        range_raw = (
            after_eval
            & orb_valid
            & (df['orb_range_multiple'] <= range_max_mult)
            & in_value_area
            & (df['session_extension_abs'] <= range_extension_threshold)
            & (df['vwap_distance_abs'] <= range_max_vwap_distance)
            & (df['trend_ema_slope'].abs() <= range_max_slope)
            & ((df['close'] - vp_mid.fillna(df['orb_mid'])).abs() <= range_extension_threshold)
        )

        up_confirm = self._session_confirm(up_raw, df['date_str'], trend_confirm_bars)
        down_confirm = self._session_confirm(down_raw, df['date_str'], trend_confirm_bars)
        range_confirm = self._session_confirm(range_raw, df['date_str'], range_confirm_bars)

        up_locked = up_confirm.groupby(df['date_str']).cummax()
        down_locked = down_confirm.groupby(df['date_str']).cummax()
        trend_conflict = up_locked & down_locked

        df['regime_range_confirmed'] = range_confirm
        df['regime_trend_up_confirmed'] = up_locked
        df['regime_trend_down_confirmed'] = down_locked

        df.loc[range_confirm & ~up_locked & ~down_locked, 'day_regime'] = 'range'
        df.loc[up_locked & ~down_locked, 'day_regime'] = 'trend_up'
        df.loc[down_locked & ~up_locked, 'day_regime'] = 'trend_down'
        df.loc[trend_conflict, 'day_regime'] = 'neutral'

        return df

    def classify_profile_regime_no_orb(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify the live auction without ORB levels.

        This uses the opening volume profile as the auction map, then checks
        session expansion, VWAP distance, and EMA slope to decide whether the
        day is balanced, trending up, trending down, or still unresolved.
        """
        df = df.copy()
        p = self.strategy_params

        df['day_regime'] = 'neutral'
        required_cols = {'vp_poc', 'vp_val', 'vp_vah', 'vwap', 'trend_ema_slope', 'atr'}
        if not required_cols.issubset(df.columns):
            df['regime_range_confirmed'] = False
            df['regime_trend_up_confirmed'] = False
            df['regime_trend_down_confirmed'] = False
            return df

        if 'date_str' not in df.columns:
            df['date_str'] = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d')
        if 'hour_min' not in df.columns:
            df['hour_min'] = pd.to_datetime(df['time']).dt.strftime('%H:%M')

        vp_valid = df['vp_poc'].notna() & df['vp_val'].notna() & df['vp_vah'].notna()
        vp_width = df['vp_width'] if 'vp_width' in df.columns else (df['vp_vah'] - df['vp_val'])
        width_floor = df['atr'].abs() * float(p.get('profile_regime_min_width_atr_multiplier', 1.0))
        profile_width = pd.Series(
            np.maximum(
                pd.to_numeric(vp_width, errors='coerce').fillna(0.0),
                pd.to_numeric(width_floor, errors='coerce').fillna(0.0),
            ),
            index=df.index,
        ).replace(0.0, np.nan)

        df['profile_session_high_so_far'] = df.groupby('date_str')['high'].cummax()
        df['profile_session_low_so_far'] = df.groupby('date_str')['low'].cummin()
        df['profile_session_range_so_far'] = df['profile_session_high_so_far'] - df['profile_session_low_so_far']
        df['profile_range_multiple'] = df['profile_session_range_so_far'] / profile_width
        bar_range = (df['high'] - df['low']).replace(0, np.nan)
        df['close_strength'] = ((df['close'] - df['low']) / bar_range).fillna(0.5)
        df['profile_extension_from_poc'] = df['close'] - df['vp_poc']
        df['profile_extension_abs'] = df['profile_extension_from_poc'].abs()
        df['vwap_distance_abs'] = (df['close'] - df['vwap']).abs()

        eval_start = p.get('profile_regime_eval_start', p.get('regime_eval_start', p.get('vp_profile_end', '10:00')))
        after_eval = df['hour_min'] >= eval_start

        long_accept_buffer_pts = float(self.get_signal_param('trend', 'long', 'acceptance_buffer_points', p.get('vp_trend_acceptance_buffer_points', 1.0)))
        short_accept_buffer_pts = float(self.get_signal_param('trend', 'short', 'acceptance_buffer_points', p.get('vp_trend_acceptance_buffer_points', 1.0)))
        long_range_mult = float(self.get_signal_param('trend', 'long', 'profile_min_range_multiple', p.get('profile_regime_trend_min_range_multiple', p.get('regime_trend_min_range_multiple', 1.7))))
        short_range_mult = float(self.get_signal_param('trend', 'short', 'profile_min_range_multiple', p.get('profile_regime_trend_min_range_multiple', p.get('regime_trend_min_range_multiple', 1.7))))
        range_max_mult = float(p.get('profile_regime_range_max_range_multiple', p.get('regime_range_max_range_multiple', 1.55)))
        range_max_slope = float(p.get('profile_regime_range_max_slope', p.get('regime_range_max_slope', 0.25)))
        trend_min_slope = float(p.get('profile_regime_trend_min_slope', p.get('regime_trend_min_slope', 0.20)))
        trend_confirm_bars = int(p.get('profile_regime_trend_confirm_bars', p.get('regime_trend_confirm_bars', 2)))
        range_confirm_bars = int(p.get('profile_regime_range_confirm_bars', p.get('regime_range_confirm_bars', 2)))
        trend_min_extension_factor = float(p.get('profile_regime_trend_min_extension_factor', p.get('regime_trend_min_extension_factor', 0.45)))
        trend_min_extension_points = float(p.get('profile_regime_trend_min_extension_points', p.get('regime_trend_min_extension_points', 5.0)))
        range_max_extension_factor = float(p.get('profile_regime_range_max_extension_factor', p.get('regime_range_max_extension_factor', 0.35)))
        range_max_extension_points = float(p.get('profile_regime_range_max_extension_points', p.get('regime_range_max_extension_points', 6.0)))
        trend_min_vwap_distance = float(p.get('profile_regime_trend_min_vwap_distance_points', p.get('regime_trend_min_vwap_distance_points', 4.0)))
        range_max_vwap_distance = float(p.get('profile_regime_range_max_vwap_distance_points', p.get('regime_range_max_vwap_distance_points', 6.0)))
        range_value_buffer = float(p.get('profile_regime_range_value_area_buffer_points', p.get('regime_range_value_area_buffer_points', 1.0)))

        upper_accept = df['vp_vah'] + long_accept_buffer_pts
        lower_accept = df['vp_val'] - short_accept_buffer_pts
        trend_extension_threshold = pd.Series(
            np.maximum(trend_min_extension_points, profile_width.fillna(0.0) * trend_min_extension_factor),
            index=df.index,
        )
        range_extension_threshold = pd.Series(
            np.maximum(range_max_extension_points, profile_width.fillna(0.0) * range_max_extension_factor),
            index=df.index,
        )

        up_raw = (
            after_eval
            & vp_valid
            & (df['profile_range_multiple'] >= long_range_mult)
            & (df['close'] > upper_accept)
            & (df['close'].shift(1) > upper_accept.shift(1))
            & (df['close'] > df['vwap'])
            & (df['trend_ema_slope'] >= trend_min_slope)
            & (df['profile_extension_from_poc'] >= trend_extension_threshold)
            & (df['vwap_distance_abs'] >= trend_min_vwap_distance)
        )
        down_raw = (
            after_eval
            & vp_valid
            & (df['profile_range_multiple'] >= short_range_mult)
            & (df['close'] < lower_accept)
            & (df['close'].shift(1) < lower_accept.shift(1))
            & (df['close'] < df['vwap'])
            & (df['trend_ema_slope'] <= -trend_min_slope)
            & (-df['profile_extension_from_poc'] >= trend_extension_threshold)
            & (df['vwap_distance_abs'] >= trend_min_vwap_distance)
        )

        in_value_area = (
            (df['close'] >= (df['vp_val'] - range_value_buffer))
            & (df['close'] <= (df['vp_vah'] + range_value_buffer))
        )
        range_raw = (
            after_eval
            & vp_valid
            & (df['profile_range_multiple'] <= range_max_mult)
            & in_value_area
            & (df['profile_extension_abs'] <= range_extension_threshold)
            & (df['vwap_distance_abs'] <= range_max_vwap_distance)
            & (df['trend_ema_slope'].abs() <= range_max_slope)
        )

        up_confirm = self._session_confirm(up_raw, df['date_str'], trend_confirm_bars)
        down_confirm = self._session_confirm(down_raw, df['date_str'], trend_confirm_bars)
        range_confirm = self._session_confirm(range_raw, df['date_str'], range_confirm_bars)

        up_locked = up_confirm.groupby(df['date_str']).cummax()
        down_locked = down_confirm.groupby(df['date_str']).cummax()
        trend_conflict = up_locked & down_locked

        df['regime_range_confirmed'] = range_confirm
        df['regime_trend_up_confirmed'] = up_locked
        df['regime_trend_down_confirmed'] = down_locked

        df.loc[range_confirm & ~up_locked & ~down_locked, 'day_regime'] = 'range'
        df.loc[up_locked & ~down_locked, 'day_regime'] = 'trend_up'
        df.loc[down_locked & ~up_locked, 'day_regime'] = 'trend_down'
        df.loc[trend_conflict, 'day_regime'] = 'neutral'

        return df


