# LogosGo V1.0.0 — Private macOS Release

LogosGo V1.0.0 is the first self-contained private macOS release of the LogosGo Go review assistant.

## Highlights

- Import and navigate SGF game records.
- Run whole-game KataGo analysis with progress and dynamic ETA.
- View evidence-grounded and directional commentary with correct black/white perspective handling.
- Review selected important/decisive moves and a structured whole-game summary.
- Open reliable KataGo recommendation variations directly in the existing trial mode.
- Continue playing temporary trial moves without changing the original SGF.
- Request foreground position judgment, score/win-rate estimates, captures, and ownership visualization while whole-game analysis runs.
- Launch one self-contained `LogosGo.app` with bundled backend, Python runtime, KataGo Metal runtime, model, configuration, and production corpus.

## Supported system

- Apple Silicon Mac
- macOS 26.0 or later

## Important limitations

- This is a private ad-hoc-signed build. It is not Developer ID signed or notarized, so macOS may require explicit approval to open it.
- Intel Macs and macOS versions earlier than 26.0 are not supported.
- Commentary intentionally abstains or uses conservative language when the available evidence cannot support a detailed Go-principle claim.
- No Windows release is included.
- Public distribution, installer/DMG, automatic updates, and App Store delivery are outside V1.0.0 scope.

See the repository `README.md` for usage instructions and `packaging/macos/README.md` for the reproducible private-build pipeline.
