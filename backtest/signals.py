"""Strategy signal generation."""


import numpy as np
import pandas as pd


class SignalMixin:
    """Mixin extracted from BacktestEngine — Strategy signal generation."""

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.strategy_params
        df['signal'] = 0
        df['signal_type'] = ''

        strategy_name = p.get('strategy_name', 'amt_mean_reversion')
        if strategy_name == 'amt_mean_reversion':
            return self.generate_signals_amt_mean_reversion(df)
        if strategy_name == 'amt_trend':
            return self.generate_signals_amt_trend(df)
        if strategy_name == 'amt_combined':
            return self.generate_signals_amt_combined(df)
        if strategy_name == 'vwap_regime':
            return self.generate_signals_vwap_regime(df)
        if strategy_name == 'volume_profile_regime':
            return self.generate_signals_volume_profile_regime(df)
        if strategy_name == 'market_profile_cross':
            return self.generate_signals_market_profile_cross(df)
        if strategy_name == 'hybrid_profile_regime_no_orb':
            return self.generate_signals_hybrid_profile_regime_no_orb(df)
        if strategy_name == 'morning_va_breakout':
            return self.generate_signals_morning_va_breakout(df)

        long_trade_start = self.get_directional_param('long', 'trade_start', p.get('trade_start', '09:30'))
        long_trade_end = self.get_directional_param('long', 'trade_end', p.get('trade_end', '16:00'))
        short_trade_start = self.get_directional_param('short', 'trade_start', p.get('trade_start', '09:30'))
        short_trade_end = self.get_directional_param('short', 'trade_end', p.get('trade_end', '16:00'))
        long_breakout_buffer = self.get_directional_param('long', 'breakout_buffer_points', p.get('breakout_buffer_points', 1.0))
        short_breakout_buffer = self.get_directional_param('short', 'breakout_buffer_points', p.get('breakout_buffer_points', 1.0))
        long_volume_spike_multiplier = self.get_directional_param(
            'long', 'volume_spike_multiplier', p.get('volume_spike_multiplier', 1.5)
        )
        short_volume_spike_multiplier = self.get_directional_param(
            'short', 'volume_spike_multiplier', p.get('volume_spike_multiplier', 1.5)
        )
        long_breakout_strength = self.get_directional_param(
            'long', 'breakout_close_min_strength', p.get('breakout_close_min_strength', 0.0)
        )
        short_breakout_strength = self.get_directional_param(
            'short', 'breakout_close_min_strength', p.get('breakout_close_min_strength', 0.0)
        )
        long_rsi_min = p.get('long_rsi_min', p.get('rsi_long_min'))
        short_rsi_max = p.get('short_rsi_max', p.get('rsi_short_max'))
        long_min_confirmations = self.get_directional_param('long', 'min_confirmations', 5)
        short_min_confirmations = self.get_directional_param('short', 'min_confirmations', 5)

        in_long_trade_window = (df['hour_min'] >= long_trade_start) & (df['hour_min'] <= long_trade_end)
        in_short_trade_window = (df['hour_min'] >= short_trade_start) & (df['hour_min'] <= short_trade_end)
        orb_valid = df['orb_range'].notna()
        bar_range = (df['high'] - df['low']).replace(0, np.nan)
        close_strength = (df['close'] - df['low']) / bar_range
        long_volume_spike = df['volume'] > (df['volume_sma'] * long_volume_spike_multiplier)
        short_volume_spike = df['volume'] > (df['volume_sma'] * short_volume_spike_multiplier)

        prev_close_below = df['close'].shift(1) <= (df['orb_high'] + long_breakout_buffer)
        curr_close_above = df['close'] > (df['orb_high'] + long_breakout_buffer)
        long_breakout = prev_close_below & curr_close_above

        prev_close_above = df['close'].shift(1) >= (df['orb_low'] - short_breakout_buffer)
        curr_close_below = df['close'] < (df['orb_low'] - short_breakout_buffer)
        short_breakout = prev_close_above & curr_close_below

        trend_up = df['close'] > df['trend_ema']
        trend_down = df['close'] < df['trend_ema']
        long_vwap = df['close'] > df['vwap']
        short_vwap = df['close'] < df['vwap']
        long_rsi = df['rsi'] > long_rsi_min
        short_rsi = df['rsi'] < short_rsi_max
        long_close_quality = close_strength >= long_breakout_strength
        short_close_quality = (1 - close_strength) >= short_breakout_strength

        long_confirmations = pd.DataFrame({
            'trend': trend_up,
            'vwap': long_vwap,
            'rsi': long_rsi,
            'volume': long_volume_spike,
            'atr': df['atr_normal'],
            'close_quality': long_close_quality,
        }).fillna(False)
        long_score = long_confirmations.sum(axis=1)

        short_confirmations = pd.DataFrame({
            'trend': trend_down,
            'vwap': short_vwap,
            'rsi': short_rsi,
            'volume': short_volume_spike,
            'atr': df['atr_normal'],
            'close_quality': short_close_quality,
        }).fillna(False)
        short_score = short_confirmations.sum(axis=1)

        long_cond = (
            long_breakout &
            in_long_trade_window &
            orb_valid &
            (long_score >= long_min_confirmations)
        )

        short_cond = (
            short_breakout &
            in_short_trade_window &
            orb_valid &
            (short_score >= short_min_confirmations)
        )

        if not p.get('allow_long', True):
            long_cond = pd.Series(False, index=df.index)
        if not p.get('allow_short', True):
            short_cond = pd.Series(False, index=df.index)

        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1

        return df

    def generate_signals_market_profile_cross(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Trade close-crosses through rolling market-profile levels.

        This mirrors the public neurotrader888 support/resistance example more
        closely than using market profile as a hard filter: the level crossing is
        the signal, while our existing engine still controls exits, max trades,
        costs, and walk-forward validation.
        """
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        required_cols = {'mp_crossed_up', 'mp_crossed_down', 'mp_level_count'}
        if not required_cols.issubset(df.columns):
            return df

        allow_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('mp', 'long')
        allow_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('mp', 'short')
        if not allow_long and not allow_short:
            return df

        long_trade_start = self.get_signal_param('mp', 'long', 'trade_start', p['trade_start'])
        long_trade_end = self.get_signal_param('mp', 'long', 'trade_end', p['trade_end'])
        short_trade_start = self.get_signal_param('mp', 'short', 'trade_start', p['trade_start'])
        short_trade_end = self.get_signal_param('mp', 'short', 'trade_end', p['trade_end'])
        in_long_window = (df['hour_min'] >= long_trade_start) & (df['hour_min'] <= long_trade_end)
        in_short_window = (df['hour_min'] >= short_trade_start) & (df['hour_min'] <= short_trade_end)

        min_levels = int(p.get('market_profile_cross_min_level_count', 1))
        valid_profile = df['mp_level_count'].fillna(0).ge(min_levels)

        min_room = float(p.get('market_profile_cross_min_opposite_room_points', 0.0))
        if min_room > 0:
            long_room = df['mp_dist_to_resistance'].fillna(np.inf).ge(min_room)
            short_room = df['mp_dist_to_support'].fillna(np.inf).ge(min_room)
        else:
            long_room = pd.Series(True, index=df.index)
            short_room = pd.Series(True, index=df.index)

        direction_filter = str(p.get('market_profile_cross_direction_filter', 'off')).lower()
        long_context = pd.Series(True, index=df.index)
        short_context = pd.Series(True, index=df.index)
        if direction_filter in ('vwap', 'both'):
            long_context &= df['close'].gt(df['vwap'])
            short_context &= df['close'].lt(df['vwap'])
        if direction_filter in ('ema', 'trend_ema', 'both'):
            long_context &= df['close'].gt(df['trend_ema'])
            short_context &= df['close'].lt(df['trend_ema'])

        long_cond = (
            allow_long
            & valid_profile
            & in_long_window
            & df['mp_crossed_up'].fillna(False)
            & long_room
            & long_context
        )
        short_cond = (
            allow_short
            & valid_profile
            & in_short_window
            & df['mp_crossed_down'].fillna(False)
            & short_room
            & short_context
        )

        df.loc[long_cond, ['signal', 'signal_type']] = [1, 'mp']
        df.loc[short_cond, ['signal', 'signal_type']] = [-1, 'mp']
        return df

    def generate_signals_hybrid_profile_regime_no_orb(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Regime-router strategy that removes ORB from the decision tree.

        The flow is:
        - balanced profile day: fade failed moves back toward POC
        - trend day: trade pullback/reclaim continuation around VWAP/value
        - unresolved transition: allow profile-level crosses with room
        """
        p = self.strategy_params
        df = self.classify_profile_regime_no_orb(df)
        df['signal'] = 0
        df['signal_type'] = ''

        required_vp_cols = {'vp_poc', 'vp_val', 'vp_vah', 'vwap', 'trend_ema_slope', 'close_strength'}
        if not required_vp_cols.issubset(df.columns):
            return df

        allow_mr_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('mr', 'long')
        allow_mr_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('mr', 'short')
        allow_trend_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('trend', 'long')
        allow_trend_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('trend', 'short')
        allow_mp_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('mp', 'long')
        allow_mp_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('mp', 'short')

        mr_long_trade_start = self.get_signal_param('mr', 'long', 'trade_start', p['trade_start'])
        mr_long_trade_end = self.get_signal_param('mr', 'long', 'trade_end', p['trade_end'])
        mr_short_trade_start = self.get_signal_param('mr', 'short', 'trade_start', p['trade_start'])
        mr_short_trade_end = self.get_signal_param('mr', 'short', 'trade_end', p['trade_end'])
        trend_long_trade_start = self.get_signal_param('trend', 'long', 'trade_start', p['trade_start'])
        trend_long_trade_end = self.get_signal_param('trend', 'long', 'trade_end', p['trade_end'])
        trend_short_trade_start = self.get_signal_param('trend', 'short', 'trade_start', p['trade_start'])
        trend_short_trade_end = self.get_signal_param('trend', 'short', 'trade_end', p['trade_end'])
        mp_long_trade_start = self.get_signal_param('mp', 'long', 'trade_start', p['trade_start'])
        mp_long_trade_end = self.get_signal_param('mp', 'long', 'trade_end', p['trade_end'])
        mp_short_trade_start = self.get_signal_param('mp', 'short', 'trade_start', p['trade_start'])
        mp_short_trade_end = self.get_signal_param('mp', 'short', 'trade_end', p['trade_end'])

        in_mr_long_window = (df['hour_min'] >= mr_long_trade_start) & (df['hour_min'] <= mr_long_trade_end)
        in_mr_short_window = (df['hour_min'] >= mr_short_trade_start) & (df['hour_min'] <= mr_short_trade_end)
        in_trend_long_window = (df['hour_min'] >= trend_long_trade_start) & (df['hour_min'] <= trend_long_trade_end)
        in_trend_short_window = (df['hour_min'] >= trend_short_trade_start) & (df['hour_min'] <= trend_short_trade_end)
        in_mp_long_window = (df['hour_min'] >= mp_long_trade_start) & (df['hour_min'] <= mp_long_trade_end)
        in_mp_short_window = (df['hour_min'] >= mp_short_trade_start) & (df['hour_min'] <= mp_short_trade_end)

        vp_valid = df['vp_poc'].notna() & df['vp_val'].notna() & df['vp_vah'].notna()
        range_day = vp_valid & df['day_regime'].eq('range')
        trend_min_slope = float(p.get('profile_regime_trend_min_slope', p.get('regime_trend_min_slope', 0.20)))
        trend_up = vp_valid & df['day_regime'].eq('trend_up') & (df['trend_ema_slope'] >= trend_min_slope)
        trend_down = vp_valid & df['day_regime'].eq('trend_down') & (df['trend_ema_slope'] <= -trend_min_slope)
        transition_day = vp_valid & df['day_regime'].eq('neutral')

        has_mp = {
            'mp_level_count',
            'mp_dist_to_support',
            'mp_dist_to_resistance',
            'mp_crossed_up',
            'mp_crossed_down',
        }.issubset(df.columns)
        if has_mp:
            min_levels = int(p.get('market_profile_cross_min_level_count', 1))
            valid_mp = df['mp_level_count'].fillna(0).ge(min_levels)
            profile_tolerance = float(p.get('hybrid_profile_near_level_tolerance_points', p.get('market_profile_near_level_tolerance_points', 6.0)))
            min_room = float(p.get('hybrid_profile_min_room_to_opposite_points', p.get('market_profile_cross_min_opposite_room_points', 4.0)))
            long_room = df['mp_dist_to_resistance'].fillna(np.inf).ge(min_room)
            short_room = df['mp_dist_to_support'].fillna(np.inf).ge(min_room)
            near_support = df['mp_dist_to_support'].between(0, profile_tolerance, inclusive='both')
            near_resistance = df['mp_dist_to_resistance'].between(0, profile_tolerance, inclusive='both')
            crossed_up = df['mp_crossed_up'].fillna(False)
            crossed_down = df['mp_crossed_down'].fillna(False)
            mr_long_profile_ok = valid_mp & long_room & (near_support | crossed_up)
            mr_short_profile_ok = valid_mp & short_room & (near_resistance | crossed_down)
            trend_long_profile_ok = valid_mp & long_room & (crossed_up | near_support)
            trend_short_profile_ok = valid_mp & short_room & (crossed_down | near_resistance)
            mp_long_profile_ok = valid_mp & long_room & crossed_up
            mp_short_profile_ok = valid_mp & short_room & crossed_down
        else:
            mr_long_profile_ok = pd.Series(False, index=df.index)
            mr_short_profile_ok = pd.Series(False, index=df.index)
            trend_long_profile_ok = pd.Series(False, index=df.index)
            trend_short_profile_ok = pd.Series(False, index=df.index)
            mp_long_profile_ok = pd.Series(False, index=df.index)
            mp_short_profile_ok = pd.Series(False, index=df.index)

        if not bool(p.get('hybrid_mr_require_profile_context', True)):
            mr_long_profile_ok = pd.Series(True, index=df.index)
            mr_short_profile_ok = pd.Series(True, index=df.index)
        if not bool(p.get('hybrid_trend_require_profile_context', True)):
            trend_long_profile_ok = pd.Series(True, index=df.index)
            trend_short_profile_ok = pd.Series(True, index=df.index)

        mr_long_excess_buffer = float(self.get_signal_param('mr', 'long', 'excess_buffer_points', p.get('mr_excess_buffer_points', 2.0)))
        mr_short_excess_buffer = float(self.get_signal_param('mr', 'short', 'excess_buffer_points', p.get('mr_excess_buffer_points', 2.0)))
        mr_long_reclaim_buffer = float(self.get_signal_param('mr', 'long', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        mr_short_reclaim_buffer = float(self.get_signal_param('mr', 'short', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        mr_long_close_strength = float(self.get_signal_param('mr', 'long', 'close_strength_min', p.get('mr_close_strength_min', 0.60)))
        mr_short_close_strength = float(self.get_signal_param('mr', 'short', 'close_strength_max', p.get('mr_close_strength_max', 0.40)))
        mr_poc_room = float(p.get('vp_mr_min_poc_room_points', 2.0))
        mr_value_extension = float(p.get('mr_value_extension_points', 0.5))

        mr_long = (
            allow_mr_long
            & range_day
            & in_mr_long_window
            & (df['low'].shift(1) < (df['vp_val'].shift(1) - mr_long_excess_buffer))
            & (df['close'] > (df['vp_val'] + mr_long_reclaim_buffer))
            & (df['close'] < (df['vp_poc'] + mr_value_extension))
            & ((df['vp_poc'] - df['close']) >= mr_poc_room)
            & (df['close_strength'] >= mr_long_close_strength)
            & mr_long_profile_ok
        )
        mr_short = (
            allow_mr_short
            & range_day
            & in_mr_short_window
            & (df['high'].shift(1) > (df['vp_vah'].shift(1) + mr_short_excess_buffer))
            & (df['close'] < (df['vp_vah'] - mr_short_reclaim_buffer))
            & (df['close'] > (df['vp_poc'] - mr_value_extension))
            & ((df['close'] - df['vp_poc']) >= mr_poc_room)
            & (df['close_strength'] <= mr_short_close_strength)
            & mr_short_profile_ok
        )

        trend_long_pullback_buffer = float(self.get_signal_param('trend', 'long', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 2.0)))
        trend_short_pullback_buffer = float(self.get_signal_param('trend', 'short', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 2.0)))
        trend_long_reclaim_buffer = float(self.get_signal_param('trend', 'long', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))
        trend_short_reclaim_buffer = float(self.get_signal_param('trend', 'short', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))
        trend_acceptance_buffer = float(p.get('vp_trend_acceptance_buffer_points', 1.0))
        trend_long_close_strength = float(self.get_signal_param('trend', 'long', 'close_strength_min', p.get('trend_close_strength_min', 0.50)))
        trend_short_close_strength = float(self.get_signal_param('trend', 'short', 'close_strength_max', p.get('trend_close_strength_max', 0.45)))

        trend_long_support = pd.Series(np.maximum(df['vp_vah'], df['vwap']), index=df.index)
        trend_short_resistance = pd.Series(np.minimum(df['vp_val'], df['vwap']), index=df.index)

        trend_long = (
            allow_trend_long
            & trend_up
            & in_trend_long_window
            & (df['close'].shift(1) > (df['vp_vah'].shift(1) + trend_acceptance_buffer))
            & (df['low'] <= (trend_long_support + trend_long_pullback_buffer))
            & (df['close'] > (trend_long_support + trend_long_reclaim_buffer))
            & (df['close'] > df['vwap'])
            & (df['close_strength'] >= trend_long_close_strength)
            & trend_long_profile_ok
        )
        trend_short = (
            allow_trend_short
            & trend_down
            & in_trend_short_window
            & (df['close'].shift(1) < (df['vp_val'].shift(1) - trend_acceptance_buffer))
            & (df['high'] >= (trend_short_resistance - trend_short_pullback_buffer))
            & (df['close'] < (trend_short_resistance - trend_short_reclaim_buffer))
            & (df['close'] < df['vwap'])
            & (df['close_strength'] <= trend_short_close_strength)
            & trend_short_profile_ok
        )

        df.loc[mr_long, ['signal', 'signal_type']] = [1, 'mr']
        df.loc[mr_short & df['signal'].eq(0), ['signal', 'signal_type']] = [-1, 'mr']
        df.loc[trend_long & df['signal'].eq(0), ['signal', 'signal_type']] = [1, 'trend']
        df.loc[trend_short & df['signal'].eq(0), ['signal', 'signal_type']] = [-1, 'trend']

        if bool(p.get('hybrid_mp_transition_enabled', True)):
            direction_filter = str(p.get('hybrid_mp_direction_filter', p.get('market_profile_cross_direction_filter', 'vwap'))).lower()
            mp_long_context = pd.Series(True, index=df.index)
            mp_short_context = pd.Series(True, index=df.index)
            if direction_filter in ('vwap', 'both'):
                mp_long_context &= df['close'].gt(df['vwap'])
                mp_short_context &= df['close'].lt(df['vwap'])
            if direction_filter in ('ema', 'trend_ema', 'both'):
                mp_long_context &= df['close'].gt(df['trend_ema'])
                mp_short_context &= df['close'].lt(df['trend_ema'])

            mp_long = (
                allow_mp_long
                & transition_day
                & in_mp_long_window
                & mp_long_profile_ok
                & mp_long_context
            )
            mp_short = (
                allow_mp_short
                & transition_day
                & in_mp_short_window
                & mp_short_profile_ok
                & mp_short_context
            )
            df.loc[mp_long & df['signal'].eq(0), ['signal', 'signal_type']] = [1, 'mp']
            df.loc[mp_short & df['signal'].eq(0), ['signal', 'signal_type']] = [-1, 'mp']

        return df

    def generate_signals_amt_mean_reversion(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        allow_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('mr', 'long')
        allow_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('mr', 'short')

        mr_long_trade_start = self.get_signal_param('mr', 'long', 'trade_start', p['trade_start'])
        mr_long_trade_end = self.get_signal_param('mr', 'long', 'trade_end', p['trade_end'])
        mr_short_trade_start = self.get_signal_param('mr', 'short', 'trade_start', p['trade_start'])
        mr_short_trade_end = self.get_signal_param('mr', 'short', 'trade_end', p['trade_end'])
        in_mr_long_window = (df['hour_min'] >= mr_long_trade_start) & (df['hour_min'] <= mr_long_trade_end)
        in_mr_short_window = (df['hour_min'] >= mr_short_trade_start) & (df['hour_min'] <= mr_short_trade_end)

        long_excess_buffer = float(self.get_signal_param('mr', 'long', 'excess_buffer_points', p.get('mr_excess_buffer_points', 3.0)))
        short_excess_buffer = float(self.get_signal_param('mr', 'short', 'excess_buffer_points', p.get('mr_excess_buffer_points', 3.0)))
        long_reclaim_buffer = float(self.get_signal_param('mr', 'long', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        short_reclaim_buffer = float(self.get_signal_param('mr', 'short', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        long_close_strength = float(self.get_signal_param('mr', 'long', 'close_strength_min', p.get('mr_close_strength_min', 0.60)))
        short_close_strength = float(self.get_signal_param('mr', 'short', 'close_strength_max', p.get('mr_close_strength_max', 0.40)))
        balance_range_mult = float(p.get('mr_balance_max_range_multiple', 1.8))

        balance_day = (
            df['orb_range'].notna()
            & df['day_regime'].eq('range')
            & (df['orb_range_multiple'] <= balance_range_mult)
        )

        failed_auction_long = (
            (df['low'].shift(1) < (df['orb_low'].shift(1) - long_excess_buffer))
            & (df['close'].shift(1) < df['orb_low'].shift(1))
            & (df['close'] > (df['orb_low'] + long_reclaim_buffer))
            & (df['close'] < df['vwap'])
            & (df['close_strength'] >= long_close_strength)
        )
        failed_auction_short = (
            (df['high'].shift(1) > (df['orb_high'].shift(1) + short_excess_buffer))
            & (df['close'].shift(1) > df['orb_high'].shift(1))
            & (df['close'] < (df['orb_high'] - short_reclaim_buffer))
            & (df['close'] > df['vwap'])
            & (df['close_strength'] <= short_close_strength)
        )

        mr_long = allow_long & balance_day & in_mr_long_window & failed_auction_long
        mr_short = allow_short & balance_day & in_mr_short_window & failed_auction_short

        df.loc[mr_long, ['signal', 'signal_type']] = [1, 'mr']
        df.loc[mr_short, ['signal', 'signal_type']] = [-1, 'mr']
        return df

    def generate_signals_amt_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        allow_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('trend', 'long')
        allow_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('trend', 'short')

        trend_long_trade_start = self.get_signal_param('trend', 'long', 'trade_start', p['trade_start'])
        trend_long_trade_end = self.get_signal_param('trend', 'long', 'trade_end', p['trade_end'])
        trend_short_trade_start = self.get_signal_param('trend', 'short', 'trade_start', p['trade_start'])
        trend_short_trade_end = self.get_signal_param('trend', 'short', 'trade_end', p['trade_end'])
        in_trend_long_window = (df['hour_min'] >= trend_long_trade_start) & (df['hour_min'] <= trend_long_trade_end)
        in_trend_short_window = (df['hour_min'] >= trend_short_trade_start) & (df['hour_min'] <= trend_short_trade_end)

        long_pullback_buffer = float(self.get_signal_param('trend', 'long', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 3.0)))
        short_pullback_buffer = float(self.get_signal_param('trend', 'short', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 3.0)))
        long_reclaim_buffer = float(self.get_signal_param('trend', 'long', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))
        short_reclaim_buffer = float(self.get_signal_param('trend', 'short', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))

        trend_up = df['day_regime'].eq('trend_up')
        trend_down = df['day_regime'].eq('trend_down')

        trend_long = (
            allow_long
            & trend_up
            & in_trend_long_window
            & (df['low'] <= (df['orb_high'] + long_pullback_buffer))
            & (df['close'] > (df['orb_high'] + long_reclaim_buffer))
            & (df['close'] > df['vwap'])
            & (df['close_strength'] >= 0.55)
        )
        trend_short = (
            allow_short
            & trend_down
            & in_trend_short_window
            & (df['high'] >= (df['orb_low'] - short_pullback_buffer))
            & (df['close'] < (df['orb_low'] - short_reclaim_buffer))
            & (df['close'] < df['vwap'])
            & (df['close_strength'] <= 0.45)
        )

        df.loc[trend_long, ['signal', 'signal_type']] = [1, 'trend']
        df.loc[trend_short, ['signal', 'signal_type']] = [-1, 'trend']
        return df

    def generate_signals_amt_combined(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        mr_df = self.generate_signals_amt_mean_reversion(df)
        trend_df = self.generate_signals_amt_trend(df)

        mr_mask = mr_df['signal'] != 0
        trend_mask = trend_df['signal'] != 0

        df.loc[mr_mask, ['signal', 'signal_type']] = mr_df.loc[mr_mask, ['signal', 'signal_type']].to_numpy()
        df.loc[trend_mask, ['signal', 'signal_type']] = trend_df.loc[trend_mask, ['signal', 'signal_type']].to_numpy()
        return df

    def generate_signals_vwap_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Two-mode strategy:
        - Range days: VWAP mean reversion using vwap_z excursions.
        - Trend days: pullback continuation (trend_up/trend_down regimes).
        """
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        allow_long = bool(p.get('allow_long', True))
        allow_short = bool(p.get('allow_short', True))

        # --- Range mode (mean reversion to VWAP)
        mr_long_trade_start = self.get_signal_param('mr', 'long', 'trade_start', p['trade_start'])
        mr_long_trade_end = self.get_signal_param('mr', 'long', 'trade_end', p['trade_end'])
        mr_short_trade_start = self.get_signal_param('mr', 'short', 'trade_start', p['trade_start'])
        mr_short_trade_end = self.get_signal_param('mr', 'short', 'trade_end', p['trade_end'])
        mr_in_long_trade_window = (df['hour_min'] >= mr_long_trade_start) & (df['hour_min'] <= mr_long_trade_end)
        mr_in_short_trade_window = (df['hour_min'] >= mr_short_trade_start) & (df['hour_min'] <= mr_short_trade_end)

        mr_long_entry_z = float(self.get_signal_param('mr', 'long', 'entry_z', p.get('mr_entry_z', 1.5)))
        mr_short_entry_z = float(self.get_signal_param('mr', 'short', 'entry_z', p.get('mr_entry_z', 1.5)))
        mr_long_max_z = float(self.get_signal_param('mr', 'long', 'max_z', p.get('mr_max_z', 4.0)))
        mr_short_max_z = float(self.get_signal_param('mr', 'short', 'max_z', p.get('mr_max_z', 4.0)))
        mr_long_rsi_max = float(self.get_signal_param('mr', 'long', 'rsi_max', p.get('mr_rsi_long_max', 45)))
        mr_short_rsi_min = float(self.get_signal_param('mr', 'short', 'rsi_min', p.get('mr_rsi_short_min', 55)))

        range_day = df['day_regime'].eq('range')

        mr_long = (
            allow_long
            & self.is_signal_direction_enabled('mr', 'long')
            & range_day
            & mr_in_long_trade_window
            & df['vwap_z'].notna()
            & df['vwap_z'].between(-mr_long_max_z, -mr_long_entry_z)
            & (df['rsi'] <= mr_long_rsi_max)
            & df['atr_normal']
        )
        mr_short = (
            allow_short
            & self.is_signal_direction_enabled('mr', 'short')
            & range_day
            & mr_in_short_trade_window
            & df['vwap_z'].notna()
            & df['vwap_z'].between(mr_short_entry_z, mr_short_max_z)
            & (df['rsi'] >= mr_short_rsi_min)
            & df['atr_normal']
        )

        # --- Trend mode (pullback continuation)
        trend_long_trade_start = self.get_signal_param('trend', 'long', 'trade_start', p['trade_start'])
        trend_long_trade_end = self.get_signal_param('trend', 'long', 'trade_end', p['trade_end'])
        trend_short_trade_start = self.get_signal_param('trend', 'short', 'trade_start', p['trade_start'])
        trend_short_trade_end = self.get_signal_param('trend', 'short', 'trade_end', p['trade_end'])
        trend_in_long_trade_window = (df['hour_min'] >= trend_long_trade_start) & (df['hour_min'] <= trend_long_trade_end)
        trend_in_short_trade_window = (df['hour_min'] >= trend_short_trade_start) & (df['hour_min'] <= trend_short_trade_end)

        trend_long_pullback_z = float(self.get_signal_param('trend', 'long', 'pullback_z', p.get('trend_pullback_z', 0.4)))
        trend_short_pullback_z = float(self.get_signal_param('trend', 'short', 'pullback_z', p.get('trend_pullback_z', 0.4)))
        trend_long_slope_thr = float(self.get_signal_param('trend', 'long', 'slope_threshold', p.get('trend_slope_threshold', 0.15)))
        trend_short_slope_thr = float(self.get_signal_param('trend', 'short', 'slope_threshold', p.get('trend_slope_threshold', 0.15)))

        trend_up = df['day_regime'].eq('trend_up') & (df['trend_ema_slope'] >= trend_long_slope_thr)
        trend_down = df['day_regime'].eq('trend_down') & (df['trend_ema_slope'] <= -trend_short_slope_thr)

        # Enter after a pullback to VWAP area then reclaim.
        reclaimed_vwap = (df['close'] > df['vwap']) & (df['close'].shift(1) <= df['vwap'].shift(1))
        lost_vwap = (df['close'] < df['vwap']) & (df['close'].shift(1) >= df['vwap'].shift(1))

        trend_long = (
            allow_long
            & self.is_signal_direction_enabled('trend', 'long')
            & trend_up
            & trend_in_long_trade_window
            & (df['close'] > df['trend_ema'])
            & df['vwap_z'].abs().le(trend_long_pullback_z)
            & reclaimed_vwap
        )
        trend_short = (
            allow_short
            & self.is_signal_direction_enabled('trend', 'short')
            & trend_down
            & trend_in_short_trade_window
            & (df['close'] < df['trend_ema'])
            & df['vwap_z'].abs().le(trend_short_pullback_z)
            & lost_vwap
        )

        df.loc[mr_long, ['signal', 'signal_type']] = [1, 'mr']
        df.loc[mr_short, ['signal', 'signal_type']] = [-1, 'mr']
        df.loc[trend_long, ['signal', 'signal_type']] = [1, 'trend']
        df.loc[trend_short, ['signal', 'signal_type']] = [-1, 'trend']

        return df

    def generate_signals_volume_profile_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Use the opening auction's approximate volume profile as the session map:
        - Range days fade failed moves through value back toward POC.
        - Trend days trade pullback continuation only after regime confirmation.
        """
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        if 'open_context' in df.columns and 'inside_ib' in df.columns and 'cusum_event' in df.columns:
            df['mr_long_blocked'] = ~((df['open_context'] == 'gap_below_prior_low') | (df['inside_ib'].fillna(False) & df['cusum_event'].fillna(False)))
        else:
            df['mr_long_blocked'] = False

        allow_long = bool(p.get('allow_long', True))
        allow_short = bool(p.get('allow_short', True))
        vp_valid = df['vp_poc'].notna() & df['vp_val'].notna() & df['vp_vah'].notna()

        mr_long_trade_start = self.get_signal_param('mr', 'long', 'trade_start', p['trade_start'])
        mr_long_trade_end = self.get_signal_param('mr', 'long', 'trade_end', p['trade_end'])
        mr_short_trade_start = self.get_signal_param('mr', 'short', 'trade_start', p['trade_start'])
        mr_short_trade_end = self.get_signal_param('mr', 'short', 'trade_end', p['trade_end'])
        mr_in_long_trade_window = (df['hour_min'] >= mr_long_trade_start) & (df['hour_min'] <= mr_long_trade_end)
        mr_in_short_trade_window = (df['hour_min'] >= mr_short_trade_start) & (df['hour_min'] <= mr_short_trade_end)

        mr_long_excess_buffer = float(self.get_signal_param('mr', 'long', 'excess_buffer_points', p.get('mr_excess_buffer_points', 2.0)))
        mr_short_excess_buffer = float(self.get_signal_param('mr', 'short', 'excess_buffer_points', p.get('mr_excess_buffer_points', 2.0)))
        mr_long_reclaim_buffer = float(self.get_signal_param('mr', 'long', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        mr_short_reclaim_buffer = float(self.get_signal_param('mr', 'short', 'reclaim_buffer_points', p.get('mr_reclaim_buffer_points', 0.5)))
        mr_long_close_strength = float(self.get_signal_param('mr', 'long', 'close_strength_min', p.get('mr_close_strength_min', 0.60)))
        mr_short_close_strength = float(self.get_signal_param('mr', 'short', 'close_strength_max', p.get('mr_close_strength_max', 0.40)))
        mr_poc_room = float(p.get('vp_mr_min_poc_room_points', 2.0))

        value_low = np.minimum(df['orb_low'], df['vp_val'].fillna(df['orb_low']))
        value_high = np.maximum(df['orb_high'], df['vp_vah'].fillna(df['orb_high']))
        value_mid = df['vp_poc'].fillna(df['orb_mid'])
        mr_value_extension = float(p.get('mr_value_extension_points', 0.5))

        range_bias = (
            (df['orb_range_multiple'] <= float(p.get('mr_balance_max_range_multiple', 1.55)))
            & (df['close'] >= (value_low - mr_long_excess_buffer))
            & (df['close'] <= (value_high + mr_short_excess_buffer))
            & (df['vwap_distance_abs'] <= float(p.get('regime_range_max_vwap_distance_points', 6.0)))
        )
        range_day = (
            vp_valid
            & ~df['regime_trend_up_confirmed'].fillna(False)
            & ~df['regime_trend_down_confirmed'].fillna(False)
            & (df['day_regime'].eq('range') | range_bias)
        )
        mr_signal_mode = str(p.get('mr_signal_mode', 'legacy_value_reclaim')).lower()
        mr_require_vwap_reclaim = bool(p.get('mr_require_vwap_reclaim', False))
        mr_long_vwap_reclaim = bool(p.get('mr_long_require_vwap_reclaim', mr_require_vwap_reclaim))
        mr_short_vwap_reclaim = bool(p.get('mr_short_require_vwap_reclaim', mr_require_vwap_reclaim))
        mr_long_vwap_ok = df['close'].gt(df['vwap']) if mr_long_vwap_reclaim else pd.Series(True, index=df.index)
        mr_short_vwap_ok = df['close'].lt(df['vwap']) if mr_short_vwap_reclaim else pd.Series(True, index=df.index)

        if mr_signal_mode in ('failed_auction_acceptance', 'failed_auction', 'acceptance'):
            sweep_lookback_bars = max(1, int(p.get('mr_sweep_lookback_bars', 3) or 3))
            acceptance_bars = max(1, int(p.get('mr_acceptance_bars', 1) or 1))
            min_wick_points = float(p.get('mr_min_rejection_wick_points', 0.0) or 0.0)
            min_wick_ratio = float(p.get('mr_min_rejection_wick_ratio', 0.0) or 0.0)

            def rolling_session_any(mask: pd.Series, window: int) -> pd.Series:
                return (
                    mask.fillna(False)
                    .astype(int)
                    .groupby(df['date_str'])
                    .transform(lambda s: s.rolling(window=window, min_periods=1).max())
                    .astype(bool)
                )

            bar_range = (df['high'] - df['low']).replace(0, np.nan)
            lower_wick = (np.minimum(df['open'], df['close']) - df['low']).clip(lower=0)
            upper_wick = (df['high'] - np.maximum(df['open'], df['close'])).clip(lower=0)
            wick_ok_long = pd.Series(True, index=df.index)
            wick_ok_short = pd.Series(True, index=df.index)
            if min_wick_points > 0:
                wick_ok_long &= lower_wick.ge(min_wick_points)
                wick_ok_short &= upper_wick.ge(min_wick_points)
            if min_wick_ratio > 0:
                wick_ok_long &= (lower_wick / bar_range).ge(min_wick_ratio).fillna(False)
                wick_ok_short &= (upper_wick / bar_range).ge(min_wick_ratio).fillna(False)

            long_sweep = (df['low'] < (value_low - mr_long_excess_buffer)) & wick_ok_long
            short_sweep = (df['high'] > (value_high + mr_short_excess_buffer)) & wick_ok_short
            recent_long_sweep = rolling_session_any(long_sweep, sweep_lookback_bars)
            recent_short_sweep = rolling_session_any(short_sweep, sweep_lookback_bars)

            long_acceptance = (
                (df['close'] > (value_low + mr_long_reclaim_buffer))
                & (df['close'] < (value_mid + mr_value_extension))
                & ((value_mid - df['close']) >= mr_poc_room)
                & (df['close_strength'] >= mr_long_close_strength)
                & mr_long_vwap_ok
            )
            short_acceptance = (
                (df['close'] < (value_high - mr_short_reclaim_buffer))
                & (df['close'] > (value_mid - mr_value_extension))
                & ((df['close'] - value_mid) >= mr_poc_room)
                & (df['close_strength'] <= mr_short_close_strength)
                & mr_short_vwap_ok
            )
            long_acceptance_confirmed = self._session_confirm(long_acceptance, df['date_str'], acceptance_bars)
            short_acceptance_confirmed = self._session_confirm(short_acceptance, df['date_str'], acceptance_bars)

            mr_long = (
                allow_long
                & self.is_signal_direction_enabled('mr', 'long')
                & range_day
                & mr_in_long_trade_window
                & recent_long_sweep
                & long_acceptance_confirmed
            )
            mr_short = (
                allow_short
                & self.is_signal_direction_enabled('mr', 'short')
                & range_day
                & mr_in_short_trade_window
                & recent_short_sweep
                & short_acceptance_confirmed
            )
        else:
            mr_long = (
                allow_long
                & self.is_signal_direction_enabled('mr', 'long')
                & range_day
                & mr_in_long_trade_window
                & (df['low'].shift(1) < (value_low.shift(1) - mr_long_excess_buffer))
                & (df['close'] > (value_low + mr_long_reclaim_buffer))
                & (df['close'] < (value_mid + mr_value_extension))
                & ((value_mid - df['close']) >= mr_poc_room)
                & (df['close_strength'] >= mr_long_close_strength)
                & mr_long_vwap_ok
            )
            mr_short = (
                allow_short
                & self.is_signal_direction_enabled('mr', 'short')
                & range_day
                & mr_in_short_trade_window
                & (df['high'].shift(1) > (value_high.shift(1) + mr_short_excess_buffer))
                & (df['close'] < (value_high - mr_short_reclaim_buffer))
                & (df['close'] > (value_mid - mr_value_extension))
                & ((df['close'] - value_mid) >= mr_poc_room)
                & (df['close_strength'] <= mr_short_close_strength)
                & mr_short_vwap_ok
            )

        trend_long_trade_start = self.get_signal_param('trend', 'long', 'trade_start', p['trade_start'])
        trend_long_trade_end = self.get_signal_param('trend', 'long', 'trade_end', p['trade_end'])
        trend_short_trade_start = self.get_signal_param('trend', 'short', 'trade_start', p['trade_start'])
        trend_short_trade_end = self.get_signal_param('trend', 'short', 'trade_end', p['trade_end'])
        trend_in_long_trade_window = (df['hour_min'] >= trend_long_trade_start) & (df['hour_min'] <= trend_long_trade_end)
        trend_in_short_trade_window = (df['hour_min'] >= trend_short_trade_start) & (df['hour_min'] <= trend_short_trade_end)

        trend_long_pullback_buffer = float(self.get_signal_param('trend', 'long', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 2.0)))
        trend_short_pullback_buffer = float(self.get_signal_param('trend', 'short', 'pullback_buffer_points', p.get('trend_pullback_buffer_points', 2.0)))
        trend_long_reclaim_buffer = float(self.get_signal_param('trend', 'long', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))
        trend_short_reclaim_buffer = float(self.get_signal_param('trend', 'short', 'reclaim_buffer_points', p.get('trend_reclaim_buffer_points', 0.5)))
        trend_acceptance_buffer = float(p.get('vp_trend_acceptance_buffer_points', 1.0))
        trend_long_close_strength = float(self.get_signal_param('trend', 'long', 'close_strength_min', p.get('trend_close_strength_min', 0.50)))
        trend_short_close_strength = float(self.get_signal_param('trend', 'short', 'close_strength_max', p.get('trend_close_strength_max', 0.45)))
        trend_min_slope = float(p.get('regime_trend_min_slope', 0.20))

        trend_up = vp_valid & df['day_regime'].eq('trend_up') & (df['trend_ema_slope'] >= trend_min_slope)
        trend_down = vp_valid & df['day_regime'].eq('trend_down') & (df['trend_ema_slope'] <= -trend_min_slope)
        trend_long_accept_level = np.maximum(df['orb_high'], df['vp_vah'])
        trend_short_accept_level = np.minimum(df['orb_low'], df['vp_val'])
        trend_long_support = np.maximum(df['vp_vah'], df['vwap'])
        trend_short_resistance = np.minimum(df['vp_val'], df['vwap'])

        trend_long = (
            allow_long
            & self.is_signal_direction_enabled('trend', 'long')
            & trend_up
            & trend_in_long_trade_window
            & (df['close'].shift(1) > (trend_long_accept_level.shift(1) + trend_acceptance_buffer))
            & (df['low'] <= (trend_long_support + trend_long_pullback_buffer))
            & (df['close'] > (trend_long_support + trend_long_reclaim_buffer))
            & (df['close'] > trend_long_accept_level)
            & (df['close'] > df['vwap'])
            & (df['close_strength'] >= trend_long_close_strength)
        )
        trend_short = (
            allow_short
            & self.is_signal_direction_enabled('trend', 'short')
            & trend_down
            & trend_in_short_trade_window
            & (df['close'].shift(1) < (trend_short_accept_level.shift(1) - trend_acceptance_buffer))
            & (df['high'] >= (trend_short_resistance - trend_short_pullback_buffer))
            & (df['close'] < (trend_short_resistance - trend_short_reclaim_buffer))
            & (df['close'] < trend_short_accept_level)
            & (df['close'] < df['vwap'])
            & (df['close_strength'] <= trend_short_close_strength)
        )

        df.loc[mr_long, ['signal', 'signal_type']] = [1, 'mr']
        df.loc[mr_short, ['signal', 'signal_type']] = [-1, 'mr']
        df.loc[trend_long, ['signal', 'signal_type']] = [1, 'trend']
        df.loc[trend_short, ['signal', 'signal_type']] = [-1, 'trend']
        return df

    def generate_signals_morning_va_breakout(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Morning Outside-Value-Area Breakout + Opening Drive (H4).

        Evaluates the first 15 minutes of RTH (09:30..09:44, corresponding to the
        close of the 09:40 5-min bar) for directional expansion outside the prior
        completed RTH session's Value Area (VAH / VAL) aligned with the overnight gap.
        """
        p = self.strategy_params
        df = df.copy()
        df['signal'] = 0
        df['signal_type'] = ''

        required_cols = {
            'hour_min',
            'prior_rth_vah',
            'prior_rth_val',
            'prior_rth_poc',
            'or15_open',
            'or15_high',
            'or15_low',
            'or15_close',
            'or15_close_location',
            'first15_return_pct',
        }
        if not required_cols.issubset(df.columns):
            return df

        allow_long = bool(p.get('allow_long', True)) and self.is_signal_direction_enabled('va_breakout', 'long')
        allow_short = bool(p.get('allow_short', True)) and self.is_signal_direction_enabled('va_breakout', 'short')
        if not allow_long and not allow_short:
            return df

        signal_bar_5m = str(p.get('or15_signal_bar_5m', '09:40'))
        at_signal_bar = df['hour_min'].eq(signal_bar_5m)

        min_abs_ret = float(p.get('va_breakout_min_abs_return_pct', 0.0010))
        min_long_loc = float(p.get('va_breakout_min_long_close_location', 0.65))
        max_short_loc = float(p.get('va_breakout_max_short_close_location', 0.35))
        require_outside_va = bool(p.get('va_breakout_require_outside_prior_va', True))
        require_with_gap = bool(p.get('va_breakout_require_with_gap', True))

        or15_close = pd.to_numeric(df['or15_close'], errors='coerce')
        or15_open = pd.to_numeric(df['or15_open'], errors='coerce')
        or15_high = pd.to_numeric(df['or15_high'], errors='coerce')
        or15_low = pd.to_numeric(df['or15_low'], errors='coerce')
        or15_loc = pd.to_numeric(df['or15_close_location'], errors='coerce')
        ret_pct = pd.to_numeric(df['first15_return_pct'], errors='coerce')
        prior_vah = pd.to_numeric(df['prior_rth_vah'], errors='coerce')
        prior_val = pd.to_numeric(df['prior_rth_val'], errors='coerce')
        prior_poc = pd.to_numeric(df['prior_rth_poc'], errors='coerce')
        prior_close = pd.to_numeric(
            df.get('prior_rth_close_1m', df.get('prior_rth_close', pd.Series(np.nan, index=df.index))),
            errors='coerce',
        )

        long_above_vah = or15_close.gt(prior_vah)
        long_poc_break = or15_low.le(prior_poc) & or15_close.gt(prior_poc)
        long_val_break = or15_low.le(prior_val) & or15_close.gt(prior_val)
        long_struct_ok = long_above_vah if require_outside_va else (long_above_vah | long_poc_break | long_val_break)

        short_below_val = or15_close.lt(prior_val)
        short_poc_break = or15_high.ge(prior_poc) & or15_close.lt(prior_poc)
        short_vah_break = or15_high.ge(prior_vah) & or15_close.lt(prior_vah)
        short_struct_ok = short_below_val if require_outside_va else (short_below_val | short_poc_break | short_vah_break)

        gap_pts = or15_open - prior_close
        long_gap_ok = gap_pts.gt(0.0) if require_with_gap else pd.Series(True, index=df.index)
        short_gap_ok = gap_pts.lt(0.0) if require_with_gap else pd.Series(True, index=df.index)

        long_cond = (
            allow_long
            & at_signal_bar
            & prior_vah.notna()
            & ret_pct.ge(min_abs_ret)
            & or15_loc.ge(min_long_loc)
            & long_struct_ok
            & long_gap_ok
        )
        short_cond = (
            allow_short
            & at_signal_bar
            & prior_val.notna()
            & ret_pct.le(-min_abs_ret)
            & or15_loc.le(max_short_loc)
            & short_struct_ok
            & short_gap_ok
        )

        df.loc[long_cond, ['signal', 'signal_type']] = [1, 'va_breakout']
        df.loc[short_cond & df['signal'].eq(0), ['signal', 'signal_type']] = [-1, 'va_breakout']

        enable_continuation = bool(p.get('enable_morning_continuation', False))
        if enable_continuation and allow_long:
            date_col = 'date_str' if 'date_str' in df.columns else ('date' if 'date' in df.columns else None)
            if date_col is None and 'time' in df.columns:
                df['date_str'] = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d')
                date_col = 'date_str'

            if date_col is not None:
                primary_dates = set(df.loc[long_cond, date_col])
                if primary_dates:
                    cont_start = str(p.get('continuation_start', '10:20'))
                    cont_end = str(p.get('continuation_end', '12:00'))
                    cont_buf = float(p.get('continuation_buffer_points', 1.0))
                    req_above_vwap = bool(p.get('continuation_require_above_vwap', True))

                    is_prim = df[date_col].isin(primary_dates)
                    m1015 = df['hour_min'].le('10:15')
                    h1015_by_date = df.loc[m1015].groupby(df[date_col])['high'].max()
                    session_h1015 = df[date_col].map(h1015_by_date)

                    in_win = df['hour_min'].ge(cont_start) & df['hour_min'].le(cont_end)
                    vwap_ok = (df['close'] > df['vwap']) if (req_above_vwap and 'vwap' in df.columns) else True
                    cross = (
                        df['close'].gt(session_h1015 + cont_buf)
                        & df['close'].shift(1).le(session_h1015.shift(1) + cont_buf)
                    )
                    cont_mask = is_prim & in_win & cross & vwap_ok & df['signal'].eq(0)
                    first_idx = df[cont_mask].groupby(df[date_col]).head(1).index
                    df.loc[first_idx, ['signal', 'signal_type']] = [1, 'va_continuation']

        return df


