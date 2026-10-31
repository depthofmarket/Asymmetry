"""Trade execution, exit levels, and intrabar simulation."""


import numpy as np
import pandas as pd


class ExecutionMixin:
    """Mixin extracted from BacktestEngine — Trade execution, exit levels, and intrabar simulation."""

    def update_trade_excursions(self, trade, high_price: float, low_price: float):
        if trade.direction == 'long':
            favorable_points = max(0.0, high_price - trade.entry_price)
            adverse_points = max(0.0, trade.entry_price - low_price)
        else:
            favorable_points = max(0.0, trade.entry_price - low_price)
            adverse_points = max(0.0, high_price - trade.entry_price)

        trade.max_favorable_excursion_points = max(
            trade.max_favorable_excursion_points,
            favorable_points,
        )
        trade.max_adverse_excursion_points = max(
            trade.max_adverse_excursion_points,
            adverse_points,
        )

    def apply_trade_management(self, trade, levels: dict, bars_held: int) -> dict:
        managed_levels = dict(levels)
        signal_type = trade.signal_type or None
        direction = trade.direction
        cv = self.futures_specs['contract_value']
        mfe_points = trade.max_favorable_excursion_points
        mfe_dollars = mfe_points * trade.contracts * cv

        trail_trigger_dollars = float(
            self.get_signal_param(
                signal_type,
                direction,
                'trail_trigger_dollars',
                self.strategy_params.get('trail_trigger_dollars', 0.0),
            ) or 0.0
        )
        trail_distance_points = float(
            self.get_signal_param(
                signal_type,
                direction,
                'trail_distance_points',
                self.strategy_params.get('trail_distance_points', 0.0),
            ) or 0.0
        )

        trigger_dollars = float(
            self.get_signal_param(
                signal_type,
                direction,
                'breakeven_trigger_dollars',
                self.strategy_params.get('breakeven_trigger_dollars', 0.0),
            ) or 0.0
        )
        min_hold_bars = int(
            self.get_signal_param(
                signal_type,
                direction,
                'breakeven_min_hold_bars',
                self.strategy_params.get('breakeven_min_hold_bars', 1),
            ) or 0
        )
        offset_points = float(
            self.get_signal_param(
                signal_type,
                direction,
                'breakeven_offset_points',
                self.strategy_params.get('breakeven_offset_points', 0.0),
            ) or 0.0
        )

        if (
            trail_trigger_dollars > 0
            and trail_distance_points > 0
            and bars_held >= min_hold_bars
            and mfe_dollars >= trail_trigger_dollars
        ):
            locked_points = max(0.0, mfe_points - trail_distance_points)
            if direction == 'long':
                managed_stop = trade.entry_price + locked_points
                existing = managed_levels.get('managed_stop')
                managed_levels['managed_stop'] = max(existing, managed_stop) if existing is not None else managed_stop
            else:
                managed_stop = trade.entry_price - locked_points
                existing = managed_levels.get('managed_stop')
                managed_levels['managed_stop'] = min(existing, managed_stop) if existing is not None else managed_stop

        if trigger_dollars <= 0 or bars_held < min_hold_bars or mfe_dollars < trigger_dollars:
            return managed_levels

        if direction == 'long':
            managed_stop = trade.entry_price + offset_points
            existing = managed_levels.get('managed_stop')
            managed_levels['managed_stop'] = max(existing, managed_stop) if existing is not None else managed_stop
        else:
            managed_stop = trade.entry_price - offset_points
            existing = managed_levels.get('managed_stop')
            managed_levels['managed_stop'] = min(existing, managed_stop) if existing is not None else managed_stop

        return managed_levels

    def managed_stop_activation_mode(self) -> str:
        mode = str(self.strategy_params.get('managed_stop_activation_mode', 'same_bar') or 'same_bar')
        mode = mode.lower().strip()
        if mode in {'next_bar', 'prior_bar', 'delayed'}:
            return 'next_bar'
        return 'same_bar'

    def managed_stop_uses_current_bar_excursion(self) -> bool:
        return self.managed_stop_activation_mode() == 'same_bar'


    def apply_market_structure_stop(
        self,
        levels: dict,
        direction: str,
        entry_price: float,
        atr: float,
        entry_row: pd.Series | None,
    ) -> dict:
        if entry_row is None or not self.strategy_params.get('market_structure_stop_enabled', False):
            return levels

        p = self.strategy_params
        level = int(p.get('market_structure_stop_level', 0))
        prefix = f'ms_l{level}'
        buffer_points = float(p.get('market_structure_stop_buffer_points', 1.0))
        max_atr_multiple = float(p.get('market_structure_stop_max_atr_multiple', 1.25))
        max_distance = float(atr) * max_atr_multiple if np.isfinite(atr) else np.inf
        if max_distance <= 0:
            return levels

        out = dict(levels)
        existing_stop = out.get('stop_loss')

        if direction == 'long':
            support = entry_row.get(f'{prefix}_last_bottom_price', np.nan)
            if not np.isfinite(support):
                return out
            structure_stop = float(support) - buffer_points
            distance = entry_price - structure_stop
            if 0 < distance <= max_distance:
                out['stop_loss'] = (
                    max(existing_stop, structure_stop)
                    if existing_stop is not None and np.isfinite(existing_stop)
                    else structure_stop
                )
        else:
            resistance = entry_row.get(f'{prefix}_last_top_price', np.nan)
            if not np.isfinite(resistance):
                return out
            structure_stop = float(resistance) + buffer_points
            distance = structure_stop - entry_price
            if 0 < distance <= max_distance:
                out['stop_loss'] = (
                    min(existing_stop, structure_stop)
                    if existing_stop is not None and np.isfinite(existing_stop)
                    else structure_stop
                )

        return out

    def apply_market_profile_target(
        self,
        levels: dict,
        direction: str,
        entry_price: float,
        entry_row: pd.Series | None,
    ) -> dict:
        if entry_row is None or not self.strategy_params.get('market_profile_target_enabled', False):
            return levels

        p = self.strategy_params
        min_distance = float(p.get('market_profile_target_min_distance_points', 4.0))
        max_distance = float(p.get('market_profile_target_max_distance_points', 40.0))
        out = dict(levels)

        if direction == 'long':
            target = entry_row.get('mp_nearest_resistance', np.nan)
            if not np.isfinite(target):
                return out
            distance = float(target) - entry_price
            if min_distance <= distance <= max_distance:
                existing = out.get('profit_target')
                out['profit_target'] = (
                    min(existing, float(target))
                    if existing is not None and np.isfinite(existing) and existing > entry_price
                    else float(target)
                )
        else:
            target = entry_row.get('mp_nearest_support', np.nan)
            if not np.isfinite(target):
                return out
            distance = entry_price - float(target)
            if min_distance <= distance <= max_distance:
                existing = out.get('profit_target')
                out['profit_target'] = (
                    max(existing, float(target))
                    if existing is not None and np.isfinite(existing) and existing < entry_price
                    else float(target)
                )

        return out


    def should_hawkes_exit(self, trade, row: pd.Series, bars_held: int) -> bool:
        p = self.strategy_params
        if not bool(p.get('hawkes_exit_enabled', False)):
            return False

        signal_type = str(trade.signal_type or "")
        enabled_signal_types = {str(x) for x in p.get('hawkes_exit_signal_types', [])}
        if enabled_signal_types and signal_type not in enabled_signal_types:
            return False

        min_hold_bars = int(
            self.get_signal_param(
                signal_type or None,
                trade.direction,
                'hawkes_exit_min_hold_bars',
                p.get('hawkes_exit_min_hold_bars', 1),
            )
            or 0
        )
        if bars_held < min_hold_bars:
            return False

        flag_col = (
            'hawkes_vol_cross_below_low'
            if bool(p.get('hawkes_exit_use_cross', False))
            else 'hawkes_vol_below_low'
        )
        if flag_col not in row.index or not bool(row.get(flag_col, False)):
            return False

        if bool(p.get('hawkes_exit_only_if_favorable', False)):
            close_price = row.get('close', np.nan)
            if not np.isfinite(close_price):
                return False
            favorable_points = (
                float(close_price) - float(trade.entry_price)
                if trade.direction == 'long'
                else float(trade.entry_price) - float(close_price)
            )
            min_favorable = float(p.get('hawkes_exit_min_favorable_points', 0.0))
            if favorable_points < min_favorable:
                return False

        return True

    def next_hawkes_exit_time(self, signal_frame: pd.DataFrame, entry_i: int, trade) -> pd.Timestamp | None:
        if not bool(self.strategy_params.get('hawkes_exit_enabled', False)):
            return None
        for row_i in range(entry_i + 1, len(signal_frame)):
            bars_held = row_i - entry_i
            row = signal_frame.iloc[row_i]
            if self.should_hawkes_exit(trade, row, bars_held=bars_held):
                return pd.Timestamp(row['time']) + pd.Timedelta(minutes=5)
        return None


    def _simulate_trade_on_1m(
        self,
        trade,
        levels: dict,
        entry_time,
        max_hold_minutes: int,
        hawkes_exit_time: pd.Timestamp | None = None,
    ) -> tuple[pd.Timestamp, float, str]:
        exec_df = self._get_execution_1m()
        if exec_df.empty or self._execution_times is None:
            return pd.Timestamp(entry_time), float(trade.entry_price), "end_of_data"

        entry_ts = pd.Timestamp(entry_time)
        start_idx = int(self._execution_times.searchsorted(np.datetime64(entry_ts), side='left'))
        if start_idx >= len(exec_df):
            return entry_ts, float(trade.entry_price), "end_of_data"

        actual_entry_time = pd.Timestamp(exec_df.iloc[start_idx]['time'])
        deadline = actual_entry_time + pd.Timedelta(minutes=max_hold_minutes)
        use_current_bar_excursion = self.managed_stop_uses_current_bar_excursion()

        for idx in range(start_idx, len(exec_df)):
            bar = exec_df.iloc[idx]
            bar_time = pd.Timestamp(bar['time'])
            if bar_time < actual_entry_time:
                continue

            bars_held = max(0, int((bar_time - actual_entry_time).total_seconds() // 300))
            if use_current_bar_excursion:
                self.update_trade_excursions(trade, float(bar['high']), float(bar['low']))
            active_levels = self.apply_trade_management(trade, levels, bars_held=bars_held)

            exit_flag, exit_reason, resolved_exit_price = self.resolve_intrabar_exit(
                trade.direction,
                float(bar['open']),
                float(bar['high']),
                float(bar['low']),
                active_levels,
            )
            if exit_flag:
                return bar_time, float(resolved_exit_price), exit_reason

            if not use_current_bar_excursion:
                self.update_trade_excursions(trade, float(bar['high']), float(bar['low']))

            if hawkes_exit_time is not None and bar_time >= hawkes_exit_time:
                return bar_time, float(bar['open']), "hawkes_vol_exit"

            if bar_time >= deadline:
                return bar_time, float(bar['close']), "time_exit"

        last_bar = exec_df.iloc[-1]
        return pd.Timestamp(last_bar['time']), float(last_bar['close']), "end_of_data"


    def calculate_contracts(self, atr: float, direction: str | None = None, signal_type: str | None = None) -> int:
        p = self.strategy_params
        sizing_mode = p.get('position_sizing_mode', 'risk_based')

        if sizing_mode == 'fixed_contracts':
            fixed_contracts = p.get('fixed_contracts', 1)
            if direction is not None:
                fixed_contracts = self.get_signal_param(signal_type, direction, 'fixed_contracts', fixed_contracts)
            contracts = int(fixed_contracts)
            if contracts <= 0:
                return 0
            return min(contracts, p['max_contracts'])

        contract_value = self.futures_specs['contract_value']
        stop_multiplier = p['atr_stop_multiplier']
        if direction is not None:
            stop_multiplier = self.get_signal_param(signal_type, direction, 'atr_stop_multiplier', stop_multiplier)
        stop_distance = atr * stop_multiplier

        if stop_distance == 0:
            return 0

        # Don't size when capital is at or below zero
        if self.portfolio.current_capital <= 0:
            return 0

        risk_dollars = self.portfolio.current_capital * p['risk_per_trade_pct']
        risk_dollars = min(risk_dollars, p['max_risk_per_trade_dollars'])
        risk_dollars = max(risk_dollars, p['min_risk_per_trade_dollars'])

        contracts = int(risk_dollars / (stop_distance * contract_value))
        contracts = max(1, contracts)
        contracts = min(contracts, p['max_contracts'])

        return contracts

    def get_hard_exit_price(self, direction: str, entry_price: float, contracts: int, limit_dollars: float) -> float:
        cv = self.futures_specs['contract_value']
        commission = self.futures_specs['commission_per_round_trip'] * contracts
        slippage = self.futures_specs['slippage_points'] * cv * contracts
        # `limit_dollars` is intended as realized/net max loss, while
        # portfolio.exit_position will subtract costs again on exit.
        # So the raw price move must exclude those costs here.
        net_move_dollars = max(0.0, limit_dollars - commission - slippage)
        price_move = net_move_dollars / (contracts * cv)
        if direction == 'long':
            return entry_price - price_move
        else:
            return entry_price + price_move

    def build_exit_levels(
        self,
        direction: str,
        entry_price: float,
        contracts: int,
        atr: float,
        vwap_target: float | None = None,
        target_price: float | None = None,
        signal_type: str | None = None,
        entry_row: pd.Series | None = None,
    ) -> dict:
        p = self.strategy_params
        exit_mode = p.get('exit_mode', 'hybrid')
        stop_multiplier = self.get_signal_param(signal_type, direction, 'atr_stop_multiplier', p['atr_stop_multiplier'])
        target_multiplier = self.get_signal_param(signal_type, direction, 'atr_target_multiplier', p['atr_target_multiplier'])
        stop_distance = atr * stop_multiplier

        levels = {
            'stop_loss': None,
            'profit_target': None,
            'hard_stop': None,
            'hard_target': None,
            'managed_stop': None,
        }

        if exit_mode in ('atr_only', 'hybrid'):
            if direction == 'long':
                levels['stop_loss'] = entry_price - stop_distance
                levels['profit_target'] = entry_price + (stop_distance * target_multiplier)
            else:
                levels['stop_loss'] = entry_price + stop_distance
                levels['profit_target'] = entry_price - (stop_distance * target_multiplier)
        elif exit_mode == 'or15_barrier' and entry_row is not None:
            or15_rng = float(entry_row.get('or15_range_points', np.nan))
            min_stop = float(self.get_signal_param(signal_type, direction, 'or15_min_stop_points', p.get('or15_min_stop_points', 15.0)))
            max_stop = float(self.get_signal_param(signal_type, direction, 'or15_max_stop_points', p.get('or15_max_stop_points', 60.0)))
            rr_ratio = float(self.get_signal_param(signal_type, direction, 'or15_reward_risk_ratio', p.get('or15_reward_risk_ratio', 1.5)))
            if np.isfinite(or15_rng) and or15_rng > 0:
                clipped_stop = float(np.clip(or15_rng, min_stop, max_stop))
                if direction == 'long':
                    levels['stop_loss'] = entry_price - clipped_stop
                    if rr_ratio > 0:
                        levels['profit_target'] = entry_price + clipped_stop * rr_ratio
                else:
                    levels['stop_loss'] = entry_price + clipped_stop
                    if rr_ratio > 0:
                        levels['profit_target'] = entry_price - clipped_stop * rr_ratio

        # If provided, use the reference target only when it is a favorable
        # exit. Bad source rows or next-bar gaps can otherwise put a target on
        # the wrong side of entry and convert it into a loss.
        reference_target = target_price
        if reference_target is None:
            reference_target = vwap_target
        if reference_target is not None and np.isfinite(reference_target):
            reference_target = float(reference_target)
            if (
                (direction == 'long' and reference_target > entry_price) or
                (direction == 'short' and reference_target < entry_price)
            ):
                levels['profit_target'] = reference_target

        levels = self.apply_market_profile_target(
            levels,
            direction,
            float(entry_price),
            entry_row,
        )
        levels = self.apply_market_structure_stop(
            levels,
            direction,
            float(entry_price),
            float(atr),
            entry_row,
        )

        if exit_mode in ('hard_only', 'hybrid'):
            max_loss_dollars = self.get_signal_param(signal_type, direction, 'max_loss_per_trade_dollars', p['max_loss_per_trade_dollars'])
            max_profit_dollars = self.get_signal_param(signal_type, direction, 'max_profit_per_trade_dollars', p['max_profit_per_trade_dollars'])
            levels['hard_stop'] = self.get_hard_exit_price(
                direction, entry_price, contracts, max_loss_dollars
            )
            commission = self.futures_specs['commission_per_round_trip'] * contracts
            slippage = self.futures_specs['slippage_points'] * self.futures_specs['contract_value'] * contracts
            net_target_dollars = max_profit_dollars + commission + slippage
            if direction == 'long':
                levels['hard_target'] = entry_price + (
                    net_target_dollars / (contracts * self.futures_specs['contract_value'])
                )
            else:
                levels['hard_target'] = entry_price - (
                    net_target_dollars / (contracts * self.futures_specs['contract_value'])
                )

        return levels

    def target_trade_through_points(self) -> float:
        p = self.strategy_params
        explicit = p.get('target_fill_trade_through_points')
        if explicit is not None:
            try:
                return max(0.0, float(explicit))
            except (TypeError, ValueError):
                return 0.0
        ticks = max(0.0, float(p.get('target_fill_trade_through_ticks', 0) or 0))
        tick_size = float(p.get('vp_tick_size', p.get('tick_size', 0.25)) or 0.25)
        return ticks * tick_size

    def favorable_target_hit(
        self,
        direction: str,
        price: float,
        high_price: float,
        low_price: float,
    ) -> bool:
        mode = str(self.strategy_params.get('target_fill_mode', 'touch') or 'touch').lower()
        through = self.target_trade_through_points() if mode == 'trade_through' else 0.0
        if direction == 'long':
            return high_price >= float(price) + through
        return low_price <= float(price) - through

    def resolve_intrabar_exit(
        self,
        direction: str,
        bar_open: float,
        high_price: float,
        low_price: float,
        levels: dict,
    ):
        p = self.strategy_params
        assumption = p.get('intrabar_exit_assumption', 'conservative')

        adverse_hits = []
        favorable_hits = []

        if direction == 'long':
            for reason in ('managed_stop', 'hard_stop', 'stop_loss'):
                price = levels.get(reason)
                if price is not None and low_price <= price:
                    adverse_hits.append((reason, price))
            for reason in ('profit_target', 'hard_target'):
                price = levels.get(reason)
                if price is not None and self.favorable_target_hit(direction, price, high_price, low_price):
                    favorable_hits.append((reason, price))

            adverse_hit = max(adverse_hits, key=lambda item: item[1]) if adverse_hits else None
            favorable_hit = min(favorable_hits, key=lambda item: item[1]) if favorable_hits else None
        else:
            for reason in ('managed_stop', 'hard_stop', 'stop_loss'):
                price = levels.get(reason)
                if price is not None and high_price >= price:
                    adverse_hits.append((reason, price))
            for reason in ('profit_target', 'hard_target'):
                price = levels.get(reason)
                if price is not None and self.favorable_target_hit(direction, price, high_price, low_price):
                    favorable_hits.append((reason, price))

            adverse_hit = min(adverse_hits, key=lambda item: item[1]) if adverse_hits else None
            favorable_hit = max(favorable_hits, key=lambda item: item[1]) if favorable_hits else None

        if adverse_hit and favorable_hit:
            if assumption == 'optimistic':
                return True, favorable_hit[0], favorable_hit[1]
            if assumption == 'proximity':
                adverse_distance = abs(bar_open - adverse_hit[1])
                favorable_distance = abs(bar_open - favorable_hit[1])
                if favorable_distance < adverse_distance:
                    return True, favorable_hit[0], favorable_hit[1]
                return True, adverse_hit[0], adverse_hit[1]
            return True, adverse_hit[0], adverse_hit[1]

        if adverse_hit:
            return True, adverse_hit[0], adverse_hit[1]
        if favorable_hit:
            return True, favorable_hit[0], favorable_hit[1]

        return False, "", None
