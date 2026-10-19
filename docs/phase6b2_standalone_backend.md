# Phase 6B-2 — Standalone Python Backend Bundle

日期：2026-10-13  
Repository：`~/Desktop/go_project`  
範圍：Apple Silicon macOS standalone Python backend component；不是最終 LogosGo.app。

## 1. Files changed

- `.gitignore`
  - 忽略 `packaging/macos/build/` 與 `packaging/macos/dist/` generated outputs。
- `packaging/macos/backend.spec`
  - committed PyInstaller onedir build graph。
- `packaging/macos/build_backend.sh`
  - deterministic clean-build entry point。
- `packaging/macos/requirements-backend.txt`
  - pinned production runtime dependency inventory。
- `packaging/macos/requirements-build.txt`
  - pinned build-only dependency inventory。
- `packaging/macos/README.md`
  - build/startup reproduction instructions。
- `test_backend_packaging.py`
  - focused build-configuration tests。
- `docs/phase6b2_standalone_backend.md`
  - 本報告。

本 Phase 沒有修改 `server.py`、runtime path/startup production code、Flutter、`analysis.cfg`、model、corpus、KataGo 或 macOS entitlements。既有 dirty working tree 完整保留，未使用 reset/restore/checkout/clean/stash。

## 2. PyInstaller strategy

採用 **PyInstaller onedir**，未改成 onefile。理由：

- 啟動時不需要把完整 Python runtime 解壓到 temporary directory。
- embedded Python、native extensions 與 load commands 可直接檢查。
- 更容易在 Phase 6B-4 放入 `.app/Contents/Helpers` 並由 Runner 管理。
- native library/codesign 問題比 onefile 容易定位。

Bundle 只包含 Python backend component。Model、config、corpus 與 KataGo 保持外部，由既有 `--resource-root` / `--katago-executable` 注入。

## 3. Build environment

- Hardware：Apple M4 / Apple Silicon
- OS：macOS 26.5.2（Build 25F84）
- Build architecture：arm64
- Python：3.14.2 arm64
- PyInstaller：6.22.3
- pyinstaller-hooks-contrib：2026.8
- altgraph：0.17.5
- macholib：1.16.4
- packaging：25.0
- setuptools：84.0.0

PyInstaller 安裝在 development venv 只作為 build dependency。Target runtime 不需此 venv 或系統 Python。

## 4. Runtime dependency inventory

Production direct dependencies：

- Flask 3.1.3
- sgfmill 1.1.1
- pandas 2.3.3

Pinned runtime closure：

- Werkzeug 3.1.6
- Jinja2 3.1.6
- MarkupSafe 3.0.3
- itsdangerous 2.2.0
- click 8.3.1
- blinker 1.9.0
- NumPy 2.3.5
- python-dateutil 2.9.0.post0
- pytz 2025.2
- tzdata 2025.3
- six 1.17.0

Development/test/legacy dependencies（例如 unittest tooling、Matplotlib、Pillow、flask-cors）不是 production dependency，沒有因為存在於 development venv 就作為功能打包。

## 5. Build configuration

`backend.spec`：

- entry point：`server.py`
- `pathex`：repository root，僅 build-time module discovery
- 明列 production local modules：startup/runtime paths、analysis、LogosEngine、SGF utilities、structured/directional explanation、feature/classifier、review selection/summary
- assets/data：空；不內嵌 model/config/corpus/KataGo
- exclusions：flask-cors、Matplotlib、Pillow、pytest、tkinter
- target：console onedir、arm64、no UPX、no Developer ID signing

`build_backend.sh` 每次只刪除其自身 ignored `build/`/`dist/`，然後使用 `--clean --noconfirm` 重建。成功 build 是在清除第一次受 sandbox cache permission 中斷的半成品後重新從零完成，因此 clean rebuild 已驗證。

Reproduction：

```bash
python3.14 -m venv /private/tmp/logosgo-packaging-venv
/private/tmp/logosgo-packaging-venv/bin/python -m pip install \
  -r packaging/macos/requirements-backend.txt \
  -r packaging/macos/requirements-build.txt
PYTHON_EXECUTABLE=/private/tmp/logosgo-packaging-venv/bin/python \
  packaging/macos/build_backend.sh
```

## 6. Output layout

```text
packaging/macos/dist/logosgo-backend/
├── logosgo-backend
└── _internal/
    ├── Python.framework/
    ├── base_library.zip
    ├── pandas/
    ├── numpy/
    ├── python3.14/
    └── bundled Python native libraries/metadata
```

整個 `logosgo-backend/` 目錄是一個 onedir component，不能只複製主 executable。Generated `build/`/`dist/` 均被 `.gitignore` 排除；它們不是 source input。

## 7. Backend bundle size

- Onedir total：60,692 KiB（`du` 顯示約 59 MiB）
- `_internal`：49,960 KiB
- Main executable：10,986,096 bytes（約 10.5 MiB）
- Files：778

主要內容：

- pandas：約 19 MiB
- NumPy：約 6.4 MiB
- Python.framework：約 5.2 MiB
- Python 3.14 dynload：約 6.4 MiB
- base library：約 1.3 MiB
- bundled libcrypto：約 4.6 MiB

沒有發現被誤包的 Matplotlib、Pillow、flask-cors 或 benchmark/test data。Setuptools hook 留下少量 runtime support/metadata，但不是明顯 size blocker；本 Phase 未做激進瘦身。

## 8. Architecture inspection

- Main executable：Mach-O 64-bit executable arm64
- `lipo -archs`：arm64
- Bundle Mach-O count：121
- x86_64-only components：0
- Main executable load commands：只直接連 `/usr/lib/libSystem.B.dylib` 與 `/usr/lib/libz.1.dylib`
- 全部 bundled Mach-O load commands 中 `/opt/homebrew` 或 `/Users/ouo1010` dependency：0
- Python.framework、NumPy/pandas extensions 與 bundled OpenSSL/lzma/zstd/sqlite 均為 arm64
- Main executable minimum macOS：11.0；SDK：26.1
- PyInstaller 產物目前只有 ad-hoc signature；Developer ID signing/notarization 不屬於本 Phase

Bundled Python framework 仍含 Homebrew build prefix 的純文字 configure metadata，但 `otool` 與 runtime open-file inspection 證明它不是 load/runtime dependency。

## 9. Frozen runtime path behavior

Frozen executable 沿用 Phase 6B-1 的同一套 CLI/startup architecture：

```text
logosgo-backend
  --port <port>
  --instance-token <token>
  --resource-root <root>
  --katago-executable <path>
```

Smoke test 使用 explicit root，因此不依賴 cwd、source location、`sys._MEIPASS` asset placement 或 PATH。`pyi-archive_viewer` 確認所有 project-local production modules 都位於 frozen PYZ archive。沒有建立第二套 PyInstaller-only startup/path logic。

第一次把新 onedir copy 放到 staging 後，macOS cold-load/verification 花費明顯較久；同一 staging bundle 的第二次 `/health` readiness 在整秒計時下小於 1 秒。這不影響 correctness，但 Phase 6B-4 readiness polling 不應假設固定極短 timeout。

## 10. Staging layout

測試在 repository 外建立：

```text
/private/tmp/logosgo-phase6b2-stage.<random>/
├── backend/
│   ├── logosgo-backend
│   └── _internal/
├── resources/
│   ├── model/model.bin.gz
│   ├── config/analysis.cfg
│   └── data/logosgo_corpus_full.csv
└── launch/
```

三個 resource copies 均以 `cmp` 確認與原始資產相同。KataGo 仍依 Phase 規定顯式使用目前 development executable，未複製或改寫。

## 11. Repository-isolation evidence

Standalone command 的 executable 為：

```text
/private/tmp/.../backend/logosgo-backend
```

證據：

- process command 沒有 `python` / `python3`
- cwd 是 `/private/tmp/.../launch`，不是 repository
- 使用 `env -i`，環境只有 HOME、TMPDIR、system-only PATH 與 LANG
- 無 `PYTHONPATH`、無 `VIRTUAL_ENV`
- runtime PATH 不含 `/opt/homebrew`
- `lsof` 在 health 與分析後均沒有開啟 repository `.py` 或 source path
- process 開啟的 Python/pandas/NumPy files 全來自 staging `backend/_internal`
- frozen archive 明列所有 project-local production modules

因此 backend 不需要 repository Python modules、development venv 或 Homebrew Python packages。

## 12. `/health` standalone result

Custom port：53124。Listener：只有 `127.0.0.1:53124`。

```json
{
  "api_schema_version": 1,
  "instance_id": "7e2a8a86d3c1f5d4e763e7de",
  "ready": true,
  "service": "LogosGoBackend",
  "token_verified": true
}
```

Health 後沒有 KataGo process，證明 frozen `/health` 仍不載入 model、不啟動 engine、不執行分析。

## 13. Minimal real analysis result

Input：1 手 19×19 SGF：

```text
(;GM[1]FF[4]SZ[19]KM[6.5];B[pd])
```

結果：

- status：completed
- completed/total moves：1/1
- position values：2（初始局面 + 第一手後）
- move analyses：1
- actual move：Q16
- best move：Q16
- structured explanation：present
- game review schema：1
- review summary schema：1
- timeout / malformed response / import error / crash：0
- KataGo model/config paths：staging resource root

分析由 PyInstaller executable 提供服務，並以現有 KataGo 完成；不是 `python server.py`。

## 14. Shutdown result

完成分析時 process tree 正確顯示：

```text
standalone logosgo-backend
└── katago analysis ... -model <staging model> -config <staging config>
```

正常 Ctrl-C 後：

- backend process：0
- KataGo child：0
- port 53124 listener：0

第二次 health-only timing test 也使用 TERM cleanup，沒有殘留 process。Native Runner watchdog/parent-death fallback 仍留給 Phase 6B-4。

## 15. Failure behavior

Standalone executable 實測：

| Case | Exit | Result |
|---|---:|---|
| missing resource root | 1 | 明確指出 root 不存在或不是目錄 |
| missing model | 1 | 列出已檢查的 model paths |
| missing config | 1 | 列出已檢查的 config paths |
| missing corpus | 1 | 列出已檢查的 corpus paths |
| missing/non-executable KataGo | 1 | 指出錯誤 executable path |
| invalid port | 2 | argparse usage + port range error |
| malformed/unknown arg | 2 | argparse usage + unrecognized argument |

上述錯誤沒有 obscure PyInstaller traceback。

## 16. Regression results

- Phase 6B-2 + 6B-1 focused tests：25 passed
  - 21 existing runtime/startup tests
  - 4 new packaging configuration tests
- Phase 1/2/4/5D/position scheduling relevant suite：199 passed
- Full Python suite：247 passed（baseline 243 + 4 new）
- `py_compile`（top-level Python + spec）：passed
- `bash -n packaging/macos/build_backend.sh`：passed
- `git diff --check`：passed
- Clean PyInstaller build：passed
- Frozen staging `/health`：passed
- Frozen minimal real analysis：passed

Flutter production source在本 Phase 是零修改，依指令不重跑 Flutter suite/analyze；Phase 6B-1 baseline 仍為 Flutter 56 passed、analyze 13 個既有 diagnostics。

Build warning review：sgfmill 在 Python 3.14 顯示其 docstring invalid-escape `SyntaxWarning`；PyInstaller static graph 也列出 Windows-only/optional imports。實際 frozen import、health 與完整最小分析均成功，未發現 production module omission。

## 17. Remaining KataGo portability issue

Python backend 已 standalone，但 Phase 6B-2 明確允許的 remaining issue 是 KataGo：

- smoke 使用 `/opt/homebrew/bin/katago` 的顯式 path
- resolved child 是 Homebrew Cellar KataGo 1.16.4 arm64
- KataGo 仍依賴 Homebrew `libzip.5.dylib`
- libzip 仍依賴 Homebrew `liblzma.5.dylib`、`libzstd.1.dylib`

這不代表 frozen Python backend 依賴 Homebrew Python；兩者是分離的 native portability layer。

## 18. Remaining Phase 6B-3 work

- 複製 KataGo arm64 executable 到最終 helper layout。
- Bundle libzip/liblzma/libzstd。
- Rewrite install names/rpaths 為 bundle-relative paths。
- 驗證所有 KataGo/native load commands 無 Homebrew dependency。
- 驗證 copied KataGo 可從 packaged resource/model/config layout 完成同等分析。
- 處理 KataGo/native component signing；不在本 Phase 執行。

## 19. Remaining Phase 6B-4 work

- Native Runner 選擇 free localhost port。
- 生成 per-launch token。
- 傳入 packaged resource root、KataGo executable 與 dynamic port。
- Poll `/health` 並驗證 service/token；cold first launch 需合理 timeout。
- 將 port/token 注入 Flutter `BackendEndpointConfig`。
- 管理 backend/KataGo process tree、normal shutdown、timeout、kill fallback 與 app close/crash。
- 依 Phase 6A 決策處理 sandbox/entitlements。
- 把 standalone backend component 放入最終 `.app`；本 Phase 沒有做。

## 20. Analytical behavior/settings confirmation

本 Phase 沒有修改任何 production analytical code或資產。Build/smoke 再次確認：

- whole-game：100 visits、16×4、PV length 8、ownership false
- position judgment：500 visits、1×16、ownership/stdev true
- BLACK canonical perspective 與 black/white conversion不變
- scheduling、foreground preemption、cancellation/resume不變
- analysis/result schema、observed loss/candidate gap semantics不變
- classifier、structured/directional commentary不變
- Review Selection、Review Summary不變
- trial/variation不變
- `analysis.cfg`、`model.bin.gz`、corpus內容不變

A. READY FOR PHASE 6B-3

The Python backend is standalone and reproducible. Remaining runtime
portability work is primarily KataGo/native assets.
