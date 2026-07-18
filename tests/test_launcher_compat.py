"""Backward compatibility of the ``bean_network_tester.py`` launcher facade.

Older docs, repro commands and user scripts import this module directly, so
it must keep re-exporting the whole public API of the ``beantester`` package.
"""
import bean_network_tester as legacy
from fakes import check

EXPECTED_API = [
    "BeanCore", "BeanEngine", "Decision", "SyntheticDivert",
    "T", "translate", "set_language", "current_language", "available_languages",
    "load_languages", "detect_language", "event_kind_label",
    "DEFAULT_SETTINGS", "parse_schedule", "apply_settings",
    "load_config_file", "save_config_file",
    "Scenario", "load_scenario_file",
    "settings_summary", "settings_to_cli", "settings_to_cli_string",
    "build_repro_report", "save_repro_report",
    "PRESETS", "resolve_preset", "FILTERS", "CLI_FILTERS",
    "find_process_ports", "clamp01", "bytes_to_mb", "nice_ceiling", "is_local_ip",
    "sort_events", "filter_sort_connections",
    "build_arg_parser", "config_from_args", "apply_config", "run_cli", "main",
    "APP_NAME",
]


def test_launcher_reexports_public_api():
    missing = [name for name in EXPECTED_API if not hasattr(legacy, name)]
    check("launcher re-exports the whole public API", not missing, f"({missing})")


def test_launcher_app_name():
    check("application name = Bean Network Tester",
          legacy.APP_NAME == "Bean Network Tester", f"({legacy.APP_NAME})")
