from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from config import (
    END_DATE,
    START_DATE,
    get_live_ingest_config,
    validate_live_ingest_config,
)
from cli_app import run_interactive_cli, run_live_cli_via_websocket
from live_ws import default_start_end, run_websocket_live_server
from pipeline import build_and_serialize, build_live_snapshot, persist_live_hourly

ROOT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = ROOT_DIR / "storage"


def build_pipeline() -> None:
    artifacts = build_and_serialize(
        start_date=START_DATE,
        end_date=END_DATE,
        missing_threshold=0.05,
        root_dir=ROOT_DIR,
    )

    cleaning = artifacts.cleaning
    if cleaning.dropped_primaries:
        dropped = ", ".join(cleaning.dropped_primaries)
        repl = ", ".join([f"{a}->{b}" for a, b in cleaning.replacements])
        print(f"Zombie tickers dropped: {dropped}")
        print(f"Replacements applied: {repl}")

    p = artifacts.paths
    print(f"Saved current matrix to: {p['current_matrix']}")
    print(f"Saved backup matrix to: {p['backup_matrix']}")
    print(f"Saved scaler params to: {p['scaler_params']}")
    print(f"Saved matrix heatmap to: {p['matrix_heatmap']}")
    print(f"Saved accessible aligned returns (30xT) to: {p['returns_csv_latest']}")
    print(f"Saved accessible standardized matrix (30xT) to: {p['standardized_csv_latest']}")


def verify_storage() -> int:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    expected = [
        STORAGE_DIR / "current_matrix.pkl",
        STORAGE_DIR / "scaler_params.pkl",
    ]

    missing = [p for p in expected if not p.exists()]
    if missing:
        for p in missing:
            print(f"Missing: {p}")
        return 1

    print("storage/ looks OK.")
    for p in expected:
        print(f"Found: {p}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive CLI to build and explore aligned NIFTY+NASDAQ matrices."
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run full pipeline and serialize outputs to storage/ and outputs/.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify storage/ contains expected output files.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Launch menu-driven interactive CLI (default if no flags).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Launch live CLI fed by a local websocket server.",
    )
    parser.add_argument(
        "--serve-live",
        action="store_true",
        help="Run the local websocket live server (pushes updates every --interval seconds).",
    )
    parser.add_argument(
        "--ingest-live",
        action="store_true",
        help="Run websocket provider -> 1-minute OHLCV -> Redis streams pipeline.",
    )
    parser.add_argument(
        "--snapshot-live",
        action="store_true",
        help="Build one-shot rolling analytics snapshot from Redis hot stream.",
    )
    parser.add_argument(
        "--persist-live-hourly",
        action="store_true",
        help="Persist recent live Redis bars into partitioned Parquet files.",
    )
    parser.add_argument(
        "--bakeoff-live",
        action="store_true",
        help="Run provider bake-off scoring (Twelve Data vs Polygon).",
    )
    parser.add_argument(
        "--provider",
        choices=["twelvedata", "polygon"],
        default=None,
        help="Override live ingestion provider for --ingest-live.",
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=500,
        help="Lookback size for --snapshot-live (default: 500).",
    )
    parser.add_argument(
        "--z-window",
        type=int,
        default=60,
        help="Rolling z-score window for --snapshot-live (default: 60).",
    )
    parser.add_argument(
        "--pca-components",
        type=int,
        default=3,
        help="PCA components for --snapshot-live (default: 3).",
    )
    parser.add_argument(
        "--persist-hours",
        type=int,
        default=1,
        help="Number of recent hours to persist for --persist-live-hourly (default: 1).",
    )
    parser.add_argument(
        "--bakeoff-seconds",
        type=int,
        default=300,
        help="Duration per provider for --bakeoff-live (default: 300).",
    )
    parser.add_argument(
        "--ws-url",
        default="ws://127.0.0.1:8765",
        help="Websocket URL for --live mode.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for --serve-live websocket server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for --serve-live websocket server.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Live rebuild interval in seconds (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # Default UX: interactive menu
    if not any(
        [
            args.build,
            args.verify,
            args.interactive,
            args.live,
            args.serve_live,
            args.ingest_live,
            args.snapshot_live,
            args.persist_live_hourly,
            args.bakeoff_live,
        ]
    ):
        return run_interactive_cli(root_dir=ROOT_DIR)

    if args.build:
        build_pipeline()

    if args.verify:
        return verify_storage()

    if args.interactive:
        return run_interactive_cli(root_dir=ROOT_DIR)

    if args.snapshot_live:
        try:
            cfg = get_live_ingest_config(provider_override=args.provider)
            validate_live_ingest_config(cfg, require_provider_keys=False)

            artifacts = build_live_snapshot(
                live_cfg=cfg,
                root_dir=ROOT_DIR,
                lookback_minutes=args.lookback_minutes,
                z_window=args.z_window,
                pca_components=args.pca_components,
            )

            print("Built live snapshot from Redis stream.")
            print(f"Close matrix shape      : {artifacts.close_matrix.shape}")
            print(f"Log returns shape       : {artifacts.log_returns.shape}")
            print(f"Rolling z-scores shape  : {artifacts.rolling_zscores.shape}")
            print(f"Latest z-score timestamp: {artifacts.latest_zscore.name}")
            print(f"Latest residual ts      : {artifacts.latest_residual_zscore.name}")
            print("Saved outputs:")
            for key, path in artifacts.paths.items():
                print(f"- {key}: {path}")
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for live snapshot. Install with:\n"
                "  py -m pip install redis\n"
                f"Details: {exc}"
            )
            return 3
        except ValueError as exc:
            print(f"Unable to build live snapshot: {exc}")
            return 2
        return 0

    if args.persist_live_hourly:
        try:
            cfg = get_live_ingest_config(provider_override=args.provider)
            validate_live_ingest_config(cfg, require_provider_keys=False)

            result = persist_live_hourly(
                live_cfg=cfg,
                root_dir=ROOT_DIR,
                hours=args.persist_hours,
            )

            print("Live Parquet janitor complete.")
            print(f"Rows scanned : {result.total_rows_scanned}")
            print(f"Rows written : {result.rows_written}")
            print(f"Rows deduped : {result.deduped_rows}")
            print("Files written:")
            if result.files_written:
                for path in result.files_written:
                    print(f"- {path}")
            else:
                print("- none")
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for live persistence. Install with:\n"
                "  py -m pip install redis pyarrow\n"
                f"Details: {exc}"
            )
            return 3
        except ValueError as exc:
            print(f"Unable to persist live data: {exc}")
            return 2
        return 0

    if args.bakeoff_live:
        try:
            import asyncio

            from live_ingest.bakeoff import run_bakeoff

            cfg = get_live_ingest_config(provider_override=None)
            validate_live_ingest_config(cfg, require_provider_keys=False)

            scores, report_path = asyncio.run(
                run_bakeoff(
                    cfg=cfg,
                    root_dir=ROOT_DIR,
                    seconds_per_provider=max(30, args.bakeoff_seconds),
                )
            )

            print("Provider bake-off complete.")
            for s in scores:
                print(
                    f"- {s.provider}: status={s.status} ticks={s.ticks_received} "
                    f"coverage={s.symbol_coverage_ratio:.2f} errors={s.errors}"
                )
            print(f"Saved report: {report_path}")
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for bake-off. Install with:\n"
                "  py -m pip install websockets\n"
                f"Details: {exc}"
            )
            return 3
        except ValueError as exc:
            print(f"Unable to run bake-off: {exc}")
            return 2
        except KeyboardInterrupt:
            return 0
        return 0

    if args.ingest_live:
        try:
            import asyncio

            from live_ingest.runner import run_live_ingest_forever

            cfg = get_live_ingest_config(provider_override=args.provider)
            if not cfg.enabled:
                print(
                    "Live ingest is feature-gated. Enable it first:\n"
                    "  set QM_ENABLE_LIVE_INGEST=1\n"
                    "Then run --ingest-live again."
                )
                return 2

            validate_live_ingest_config(cfg)
            asyncio.run(run_live_ingest_forever(cfg, root_dir=ROOT_DIR))
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for live ingestion. Install with:\n"
                "  py -m pip install websockets redis\n"
                f"Details: {exc}"
            )
            return 3
        except ValueError as exc:
            print(f"Invalid live ingest configuration: {exc}")
            return 2
        except KeyboardInterrupt:
            return 0
        return 0

    if args.serve_live:
        try:
            import asyncio

            s, e = default_start_end()
            asyncio.run(
                run_websocket_live_server(
                    host=args.host,
                    port=args.port,
                    root_dir=ROOT_DIR,
                    interval_seconds=args.interval,
                    start_date=s,
                    end_date=e,
                    missing_threshold=0.05,
                )
            )
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for live server. Install with:\n"
                "  py -m pip install websockets\n"
                f"Details: {exc}"
            )
            return 3
        except KeyboardInterrupt:
            return 0
        return 0

    if args.live:
        try:
            import asyncio

            asyncio.run(run_live_cli_via_websocket(ws_url=args.ws_url, root_dir=ROOT_DIR))
        except ModuleNotFoundError as exc:
            print(
                "Missing dependency for live mode. Install with:\n"
                "  py -m pip install websockets\n"
                f"Details: {exc}"
            )
            return 3
        except KeyboardInterrupt:
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

