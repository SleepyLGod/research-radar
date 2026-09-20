"""PyInstaller entrypoint for the foundation-only macOS engine."""

from research_radar.app_bridge.__main__ import main

raise SystemExit(main())
