"""BeanNetworkTester - poor network conditions simulator for Windows.

A QA/developer tool for testing applications under a bad network: packet
loss / corruption / duplication, latency + jitter + spikes, per-direction
speed limits and schedules, link flapping, LAN mode, NAT expiry, RST
injection, process/destination targeting, seeded reproducibility, scenarios
and full reproduction reports. Runs on the WinDivert driver (``pydivert``,
requires Administrator); the engine itself is platform-independent and fully
covered by tests that need neither Windows nor WinDivert.

This package intentionally does NOT import the GUI at import time - the GUI
(tkinter) is loaded lazily by ``beantester.cli.main`` or via the
``bean_network_tester.py`` launcher, so the engine/CLI work on systems
without tkinter.
"""
from .appinfo import APP_NAME, AUTHOR, SUPPORT_URL, TOOL_ID, __version__
from . import clilog, driver, exitcodes, winenv
from .cli import (CliError, apply_config, build_arg_parser, config_from_args,
                  main, run_cli)
from .core import BeanCore, Decision
from .engine import BeanEngine
from .fields import FIELD_DEFS, FIELDS, SECTIONS, Field, Section
from .filters import (CLI_FILTERS, FILTER_DEFS, FILTERS, cli_key_for,
                      i18n_key_for, i18n_keys, windivert_for)
from .i18n import (FALLBACK_LANGUAGE, T, available_languages, current_language,
                   detect_language, event_kind_label, load_languages,
                   set_language, translate)
from .matchers import (KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS, Matcher,
                       parse_matcher, port_expression, split_terms,
                       validate_matcher)
from .paths import CONNECTIONS_CSV_FILE, CSV_FILE, PROFILE_FILE, resource_path
from .presets import (PRESETS, preset_to_settings, resolve_preset,
                      settings_to_preset)
from . import portmap
from .processes import (compile_target, find_process_ports, make_targeting,
                        parse_target, port_process_map)
from .targeting import ProcessTargeting
from .repro import (build_repro_report, save_repro_report, settings_to_cli,
                    settings_to_cli_string)
from .scenario import Scenario, load_scenario_file
from .scenario_runner import ScenarioRunner
from .settings import (DEFAULT_SETTINGS, MATCH_FIELDS, apply_settings,
                       apply_targeting, build_matchers, load_config_file,
                       non_profile_active, parse_schedule, save_config_file,
                       setting_expression, settings_from_raw, validate_ranges,
                       validate_settings)
from .summary import settings_summary
from .synthetic import SyntheticDivert
from .utils import (_num, bytes_to_mb, canonical_ip, clamp01, is_local_ip,
                    nice_ceiling, to_number)
from .validators import parse_number, parse_seed
from .views import filter_sort_connections, sort_events

__all__ = [
    "APP_NAME", "AUTHOR", "SUPPORT_URL", "TOOL_ID", "__version__",
    "BeanCore", "BeanEngine", "Decision", "SyntheticDivert",
    "T", "translate", "set_language", "current_language", "available_languages",
    "load_languages", "detect_language", "event_kind_label", "FALLBACK_LANGUAGE",
    "DEFAULT_SETTINGS", "parse_schedule", "apply_settings",
    "load_config_file", "save_config_file",
    "MATCH_FIELDS", "build_matchers", "validate_settings", "setting_expression",
    "apply_targeting", "settings_from_raw", "validate_ranges", "non_profile_active",
    "FIELD_DEFS", "FIELDS", "SECTIONS", "Field", "Section",
    "parse_number", "parse_seed",
    "Matcher", "parse_matcher", "validate_matcher", "port_expression",
    "split_terms", "KIND_INT", "KIND_IP", "KIND_PROCESS", "PORT_BOUNDS",
    "Scenario", "load_scenario_file", "ScenarioRunner",
    "settings_summary", "settings_to_cli", "settings_to_cli_string",
    "build_repro_report", "save_repro_report",
    "PRESETS", "resolve_preset", "preset_to_settings", "settings_to_preset",
    "FILTERS", "CLI_FILTERS", "FILTER_DEFS",
    "cli_key_for", "i18n_key_for", "i18n_keys", "windivert_for",
    "find_process_ports", "parse_target", "port_process_map",
    "compile_target", "make_targeting", "ProcessTargeting", "portmap",
    "clamp01", "to_number", "_num", "bytes_to_mb", "nice_ceiling", "is_local_ip",
    "canonical_ip",
    "sort_events", "filter_sort_connections",
    "build_arg_parser", "config_from_args", "apply_config", "run_cli", "main",
    "CliError", "exitcodes", "clilog", "driver", "winenv",
    "PROFILE_FILE", "CSV_FILE", "CONNECTIONS_CSV_FILE", "resource_path",
]
