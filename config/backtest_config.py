# NQ Futures Specifications
FUTURES_SPECS = {
    'symbol': 'NQ',
    'contract_value': 20,
    'commission_per_round_trip': 3.50,
    # Round-trip point assumptions from validated L2 top-book evidence.
    # Evidence: results/research_master/execution_cost_assumptions/
    # Accepted rows are 2020/2021 semicolon-schema samples only; 2022+
    # structured warm-state rows are excluded until reconstruction is accepted.
    'slippage_points': 1.50,
    # Stops and other urgent exits use tail trade-vs-mid evidence.
    'slippage_stop_points': 2.50,
    # Targets/limit exits remain cheaper than urgent fills, but are not free.
    'slippage_limit_points': 0.75,
}

EXECUTION_COST_EVIDENCE = {
    'assumption_version': 'l2_topbook_20260531',
    'recommendation_path': (
        'results/research_master/execution_cost_assumptions/'
        'execution_cost_assumptions_recommendation.csv'
    ),
    'report_path': (
        'results/research_master/execution_cost_assumptions/'
        'execution_cost_assumptions.md'
    ),
    'accepted_evidence': (
        '2020/2021 semicolon-schema L2 top-book validation rows with >=30 minutes, '
        '>=1000 usable quote rows, and >=1% quote/depth-update ratio'
    ),
    'excluded_evidence': (
        '2022+ structured-schema rows and warm-state smoke cells until they produce '
        'accepted non-trivial quote coverage'
    ),
}

# Backtest Settings
BACKTEST_CONFIG = {
    'data_path': 'data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv',
    # Databento NQ.FUT contains multiple outright contracts at the same minute.
    # Use the prior session's dominant contract where possible; selecting by the
    # current full session's volume leaks future roll/universe information.
    'continuous_contract_method': 'prior_session_volume',  # prior_session_volume | session_volume | daily_volume | timestamp_volume
    'starting_capital': 100000,
    'risk_per_trade_pct': 0.005,
    'max_risk_per_trade_dollars': 400,
    'min_risk_per_trade_dollars': 100,
    'max_loss_per_trade_dollars': 250,
    'max_profit_per_trade_dollars': 1000,
    'max_contracts': 2,
    'enable_circuit_breaker': False,
    'max_drawdown_pct': 0.25,
    'position_sizing_mode': 'fixed_contracts',
    'fixed_contracts': 1,
}

OPTIONS_FLOW_CONFIG = {
    'statistics_source': 'data/raw/options_nq/statistics/GLBX-20260505-VT65CHSJE8.zip',
    'definition_source': 'data/raw/options_nq/definition/GLBX-20260505-KJLD654KQQ.zip',
    'features_path': 'data/processed/options_nq/options_flow_daily.csv',
    'strike_levels_path': 'data/processed/options_nq/options_flow_strike_levels.csv',
    'dashboard_path': 'data/processed/options_nq/options_flow_dashboard.csv',
    'dashboard_strike_levels_path': 'data/processed/options_nq/options_flow_dashboard_strike_levels.csv',
    'contract_multiplier': 20.0,
    'risk_free_rate': 0.0,
    'min_dte': 0,
    'max_dte': 120,
    'strike_window_points': 600.0,
    'min_open_interest': 1,
    'iv_floor': 0.01,
    'iv_cap': 5.0,
    'gex_neutral_threshold': 0.0,
    'put_gamma_sign': -1.0,
}

# Strategy parameters.
STRATEGY_PARAMS = {
    # Select strategy implementation:
    # 'amt_mean_reversion', 'amt_trend', 'amt_combined',
    # 'vwap_regime', 'volume_profile_regime', 'market_profile_cross',
    # or 'hybrid_profile_regime_no_orb'
    'strategy_name': 'volume_profile_regime',
    'orb_start': '09:30',
    'orb_end': '10:00',
    'trade_start': '11:00',
    'trade_end': '14:30',
    'rth_start': '09:30',
    'rth_end': '16:00',
    # RTH VWAP matches the location tool most discretionary NQ traders watch.
    # Set to 'calendar' for the old midnight-reset behavior or 'globex' for
    # futures session VWAP.
    'vwap_session': 'rth',  # rth | globex | calendar
    'initial_balance_end': '10:30',
    'allow_long': True,
    'allow_short': True,
    'execution_timeframe': '1min',
    'trend_ema_period': 50,
    'volume_sma_period': 20,
    'volume_spike_multiplier': 1.2,
    'vsa_enabled': True,
    'vsa_lookback_bars': 390,
    'vsa_min_r2': 0.10,
    'vsa_min_slope': 0.0,
    'vsa_score_scale': 1.0,
    'vsa_extreme_threshold': 0.65,
    'vsa_filter': 'off',  # off | require_absorption | require_thin_move | avoid_absorption | avoid_thin_move | context
    'vsa_filter_signal_types': [],
    'hawkes_enabled': True,
    'hawkes_norm_lookback_bars': 390,
    'hawkes_threshold_lookback_bars': 390,
    'hawkes_kappa': 0.10,
    'hawkes_low_quantile': 0.05,
    'hawkes_high_quantile': 0.95,
    'hawkes_exit_enabled': False,
    'hawkes_exit_signal_types': ['trend', 'mp'],
    'hawkes_exit_min_hold_bars': 1,
    'hawkes_exit_use_cross': False,
    'hawkes_exit_only_if_favorable': False,
    'hawkes_exit_min_favorable_points': 0.0,
    'cusum_event_enabled': True,
    'cusum_event_atr_multiple': 1.0,
    'cusum_event_min_threshold_points': 0.25,

    # Point-in-time Gaussian Markov volatility regimes.
    # The model is calibrated only on bars before the current bar, then the
    # current completed bar is classified for next-bar decisions.
    'markov_regime_enabled': False,
    'markov_n_states': 3,
    'markov_calibration_bars': 78,
    'markov_min_calibration_bars': 30,
    'markov_refit_every_bars': 12,
    'markov_transition_smoothing': 0.1,
    'markov_min_std': 1e-8,
    'markov_min_state_observations': 3,
    'markov_volatility_method': 'range_close',  # range_close | log_range | abs_return
    'markov_initial_prob_mode': 'uniform',  # uniform | empirical
    'markov_regime_filter': 'off',  # off | context | avoid_high | require_low_mid | require_mid_high | map
    'markov_min_confidence': 0.0,
    'markov_allowed_states': {},
    'markov_blocked_states': {},

    # Options-flow confluence features. Build the feature cache with:
    # python3 scripts/build_options_flow_features.py
    'options_flow_enabled': False,
    'options_flow_features_path': OPTIONS_FLOW_CONFIG['features_path'],
    'options_flow_filter': 'off',  # off | context | gamma_environment | require_positive_gex | require_negative_gex | avoid_negative_gex | gex_wall_room
    'options_flow_allow_missing': True,
    'options_flow_min_abs_gex': 0.0,
    'options_flow_wall_room_points': 12.0,
    'options_flow_amplifier_trigger_points': 12.0,
    'options_flow_require_negative_gamma_amplifier': True,

    'atr_period': 14,
    'atr_stop_multiplier': 0.9,
    'atr_target_multiplier': 1.8,
    'atr_max_multiplier': 2.0,
    'orb_min_points': 10,
    'orb_max_points': 120,
    'max_hold_bars': 14,
    'max_trades_per_day': 3,
    'entry_mode': 'next_bar_open',
    'entry_delay_bars': 0,
    'exit_mode': 'hybrid',
    'intrabar_exit_assumption': 'proximity',
    # Target fills are a major scalping-backtest failure mode.  The default
    # preserves legacy behavior; validation candidates can require price to
    # trade through targets before assuming the resting limit was filled.
    'target_fill_mode': 'touch',  # touch | trade_through
    'target_fill_trade_through_ticks': 1,
    'target_fill_trade_through_points': None,
    'breakeven_trigger_dollars': 0,
    'breakeven_offset_points': 0.0,
    'breakeven_min_hold_bars': 1,
    'trail_trigger_dollars': 160,
    'trail_distance_points': 3.5,
    # same_bar preserves legacy behavior: current bar MFE can activate a
    # managed stop that is also fillable on that bar. next_bar only lets prior
    # completed-bar MFE activate managed stops for the current execution bar.
    'managed_stop_activation_mode': 'same_bar',  # same_bar | next_bar

    # Day regime classifier:
    # keep ambiguous sessions neutral, confirm trend after acceptance + follow-through,
    # and only allow MR when the session keeps rotating near value.
    'regime_eval_start': '10:05',
    'regime_trend_confirm_bars': 2,
    'regime_range_confirm_bars': 2,
    'regime_trend_min_range_multiple': 1.70,
    'regime_range_max_range_multiple': 1.55,
    'regime_trend_min_extension_factor': 0.45,
    'regime_trend_min_extension_points': 5.0,
    'regime_range_max_extension_factor': 0.35,
    'regime_range_max_extension_points': 6.0,
    'regime_trend_min_vwap_distance_points': 4.0,
    'regime_range_max_vwap_distance_points': 6.0,
    'regime_range_value_area_buffer_points': 1.0,
    'regime_range_max_slope': 0.25,
    'regime_trend_min_slope': 0.24,

    # Shared regime structure settings
    'trend_acceptance_buffer_points': 1.0,
    'trend_min_range_multiple': 1.70,
    'mr_balance_max_range_multiple': 1.55,
    'mr_excess_buffer_points': 2.5,
    'mr_reclaim_buffer_points': 0.75,
    'mr_value_extension_points': 1.0,
    'mr_close_strength_min': 0.60,
    'mr_close_strength_max': 0.40,
    'mr_signal_mode': 'legacy_value_reclaim',  # legacy_value_reclaim | failed_auction_acceptance
    'mr_sweep_lookback_bars': 3,
    'mr_acceptance_bars': 1,
    'mr_min_rejection_wick_points': 0.0,
    'mr_min_rejection_wick_ratio': 0.0,
    'trend_pullback_buffer_points': 2.5,
    'trend_reclaim_buffer_points': 0.25,
    'vp_profile_start': '09:30',
    'vp_profile_end': '10:00',
    'vp_tick_size': 0.25,
    'vp_value_area_pct': 0.70,
    'vp_mr_min_poc_room_points': 2.0,
    'vp_trend_acceptance_buffer_points': 0.75,
    'trend_close_strength_min': 0.50,
    'trend_close_strength_max': 0.45,

    # Mean reversion bucket
    'mr_trade_start': '10:15',
    'mr_trade_end': '12:00',
    'mr_atr_stop_multiplier': 0.95,
    'mr_atr_target_multiplier': 1.7,
    'mr_max_loss_per_trade_dollars': 180,
    'mr_trail_trigger_dollars': 140,
    'mr_trail_distance_points': 2.5,
    'mr_long_close_strength_min': 0.55,
    'mr_short_close_strength_max': 0.40,
    'mr_short_enabled': True,

    # Trend bucket
    'trend_trade_start': '10:30',
    'trend_trade_end': '14:30',
    'trend_atr_stop_multiplier': 0.85,
    'trend_atr_target_multiplier': 2.2,
    'trend_max_loss_per_trade_dollars': 180,
    'trend_trail_trigger_dollars': 180,
    'trend_trail_distance_points': 3.0,
    'trend_long_close_strength_min': 0.50,
    'trend_short_close_strength_max': 0.45,
    'trend_short_enabled': True,

    # Optional research filters. Candidate configs below can override these.
    # Keys can be setup tags such as "mr_long" / "trend_short", directions
    # such as "long" / "short", or signal types such as "mr" / "trend".
    'blocked_setup_hours': {},
    'allowed_setup_hours': {},
    'blocked_setup_tags': [],
    'allowed_setup_tags': [],

    # Point-in-time market-memory diagnostics from Hurst, entropy, Lempel-Ziv,
    # and Hill tail estimates. Defaults stay off; candidates can turn these
    # into execution filters after the reports say they deserve attention.
    'market_memory_enabled': True,
    'market_memory_filter': 'off',  # off | context | avoid_fragile | avoid_chaotic | avoid_tail_risk | require_persistent | require_mean_reverting | map
    'market_memory_filter_signal_types': [],
    'market_memory_allow_missing': True,
    'market_memory_hurst_window_bars': 156,
    'market_memory_hurst_min_bars': 64,
    'market_memory_entropy_window_bars': 156,
    'market_memory_entropy_min_bars': 64,
    'market_memory_entropy_bins': 10,
    'market_memory_lz_window_bars': 96,
    'market_memory_lz_min_bars': 48,
    'market_memory_tail_window_bars': 390,
    'market_memory_tail_min_bars': 120,
    'market_memory_tail_fraction': 0.10,
    'market_memory_tail_min_observations': 8,
    'market_memory_tail_event_quantile': 0.99,
    'market_memory_recompute_every_bars': 6,
    'market_memory_hurst_low_threshold': 0.45,
    'market_memory_hurst_high_threshold': 0.55,
    'market_memory_entropy_low_threshold': 0.55,
    'market_memory_entropy_high_threshold': 0.85,
    'market_memory_lz_low_threshold': 0.75,
    'market_memory_lz_high_threshold': 1.05,
    'market_memory_tail_alpha_fat_threshold': 3.0,
    'market_memory_tail_alpha_thin_threshold': 5.0,
    'market_memory_context_avoid_fragile': True,
    'market_memory_mr_allowed_states': ['mean_reverting_memory', 'neutral_memory'],
    'market_memory_trend_allowed_states': ['persistent_memory', 'neutral_memory'],
    'market_memory_mp_allowed_states': ['persistent_memory', 'neutral_memory'],
    'market_memory_allowed_states': {},
    'market_memory_blocked_states': {},

    # Confirmed market-structure hierarchy from directional change.
    # Defaults are off; candidate configs below turn these into testable ideas.
    'market_structure_enabled': False,
    'market_structure_atr_period': 78,
    'market_structure_atr_multiplier': 1.0,
    'market_structure_levels': 3,
    'market_structure_filter': 'off',  # off | swing | reversal | room | swing_room | reversal_room
    'market_structure_filter_level': 1,
    'market_structure_filter_signal_types': [],
    'market_structure_max_bars_since_extreme': 12,
    'market_structure_min_room_to_opposite_points': 8.0,
    'market_structure_stop_enabled': False,
    'market_structure_stop_level': 0,
    'market_structure_stop_buffer_points': 1.0,
    'market_structure_stop_max_atr_multiple': 1.25,

    # Rolling market-profile support/resistance levels from close-time density.
    # Uses a fast smoothed histogram backend by default; set backend to "kde"
    # for closer transcript parity on smaller research slices.
    'market_profile_enabled': False,
    'market_profile_backend': 'histogram',  # histogram | kde
    'market_profile_lookback_bars': 390,
    'market_profile_recompute_every_bars': 12,
    'market_profile_grid_size': 160,
    'market_profile_atr_multiplier': 3.0,
    'market_profile_first_weight': 1.0,
    'market_profile_prominence_threshold': 0.25,
    'market_profile_max_levels': 8,
    'market_profile_min_level_distance_points': 4.0,
    'market_profile_filter': 'off',  # off | room | reversion | breakout | reversion_room | breakout_room | context
    'market_profile_filter_signal_types': [],
    'market_profile_min_room_to_opposite_points': 8.0,
    'market_profile_near_level_tolerance_points': 5.0,
    'market_profile_context_requires_room': True,
    'market_profile_target_enabled': False,
    'market_profile_target_min_distance_points': 4.0,
    'market_profile_target_max_distance_points': 40.0,
    'market_profile_cross_min_level_count': 1,
    'market_profile_cross_min_opposite_room_points': 0.0,
    'market_profile_cross_direction_filter': 'off',  # off | vwap | trend_ema | both
}

# Repeatable research variants. These are candidate toggles, not conclusions:
# each one still needs normal backtest, walk-forward, and eventually permutation
# validation before it earns trust.
CANDIDATE_CONFIGS = {
    'current': {},
    'markov_regime_overlay': {
        'markov_regime_enabled': True,
        'markov_regime_filter': 'context',
        'markov_calibration_bars': 78,
        'markov_refit_every_bars': 12,
        'markov_allowed_states': {
            'mr': ['low_vol', 'mid_vol'],
            'trend': ['mid_vol', 'high_vol'],
            'mp': ['mid_vol', 'high_vol'],
        },
        'wf_param_grid': {
            'markov_calibration_bars': [60, 78, 96],
            'markov_refit_every_bars': [6, 12, 24],
            'markov_min_confidence': [0.0, 0.45, 0.55],
        },
        'sweep_specs': [
            {
                'name': 'markov_calibration_vs_confidence',
                'metric': 'bar_profit_factor',
                'min_trades': 40,
                'x_param': 'markov_calibration_bars',
                'x_values': [60, 78, 96],
                'y_param': 'markov_min_confidence',
                'y_values': [0.0, 0.45, 0.55],
            },
        ],
    },
    'markov_avoid_high_vol': {
        'markov_regime_enabled': True,
        'markov_regime_filter': 'avoid_high',
        'markov_calibration_bars': 78,
        'markov_refit_every_bars': 12,
    },
    'options_flow_context': {
        'options_flow_enabled': True,
        'options_flow_filter': 'context',
        'options_flow_min_abs_gex': 0.0,
    },
    'options_flow_wall_room': {
        'options_flow_enabled': True,
        'options_flow_filter': 'gex_wall_room',
        'options_flow_wall_room_points': 12.0,
    },
    'options_flow_gamma_environment': {
        'options_flow_enabled': True,
        'options_flow_filter': 'gamma_environment',
        'options_flow_wall_room_points': 12.0,
        'options_flow_amplifier_trigger_points': 12.0,
        'options_flow_require_negative_gamma_amplifier': True,
    },
    'vwap_time_of_day_probe': {
        # Paper-inspired hypothesis only: test whether VWAP-side continuation
        # weakens during the midday execution lull before treating it as a rule.
        'blocked_setup_hours': {
            'mr': [12, 13, 14],
            'trend': [12, 13, 14],
            'mp': [12, 13, 14],
        },
    },
    'market_memory_context_probe': {
        'market_memory_enabled': True,
        'market_memory_filter': 'context',
        'market_memory_recompute_every_bars': 6,
        'market_memory_context_avoid_fragile': True,
        'wf_param_grid': {
            'market_memory_hurst_low_threshold': [0.42, 0.45, 0.48],
            'market_memory_hurst_high_threshold': [0.52, 0.55, 0.58],
            'market_memory_entropy_high_threshold': [0.80, 0.85, 0.90],
        },
        'sweep_specs': [
            {
                'name': 'memory_hurst_context',
                'metric': 'bar_profit_factor',
                'min_trades': 40,
                'x_param': 'market_memory_hurst_low_threshold',
                'x_values': [0.42, 0.45, 0.48],
                'y_param': 'market_memory_hurst_high_threshold',
                'y_values': [0.52, 0.55, 0.58],
            },
        ],
    },
    'market_memory_avoid_fragile': {
        'market_memory_enabled': True,
        'market_memory_filter': 'avoid_fragile',
        'market_memory_recompute_every_bars': 6,
    },
    'mr_long_only': {
        'allow_long': True,
        'allow_short': False,
        'mr_long_enabled': True,
        'mr_short_enabled': False,
        'trend_long_enabled': False,
        'trend_short_enabled': False,
    },
    'long_only': {
        'allow_long': True,
        'allow_short': False,
        'mr_long_enabled': True,
        'mr_short_enabled': False,
        'trend_long_enabled': True,
        'trend_short_enabled': False,
    },
    'no_short_11_13': {
        'blocked_setup_hours': {
            'short': [11, 13],
        },
    },
    'setup_hour_whitelist_experimental': {
        'allowed_setup_hours': {
            'mr_long': [11],
            'trend_long': [11, 12, 13],
            'trend_short': [10, 14],
        },
    },
    'higher_frequency_probe': {
        'max_trades_per_day': 5,
        'regime_trend_confirm_bars': 1,
        'regime_range_confirm_bars': 1,
        'mr_trade_end': '12:30',
        'trend_trade_start': '10:15',
        'vp_mr_min_poc_room_points': 1.0,
        'trend_pullback_buffer_points': 3.0,
    },
    'structure_swing_filter': {
        'market_structure_enabled': True,
        'market_structure_filter': 'swing',
        'market_structure_filter_level': 1,
    },
    'structure_reversal_filter': {
        'market_structure_enabled': True,
        'market_structure_filter': 'reversal',
        'market_structure_filter_level': 0,
        'market_structure_max_bars_since_extreme': 8,
    },
    'structure_room_filter': {
        'market_structure_enabled': True,
        'market_structure_filter': 'room',
        'market_structure_filter_level': 1,
        'market_structure_min_room_to_opposite_points': 10.0,
    },
    'structure_stop_probe': {
        'market_structure_enabled': True,
        'market_structure_stop_enabled': True,
        'market_structure_stop_level': 0,
        'market_structure_stop_buffer_points': 1.0,
        'market_structure_stop_max_atr_multiple': 1.25,
    },
    'higher_frequency_structure_probe': {
        'max_trades_per_day': 5,
        'regime_trend_confirm_bars': 1,
        'regime_range_confirm_bars': 1,
        'mr_trade_end': '12:30',
        'trend_trade_start': '10:15',
        'vp_mr_min_poc_room_points': 1.0,
        'trend_pullback_buffer_points': 3.0,
        'market_structure_enabled': True,
        'market_structure_filter': 'swing_room',
        'market_structure_filter_level': 0,
        'market_structure_min_room_to_opposite_points': 6.0,
    },
    'market_profile_room_filter': {
        'market_profile_enabled': True,
        'market_profile_filter': 'room',
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
        'market_profile_min_room_to_opposite_points': 8.0,
    },
    'market_profile_reversion_filter': {
        'market_profile_enabled': True,
        'market_profile_filter': 'reversion',
        'market_profile_filter_signal_types': ['mr'],
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
        'market_profile_near_level_tolerance_points': 6.0,
    },
    'market_profile_breakout_filter': {
        'market_profile_enabled': True,
        'market_profile_filter': 'breakout',
        'market_profile_filter_signal_types': ['trend'],
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
    },
    'market_profile_context_probe': {
        'market_profile_enabled': True,
        'market_profile_filter': 'context',
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
        'market_profile_min_room_to_opposite_points': 6.0,
        'market_profile_near_level_tolerance_points': 6.0,
    },
    'market_profile_target_probe': {
        'market_profile_enabled': True,
        'market_profile_target_enabled': True,
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
        'market_profile_target_min_distance_points': 6.0,
        'market_profile_target_max_distance_points': 35.0,
    },
    'market_profile_cross_signal_probe': {
        'strategy_name': 'market_profile_cross',
        'market_profile_enabled': True,
        'market_profile_filter': 'off',
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 6,
        'market_profile_prominence_threshold': 0.20,
        'market_profile_max_levels': 10,
        'market_profile_min_level_distance_points': 3.0,
        'market_profile_cross_min_level_count': 1,
        'market_profile_cross_min_opposite_room_points': 4.0,
        'market_profile_cross_direction_filter': 'off',
        'mp_trade_start': '10:00',
        'mp_trade_end': '14:30',
        'mp_atr_stop_multiplier': 0.85,
        'mp_atr_target_multiplier': 1.8,
        'mp_max_loss_per_trade_dollars': 180,
        'mp_trail_trigger_dollars': 160,
        'mp_trail_distance_points': 3.0,
        'max_trades_per_day': 5,
        'wf_param_grid': {
            'mp_trade_start': ['10:00', '10:30', '11:00'],
            'market_profile_cross_min_opposite_room_points': [0.0, 2.0, 4.0, 6.0],
            'mp_atr_target_multiplier': [1.4, 1.8, 2.2],
            'mp_trail_trigger_dollars': [120, 160, 200],
        },
        'sweep_specs': [
            {
                'name': 'mp_start_vs_room',
                'metric': 'bar_profit_factor',
                'min_trades': 50,
                'x_param': 'mp_trade_start',
                'x_values': ['10:00', '10:30', '11:00'],
                'y_param': 'market_profile_cross_min_opposite_room_points',
                'y_values': [0.0, 2.0, 4.0, 6.0],
            },
            {
                'name': 'mp_target_vs_trail_trigger',
                'metric': 'profit_factor',
                'min_trades': 50,
                'x_param': 'mp_atr_target_multiplier',
                'x_values': [1.4, 1.8, 2.2],
                'y_param': 'mp_trail_trigger_dollars',
                'y_values': [120, 160, 200],
            },
        ],
    },
    'hybrid_profile_regime_no_orb': {
        'strategy_name': 'hybrid_profile_regime_no_orb',
        'market_profile_enabled': True,
        'market_profile_filter': 'off',
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 6,
        'market_profile_prominence_threshold': 0.20,
        'market_profile_max_levels': 10,
        'market_profile_min_level_distance_points': 3.0,
        'market_profile_cross_min_level_count': 1,
        'market_profile_cross_min_opposite_room_points': 4.0,
        'hybrid_profile_min_room_to_opposite_points': 4.0,
        'hybrid_profile_near_level_tolerance_points': 6.0,
        'hybrid_mr_require_profile_context': True,
        'hybrid_trend_require_profile_context': True,
        'hybrid_mp_transition_enabled': True,
        'hybrid_mp_direction_filter': 'vwap',
        'profile_regime_eval_start': '10:05',
        'profile_regime_trend_confirm_bars': 2,
        'profile_regime_range_confirm_bars': 2,
        'profile_regime_trend_min_range_multiple': 1.60,
        'profile_regime_range_max_range_multiple': 1.45,
        'profile_regime_trend_min_extension_factor': 0.55,
        'profile_regime_trend_min_extension_points': 5.0,
        'profile_regime_range_max_extension_factor': 0.45,
        'profile_regime_range_max_extension_points': 7.0,
        'profile_regime_trend_min_vwap_distance_points': 3.0,
        'profile_regime_range_max_vwap_distance_points': 7.0,
        'profile_regime_range_value_area_buffer_points': 1.5,
        'profile_regime_range_max_slope': 0.25,
        'profile_regime_trend_min_slope': 0.18,
        'mr_trade_start': '10:15',
        'mr_trade_end': '12:30',
        'vp_mr_min_poc_room_points': 1.5,
        'mr_excess_buffer_points': 2.0,
        'mr_reclaim_buffer_points': 0.75,
        'mr_value_extension_points': 1.0,
        'mr_atr_stop_multiplier': 0.95,
        'mr_atr_target_multiplier': 1.7,
        'mr_max_loss_per_trade_dollars': 180,
        'mr_trail_trigger_dollars': 140,
        'mr_trail_distance_points': 2.5,
        'trend_trade_start': '10:15',
        'trend_trade_end': '13:55',
        'vp_trend_acceptance_buffer_points': 0.75,
        'trend_pullback_buffer_points': 3.0,
        'trend_reclaim_buffer_points': 0.25,
        'trend_atr_stop_multiplier': 0.85,
        'trend_atr_target_multiplier': 2.2,
        'trend_max_loss_per_trade_dollars': 180,
        'trend_trail_trigger_dollars': 180,
        'trend_trail_distance_points': 3.0,
        'mp_trade_start': '10:00',
        'mp_trade_end': '13:55',
        'mp_atr_stop_multiplier': 0.85,
        'mp_atr_target_multiplier': 1.8,
        'mp_max_loss_per_trade_dollars': 180,
        'mp_trail_trigger_dollars': 160,
        'mp_trail_distance_points': 3.0,
        'max_trades_per_day': 5,
        'blocked_setup_hours': {'mp': [14], 'trend': [14]},
        'mr_target_reference': 'vp_poc',
        'wf_param_grid': {
            'profile_regime_trend_min_range_multiple': [1.4, 1.6, 1.8],
            'hybrid_profile_min_room_to_opposite_points': [2.0, 4.0, 6.0],
            'vp_mr_min_poc_room_points': [1.0, 1.5, 2.0],
            'mp_atr_target_multiplier': [1.4, 1.8, 2.2],
        },
        'sweep_specs': [
            {
                'name': 'hybrid_regime_vs_room',
                'metric': 'bar_profit_factor',
                'min_trades': 50,
                'x_param': 'profile_regime_trend_min_range_multiple',
                'x_values': [1.4, 1.6, 1.8],
                'y_param': 'hybrid_profile_min_room_to_opposite_points',
                'y_values': [2.0, 4.0, 6.0],
            },
            {
                'name': 'hybrid_mr_room_vs_mp_target',
                'metric': 'profit_factor',
                'min_trades': 50,
                'x_param': 'vp_mr_min_poc_room_points',
                'x_values': [1.0, 1.5, 2.0],
                'y_param': 'mp_atr_target_multiplier',
                'y_values': [1.4, 1.8, 2.2],
            },
        ],
    },
    'higher_frequency_market_profile_probe': {
        'max_trades_per_day': 5,
        'regime_trend_confirm_bars': 1,
        'regime_range_confirm_bars': 1,
        'mr_trade_end': '12:30',
        'trend_trade_start': '10:15',
        'vp_mr_min_poc_room_points': 1.0,
        'trend_pullback_buffer_points': 3.0,
        'market_profile_enabled': True,
        'market_profile_filter': 'room',
        'market_profile_lookback_bars': 390,
        'market_profile_recompute_every_bars': 12,
        'market_profile_min_room_to_opposite_points': 6.0,
    },
}

# ---------------------------------------------------------------------------
# Helper for composing edge candidates with shared entry-context guards.
#
# make_candidate(builds on a base candidate and/or extra overrides, with
# optional deep-merged blocked/allowed entry context blocks.
# ---------------------------------------------------------------------------

def merge_entry_context(*contexts):
    """Deep-merge multiple blocked_entry_context (or allowed_entry_context) dicts.

    Example:
        merged = merge_entry_context(
            {'trend': {'vwap_cross_direction': ['cross_up']}},
            {'trend_long': {'cusum_event_direction': [-1]}},
        )
        # -> {'trend': {'vwap_cross_direction': ['cross_up']},
        #     'trend_long': {'cusum_event_direction': [-1]}}
    """
    merged: dict[str, dict] = {}
    for ctx in contexts:
        if ctx is None:
            continue
        for signal_type, filters in ctx.items():
            if signal_type in merged:
                merged[signal_type] = {**merged[signal_type], **filters}
            else:
                merged[signal_type] = dict(filters)
    return merged


def make_candidate(*, base=None, entry_context=None, **overrides):
    """Build an edge candidate config dict.

    Parameters
    ----------
    base : dict or None
        A base candidate dict to inherit from (e.g. CANDIDATE_CONFIGS[...]).
    entry_context : dict or None
        A ``blocked_entry_context`` (or ``allowed_entry_context``) block that
        will be deep-merged with any existing context in *base*.
    **overrides :
        Additional key-value overrides applied last (shallow).

    Returns
    -------
    dict
        A candidate config dict suitable for inclusion in EDGE_CANDIDATE_CONFIGS.
    """
    result = dict(base) if base is not None else {}
    if entry_context is not None:
        existing = result.get('blocked_entry_context', {})
        result['blocked_entry_context'] = merge_entry_context(existing, entry_context)
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# Shared entry-context guard blocks
#
# These define the reusable veto patterns used across the edge candidates.
# Defining them once instead of repeating 200 lines of identical dicts.
# ---------------------------------------------------------------------------

_BLOCKED_VWAP_CROSS = {
    'trend': {'vwap_cross_direction': ['cross_up', 'cross_down']},
}

_BLOCKED_CUSUM_LONG_SHORT = {
    'trend_long': {'cusum_event_direction': [-1]},
    'trend_short': {'cusum_event_direction': [1]},
}

_BLOCKED_GAP_BELOW_LOW = {
    'trend_long': {'open_context': ['gap_below_prior_low']},
}

# Named guard compositions
_GUARD_VWAP_CROSS = _BLOCKED_VWAP_CROSS
_GUARD_VWAP_CROSS_CUSUM = merge_entry_context(_BLOCKED_VWAP_CROSS, _BLOCKED_CUSUM_LONG_SHORT)
_GUARD_VWAP_GAP = merge_entry_context(_BLOCKED_VWAP_CROSS, _BLOCKED_GAP_BELOW_LOW)
_GUARD_FULL_GAP_CUSUM = merge_entry_context(
    _BLOCKED_VWAP_CROSS, _BLOCKED_GAP_BELOW_LOW, _BLOCKED_CUSUM_LONG_SHORT,
)

# ---------------------------------------------------------------------------
# Shared 2021+ throttle parameters used by multiple edge candidates
# ---------------------------------------------------------------------------

_2021_THROTTLE_PARAMS = {
    'max_trades_per_day': 12,
    'regime_trend_confirm_bars': 1,
    'regime_range_confirm_bars': 1,
    'regime_trend_min_range_multiple': 1.20,
    'regime_range_max_range_multiple': 2.20,
    'regime_trend_min_extension_factor': 0.20,
    'regime_trend_min_extension_points': 1.5,
    'regime_trend_min_vwap_distance_points': 0.75,
    'regime_range_max_vwap_distance_points': 12.0,
    'trend_min_range_multiple': 1.20,
    'mr_balance_max_range_multiple': 2.20,
    'mr_excess_buffer_points': 1.0,
    'mr_reclaim_buffer_points': 0.25,
    'mr_value_extension_points': 0.25,
    'mr_close_strength_min': 0.52,
    'mr_close_strength_max': 0.48,
    'mr_trade_start': '09:45',
    'mr_trade_end': '15:00',
    'trend_trade_start': '09:45',
    'trend_trade_end': '15:30',
    'vp_mr_min_poc_room_points': 0.0,
    'trend_pullback_buffer_points': 6.0,
    'trend_reclaim_buffer_points': 0.75,
    'trend_close_strength_min': 0.45,
    'trend_close_strength_max': 0.55,
}

_2021_TREND_THROTTLE_PARAMS = {
    **_2021_THROTTLE_PARAMS,
    'max_trades_per_day': 12,
    'regime_trend_confirm_bars': 1,
    'regime_range_confirm_bars': 1,
    'trend_min_range_multiple': 1.15,
    'trend_trade_start': '09:45',
    'trend_trade_end': '15:30',
    'trend_pullback_buffer_points': 7.0,
    'trend_close_strength_min': 0.45,
    'trend_close_strength_max': 0.55,
    'regime_trend_min_range_multiple': 1.15,
    'regime_trend_min_extension_factor': 0.15,
    'regime_trend_min_extension_points': 1.0,
    'regime_trend_min_vwap_distance_points': 0.50,
    'vp_mr_min_poc_room_points': 0.0,
    'mr_trade_start': '09:45',
    'mr_trade_end': '15:00',
}

# ---------------------------------------------------------------------------
# Edge candidates — composed from shared blocks above
# ---------------------------------------------------------------------------

EDGE_CANDIDATE_CONFIGS = {
    # === VWAP-cross guard variants (base findings) ===
    'edge_vp_no_trend_vwap_cross': make_candidate(
        entry_context=_GUARD_VWAP_CROSS,
    ),
    'edge_vp_no_trend_vwap_cross_cusum_guard': make_candidate(
        entry_context=_GUARD_VWAP_CROSS_CUSUM,
    ),
    'edge_vp_no_trend_vwap_cross_delay_1': make_candidate(
        entry_context=_GUARD_VWAP_CROSS,
        entry_delay_bars=1,
    ),
    'edge_vp_no_trend_vwap_cross_delay_2': make_candidate(
        entry_context=_GUARD_VWAP_CROSS,
        entry_delay_bars=2,
    ),

    # === Higher-frequency VWAP-cross guard variants ===
    'edge_vp_no_trend_vwap_cross_high_freq': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_VWAP_CROSS,
    ),
    'edge_vp_no_trend_vwap_cross_high_freq_gap_guard': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_VWAP_GAP,
    ),
    'edge_vp_no_trend_vwap_cross_high_freq_gap_cusum_guard': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
    ),

    # === Higher-frequency with MR-long removed ===
    'edge_vp_hf_gap_cusum_no_mr_long': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        mr_long_enabled=False,
    ),
    'edge_vp_hf_quality_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        mr_long_enabled=False,
        max_trades_per_day=8,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        trend_min_range_multiple=1.55,
    ),
    'edge_vp_hf_gap_cusum_delay_1': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        entry_delay_bars=1,
    ),
    'edge_vp_hf_gap_cusum_no_mr_long_delay_1': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        entry_delay_bars=1,
        mr_long_enabled=False,
    ),

    # === Trend-only isolation ===
    'edge_vp_hf_gap_cusum_trend_only': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        mr_long_enabled=False,
        mr_short_enabled=False,
        allowed_setup_tags=['trend_long', 'trend_short'],
    ),
    'edge_vp_hf_gap_cusum_trend_long_only': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_BLOCKED_VWAP_CROSS, _BLOCKED_GAP_BELOW_LOW, {
            'trend_long': {'cusum_event_direction': [-1]},
        }),
        allow_long=True,
        allow_short=False,
        mr_long_enabled=False,
        trend_long_enabled=True,
        allowed_setup_tags=['trend_long'],
    ),

    # === Regime-switcher probes: optimized trend core + rebuilt MR side ===
    'edge_vp_mr_trend_vwap_reclaim_quality_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'mr': {'open_context': ['gap_below_prior_low']},
        }),
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=8,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        trend_min_range_multiple=1.55,
        mr_trade_start='10:15',
        mr_trade_end='12:30',
        mr_require_vwap_reclaim=True,
        vp_mr_min_poc_room_points=1.0,
    ),
    'edge_vp_mr_trend_vwap_reclaim_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'mr': {'open_context': ['gap_below_prior_low']},
        }),
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=10,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        regime_range_max_range_multiple=1.85,
        regime_range_max_vwap_distance_points=8.0,
        trend_min_range_multiple=1.55,
        mr_balance_max_range_multiple=1.85,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        vp_mr_min_poc_room_points=0.5,
        mr_excess_buffer_points=1.5,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
        mr_require_vwap_reclaim=True,
    ),
    'edge_vp_mr_trend_threshold_sweep': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'mr': {'open_context': ['gap_below_prior_low']},
        }),
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=10,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        regime_range_max_range_multiple=1.85,
        regime_range_max_vwap_distance_points=8.0,
        trend_min_range_multiple=1.55,
        mr_balance_max_range_multiple=1.85,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        vp_mr_min_poc_room_points=0.5,
        mr_excess_buffer_points=1.5,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
        mr_require_vwap_reclaim=True,
        sweep_specs=[
            {
                'name': 'mr_excess_vs_poc_room',
                'metric': 'profit_factor',
                'min_trades': 30,
                'x_param': 'vp_mr_min_poc_room_points',
                'x_values': [0.5, 1.5, 2.5, 3.5],
                'y_param': 'mr_excess_buffer_points',
                'y_values': [1.5, 2.0, 2.5, 3.0],
            },
            {
                'name': 'trend_pullback_vs_range_multiple',
                'metric': 'profit_factor',
                'min_trades': 30,
                'x_param': 'trend_pullback_buffer_points',
                'x_values': [2.5, 3.0, 3.5, 4.0],
                'y_param': 'regime_trend_min_range_multiple',
                'y_values': [1.45, 1.55, 1.70, 1.85],
            },
        ],
    ),
    'edge_vp_mr_trend_failed_auction_quality_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'mr': {'open_context': ['gap_below_prior_low']},
        }),
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=8,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        trend_min_range_multiple=1.55,
        mr_signal_mode='failed_auction_acceptance',
        mr_sweep_lookback_bars=3,
        mr_acceptance_bars=2,
        mr_trade_start='10:15',
        mr_trade_end='12:30',
        vp_mr_min_poc_room_points=1.0,
        mr_excess_buffer_points=1.5,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
    ),
    'edge_vp_mr_trend_failed_auction_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'mr': {'open_context': ['gap_below_prior_low']},
        }),
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=10,
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        regime_trend_min_range_multiple=1.55,
        regime_trend_min_extension_factor=0.35,
        regime_trend_min_extension_points=4.0,
        regime_trend_min_vwap_distance_points=3.0,
        regime_range_max_range_multiple=1.85,
        regime_range_max_vwap_distance_points=8.0,
        trend_min_range_multiple=1.55,
        mr_balance_max_range_multiple=1.85,
        mr_signal_mode='failed_auction_acceptance',
        mr_sweep_lookback_bars=3,
        mr_acceptance_bars=1,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        vp_mr_min_poc_room_points=0.5,
        mr_excess_buffer_points=1.25,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
    ),

    # === MR rebuild probes ===
    'edge_vp_mr_vwap_reclaim_quality_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context={'mr': {'open_context': ['gap_below_prior_low']}},
        allowed_setup_tags=['mr_long', 'mr_short'],
        trend_long_enabled=False,
        trend_short_enabled=False,
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=6,
        mr_trade_start='10:15',
        mr_trade_end='12:30',
        mr_require_vwap_reclaim=True,
        vp_mr_min_poc_room_points=1.0,
    ),
    'edge_vp_mr_vwap_reclaim_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context={'mr': {'open_context': ['gap_below_prior_low']}},
        allowed_setup_tags=['mr_long', 'mr_short'],
        trend_long_enabled=False,
        trend_short_enabled=False,
        mr_long_enabled=True,
        mr_short_enabled=True,
        max_trades_per_day=8,
        regime_range_confirm_bars=1,
        regime_range_max_range_multiple=1.85,
        regime_range_max_vwap_distance_points=8.0,
        mr_balance_max_range_multiple=1.85,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        vp_mr_min_poc_room_points=0.5,
        mr_excess_buffer_points=1.5,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
        mr_require_vwap_reclaim=True,
    ),
    'edge_vp_mr_short_vwap_reclaim_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context={'mr': {'open_context': ['gap_below_prior_low']}},
        allowed_setup_tags=['mr_short'],
        trend_long_enabled=False,
        trend_short_enabled=False,
        mr_long_enabled=False,
        mr_short_enabled=True,
        max_trades_per_day=8,
        regime_range_confirm_bars=1,
        regime_range_max_range_multiple=1.85,
        regime_range_max_vwap_distance_points=8.0,
        mr_balance_max_range_multiple=1.85,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        vp_mr_min_poc_room_points=0.5,
        mr_excess_buffer_points=1.5,
        mr_reclaim_buffer_points=0.50,
        mr_value_extension_points=0.75,
        mr_short_require_vwap_reclaim=True,
    ),

    # === Scalp frequency probes ===
    'edge_vp_scalp_frequency_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_VWAP_GAP,
        max_trades_per_day=8,
        regime_trend_min_range_multiple=1.45,
        regime_range_max_range_multiple=1.75,
        regime_trend_min_extension_factor=0.30,
        regime_trend_min_extension_points=3.0,
        regime_trend_min_vwap_distance_points=2.0,
        regime_range_max_vwap_distance_points=8.0,
        trend_min_range_multiple=1.45,
        mr_balance_max_range_multiple=1.75,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        vp_mr_min_poc_room_points=0.5,
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
    ),
    'edge_vp_scalp_frequency_gap_cusum_no_mr_long': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        max_trades_per_day=8,
        regime_trend_min_range_multiple=1.45,
        regime_range_max_range_multiple=1.75,
        regime_trend_min_extension_factor=0.30,
        regime_trend_min_extension_points=3.0,
        regime_trend_min_vwap_distance_points=2.0,
        regime_range_max_vwap_distance_points=8.0,
        trend_min_range_multiple=1.45,
        mr_balance_max_range_multiple=1.75,
        mr_trade_start='10:00',
        mr_trade_end='13:30',
        trend_trade_start='10:00',
        trend_trade_end='15:00',
        vp_mr_min_poc_room_points=0.5,
        trend_pullback_buffer_points=4.0,
        trend_reclaim_buffer_points=0.50,
        mr_long_enabled=False,
    ),

    # === 2021+ frequency throttle ===
    'edge_vp_2021_frequency_open_throttle': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        **_2021_THROTTLE_PARAMS,
        mr_long_enabled=False,
    ),
    'edge_vp_2021_frequency_trend_throttle': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        **_2021_TREND_THROTTLE_PARAMS,
        mr_long_enabled=False,
        mr_short_enabled=False,
        allowed_setup_tags=['trend_long', 'trend_short'],
    ),
    'edge_vp_2021_frequency_clean_throttle': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=merge_entry_context(_GUARD_FULL_GAP_CUSUM, {
            'trend': {'open_context': ['gap_below_prior_low']},
        }),
        **_2021_TREND_THROTTLE_PARAMS,
        entry_delay_bars=1,
        mr_long_enabled=False,
        mr_short_enabled=False,
        allowed_setup_tags=['trend_long', 'trend_short'],
        blocked_setup_hours={
            'trend_short': [10],
            'trend_long': [11],
            'trend': [18],
        },
    ),
    'edge_vp_2021_frequency_no_gap_guard': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_VWAP_CROSS_CUSUM,
        **_2021_THROTTLE_PARAMS,
        mr_long_enabled=False,
    ),
    'edge_vp_2021_frequency_open_throttle_delay_1': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        entry_context=_GUARD_FULL_GAP_CUSUM,
        **_2021_THROTTLE_PARAMS,
        entry_delay_bars=1,
        mr_long_enabled=False,
    ),

    # === Historical MP cross refinements ===
    'edge_vp_trend_short_entry_confirmed': {
        # Refined from the 2026-05-08 volume-profile run:
        # keep only short trend continuation when the actual entry bar confirms
        # below-VWAP pressure, has escaped the initial balance, and is not a
        # bullish CUSUM reversal event.
        'allow_long': False,
        'allow_short': True,
        'mr_long_enabled': False,
        'mr_short_enabled': False,
        'trend_long_enabled': False,
        'trend_short_enabled': True,
        'allowed_setup_tags': ['trend_short'],
        'allowed_entry_context': {
            'trend_short': {
                'vwap_side': ['below_vwap'],
                'inside_ib': [False],
                'cusum_event_direction': [-1, 0],
            },
        },
    },
    'edge_mp_cross_no_hour14': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'blocked_setup_hours': {'mp': [14]},
    },
    'edge_mp_cross_all_be_100': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'mp_breakeven_trigger_dollars': 100,
        'mp_breakeven_offset_points': 1.0,
        'mp_breakeven_min_hold_bars': 1,
    },
    'edge_mp_cross_all_trail_100': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'mp_trail_trigger_dollars': 100,
        'mp_trail_distance_points': 3.0,
    },
    'edge_mp_cross_no_hour14_be_100': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'blocked_setup_hours': {'mp': [14]},
        'mp_breakeven_trigger_dollars': 100,
        'mp_breakeven_offset_points': 1.0,
        'mp_breakeven_min_hold_bars': 1,
    },
    'edge_mp_short_11_13': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'allow_long': False,
        'allow_short': True,
        'allowed_setup_hours': {'mp_short': [11, 12, 13]},
        'wf_param_grid': {
            'mp_trade_start': ['10:30', '11:00', '11:30'],
            'market_profile_cross_min_opposite_room_points': [2.0, 4.0, 6.0],
            'mp_atr_target_multiplier': [1.4, 1.8, 2.2],
            'mp_trail_trigger_dollars': [120, 160, 200],
        },
        'sweep_specs': [
            {
                'name': 'mp_short_start_vs_room',
                'metric': 'bar_profit_factor',
                'min_trades': 50,
                'x_param': 'mp_trade_start',
                'x_values': ['10:30', '11:00', '11:30'],
                'y_param': 'market_profile_cross_min_opposite_room_points',
                'y_values': [2.0, 4.0, 6.0],
            },
            {
                'name': 'mp_short_target_vs_trail_trigger',
                'metric': 'profit_factor',
                'min_trades': 50,
                'x_param': 'mp_atr_target_multiplier',
                'x_values': [1.4, 1.8, 2.2],
                'y_param': 'mp_trail_trigger_dollars',
                'y_values': [100, 120, 160],
            },
        ],
    },
    'edge_mp_short_10_13': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'allow_long': False,
        'allow_short': True,
        'allowed_setup_hours': {'mp_short': [10, 11, 12, 13]},
        'wf_param_grid': {
            'mp_trade_start': ['10:00', '10:30', '11:00'],
            'market_profile_cross_min_opposite_room_points': [2.0, 4.0, 6.0],
            'mp_atr_target_multiplier': [1.4, 1.8, 2.2],
            'mp_trail_trigger_dollars': [120, 160, 200],
        },
    },
    'edge_mp_short_11_13_be_100': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'allow_long': False,
        'allow_short': True,
        'allowed_setup_hours': {'mp_short': [11, 12, 13]},
        'mp_short_breakeven_trigger_dollars': 100,
        'mp_short_breakeven_offset_points': 1.0,
        'mp_short_breakeven_min_hold_bars': 1,
    },
    'edge_mp_short_11_13_be_160': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'allow_long': False,
        'allow_short': True,
        'allowed_setup_hours': {'mp_short': [11, 12, 13]},
        'mp_short_breakeven_trigger_dollars': 160,
        'mp_short_breakeven_offset_points': 1.0,
        'mp_short_breakeven_min_hold_bars': 1,
    },
    'edge_mp_short_11_13_trail_100': {
        **CANDIDATE_CONFIGS['market_profile_cross_signal_probe'],
        'allow_long': False,
        'allow_short': True,
        'allowed_setup_hours': {'mp_short': [11, 12, 13]},
        'mp_short_trail_trigger_dollars': 100,
        'mp_short_trail_distance_points': 3.0,
    },
    'edge_target_long_only': {
        **CANDIDATE_CONFIGS['market_profile_target_probe'],
        'allow_long': True,
        'allow_short': False,
        'mr_long_enabled': True,
        'mr_short_enabled': False,
        'trend_long_enabled': True,
        'trend_short_enabled': False,
    },
    'edge_target_long_10_12': {
        **CANDIDATE_CONFIGS['market_profile_target_probe'],
        'allow_long': True,
        'allow_short': False,
        'mr_long_enabled': True,
        'mr_short_enabled': False,
        'trend_long_enabled': True,
        'trend_short_enabled': False,
        'allowed_setup_hours': {'long': [10, 11, 12]},
    },
    'edge_target_long_10_12_be_100': {
        **CANDIDATE_CONFIGS['market_profile_target_probe'],
        'allow_long': True,
        'allow_short': False,
        'mr_long_enabled': True,
        'mr_short_enabled': False,
        'trend_long_enabled': True,
        'trend_short_enabled': False,
        'allowed_setup_hours': {'long': [10, 11, 12]},
        'long_breakeven_trigger_dollars': 100,
        'long_breakeven_offset_points': 1.0,
        'long_breakeven_min_hold_bars': 1,
    },
    'edge_room_trend_long': {
        **CANDIDATE_CONFIGS['market_profile_room_filter'],
        'allow_long': True,
        'allow_short': False,
        'allowed_setup_tags': ['trend_long'],
    },
    'edge_higher_freq_trend_long': {
        **CANDIDATE_CONFIGS['higher_frequency_market_profile_probe'],
        'allow_long': True,
        'allow_short': False,
        'allowed_setup_tags': ['trend_long'],
    },
}
CANDIDATE_CONFIGS.update(EDGE_CANDIDATE_CONFIGS)


# === Prop-firm optimisation candidates ===
#
# These are intentionally layered after EDGE_CANDIDATE_CONFIGS so they can use
# the latest failed-auction quality/frequency probes as explicit bases.
PROP_FIRM_OPTIMIZATION_CANDIDATES = {
    'edge_vp_mr_trend_failed_auction_quality_no_mr_long': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        mr_long_enabled=False,
    ),
    'edge_vp_mr_trend_failed_auction_quality_no_mr_long_target_through_1t': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        mr_long_enabled=False,
        target_fill_mode='trade_through',
        target_fill_trade_through_ticks=1,
    ),
    'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_guard': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        # Saved-run hypothesis: inside-IB entries were weak unless the entry
        # bar had an active CUSUM displacement event.  Use direction keys so
        # this remains an independent blocked clause instead of being merged
        # into existing trend/setup-specific guards.
        entry_context={
            'long': {'inside_ib': [True], 'cusum_event': [False]},
            'short': {'inside_ib': [True], 'cusum_event': [False]},
        },
        mr_long_enabled=False,
        target_fill_mode='trade_through',
        target_fill_trade_through_ticks=1,
    ),
    'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        # Freeze candidate: same IB/CUSUM guard, plus the parameter set selected
        # independently by both walk-forward folds of the guard run.
        entry_context={
            'long': {'inside_ib': [True], 'cusum_event': [False]},
            'short': {'inside_ib': [True], 'cusum_event': [False]},
        },
        mr_long_enabled=False,
        target_fill_mode='trade_through',
        target_fill_trade_through_ticks=1,
        mr_trade_end='12:00',
        mr_trail_trigger_dollars=140,
        trend_trade_start='10:30',
        trend_pullback_buffer_points=3.5,
    ),
    'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        entry_context={
            'trend': {'open_context': ['gap_below_prior_low']},
        },
        mr_long_enabled=False,
    ),
    'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long_delay_1': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        entry_context={
            'trend': {'open_context': ['gap_below_prior_low']},
        },
        mr_long_enabled=False,
        entry_delay_bars=1,
    ),
    'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long_memory_guard': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_probe'],
        entry_context={
            'trend': {'open_context': ['gap_below_prior_low']},
        },
        mr_long_enabled=False,
        market_memory_filter='map',
        market_memory_blocked_states={
            'trend_long': ['chaotic_memory'],
        },
    ),
    'edge_vp_mr_trend_failed_auction_frequency_vwap_guard': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_frequency_probe'],
        entry_context={
            'trend': {'open_context': ['gap_below_prior_low']},
        },
        mr_long_enabled=False,
        mr_short_require_vwap_reclaim=True,
    ),
    'edge_vp_mr_trend_failed_auction_frequency_aggressive_payout': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_frequency_probe'],
        entry_context={
            'trend': {'open_context': ['gap_below_prior_low']},
        },
        max_trades_per_day=14,
        trend_trade_start='09:45',
        trend_trade_end='15:30',
        trend_pullback_buffer_points=3.0,
        trend_reclaim_buffer_points=0.25,
        regime_trend_min_range_multiple=1.45,
        regime_trend_min_extension_factor=0.30,
        regime_trend_min_extension_points=3.0,
        regime_trend_min_vwap_distance_points=2.0,
        regime_range_max_range_multiple=2.00,
        regime_range_max_vwap_distance_points=10.0,
        trend_min_range_multiple=1.45,
        mr_balance_max_range_multiple=2.00,
        mr_trade_start='09:45',
        mr_trade_end='14:30',
        vp_mr_min_poc_room_points=0.25,
        mr_excess_buffer_points=1.00,
        mr_reclaim_buffer_points=0.25,
        mr_long_enabled=False,
        mr_short_enabled=True,
        mr_short_require_vwap_reclaim=True,
    ),
}
CANDIDATE_CONFIGS.update(PROP_FIRM_OPTIMIZATION_CANDIDATES)

# === High-frequency observation candidates ===
#
# These are not validation or funded candidates.  They intentionally trade more
# often so exploratory runs can accumulate observations faster, while keeping
# size fixed and fill assumptions conservative enough for diagnosis.
HIGH_FREQUENCY_OBSERVATION_CANDIDATES = {
    'edge_vp_mr_trend_failed_auction_hf_observation_probe': make_candidate(
        base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_frequency_probe'],
        blocked_entry_context=_GUARD_VWAP_CROSS_CUSUM,
        position_sizing_mode='fixed_contracts',
        fixed_contracts=1,
        max_contracts=1,
        max_trades_per_day=20,
        max_hold_bars=4,
        target_fill_mode='trade_through',
        target_fill_trade_through_ticks=1,
        managed_stop_activation_mode='next_bar',
        regime_trend_confirm_bars=1,
        regime_range_confirm_bars=1,
        regime_trend_min_range_multiple=1.15,
        regime_range_max_range_multiple=2.25,
        regime_trend_min_extension_factor=0.15,
        regime_trend_min_extension_points=1.0,
        regime_trend_min_vwap_distance_points=0.50,
        regime_range_max_vwap_distance_points=12.0,
        trend_min_range_multiple=1.15,
        mr_balance_max_range_multiple=2.25,
        mr_signal_mode='failed_auction_acceptance',
        mr_sweep_lookback_bars=3,
        mr_acceptance_bars=1,
        mr_trade_start='09:40',
        mr_trade_end='15:30',
        vp_mr_min_poc_room_points=0.0,
        mr_excess_buffer_points=0.75,
        mr_reclaim_buffer_points=0.25,
        mr_value_extension_points=0.25,
        mr_close_strength_min=0.50,
        mr_close_strength_max=0.50,
        mr_atr_stop_multiplier=0.75,
        mr_atr_target_multiplier=1.0,
        mr_trail_trigger_dollars=80,
        mr_trail_distance_points=2.0,
        trend_trade_start='09:40',
        trend_trade_end='15:45',
        trend_pullback_buffer_points=7.0,
        trend_reclaim_buffer_points=0.50,
        trend_close_strength_min=0.45,
        trend_close_strength_max=0.55,
        trend_atr_stop_multiplier=0.75,
        trend_atr_target_multiplier=1.0,
        trend_trail_trigger_dollars=100,
        trend_trail_distance_points=2.5,
        allow_long=True,
        allow_short=True,
        mr_long_enabled=True,
        mr_short_enabled=True,
        trend_long_enabled=True,
        trend_short_enabled=True,
    ),
}
CANDIDATE_CONFIGS.update(HIGH_FREQUENCY_OBSERVATION_CANDIDATES)
CANDIDATE_CONFIGS[
    'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable_managed_stop_next_bar'
] = make_candidate(
    base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable'],
    managed_stop_activation_mode='next_bar',
)

CANDIDATE_CONFIGS[
    'edge_vp_mr_trend_failed_auction_quality_rebuilt_mr_long'
] = make_candidate(
    base=CANDIDATE_CONFIGS['edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable_managed_stop_next_bar'],
    mr_long_enabled=True,
    mr_trade_end='11:45',
    trend_trade_start='10:15',
    blocked_entry_context={
        'trend': {'vwap_cross_direction': ['cross_up', 'cross_down']},
        'trend_long': {'open_context': ['gap_below_prior_low'], 'cusum_event_direction': [-1]},
        'trend_short': {'cusum_event_direction': [1]},
        'mr_short': {'open_context': ['gap_below_prior_low']},
        'mr_long': {'mr_long_blocked': [True]},
        'long': {'inside_ib': [True], 'cusum_event': [False]},
        'short': {'inside_ib': [True], 'cusum_event': [False]},
    },
)


# === Execution-first microstructure candidates ===
#
# This family starts from an ex-ante hypothesis document, not from the rejected
# failed-auction sample.  Keep it deliberately narrow: one fixed parameter point,
# conservative target fills, next-bar managed stops, and fixed one-contract size.
MICROSTRUCTURE_EXECUTION_FIRST_CANDIDATES = {
    'edge_microstructure_liquidity_taking_trend_probe': make_candidate(
        base=CANDIDATE_CONFIGS['higher_frequency_probe'],
        allowed_setup_tags=['trend_long', 'trend_short'],
        allow_long=True,
        allow_short=True,
        mr_long_enabled=False,
        mr_short_enabled=False,
        trend_long_enabled=True,
        trend_short_enabled=True,
        position_sizing_mode='fixed_contracts',
        fixed_contracts=1,
        max_contracts=1,
        max_trades_per_day=5,
        max_hold_bars=6,
        trend_trade_start='10:15',
        trend_trade_end='15:00',
        target_fill_mode='trade_through',
        target_fill_trade_through_ticks=1,
        managed_stop_activation_mode='next_bar',
        wf_param_grid={
            'trend_trade_start': ['10:15'],
            'trend_pullback_buffer_points': [3.0],
            'max_hold_bars': [6],
        },
        wf_random_samples=1,
        wf_selection_mode='stable',
        sweep_specs=[
            {
                'name': 'fixed_microstructure_probe',
                'metric': 'bar_profit_factor',
                'min_trades': 30,
                'x_param': 'trend_pullback_buffer_points',
                'x_values': [3.0],
                'y_param': 'max_hold_bars',
                'y_values': [6],
            },
        ],
    ),
}
CANDIDATE_CONFIGS.update(MICROSTRUCTURE_EXECUTION_FIRST_CANDIDATES)


# Optional: walk-forward + parameter sweep tooling
RESEARCH_CONFIG = {
    'enable_monte_carlo': True,
    'monte_carlo_n_sims': 2000,
    'monte_carlo_bootstrap_modes': ['trade', 'day', 'week', 'month'],
    'monte_carlo_paths_shown': 200,
    'enable_advanced_monte_carlo': True,
    'advanced_monte_carlo_n_sims': 2000,
    'advanced_monte_carlo_regime_col': 'entry_day_regime',
    'advanced_monte_carlo_transition_smoothing': 1.0,
    'advanced_monte_carlo_student_t_df': 5.0,
    'advanced_monte_carlo_path_horizons': [40, 100, 250, 500, 1000],
    'advanced_monte_carlo_drawdown_barriers_pct': [5, 10, 15, 20, 25],
    'advanced_monte_carlo_profit_target_pct': 8.0,
    'advanced_monte_carlo_drawdown_limit_pct': 5.0,
    'enable_trade_stress_tests': True,
    'enable_execution_delay_stress_tests': True,
    'execution_delay_stress_bars': [0, 1, 2, 3],
    'enable_cusum_event_study': True,
    'cusum_event_study_horizons_bars': [1, 3, 6, 12, 24],
    'cusum_event_frequency_thresholds': [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
    'cusum_event_random_baseline_samples': 200,
    'enable_feature_research_lab': True,
    'feature_research_horizons_bars': [1, 3, 6, 12, 24],
    'feature_research_target_atr_multiple': 1.0,
    'feature_research_stop_atr_multiple': 1.0,
    'feature_research_max_hold_bars': 24,
    'feature_research_bootstrap_samples': 300,
    'feature_research_min_events': 30,
    'enable_conditional_distribution_reports': True,
    'conditional_distribution_min_trades': 30,
    'conditional_distribution_min_periods': 3,
    'conditional_distribution_period': 'Q',
    'conditional_distribution_bootstrap_samples': 300,
    'conditional_distribution_random_seed': 7,
    'conditional_distribution_max_groups_per_set': 80,
    # Multiple-testing debt guard. Once a family has too many saved runs, new
    # variants are treated as contaminated until an untouched holdout/paper
    # sample supplies the next evidence.
    'max_candidate_family_runs_before_holdout': 4,
    'enable_vwap_repricing_report': True,
    'vwap_repricing_period': 'Q',
    'vwap_repricing_midday_start': '12:00',
    'vwap_repricing_midday_end': '15:00',
    'enable_market_memory_report': True,
    'market_memory_report_period': 'Q',
    'market_memory_report_forward_horizon_bars': 3,
    'market_memory_report_recent_fraction': 0.25,
    'market_memory_report_drift_warning_threshold': 0.75,
    'enable_prop_firm_report': True,
    'prop_firm_n_sims': 5000,
    'enable_prop_firm_surfaces': True,
    'prop_firm_surface_n_sims': 1000,
    'prop_firm_seed': 17,
    'prop_firm_profiles': [
        {
            'name': 'traders_launch_100k_nyc',
            'account_size': 100_000,
            'eval_cost': 42,
            'activation_fee': 0,
            'reset_fee': 0,
            'max_resets_per_account': 0,
            'monthly_fee': 0,
            'account_bundle_cost': 0,
            'max_accounts': 20,
            'profit_target': 2_000,
            'max_drawdown': 1_000,
            'daily_loss_limit': 0,
            'min_trading_days': 3,
            'initial_max_trading_days': 60,
            'extension_trading_days': 30,
            'extension_threshold_pct_of_target': 50,
            'drawdown_mode': 'eod_trailing',
            'drawdown_check': 'eod',
            'trailing_drawdown_cap_at_initial': True,
            'consistency_profit_limit_pct': 40,
            # Current backtests are NQ-mini denominated; Traders Launch starts
            # this plan at 5 MNQ micros, equivalent to 0.5 NQ.
            'pnl_multiplier': 0.5,
            'profit_split_pct': 80,
            'funded_buffer_target': 1_000,
            'minimum_payout': 200,
            'payout_cap': 0,
            'payout_cap_period': 'none',
            'payout_cadence_days': 0,
            'funded_horizon_days': 60,
            'trading_objective': 'prop_eval_flip',
            'fill_model': 'prop_demo_fill_assumption',
            'minimum_trade_sample': 500,
            'portfolio_account_counts': [1, 5, 10, 20],
            'portfolio_n_sims': 20_000,
            'surface_n_sims': 1000,
            'sizing_multipliers': [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
            'daily_loss_stops': [0, 250, 400, 500, 750],
            'daily_profit_locks': [0, 250, 500, 750, 1000],
            'risk_geometry_reward_risk': [0.33, 0.5, 1.0, 2.0, 3.0, 4.0],
            'risk_geometry_drawdown_risk_fracs': [0.10, 0.20, 0.30, 0.40, 0.50],
            'risk_geometry_trades_per_day': 1,
            'stop_after_target_until_min_days': True,
        },
        {
            'name': 'generic_static_50k_no_consistency_prop_flip',
            'account_size': 50_000,
            'eval_cost': 35,
            'activation_fee': 85,
            'reset_fee': 25,
            'max_resets_per_account': 0,
            'monthly_fee': 0,
            'account_bundle_cost': 0,
            'max_accounts': 20,
            'profit_target': 3_000,
            'max_drawdown': 2_500,
            'daily_loss_limit': 0,
            'min_trading_days': 1,
            'max_trading_days': 30,
            'drawdown_mode': 'static',
            'drawdown_check': 'eod',
            'trailing_drawdown_cap_at_initial': False,
            'consistency_profit_limit_pct': 0,
            'pnl_multiplier': 1.0,
            'profit_split_pct': 90,
            'funded_buffer_target': 2_500,
            'minimum_payout': 500,
            'payout_cap': 0,
            'payout_cap_period': 'none',
            'payout_cadence_days': 0,
            'funded_horizon_days': 60,
            'trading_objective': 'prop_eval_flip',
            'fill_model': 'prop_demo_fill_assumption',
            'minimum_trade_sample': 500,
            'portfolio_account_counts': [1, 5, 10, 20],
            'portfolio_n_sims': 20_000,
            'surface_n_sims': 1000,
            'sizing_multipliers': [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
            'daily_loss_stops': [0, 500, 750, 1000],
            'daily_profit_locks': [0, 500, 1000, 1500],
            'risk_geometry_reward_risk': [0.33, 0.5, 1.0, 2.0, 3.0, 4.0],
            'risk_geometry_drawdown_risk_fracs': [0.10, 0.20, 0.30, 0.40, 0.50],
            'risk_geometry_trades_per_day': 1,
            'stop_after_target_until_min_days': False,
        },
    ],
    # Permutation tests from the strategy-development workflow:
    # - in-sample: can the optimizer beat randomized price paths?
    # - walk-forward: can stitched OOS beat randomized future paths?
    # These multiply runtime heavily, so keep disabled for normal backtests and
    # turn on for dedicated validation runs. Raise n toward 1000 for final use.
    'enable_permutation_tests': False,
    'permutation_enable_in_sample': True,
    'permutation_enable_walk_forward': True,
    'permutation_metric': 'bar_profit_factor',
    'permutation_in_sample_n': 100,
    'permutation_walk_forward_n': 25,
    'permutation_min_trades_total': 30,

    # Walk-forward (train->select params->OOS trade) across the full dataset
    'enable_walk_forward': True,
    'skip_permutation_on_failed_walk_forward': True,
    'skip_sweeps_on_failed_walk_forward': True,
    'wf_train_years': 3,
    'wf_test_months': 6,
    'wf_step_months': 12,
    'wf_window_mode': 'rolling',  # rolling | anchored
    'wf_purge_bars': 'auto',  # auto = max_hold_bars + entry_delay_bars + 1
    'wf_embargo_bars': 1,  # extra completed bars between train labels and OOS test
    'wf_metric': 'bar_profit_factor',  # sharpe | profit_factor | bar_profit_factor | bar_sharpe | expectancy | total_pnl
    'wf_selection_mode': 'stable',  # best | stable
    'wf_min_trades_train': 40,
    'wf_min_trades_test': 5,
    'wf_random_samples': 8,
    'wf_param_grid': {
        'mr_trade_end': ['11:30', '11:45', '12:00', '12:15'],
        'mr_trail_trigger_dollars': [120, 140, 160, 180],
        'trend_trade_start': ['10:30', '11:00', '11:30', '12:00'],
        'trend_pullback_buffer_points': [2.0, 2.5, 3.0, 3.5],
    },
    # Active queue is intentionally empty until a fresh pre-candidate signal
    # report shows raw predictive evidence worth freezing into a candidate.
    'next_validation_candidates': [],
    'rejected_research_families': {
        'failed_auction_quality': {
            'status': 'rejected',
            'decision_date': '2026-05-20',
            'rejected_after_run': (
                '20260520_152332_'
                'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable_managed_stop_next_bar_'
                'long_short_next_bar_open_hybrid'
            ),
            'reason': (
                'Strict managed-stop variant failed before walk-forward: 157 trades, '
                'profit factor 0.85, net PnL -2757.99, daily Sharpe -1.30, '
                'all traded setups negative, and in-sample prop expected value negative.'
            ),
            'allow_new_variants': False,
            'revival_requirements': [
                'new ex-ante hypothesis not derived from the failed-auction sample',
                'untouched holdout or paper evidence',
                'survives execution realism plus purged/embargoed walk-forward validation',
            ],
        },
        'microstructure_execution_first': {
            'status': 'rejected',
            'decision_date': '2026-05-20',
            'rejected_after_run': (
                '20260520_190728_'
                'edge_microstructure_liquidity_taking_trend_probe_long_short_next_bar_open_hybrid'
            ),
            'reason': (
                'Stopped development run showed no prop-firm viability: 0.0% eval pass, '
                '0.0% eval-to-first-payout, 99.34% extension-threshold failures, '
                'trade profit factor 1.05, median trade -92.50, and random-walk/sign-flip '
                'p-values around 0.34. The long side was negative and the short side was '
                'not strong enough to justify mining a same-sample variant.'
            ),
            'allow_new_variants': False,
            'revival_requirements': [
                'new written ex-ante hypothesis not derived from the stopped development run',
                'pre-candidate signal report with positive IC or forward-return evidence',
                'separate validation sample before any prop-firm interpretation',
            ],
        },
    },
    # Disk cleanup should not erase multiple-testing debt. These are
    # conservative known-run floors for families already explored in this repo.
    'candidate_family_run_count_floors': {
        'failed_auction_quality': 10,
        'failed_auction_frequency': 3,
        'high_frequency_observation': 1,
        'microstructure_execution_first': 1,
    },
    'candidate_research_families': {
        'failed_auction_quality': [
            'edge_vp_mr_trend_failed_auction_quality_probe',
            'edge_vp_mr_trend_failed_auction_quality_no_mr_long',
            'edge_vp_mr_trend_failed_auction_quality_no_mr_long_target_through_1t',
            'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_guard',
            'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable',
            'edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable_managed_stop_next_bar',
            'edge_vp_mr_trend_failed_auction_quality_rebuilt_mr_long',
            'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long',
            'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long_delay_1',
            'edge_vp_mr_trend_failed_auction_quality_gap_guard_no_mr_long_memory_guard',
        ],
        'failed_auction_frequency': [
            'edge_vp_mr_trend_failed_auction_frequency_probe',
            'edge_vp_mr_trend_failed_auction_frequency_vwap_guard',
            'edge_vp_mr_trend_failed_auction_frequency_aggressive_payout',
        ],
        'high_frequency_observation': [
            'edge_vp_mr_trend_failed_auction_hf_observation_probe',
        ],
        'microstructure_execution_first': [
            'edge_microstructure_liquidity_taking_trend_probe',
        ],
    },

    # 2D parameter sweep (heatmap)
    'enable_param_sweep': True,
    'sweep_metric': 'profit_factor',
    'sweep_min_trades': 30,
    'sweep_x_param': 'mr_trail_trigger_dollars',
    'sweep_x_values': [120, 140, 160, 180],
    'sweep_y_param': 'mr_trade_end',
    'sweep_y_values': ['11:30', '11:45', '12:00', '12:15'],
    'sweep_specs': [
        {
            'name': 'mr_trail_trigger_vs_mr_end',
            'metric': 'profit_factor',
            'min_trades': 30,
            'x_param': 'mr_trail_trigger_dollars',
            'x_values': [120, 140, 160, 180],
            'y_param': 'mr_trade_end',
            'y_values': ['11:30', '11:45', '12:00', '12:15'],
        },
        {
            'name': 'trend_start_vs_pullback_buffer',
            'metric': 'profit_factor',
            'min_trades': 30,
            'x_param': 'trend_trade_start',
            'x_values': ['10:30', '11:00', '11:30', '12:00'],
            'y_param': 'trend_pullback_buffer_points',
            'y_values': [2.0, 2.5, 3.0, 3.5],
        },
        {
            'name': 'regime_range_vs_trend_multiple',
            'metric': 'profit_factor',
            'min_trades': 30,
            'x_param': 'regime_range_max_range_multiple',
            'x_values': [1.30, 1.45, 1.55, 1.65],
            'y_param': 'regime_trend_min_range_multiple',
            'y_values': [1.55, 1.70, 1.85, 2.00],
        },
    ],

    # Animated research exports. These are GIFs by default because the project
    # dependency set includes Pillow but not ffmpeg.
    'enable_research_animations': True,
    'research_animation_frames': 48,
    'research_animation_fps': 12,
    'research_animation_dpi': 110,
}

VALIDATION_CONFIG = {
    'min_in_sample_profit_factor': 1.10,
    'min_in_sample_bar_profit_factor': 1.05,
    'min_walk_forward_profit_factor': 1.05,
    'min_walk_forward_bar_profit_factor': 1.00,
    'min_walk_forward_total_pnl': 0.0,
    'min_walk_forward_neighbor_metric_ratio': 0.75,
    'min_trades_per_year': 20.0,
    'max_suspicious_win_rate_pct': 75.0,
    'max_suspicious_profit_factor': 3.0,
    'max_suspicious_sharpe_ratio': 3.0,
    'max_in_sample_permutation_p': 0.01,
    'max_walk_forward_permutation_p': 0.05,
    'min_combined_mild_profit_factor': 1.05,
    'min_combined_mild_total_pnl': 0.0,
    'research_discipline_require_permutation': True,
    'research_discipline_require_bar_exposure_audit': True,
    'research_discipline_require_execution_realism': True,
    'max_in_sample_to_walk_forward_profit_factor_ratio': 2.5,
    'min_execution_realism_profit_factor': 1.0,
}
