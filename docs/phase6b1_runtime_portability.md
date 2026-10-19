# Phase 6B-1 — Runtime Portability Foundation

日期：2026-10-07  
範圍：runtime portability foundation；未進行 Python freezing、KataGo/dylib bundling、Native Runner process ownership 或正式 `.app` packaging。

## 1. Files changed

- `runtime_paths.py`：新增唯一的 runtime resource / writable path resolver。
- `backend_startup.py`：新增明確的 backend CLI/environment startup configuration 與 instance identity。
- `server.py`：改用 resolved resources、將 KataGo working directory 指向可寫 log 目錄、加入 `/health`，並改成 localhost-only、debug-off 啟動。
- `flutter_application_1/lib/main.dart`：新增集中式 `BackendEndpointConfig`，五個既有 API call site 不再各自硬編碼 URL。
- `test_runtime_paths.py`：新增 runtime path、packaged-layout、錯誤訊息、cwd independence 與 temp-SGF regression tests。
- `test_backend_startup.py`：新增 startup parsing、identity、health、CORS 與 KataGo side-effect tests。
- `flutter_application_1/test/widget_test.dart`：新增 development default、任意 port、token header 與既有 API path tests。
- `docs/phase6b1_runtime_portability.md`：本報告。

Working tree 內其他 Phase 1–6A 既有修改與未追蹤驗證檔均保留，未 reset、restore、checkout、clean 或 stash。

## 2. Runtime-path architecture

`runtime_paths.resolve_runtime_paths()` 是 backend resource lookup 的單一來源，回傳 immutable `RuntimePaths`：

- `resource_root`
- `katago_executable`
- `model_file`
- `config_file`
- `corpus_file`
- `writable`
- `mode`（`explicit` / `environment` / `packaged` / `development`）

`server.py` 只消費此結果，不再自行拼接 model/config/corpus/KataGo 路徑。resolver 不使用 process cwd 作為 resource truth。

## 3. Resource-root precedence

由高至低：

1. `--resource-root`
2. `LOGOSGO_RESOURCE_ROOT`
3. 由未來 `.app` executable 推導的 `Contents/Resources/LogosGo`
4. frozen runtime 的 `_MEIPASS/Resources/LogosGo`
5. 僅 development 使用的 `runtime_paths.py` 所在 source directory

顯式或 packaged root 缺失時會立即拋出含路徑與修正方式的 `RuntimePathError`，不會靜默退回 cwd/source tree。

## 4. Writable path architecture

`writable_paths()` 定義：

- persistent app data：`~/Library/Application Support/LogosGo`
- future cache：`~/Library/Caches/LogosGo`
- logs：`~/Library/Logs/LogosGo`
- temporary：系統 temp directory 下的 `LogosGo`

目前只在真正啟動 KataGo 時建立 logs directory。沒有為本 Phase 發明 cache，也不會在 import 或 `/health` 時建立未使用的目錄。KataGo subprocess 的 cwd 改為 logs directory，因此 `analysis.cfg` 的相對 `analysis_logs` 不再寫入 repository 或未來 `.app` Resources。

## 5. Removed production absolute-path dependencies

`server.py` 的 developer-specific model/config 路徑已移除。Production runtime modules `server.py`、`runtime_paths.py`、`backend_startup.py` 均沒有 `/Users/ouo1010`。Development smoke 中顯示的 source path 是 resolver 在明確 development mode 的正常輸出，不是 production hard-code。

歷史 docs、benchmark artifacts、test fixtures 與先前 logs 沒有做無關的 mass replacement。

## 6. KataGo resolution

由高至低：

1. `--katago-executable`
2. `LOGOSGO_KATAGO_EXECUTABLE`
3. packaged helper `Contents/Helpers/KataGo/katago` 或 resource-root 下已知候選位置
4. 僅 development mode 允許 `PATH` lookup

Resolved path 必須是存在且可執行的檔案。KataGo command、analysis protocol、flags、query routing 與 lifecycle 沒有改變。

## 7. Model/config/data resolution

Resolver 支援目前 development flat layout，以及未來可直接放入 resource root 的 nested layout：

- model：`model.bin.gz` 或 `model/model.bin.gz`
- config：`analysis.cfg` 或 `config/analysis.cfg`
- corpus：`logosgo_corpus_full.csv` 或 `data/logosgo_corpus_full.csv`

`LogosEngine` 現在收到 resolved corpus path。三個資產內容均未修改。

## 8. Temp SGF behavior

目前 production backend 直接解析 request 中的 `sgf_content`，沒有建立 `temp_upload.sgf`，也沒有把 user SGF 寫入 repository。Regression test 掃描實際 runtime modules，防止重新引入固定 repository temp filename。

UI smoke 使用的 `/private/tmp/logosgo_phase6b1_smoke.sgf` 僅為測試 fixture，測試後已刪除；原始棋譜與正式 history 均未修改。

## 9. Flask bind/debug/CORS behavior

- bind：固定 `127.0.0.1`
- debug：`False`
- reloader：停用
- CORS：移除 unrestricted `flask_cors.CORS(app)`；native Flutter localhost HTTP 不需要 browser CORS

Health test 也確認 response 不含 `Access-Control-Allow-Origin`。Flask development server 仍只用於目前 development smoke；Phase 6B-2 frozen executable 可再決定 production serving wrapper，而不需重做 path/startup interface。

## 10. Dynamic-port interface

Backend 支援：

```text
server.py --port <1..65535>
```

亦支援 `LOGOSGO_PORT`。CLI 優先於 environment，development default 保留 5001。非法、非整數或超出範圍的 port 會清楚失敗。5001 現在只是 development default，不再散落於 backend/frontend call sites。

## 11. Instance identity design

Backend 支援 `--instance-token` / `LOGOSGO_INSTANCE_TOKEN`；未提供時每次 launch 產生 cryptographically random token。`BackendIdentity`：

- 使用 constant-time token comparison
- 對外只回傳 token 的 SHA-256 前 24 hex 字元作為 `instance_id`
- 不記錄、不回傳 raw token
- 使用 `X-LogosGo-Instance` header 驗證 future Runner 所啟動的 instance

這是 localhost process identity foundation，不是 cloud authentication；本 Phase 沒有把所有 API 改造成 authenticated API。

## 12. Health endpoint

`GET /health` 回傳：

```json
{
  "service": "LogosGoBackend",
  "api_schema_version": 1,
  "ready": true,
  "instance_id": "<token-derived non-secret id>",
  "token_verified": true
}
```

未帶/帶錯 token 時仍可辨識 service，但 `token_verified` 為 false。Endpoint 不回傳 filesystem path，不載入 model、不啟動 KataGo、不執行分析；focused unit test 與 process-level smoke 都驗證此性質。

## 13. Flutter endpoint centralization

`BackendEndpointConfig` 集中保存 host、port、optional instance token，並統一產生 URI/header。五個既有 call site：

- `/analysis/start`
- `/analysis/<job_id>`
- `/analysis/<job_id>/cancel`
- `/analysis/<job_id>/ask`
- `/analyze_position`

都使用同一 config。Development 預設仍為 `127.0.0.1:5001`；constructor 可表示 future Runner 提供的 arbitrary port/token。Native Runner injection 尚未實作，留在 Phase 6B-4。

## 14. Focused tests

- Python runtime/startup focused suite：21 passed。
- Flutter endpoint + existing widget focused file：17 passed。
- 覆蓋 explicit root、environment/source/packaged precedence、cwd independence、nested resources、KataGo explicit/discovery、writable paths、missing/malformed resources、無 developer absolute path、無固定 temp SGF、default/custom port、token、identity、localhost/debug、CORS、health、health 無 KataGo side effect、log cwd 與 API paths。

## 15. Regression results

- Phase-focused Python（Phase 1 evidence、Phase 2 features/classifier、Phase 4A structured explanation、Phase 4B review selection、Phase 4C review summary、Phase 5C directional commentary、Phase 5D perspective parity、position-priority）：199 passed。
- Full Python suite：243 passed（pre-phase 222 + 21 new）。
- Full Flutter suite：56 passed（pre-phase 54 + 2 new）。
- `flutter analyze`：13 diagnostics，與 pre-phase baseline 相同；本 Phase 新增 0。
- `py_compile`：passed。
- `git diff --check`：passed。

## 16. Development smoke-test results

### Explicit custom-port smoke

- startup：`--port 53123 --instance-token ... --resource-root ... --katago-executable ...`
- listener：只有 `127.0.0.1:53123`
- `/health`：service/schema/readiness/identity 正確，token verified
- health 後：未啟動 KataGo
- minimal SGF：1 手（KataGo request 包含初始與落子後 2 個 position）
- `/analysis/start` 與 progress polling：completed，無 timeout/malformed response/crash
- response：既有 move analysis、structured explanation、review selection/summary schema 正常
- actual visits：root 約 103，符合 whole-game request 100 visits 的既有行為

### Default Flutter development smoke

- backend 無 explicit resource/KataGo/port argument，以 source/PATH development fallback 啟動
- listener：只有 `127.0.0.1:5001`
- Flutter macOS debug app 正常啟動並使用集中式 default endpoint
- macOS file picker 成功匯入暫存 1 手 SGF
- UI 顯示分析進度，polling 完成後顯示第 1 手 KataGo 客觀分析與 LogosGo 解說
- smoke 結束後 Flutter、Flask、KataGo process 均退出，port 釋放

未執行長棋譜 benchmark，也未改變已知 336 手 performance baseline。

## 17. Remaining Phase 6B-2 requirements

- 選定 backend freezer/standalone executable 方案。
- 建立明確 asset manifest，把 Python modules/runtime dependencies 納入 frozen backend。
- 驗證 frozen executable 的 `_MEIPASS` 或 explicit resource-root 行為。
- 決定 production WSGI/serving wrapper。
- 執行 standalone backend tests；本 Phase 不安裝 PyInstaller、不新增 `.spec`。

## 18. Remaining Phase 6B-3 requirements

- 將 Apple Silicon KataGo executable 放入既定 helper layout。
- 盤點並 bundle Homebrew dylib dependencies。
- 必要時處理 install names/rpaths。
- 對 KataGo、dylibs 與 model/config/data 做完整 runtime/codesign 驗證。
- 本 Phase 沒有 copy binary、dylib、rewrite rpath 或 codesign。

## 19. Remaining Phase 6B-4 requirements

- Native Runner 分配 free localhost port。
- Runner 生成 token、傳入 resource root/KataGo path、啟動 backend。
- readiness polling 與 `/health` service/token verification。
- 把 dynamic port/token 注入 Flutter endpoint config。
- parent/child lifecycle、normal shutdown、timeout/kill fallback 與 collision handling。
- 依 Phase 6A 決策處理 App Sandbox/entitlements。

本 Phase 未改 Runner 或 entitlements，sandbox 維持原狀。

## 20. Frozen analytical behavior confirmation

再次由 production constants/config 與 full regressions確認：

- whole-game：100 visits、16×4、`analysisPVLen = 8`、`includeOwnership = false`
- position judgment：500 visits、1×16、ownership + ownership stdev
- `reportAnalysisWinratesAs = BLACK`
- scheduling、foreground preemption、cancellation/resume、query routing 未改
- analysis schema、observed loss、candidate gap、classifier、structured/directional commentary、Review Selection、Review Summary 未改
- trial/variation 與 black/white perspective conversion 未改
- `analysis.cfg`、model、corpus contents 未改

A. READY FOR PHASE 6B-2
Runtime portability foundation is complete and the backend is ready to
be frozen into a standalone executable.
