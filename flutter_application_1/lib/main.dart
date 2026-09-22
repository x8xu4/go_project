import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:convert';
import 'dart:math';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:flutter/services.dart';

//cd flutter_application_1 flutter run

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    const MaterialApp(debugShowCheckedModeBanner: false, home: GoBoardPage()),
  );
}

class StoneInfo {
  final Color color;
  final int moveNumber;
  StoneInfo(this.color, this.moveNumber);
}

const double ownershipDisplayThreshold = 0.60;
const double deadStoneOwnershipThreshold = 0.80;
const double maxDeadStoneOwnershipStdev = 0.25;

int ownershipIndex(int x, int y) => y * 19 + x;

bool shouldShowDeadStoneMarker({
  required bool isBlackStone,
  required double ownership,
  required double ownershipStdev,
}) {
  if (ownershipStdev > maxDeadStoneOwnershipStdev) return false;
  return isBlackStone
      ? ownership <= -deadStoneOwnershipThreshold
      : ownership >= deadStoneOwnershipThreshold;
}

class PositionAnalysisResult {
  final List<double> ownership;
  final List<double> ownershipStdev;
  final double blackScoreLead;
  final double blackWinrate;
  final double whiteWinrate;
  final double blackOwnershipPoints;
  final double whiteOwnershipPoints;
  final int blackCaptures;
  final int whiteCaptures;
  final int moveCount;
  final int? visits;

  const PositionAnalysisResult({
    required this.ownership,
    required this.ownershipStdev,
    required this.blackScoreLead,
    required this.blackWinrate,
    required this.whiteWinrate,
    required this.blackOwnershipPoints,
    required this.whiteOwnershipPoints,
    required this.blackCaptures,
    required this.whiteCaptures,
    required this.moveCount,
    this.visits,
  });
}

class GoBoardPage extends StatefulWidget {
  const GoBoardPage({super.key});

  @override
  State<GoBoardPage> createState() => _GoBoardPageState();
}

class _GoBoardPageState extends State<GoBoardPage> {
  String _currentTag = "準備中";
  String _currentCommentary = "等待落子或匯入 SGF 以開始分析...";
  List<FlSpot> _winrateSpots = [const FlSpot(0, 0.5)];
  List<int> _blunderMoves = [];
  Map<String, StoneInfo> _stones = {};
  Map<String, StoneInfo> _initialStones = {};
  final List<Map<String, StoneInfo>> _history = [];
  final List<String> _gameMoveColors = [];
  String? _lastBoardState;
  bool _isBlack = true;
  bool _showMoveNumbers = false;
  int _currentMoveCount = 0;
  final FocusNode _focusNode = FocusNode();
  bool _showBlackWinrate = true; // true = 黑棋勝率，false = 白棋勝率
  bool _isTrialMode = false;
  List<Map<String, StoneInfo>> _trialHistory = [];
  final List<List<String>> _trialMoves = [];
  int _trialMoveCount = 0;
  int _analysisGeneration = 0; // 每次匯入新棋譜時遞增
  String? _analysisJobId;
  bool _isGameAnalyzing = false;
  int _analysisCompletedMoves = 0;
  int _analysisTotalMoves = 0;
  double? _analysisEtaSeconds;
  List<Map<String, dynamic>> _moveAnalyses = [];
  final Map<int, String> _questionCommentaryCache = {};
  bool _isQuestionLoading = false;
  String? _loadedSgfContent;
  List<double>? _ownership;
  List<double>? _ownershipStdev;
  PositionAnalysisResult? _positionAnalysisResult;
  Offset? _positionPanelOffset;
  bool _isPositionAnalyzing = false;
  int _positionAnalysisGeneration = 0;

  static const double _positionPanelWidth = 260;
  static const double _positionPanelHeight = 252;

  // ★ 修正落子偏移：用 GlobalKey 取得棋盤的真實位置
  final GlobalKey _boardKey = GlobalKey();
  final TextEditingController _jumpController = TextEditingController();
  final List<List<int>> _directions = [
    [0, 1],
    [0, -1],
    [1, 0],
    [-1, 0],
  ];

  @override
  void dispose() {
    _focusNode.dispose();
    _jumpController.dispose();
    super.dispose();
  }

  // --- 1. SGF 匯入（本地解析，不依賴後端）---
  Future<void> _importSGF() async {
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['sgf'],
        withData: true,
        allowCompression: false,
      );

      if (!mounted) return;
      if (result == null || result.files.isEmpty) return;

      final file = result.files.first;
      String sgfContent;

      if (file.bytes != null) {
        try {
          sgfContent = utf8.decode(file.bytes!);
        } catch (_) {
          // UTF-8 失敗，改用 latin1 解碼（相容 GB2312/GBK 檔案）
          sgfContent = latin1.decode(file.bytes!);
        }
      } else if (file.path != null) {
        sgfContent = await File(file.path!).readAsString();
      } else {
        return;
      }
      final fileName = file.name;

      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text("正在載入 $fileName ...")));

      // 切換棋譜前，重置試下狀態與舊的解說文字
      setState(() {
        _isTrialMode = false;
        _trialHistory.clear();
        _trialMoves.clear();
        _trialMoveCount = 0;
        _analysisGeneration++;
        _analysisJobId = null;
        _isGameAnalyzing = true;
        _analysisCompletedMoves = 0;
        _analysisTotalMoves = 0;
        _analysisEtaSeconds = null;
        _moveAnalyses = [];
        _questionCommentaryCache.clear();
        _isQuestionLoading = false;
        _loadedSgfContent = sgfContent;
        _invalidatePositionAnalysis();
        _currentCommentary = "AI 引擎正在計算勝率與評估數據，請稍候..."; // 先設定為分析中
        _currentTag = "分析中";
      });

      // ★ 本地解析 SGF，不需要後端也能顯示棋譜
      _parseSGFLocally(sgfContent);

      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text("棋譜載入完成！")));
    } catch (e) {
      debugPrint("載入失敗: $e");
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text("載入失敗: $e")));
      }
    }
  }

  Map<String, StoneInfo> _parseRootSetupStones(String rootNode) {
    final setup = <String, StoneInfo>{};
    final propertyRegex = RegExp(r'(AB|AW)((?:\[[a-s]{2}\])+)');
    final coordinateRegex = RegExp(r'\[([a-s]{2})\]');
    for (final property in propertyRegex.allMatches(rootNode)) {
      final color = property.group(1) == 'AB' ? Colors.black : Colors.white;
      for (final coordinate in coordinateRegex.allMatches(property.group(2)!)) {
        final value = coordinate.group(1)!;
        final x = value.codeUnitAt(0) - 'a'.codeUnitAt(0);
        final y = value.codeUnitAt(1) - 'a'.codeUnitAt(0);
        setup["$x,$y"] = StoneInfo(color, 0);
      }
    }
    return setup;
  }

  // ★ 本地 SGF 解析：把棋譜一步步重建成 _history
  Future<void> _parseSGFLocally(String sgf) async {
    // 主線的每手都以 ;B[...] / ;W[...] 表示；後面的間距、
    // 顏色交替與重複座標檢查仍負責在變化圖開始時停止。
    final moveRegex = RegExp(r';([BW])\[([a-s]{0,2})\]');
    final firstMatch = moveRegex.firstMatch(sgf);
    final rootNode = firstMatch == null
        ? sgf
        : sgf.substring(0, firstMatch.start);
    final initialStones = _parseRootSetupStones(rootNode);
    Map<String, StoneInfo> currentStones = Map.from(initialStones);
    List<Map<String, StoneInfo>> newHistory = [];
    final moveColors = <String>[];
    int moveNum = 0;
    String lastCoord = '';
    String? previousColor;

    // 把第一手位置記下來，之後間距從這裡算
    int lastPos = firstMatch?.start ?? 0;

    final matches = moveRegex.allMatches(sgf);

    for (final match in matches) {
      final colorChar = match.group(1)!;
      final coord = match.group(2)!;

      // ★ 間距超過 50 代表進入變化圖注釋區，停止解析
      if (lastPos != 0 && (match.start - lastPos) > 200) {
        debugPrint("間距中斷在第${moveNum + 1}手，間距${match.start - lastPos}，座標$coord");
        break;
      }
      lastPos = match.start;

      if (previousColor == colorChar) {
        debugPrint("顏色不交替中斷：第${moveNum + 1}手再次出現$colorChar");
        break;
      }
      previousColor = colorChar;

      // ★ 同座標連續出現代表進入變化圖，停止
      if (coord.isNotEmpty && newHistory.isNotEmpty && coord == lastCoord) {
        debugPrint("重複座標中斷在第${moveNum + 1}手，座標$coord");
        break;
      }
      lastCoord = coord;

      moveNum++;
      moveColors.add(colorChar);
      if (coord.isEmpty || coord.length < 2) {
        // pass 仍然是一手，盤面不變但 history 必須保留一個 snapshot。
        newHistory.add(Map.from(currentStones));
        continue;
      }

      int x = coord.codeUnitAt(0) - 'a'.codeUnitAt(0);
      int y = coord.codeUnitAt(1) - 'a'.codeUnitAt(0);

      if (x < 0 || x >= 19 || y < 0 || y >= 19) continue;

      Color mine = colorChar == 'B' ? Colors.black : Colors.white;
      Color opp = colorChar == 'B' ? Colors.white : Colors.black;

      String key = "$x,$y";
      if (moveNum >= 203)
        debugPrint("第${moveNum + 1}手: $colorChar[$coord] 位置${match.start}");
      currentStones[key] = StoneInfo(mine, moveNum);

      for (var d in _directions) {
        int nx = x + d[0], ny = y + d[1];
        if (nx < 0 || nx >= 19 || ny < 0 || ny >= 19) continue;
        String nk = "$nx,$ny";
        if (currentStones.containsKey(nk) && currentStones[nk]!.color == opp) {
          if (_getLiberties(nx, ny, opp, currentStones).isEmpty) {
            _removeGroup(nx, ny, opp, currentStones);
          }
        }
      }

      newHistory.add(Map.from(currentStones));
    }

    debugPrint("解析手數: ${newHistory.length}");

    setState(() {
      _history.clear();
      _history.addAll(newHistory);
      _gameMoveColors
        ..clear()
        ..addAll(moveColors);
      _initialStones = Map.from(initialStones);
      _currentMoveCount = newHistory.length;
      if (newHistory.isNotEmpty) {
        _stones = Map.from(newHistory.last);
      } else {
        _stones = Map.from(_initialStones);
      }
      _isBlack = _isBlackToMove(_currentMoveCount);
      _lastBoardState = null;
      // ★ 先用平線填滿，後端回來後再更新
      _winrateSpots = List.generate(newHistory.length + 1, (i) {
        return FlSpot(i.toDouble(), 0.5);
      });
    });
    await _tryServerAnalysis(sgf);
  }

  Future<void> _tryServerAnalysis(String sgfContent) async {
    final myGeneration = _analysisGeneration;
    try {
      debugPrint("建立背景整盤分析...");
      final startResponse = await http
          .post(
            Uri.parse('http://127.0.0.1:5001/analysis/start'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({"sgf_content": sgfContent}),
          )
          .timeout(const Duration(seconds: 15));
      final startData = jsonDecode(startResponse.body);
      if (startResponse.statusCode != 202 || startData is! Map) {
        throw Exception(
          startData is Map ? startData['message'] ?? "無法建立分析任務" : "無法建立分析任務",
        );
      }
      final jobId = startData['job_id'];
      if (jobId is! String || jobId.isEmpty) {
        throw const FormatException("後端未回傳 analysis job id");
      }
      if (!mounted || myGeneration != _analysisGeneration) {
        await _cancelAnalysisJob(jobId, silent: true);
        return;
      }
      setState(() {
        _analysisJobId = jobId;
        _isGameAnalyzing = true;
        _analysisCompletedMoves =
            (startData['completed_moves'] as num?)?.toInt() ?? 0;
        _analysisTotalMoves =
            (startData['total_moves'] as num?)?.toInt() ?? _history.length;
        _analysisEtaSeconds = null;
        _updateAnalysisProgressCommentary();
      });
      await _pollAnalysisJob(jobId, myGeneration);
    } catch (error) {
      if (!mounted || myGeneration != _analysisGeneration) return;
      debugPrint("後端分析例外: $error");
      setState(() {
        _isGameAnalyzing = false;
        _currentTag = "分析失敗";
        _currentCommentary = "整盤分析失敗：${_cleanError(error)}";
      });
    }
  }

  String _cleanError(Object error) {
    return error
        .toString()
        .replaceFirst('Exception: ', '')
        .replaceFirst('FormatException: ', '');
  }

  String _formatEta(double seconds) {
    final rounded = max(0, seconds.round());
    final minutes = rounded ~/ 60;
    final remainder = rounded % 60;
    if (minutes == 0) return "約 $remainder 秒";
    if (remainder == 0) return "約 $minutes 分";
    return "約 $minutes 分 $remainder 秒";
  }

  void _updateAnalysisProgressCommentary() {
    final total = max(1, _analysisTotalMoves);
    final percent = ((_analysisCompletedMoves / total) * 100)
        .clamp(0, 100)
        .round();
    final etaText = _analysisEtaSeconds == null
        ? "正在估算分析時間…"
        : "預估剩餘時間：${_formatEta(_analysisEtaSeconds!)}";
    _currentTag = "分析中";
    _currentCommentary =
        "正在分析棋譜：$_analysisCompletedMoves / $_analysisTotalMoves 手（$percent%）\n\n$etaText";
  }

  Future<void> _pollAnalysisJob(String jobId, int generation) async {
    int consecutiveErrors = 0;
    while (mounted && generation == _analysisGeneration) {
      try {
        final response = await http
            .get(Uri.parse('http://127.0.0.1:5001/analysis/$jobId'))
            .timeout(const Duration(seconds: 10));
        if (response.statusCode != 200) {
          throw Exception("進度查詢失敗（HTTP ${response.statusCode}）");
        }
        final data = jsonDecode(response.body);
        if (data is! Map<String, dynamic>) {
          throw const FormatException("進度回傳格式錯誤");
        }
        consecutiveErrors = 0;
        final status = data['status'];
        if (status == 'queued' || status == 'running') {
          setState(() {
            _analysisCompletedMoves =
                (data['completed_moves'] as num?)?.toInt() ?? 0;
            _analysisTotalMoves =
                (data['total_moves'] as num?)?.toInt() ?? _history.length;
            _analysisEtaSeconds = (data['eta_seconds'] as num?)?.toDouble();
            _isGameAnalyzing = true;
            _updateAnalysisProgressCommentary();
          });
        } else if (status == 'completed') {
          final result = data['result'];
          if (result is! Map<String, dynamic>) {
            throw const FormatException("完成的分析缺少 result");
          }
          _applyCompletedGameAnalysis(result);
          return;
        } else if (status == 'cancelled') {
          setState(() {
            _isGameAnalyzing = false;
            _currentTag = "已取消";
            _currentCommentary = "整盤分析已取消。";
          });
          return;
        } else if (status == 'failed') {
          throw Exception(data['error'] ?? "後端分析失敗");
        } else {
          throw FormatException("未知的分析狀態：$status");
        }
      } catch (error) {
        consecutiveErrors++;
        debugPrint("進度輪詢失敗 ($consecutiveErrors): $error");
        if (consecutiveErrors >= 5) {
          if (!mounted || generation != _analysisGeneration) return;
          setState(() {
            _isGameAnalyzing = false;
            _currentTag = "連線失敗";
            _currentCommentary = "無法取得分析進度，後端任務可能仍在執行：${_cleanError(error)}";
          });
          return;
        }
      }
      await Future<void>.delayed(const Duration(milliseconds: 800));
    }
  }

  void _applyCompletedGameAnalysis(Map<String, dynamic> result) {
    final rawWinrates = result['winrates'];
    final rawMoves = result['move_analyses'];
    if (rawWinrates is! List || rawMoves is! List) {
      throw const FormatException("整盤分析結果格式錯誤");
    }
    final winrates = rawWinrates
        .map((value) {
          if (value is! num) throw const FormatException("勝率格式錯誤");
          return value.toDouble();
        })
        .toList(growable: false);
    final moves = rawMoves
        .map((value) {
          if (value is! Map) throw const FormatException("棋步分析格式錯誤");
          return Map<String, dynamic>.from(value);
        })
        .toList(growable: false);
    final rawImportant = result['important_moves'];
    setState(() {
      _winrateSpots = winrates
          .asMap()
          .entries
          .map((entry) => FlSpot(entry.key.toDouble(), entry.value))
          .toList(growable: false);
      _moveAnalyses = moves;
      _blunderMoves = rawImportant is List
          ? rawImportant.whereType<num>().map((value) => value.toInt()).toList()
          : <int>[];
      _analysisCompletedMoves = _history.length;
      _analysisTotalMoves = _history.length;
      _analysisEtaSeconds = 0;
      _isGameAnalyzing = false;
      _questionCommentaryCache.clear();
    });
    _fetchLogosCommentary(_currentMoveCount);
  }

  Future<void> _cancelAnalysisJob(String jobId, {bool silent = false}) async {
    try {
      await http
          .post(Uri.parse('http://127.0.0.1:5001/analysis/$jobId/cancel'))
          .timeout(const Duration(seconds: 10));
    } catch (error) {
      if (!silent) {
        debugPrint("取消分析失敗: $error");
      }
    }
  }

  Future<void> _cancelCurrentGameAnalysis() async {
    final jobId = _analysisJobId;
    if (jobId == null || !_isGameAnalyzing) return;
    _analysisGeneration++;
    setState(() {
      _isGameAnalyzing = false;
      _currentTag = "取消中";
      _currentCommentary = "正在取消整盤分析…";
    });
    await _cancelAnalysisJob(jobId);
    if (!mounted) return;
    setState(() {
      _currentTag = "已取消";
      _currentCommentary = "整盤分析已取消。";
    });
  }

  void _invalidatePositionAnalysis() {
    _positionAnalysisGeneration++;
    _ownership = null;
    _ownershipStdev = null;
    _positionAnalysisResult = null;
    _positionPanelOffset = null;
    _isPositionAnalyzing = false;
  }

  void _closePositionAnalysis() {
    setState(_invalidatePositionAnalysis);
  }

  String _toGtpCoordinate(int x, int y) {
    const columns = 'ABCDEFGHJKLMNOPQRST';
    return '${columns[x]}${19 - y}';
  }

  bool _isBlackToMove(int moveCount) {
    if (_gameMoveColors.isEmpty || moveCount <= 0) {
      return _gameMoveColors.isEmpty || _gameMoveColors.first == 'B';
    }
    final lastIndex = min(moveCount, _gameMoveColors.length) - 1;
    return _gameMoveColors[lastIndex] != 'B';
  }

  Future<void> _analyzeCurrentPosition() async {
    final sgfContent = _loadedSgfContent;
    if (sgfContent == null || sgfContent.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text("請先匯入 SGF 棋譜")));
      return;
    }

    final requestGeneration = ++_positionAnalysisGeneration;
    final analyzedBaseMove = _currentMoveCount;
    final analyzedTrialMove = _isTrialMode ? _trialMoveCount : 0;
    final extraMoves = _isTrialMode
        ? _trialMoves.take(_trialMoveCount).map((move) => [...move]).toList()
        : <List<String>>[];

    setState(() {
      _isPositionAnalyzing = true;
      _ownership = null;
      _ownershipStdev = null;
      _positionAnalysisResult = null;
      _positionPanelOffset = null;
    });

    try {
      final response = await http
          .post(
            Uri.parse('http://127.0.0.1:5001/analyze_position'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({
              "sgf_content": sgfContent,
              "move_count": analyzedBaseMove,
              "extra_moves": extraMoves,
            }),
          )
          .timeout(const Duration(seconds: 50));

      dynamic decoded;
      try {
        decoded = jsonDecode(response.body);
      } catch (_) {
        throw const FormatException("後端回傳的資料不是有效 JSON");
      }
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException("後端回傳格式錯誤");
      }
      if (response.statusCode != 200 || decoded['status'] != 'success') {
        throw Exception(decoded['message'] ?? "後端形勢分析失敗");
      }
      if (decoded['perspective'] != 'black') {
        throw const FormatException("後端分析視角不是黑方，無法安全顯示結果");
      }

      final rawOwnership = decoded['ownership'];
      final rawOwnershipStdev = decoded['ownership_stdev'];
      if (rawOwnership is! List || rawOwnership.length != 361) {
        throw const FormatException("ownership 資料缺失或不是 19×19");
      }
      if (rawOwnershipStdev is! List || rawOwnershipStdev.length != 361) {
        throw const FormatException("ownership stdev 資料缺失或不是 19×19");
      }
      final ownership = rawOwnership
          .map((value) {
            if (value is! num) {
              throw const FormatException("ownership 含有非數值資料");
            }
            final converted = value.toDouble();
            if (!converted.isFinite ||
                converted < -1.001 ||
                converted > 1.001) {
              throw const FormatException("ownership 數值超出合理範圍");
            }
            return converted;
          })
          .toList(growable: false);
      final ownershipStdev = rawOwnershipStdev
          .map((value) {
            if (value is! num) {
              throw const FormatException("ownership stdev 含有非數值資料");
            }
            final converted = value.toDouble();
            if (!converted.isFinite || converted < 0 || converted > 1.001) {
              throw const FormatException("ownership stdev 數值超出合理範圍");
            }
            return converted;
          })
          .toList(growable: false);

      final blackScoreLead = decoded['black_score_lead'];
      final blackWinrate = decoded['black_winrate'];
      final whiteWinrate = decoded['white_winrate'];
      final blackOwnershipPoints = decoded['black_ownership_points'];
      final whiteOwnershipPoints = decoded['white_ownership_points'];
      final blackCaptures = decoded['black_captures'];
      final whiteCaptures = decoded['white_captures'];
      if (blackScoreLead is! num ||
          blackWinrate is! num ||
          whiteWinrate is! num ||
          blackOwnershipPoints is! num ||
          whiteOwnershipPoints is! num ||
          blackCaptures is! num ||
          whiteCaptures is! num) {
        throw const FormatException("形勢分差、領地、提子或勝率資料缺失");
      }

      final result = PositionAnalysisResult(
        ownership: ownership,
        ownershipStdev: ownershipStdev,
        blackScoreLead: blackScoreLead.toDouble(),
        blackWinrate: blackWinrate.toDouble(),
        whiteWinrate: whiteWinrate.toDouble(),
        blackOwnershipPoints: blackOwnershipPoints.toDouble(),
        whiteOwnershipPoints: whiteOwnershipPoints.toDouble(),
        blackCaptures: blackCaptures.toInt(),
        whiteCaptures: whiteCaptures.toInt(),
        moveCount:
            (decoded['move_count'] as num?)?.toInt() ??
            analyzedBaseMove + analyzedTrialMove,
        visits: (decoded['visits'] as num?)?.toInt(),
      );

      if (!mounted || requestGeneration != _positionAnalysisGeneration) return;
      setState(() {
        _ownership = result.ownership;
        _ownershipStdev = result.ownershipStdev;
        _positionAnalysisResult = result;
        _positionPanelOffset = null;
        _isPositionAnalyzing = false;
      });
    } catch (error) {
      if (!mounted || requestGeneration != _positionAnalysisGeneration) return;
      setState(() {
        _isPositionAnalyzing = false;
        _ownership = null;
        _ownershipStdev = null;
        _positionAnalysisResult = null;
        _positionPanelOffset = null;
      });
      final message = error.toString().replaceFirst('Exception: ', '');
      debugPrint("形勢判斷失敗: $error");
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text("形勢判斷失敗：$message")));
    }
  }

  Size _positionPanelSize(Size viewport) {
    return Size(
      min(_positionPanelWidth, max(0, viewport.width - 16)),
      min(_positionPanelHeight, max(0, viewport.height - 16)),
    );
  }

  Offset _defaultPositionPanelOffset(Size viewport) {
    final panelSize = _positionPanelSize(viewport);
    return Offset(max(8, viewport.width - panelSize.width - 16), 16);
  }

  Offset _clampPositionPanelOffset(Offset offset, Size viewport) {
    final panelSize = _positionPanelSize(viewport);
    final maxX = max(8, viewport.width - panelSize.width - 8);
    final maxY = max(8, viewport.height - panelSize.height - 8);
    return Offset(
      offset.dx.clamp(8, maxX).toDouble(),
      offset.dy.clamp(8, maxY).toDouble(),
    );
  }

  void _dragPositionPanel(DragUpdateDetails details, Size viewport) {
    setState(() {
      final current =
          _positionPanelOffset ?? _defaultPositionPanelOffset(viewport);
      _positionPanelOffset = _clampPositionPanelOffset(
        current + details.delta,
        viewport,
      );
    });
  }

  Widget _positionSideRow({
    required Color color,
    required String label,
    required double points,
    required int captures,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Container(
            width: 14,
            height: 14,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white54),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 38,
            child: Text(
              label,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Expanded(
            child: Text(
              "估計控制 ${points.toStringAsFixed(1)}　提子 $captures",
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPositionAnalysisPanel(
    PositionAnalysisResult result,
    Size viewport,
  ) {
    final score = result.blackScoreLead;
    final isEven = score.abs() < 0.1;
    final leader = isEven ? "形勢接近" : (score > 0 ? "黑方較有利" : "白方較有利");
    final scoreText = isEven
        ? "分差接近 0 目"
        : "${score > 0 ? '黑方' : '白方'}領先約 ${score.abs().toStringAsFixed(1)} 目";
    final panelSize = _positionPanelSize(viewport);

    return SizedBox(
      width: panelSize.width,
      height: panelSize.height,
      child: Material(
        color: const Color(0xFF252525),
        elevation: 16,
        shadowColor: Colors.black,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(color: Colors.amber.withValues(alpha: 0.55)),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          children: [
            MouseRegion(
              cursor: SystemMouseCursors.move,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanUpdate: (details) => _dragPositionPanel(details, viewport),
                child: Container(
                  height: 42,
                  padding: const EdgeInsets.only(left: 12, right: 4),
                  color: Colors.amber,
                  child: Row(
                    children: [
                      const Icon(Icons.drag_indicator, size: 18),
                      const SizedBox(width: 6),
                      const Expanded(
                        child: Text(
                          "形勢判斷",
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      Text(
                        "第 ${result.moveCount} 手",
                        style: const TextStyle(fontSize: 11),
                      ),
                      IconButton(
                        tooltip: "關閉形勢判斷",
                        onPressed: _closePositionAnalysis,
                        icon: const Icon(Icons.close, size: 19),
                        padding: const EdgeInsets.all(6),
                        constraints: const BoxConstraints(),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _positionSideRow(
                      color: Colors.black,
                      label: "黑方",
                      points: result.blackOwnershipPoints,
                      captures: result.blackCaptures,
                    ),
                    _positionSideRow(
                      color: Colors.white,
                      label: "白方",
                      points: result.whiteOwnershipPoints,
                      captures: result.whiteCaptures,
                    ),
                    const Divider(color: Colors.white24, height: 20),
                    Text(
                      leader,
                      style: const TextStyle(
                        color: Colors.amber,
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      scoreText,
                      style: const TextStyle(color: Colors.white, fontSize: 15),
                    ),
                    const SizedBox(height: 7),
                    Text(
                      "勝率　黑 ${(result.blackWinrate * 100).toStringAsFixed(1)}%　"
                      "白 ${(result.whiteWinrate * 100).toStringAsFixed(1)}%",
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 13,
                      ),
                    ),
                    if (result.visits != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        "KataGo visits：${result.visits}",
                        style: const TextStyle(
                          color: Colors.white38,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _fetchLogosCommentary(int moveIndex) async {
    if (_isGameAnalyzing) {
      setState(() {
        _updateAnalysisProgressCommentary();
      });
      return;
    }
    if (_currentTag == "分析失敗" ||
        _currentTag == "連線失敗" ||
        _currentTag == "已取消") {
      return;
    }
    if (moveIndex == 0) {
      setState(() {
        _currentTag = "起始局面";
        _currentCommentary = "KataGo 客觀分析\n尚未落子。\n\nLogosGo 解說\n請切換到某一手查看棋步分析。";
      });
      return;
    }
    if (moveIndex < 1 || moveIndex > _moveAnalyses.length) return;
    final record = _moveAnalyses[moveIndex - 1];
    setState(() {
      _currentTag = record['auto_tag']?.toString() ?? "普通手";
      _currentCommentary = _composeMoveCommentary(record, moveIndex);
    });
  }

  String _composeMoveCommentary(Map<String, dynamic> record, int moveIndex) {
    final player = record['player'] == 'B' ? '黑方' : '白方';
    final actual = record['actual_move']?.toString() ?? '未知';
    final best = record['best_move']?.toString();
    final before =
        ((record['mover_winrate_before'] as num?)?.toDouble() ?? 0.5) * 100;
    final after =
        ((record['mover_winrate_after'] as num?)?.toDouble() ?? 0.5) * 100;
    final wrLoss = ((record['winrate_loss'] as num?)?.toDouble() ?? 0) * 100;
    final scoreLoss = (record['score_loss'] as num?)?.toDouble() ?? 0;
    final autoCommentary = record['auto_commentary']?.toString() ?? '';
    final cached = _questionCommentaryCache[moveIndex];
    final objective = StringBuffer()
      ..writeln('KataGo 客觀分析')
      ..writeln('第 $moveIndex 手：$player $actual')
      ..writeln(
        '落子方勝率：${before.toStringAsFixed(1)}% → ${after.toStringAsFixed(1)}%',
      )
      ..writeln(
        '估計損失：${wrLoss.toStringAsFixed(1)}% 勝率／${scoreLoss.toStringAsFixed(1)} 目',
      )
      ..writeln('KataGo 一選：${best ?? '未回傳'}')
      ..writeln()
      ..writeln('LogosGo 解說')
      ..write(autoCommentary);
    if (cached != null) {
      objective
        ..writeln()
        ..writeln()
        ..writeln('按需講解（已快取）')
        ..write(cached);
    }
    return objective.toString();
  }

  Future<void> _askWhyCurrentMove() async {
    final moveIndex = _currentMoveCount;
    final jobId = _analysisJobId;
    if (_isGameAnalyzing ||
        jobId == null ||
        moveIndex < 1 ||
        moveIndex > _moveAnalyses.length ||
        _isQuestionLoading) {
      return;
    }
    final localCached = _questionCommentaryCache[moveIndex];
    if (localCached != null) {
      setState(() {
        _currentCommentary = _composeMoveCommentary(
          _moveAnalyses[moveIndex - 1],
          moveIndex,
        );
      });
      return;
    }
    setState(() => _isQuestionLoading = true);
    try {
      final response = await http
          .post(
            Uri.parse('http://127.0.0.1:5001/analysis/$jobId/ask'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({"move_number": moveIndex}),
          )
          .timeout(const Duration(seconds: 30));
      final data = jsonDecode(response.body);
      if (response.statusCode != 200 ||
          data is! Map ||
          data['status'] != 'success') {
        throw Exception(data is Map ? data['message'] : '講解回傳格式錯誤');
      }
      final commentary = data['commentary'];
      if (commentary is! String || commentary.isEmpty) {
        throw const FormatException('按需講解為空');
      }
      if (!mounted ||
          jobId != _analysisJobId ||
          moveIndex != _currentMoveCount) {
        return;
      }
      setState(() {
        _questionCommentaryCache[moveIndex] = commentary;
        _currentCommentary = _composeMoveCommentary(
          _moveAnalyses[moveIndex - 1],
          moveIndex,
        );
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('提問失敗：${_cleanError(error)}')));
      }
    } finally {
      if (mounted) setState(() => _isQuestionLoading = false);
    }
  }

  // --- 2. 核心規則邏輯 ---
  String _getBoardSnapshot(Map<String, StoneInfo> stones) {
    var sortedKeys = stones.keys.toList()..sort();
    return sortedKeys
        .map((k) => "$k:${stones[k]!.color == Colors.black ? 'B' : 'W'}")
        .join("|");
  }

  Set<String> _getLiberties(
    int startX,
    int startY,
    Color color,
    Map<String, StoneInfo> currentStones,
  ) {
    if (!currentStones.containsKey("$startX,$startY") ||
        currentStones["$startX,$startY"]!.color != color)
      return {"dummy"};
    Set<String> group = {"$startX,$startY"};
    Set<String> liberties = {};
    List<String> queue = ["$startX,$startY"];
    int index = 0;
    while (index < queue.length) {
      String current = queue[index++];
      List<int> pos = current.split(',').map(int.parse).toList();
      for (var dir in _directions) {
        int nx = pos[0] + dir[0], ny = pos[1] + dir[1];
        if (nx < 0 || nx >= 19 || ny < 0 || ny >= 19) continue;
        String key = "$nx,$ny";
        if (!currentStones.containsKey(key)) {
          liberties.add(key);
        } else if (currentStones[key]!.color == color && !group.contains(key)) {
          group.add(key);
          queue.add(key);
        }
      }
    }
    return liberties;
  }

  void _removeGroup(
    int startX,
    int startY,
    Color color,
    Map<String, StoneInfo> currentStones,
  ) {
    List<String> queue = ["$startX,$startY"];
    Set<String> visited = {"$startX,$startY"};
    int index = 0;
    while (index < queue.length) {
      String current = queue[index++];
      currentStones.remove(current);
      List<int> pos = current.split(',').map(int.parse).toList();
      for (var dir in _directions) {
        int nx = pos[0] + dir[0], ny = pos[1] + dir[1];
        String key = "$nx,$ny";
        if (currentStones.containsKey(key) &&
            currentStones[key]!.color == color &&
            !visited.contains(key)) {
          visited.add(key);
          queue.add(key);
        }
      }
    }
  }

  // --- 3. 跳轉與落子 ---
  void _jumpToMove(int target) {
    if (_isTrialMode) {
      int safeTarget = target.clamp(0, _trialHistory.length);
      setState(() {
        _invalidatePositionAnalysis();
        _trialMoveCount = safeTarget;
        if (safeTarget == 0) {
          // 試下模式跳到0，回到試下起點
          _stones = _currentMoveCount > 0
              ? Map.from(_history[_currentMoveCount - 1])
              : Map.from(_initialStones);
          _isBlack = _isBlackToMove(_currentMoveCount);
        } else {
          _stones = Map.from(_trialHistory[safeTarget - 1]);
          final baseIsBlack = _isBlackToMove(_currentMoveCount);
          _isBlack = safeTarget.isEven ? baseIsBlack : !baseIsBlack;
        }
      });
      return;
    }
    int safeTarget = target.clamp(0, _history.length);
    setState(() {
      _invalidatePositionAnalysis();
      _currentMoveCount = safeTarget;
      if (safeTarget == 0) {
        _stones = Map.from(_initialStones);
        _isBlack = _isBlackToMove(0);
        _lastBoardState = null;
      } else {
        _stones = Map.from(_history[safeTarget - 1]);
        _isBlack = _isBlackToMove(safeTarget);
        _lastBoardState = (safeTarget > 1)
            ? _getBoardSnapshot(_history[safeTarget - 2])
            : null;
      }
    });
    _fetchLogosCommentary(safeTarget);
  }

  void _resetGame() {
    setState(() {
      _stones = {};
      _initialStones = {};
      _history.clear();
      _gameMoveColors.clear();
      _trialHistory.clear();
      _trialMoves.clear();
      _analysisJobId = null;
      _isGameAnalyzing = false;
      _analysisCompletedMoves = 0;
      _analysisTotalMoves = 0;
      _analysisEtaSeconds = null;
      _moveAnalyses = [];
      _questionCommentaryCache.clear();
      _isQuestionLoading = false;
      _currentMoveCount = 0;
      _isBlack = true;
      _lastBoardState = null;
      _loadedSgfContent = null;
      _invalidatePositionAnalysis();
    });
  }

  void _undo() {
    if (_currentMoveCount <= 0) return;
    _jumpToMove(_currentMoveCount - 1);
  }

  // ★ 修正落子位置：使用 GlobalKey 取得棋盤真實座標
  void _handleTap(TapUpDetails details) {
    if (!_isTrialMode) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text("請先點擊「試下」按鈕進入試下模式再落子")));
      return;
    }

    final RenderBox? renderBox =
        _boardKey.currentContext?.findRenderObject() as RenderBox?;
    if (renderBox == null) return;

    // 轉換為棋盤內的本地座標
    Offset localPos = renderBox.globalToLocal(details.globalPosition);

    final double boardSize = renderBox.size.width;
    double padding = boardSize * 0.06;
    double step = (boardSize - padding * 2) / 18;

    int x = ((localPos.dx - padding) / step).round();
    int y = ((localPos.dy - padding) / step).round();

    if (x >= 0 && x < 19 && y >= 0 && y < 19) {
      String key = "$x,$y";
      if (!_stones.containsKey(key)) {
        Map<String, StoneInfo> next = Map.from(_stones);
        Color mine = _isBlack ? Colors.black : Colors.white;
        Color opp = _isBlack ? Colors.white : Colors.black;
        next[key] = StoneInfo(mine, _currentMoveCount + 1);

        bool captured = false;
        for (var d in _directions) {
          int nx = x + d[0], ny = y + d[1];
          if (next.containsKey("$nx,$ny") && next["$nx,$ny"]!.color == opp) {
            if (_getLiberties(nx, ny, opp, next).isEmpty) {
              _removeGroup(nx, ny, opp, next);
              captured = true;
            }
          }
        }
        if (!captured && _getLiberties(x, y, mine, next).isEmpty) return;
        if (_lastBoardState != null &&
            _getBoardSnapshot(next) == _lastBoardState)
          return;

        setState(() {
          _invalidatePositionAnalysis();
          _lastBoardState = _getBoardSnapshot(_stones);
          _stones = next;
          if (_isTrialMode) {
            // 試下模式下，我們給予特殊的 moveNumber，加上 10000 作為標記
            if (_trialMoveCount < _trialHistory.length) {
              _trialHistory.removeRange(_trialMoveCount, _trialHistory.length);
              _trialMoves.removeRange(_trialMoveCount, _trialMoves.length);
            }
            _trialMoveCount++;
            next[key] = StoneInfo(
              mine,
              10000 + _trialMoveCount,
            ); // 加上 offset 標記
            _stones = next;
            _trialHistory.add(Map.from(_stones));
            _trialMoves.add([
              mine == Colors.black ? "B" : "W",
              _toGtpCoordinate(x, y),
            ]);
          } else {
            _currentMoveCount++;
            next[key] = StoneInfo(mine, _currentMoveCount);
            _stones = next;
            _history.add(Map.from(_stones));
          }
          _isBlack = !_isBlack;
        });

        _fetchLogosCommentary(_currentMoveCount);
      }
    }
  }

  // --- 4. UI 構建 ---
  @override
  Widget build(BuildContext context) {
    return KeyboardListener(
      focusNode: _focusNode,
      autofocus: true,
      onKeyEvent: (event) {
        if (event is KeyDownEvent || event is KeyRepeatEvent) {
          if (event.logicalKey == LogicalKeyboardKey.arrowLeft) {
            _jumpToMove(
              (_isTrialMode ? _trialMoveCount : _currentMoveCount) - 1,
            );
          } else if (event.logicalKey == LogicalKeyboardKey.arrowRight) {
            _jumpToMove(
              (_isTrialMode ? _trialMoveCount : _currentMoveCount) + 1,
            );
          }
        }
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF1A1A1A),
        appBar: AppBar(
          title: const Text("LogosGo", style: TextStyle(color: Colors.white)),
          backgroundColor: Colors.black,
          elevation: 0,
          actions: [
            TextButton.icon(
              onPressed: _importSGF,
              icon: const Icon(Icons.upload_file, color: Colors.amber),
              label: const Text(
                "匯入 SGF",
                style: TextStyle(color: Colors.amber),
              ),
            ),
            const SizedBox(width: 12),
          ],
        ),
        body: LayoutBuilder(
          builder: (context, constraints) {
            final viewport = Size(constraints.maxWidth, constraints.maxHeight);
            final result = _positionAnalysisResult;
            final panelOffset = _clampPositionPanelOffset(
              _positionPanelOffset ?? _defaultPositionPanelOffset(viewport),
              viewport,
            );
            return Stack(
              children: [
                Positioned.fill(
                  child: Row(
                    children: [
                      // 左側：棋盤與控制
                      Expanded(
                        flex: 3,
                        child: Column(
                          children: [
                            Expanded(child: _buildGoBoard()),
                            _buildMoveController(),
                            const SizedBox(height: 8),
                          ],
                        ),
                      ),

                      // 右側：解說面板
                      Expanded(
                        flex: 1,
                        child: Container(
                          margin: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: const Color(0xFF252525),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: Colors.amber.withOpacity(0.3),
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(16),
                                decoration: const BoxDecoration(
                                  color: Colors.amber,
                                  borderRadius: BorderRadius.vertical(
                                    top: Radius.circular(10),
                                  ),
                                ),
                                child: const Text(
                                  "老狗 AI 評價",
                                  style: TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 18,
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.all(16.0),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 10,
                                    vertical: 5,
                                  ),
                                  decoration: BoxDecoration(
                                    color: Colors.amber.withOpacity(0.2),
                                    borderRadius: BorderRadius.circular(5),
                                  ),
                                  child: Text(
                                    _currentTag,
                                    style: const TextStyle(
                                      color: Colors.amber,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.fromLTRB(
                                  16,
                                  0,
                                  16,
                                  10,
                                ),
                                child: SizedBox(
                                  width: double.infinity,
                                  child: _isGameAnalyzing
                                      ? OutlinedButton.icon(
                                          onPressed: _cancelCurrentGameAnalysis,
                                          icon: const Icon(
                                            Icons.stop_circle_outlined,
                                          ),
                                          label: const Text("取消整盤分析"),
                                          style: OutlinedButton.styleFrom(
                                            foregroundColor:
                                                Colors.orangeAccent,
                                          ),
                                        )
                                      : ElevatedButton.icon(
                                          onPressed:
                                              _currentMoveCount > 0 &&
                                                  _currentMoveCount <=
                                                      _moveAnalyses.length &&
                                                  !_isTrialMode &&
                                                  !_isQuestionLoading
                                              ? _askWhyCurrentMove
                                              : null,
                                          icon: _isQuestionLoading
                                              ? const SizedBox(
                                                  width: 14,
                                                  height: 14,
                                                  child:
                                                      CircularProgressIndicator(
                                                        strokeWidth: 2,
                                                        color: Colors.black,
                                                      ),
                                                )
                                              : const Icon(Icons.help_outline),
                                          label: Text(
                                            _questionCommentaryCache
                                                    .containsKey(
                                                      _currentMoveCount,
                                                    )
                                                ? "查看已快取講解"
                                                : "提問／為什麼？",
                                          ),
                                          style: ElevatedButton.styleFrom(
                                            backgroundColor: Colors.amber,
                                            foregroundColor: Colors.black,
                                          ),
                                        ),
                                ),
                              ),
                              Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  TextButton(
                                    onPressed: () => setState(
                                      () => _showBlackWinrate = true,
                                    ),
                                    child: Text(
                                      "黑棋勝率",
                                      style: TextStyle(
                                        color: _showBlackWinrate
                                            ? Colors.black
                                            : Colors.white38,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    style: TextButton.styleFrom(
                                      backgroundColor: _showBlackWinrate
                                          ? Colors.amber
                                          : Colors.transparent,
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  TextButton(
                                    onPressed: () => setState(
                                      () => _showBlackWinrate = false,
                                    ),
                                    child: Text(
                                      "白棋勝率",
                                      style: TextStyle(
                                        color: !_showBlackWinrate
                                            ? Colors.black
                                            : Colors.white38,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    style: TextButton.styleFrom(
                                      backgroundColor: !_showBlackWinrate
                                          ? Colors.amber
                                          : Colors.transparent,
                                    ),
                                  ),
                                ],
                              ),
                              // 勝率圖
                              SizedBox(
                                height: 145,
                                child: _buildWinrateChart(),
                              ),
                              const Divider(color: Colors.white24, height: 1),
                              // 手數資訊
                              Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                ),
                                child: Text(
                                  "第 $_currentMoveCount 手 / 共 ${_history.length} 手",
                                  style: const TextStyle(
                                    color: Colors.white54,
                                    fontSize: 13,
                                  ),
                                ),
                              ),
                              const SizedBox(height: 8),
                              Expanded(
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 16.0,
                                  ),
                                  child: SingleChildScrollView(
                                    child: Text(
                                      _currentCommentary,
                                      style: const TextStyle(
                                        color: Colors.white70,
                                        fontSize: 17,
                                        height: 1.5,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                              const Padding(
                                padding: EdgeInsets.all(16.0),
                                child: Text(
                                  "Powered by LogosEngine",
                                  style: TextStyle(
                                    color: Colors.grey,
                                    fontSize: 10,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                if (result != null)
                  Positioned(
                    left: panelOffset.dx,
                    top: panelOffset.dy,
                    child: _buildPositionAnalysisPanel(result, viewport),
                  ),
              ],
            );
          },
        ),
      ),
    );
  }

  // --- 棋盤組件（使用 GlobalKey）---
  Widget _buildGoBoard() {
    return LayoutBuilder(
      builder: (context, constraints) {
        // 取寬高較小的那邊，確保棋盤是正方形且不超出範圍
        double boardSize =
            (constraints.maxWidth < constraints.maxHeight
                ? constraints.maxWidth
                : constraints.maxHeight) -
            16;
        return Center(
          child: Container(
            padding: const EdgeInsets.all(8.0),
            decoration: BoxDecoration(
              color: const Color(0xFFD2B48C),
              borderRadius: BorderRadius.circular(8),
              boxShadow: [
                BoxShadow(color: Colors.black.withOpacity(0.5), blurRadius: 10),
              ],
            ),
            // ★ GestureDetector 包住 CustomPaint，onTapUp 改用 _handleTap
            child: GestureDetector(
              onTapUp: _handleTap,
              child: CustomPaint(
                key: _boardKey, // ★ 綁定 GlobalKey
                size: Size(boardSize, boardSize),
                painter: GoBoardPainter(
                  stones: _stones,
                  ownership: _ownership,
                  ownershipStdev: _ownershipStdev,
                  lastMoveIndex: _isTrialMode
                      ? _trialMoveCount
                      : _currentMoveCount,
                  showNumbers: _showMoveNumbers,
                  isTrialMode: _isTrialMode,
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  // --- 勝率圖表 ---
  Widget _buildWinrateChart() {
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 16, 20, 8),
      child: LineChart(
        LineChartData(
          extraLinesData: ExtraLinesData(
            horizontalLines: [
              HorizontalLine(
                y: 0.5,
                color: Colors.white54,
                strokeWidth: 2,
                dashArray: null, // 實線
              ),
            ],
          ),
          gridData: const FlGridData(show: false), // 刪除所有格線
          minY: 0,
          maxY: 1,
          minX: 0,
          maxX: _winrateSpots.length > 1
              ? (_winrateSpots.length - 1).toDouble()
              : 10,
          lineBarsData: [
            LineChartBarData(
              spots: _showBlackWinrate
                  ? _winrateSpots
                  : _winrateSpots.map((e) => FlSpot(e.x, 1 - e.y)).toList(),
              isCurved: true,
              color: Colors.greenAccent,
              barWidth: 2,
              dotData: FlDotData(
                show: true,
                getDotPainter: (s, p, b, i) {
                  int moveIndex = s.x.toInt();
                  return FlDotCirclePainter(
                    radius: _blunderMoves.contains(moveIndex) ? 4 : 0,
                    color: Colors.red,
                  );
                },
              ),
            ),
            LineChartBarData(
              spots: _winrateSpots.length > _currentMoveCount
                  ? [
                      _showBlackWinrate
                          ? _winrateSpots[_currentMoveCount]
                          : FlSpot(
                              _winrateSpots[_currentMoveCount].x,
                              1 - _winrateSpots[_currentMoveCount].y,
                            ),
                    ]
                  : [],
              barWidth: 0,
              dotData: FlDotData(
                show: true,
                getDotPainter: (s, p, b, i) => FlDotCirclePainter(
                  radius: 5,
                  color: Colors.amber,
                  strokeWidth: 2,
                  strokeColor: Colors.white,
                ),
              ),
            ),
          ],
          lineTouchData: LineTouchData(
            touchCallback: (e, r) {
              if (e is FlTapUpEvent && r?.lineBarSpots != null) {
                _jumpToMove(r!.lineBarSpots![0].x.toInt());
              }
            },
            touchTooltipData: LineTouchTooltipData(
              getTooltipItems: (spots) {
                return spots.map((s) {
                  return LineTooltipItem(
                    "${(s.y * 100).toStringAsFixed(2)}%",
                    const TextStyle(color: Colors.white, fontSize: 12),
                  );
                }).toList();
              },
            ),
          ),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            bottomTitles: const AxisTitles(),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                interval: 0.25,
                getTitlesWidget: (value, meta) {
                  return Text(
                    "${(value * 100).toInt()}%",
                    style: const TextStyle(color: Colors.white54, fontSize: 10),
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  // ★ 手順控制列（五個按鈕 + 輸入框）
  Widget _buildMoveController() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
      color: Colors.black45,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // 跳到第 0 手
            _navBtn(Icons.first_page, "第0手", () => _jumpToMove(0)),
            // 往前跳 5 手
            _navBtn(
              Icons.fast_rewind,
              "-5",
              () => _jumpToMove(
                (_isTrialMode ? _trialMoveCount : _currentMoveCount) - 5,
              ),
            ),
            _navBtn(
              Icons.chevron_left,
              "-1",
              () => _jumpToMove(
                (_isTrialMode ? _trialMoveCount : _currentMoveCount) - 1,
              ),
            ),
            // 輸入數字跳到指定手順
            SizedBox(
              width: 64,
              child: TextField(
                controller: _jumpController,
                style: const TextStyle(color: Colors.white, fontSize: 14),
                textAlign: TextAlign.center,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  hintText:
                      "${_isTrialMode ? _trialMoveCount : _currentMoveCount}",
                  hintStyle: const TextStyle(color: Colors.white38),
                  isDense: true,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 8,
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(
                      color: Colors.greenAccent.withOpacity(0.5),
                    ),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: Colors.greenAccent),
                    borderRadius: BorderRadius.circular(6),
                  ),
                ),
                onSubmitted: (v) {
                  _jumpToMove(int.tryParse(v) ?? _currentMoveCount);
                  _jumpController.clear();
                },
              ),
            ),
            _navBtn(
              Icons.chevron_right,
              "+1",
              () => _jumpToMove(
                (_isTrialMode ? _trialMoveCount : _currentMoveCount) + 1,
              ),
            ),
            _navBtn(
              Icons.fast_forward,
              "+5",
              () => _jumpToMove(
                (_isTrialMode ? _trialMoveCount : _currentMoveCount) + 5,
              ),
            ),
            _navBtn(
              Icons.last_page,
              "最後",
              () => _jumpToMove(
                _isTrialMode ? _trialHistory.length : _history.length,
              ),
            ),
            // 顯示手順 Switch
            const SizedBox(width: 16),
            const Text(
              "手順",
              style: TextStyle(color: Colors.white70, fontSize: 13),
            ),
            Switch(
              value: _showMoveNumbers,
              onChanged: (v) => setState(() => _showMoveNumbers = v),
              activeColor: Colors.greenAccent,
            ),
            const SizedBox(width: 16),
            ElevatedButton(
              onPressed: () {
                setState(() {
                  if (_isTrialMode) {
                    // 結束試下：恢復原棋譜狀態
                    _isTrialMode = false;
                    _trialHistory.clear();
                    _trialMoves.clear();
                    _trialMoveCount = 0;
                    if (_currentMoveCount > 0) {
                      _stones = Map.from(_history[_currentMoveCount - 1]);
                    } else {
                      _stones = Map.from(_initialStones);
                    }
                    _isBlack = _isBlackToMove(_currentMoveCount);
                  } else {
                    // 進入試下
                    _isTrialMode = true;
                    _trialHistory.clear();
                    _trialMoves.clear();
                    _trialMoveCount = 0;
                  }
                  _invalidatePositionAnalysis();
                });
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: _isTrialMode
                    ? Colors.redAccent
                    : Colors.blueGrey,
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
              ),
              child: Text(
                _isTrialMode ? "結束試下" : "試下",
                style: const TextStyle(color: Colors.white, fontSize: 13),
              ),
            ),
            const SizedBox(width: 12),
            ElevatedButton(
              onPressed: _isPositionAnalyzing ? null : _analyzeCurrentPosition,
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blueGrey,
                disabledBackgroundColor: Colors.blueGrey.withValues(
                  alpha: 0.55,
                ),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
              ),
              child: _isPositionAnalyzing
                  ? const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        ),
                        SizedBox(width: 7),
                        Text(
                          "分析中",
                          style: TextStyle(color: Colors.white, fontSize: 13),
                        ),
                      ],
                    )
                  : const Text(
                      "形勢判斷",
                      style: TextStyle(color: Colors.white, fontSize: 13),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _navBtn(IconData icon, String label, VoidCallback onPressed) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          icon: Icon(icon, color: Colors.greenAccent),
          onPressed: onPressed,
          padding: const EdgeInsets.all(4),
          constraints: const BoxConstraints(),
        ),
        Text(
          label,
          style: const TextStyle(color: Colors.white54, fontSize: 10),
        ),
      ],
    );
  }
}

// --- GoBoardPainter（padding 比例與 _handleTap 保持一致）---
class GoBoardPainter extends CustomPainter {
  final Map<String, StoneInfo> stones;
  final List<double>? ownership;
  final List<double>? ownershipStdev;
  final bool showNumbers;
  final int lastMoveIndex;
  final bool isTrialMode;

  GoBoardPainter({
    required this.stones,
    this.ownership,
    this.ownershipStdev,
    required this.showNumbers,
    required this.lastMoveIndex,
    this.isTrialMode = false,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // ★ padding 比例改為 0.06，與 _handleTap 計算一致
    double padding = size.width * 0.06;
    double step = (size.width - padding * 2) / 18;

    // 棋盤底色
    canvas.drawRect(
      Rect.fromLTWH(0, 0, size.width, size.height),
      Paint()..color = const Color(0xFFE3C193),
    );

    final lp = Paint()
      ..color = Colors.black
      ..strokeWidth = 1;

    // 畫線 + 座標標記
    for (int i = 0; i < 19; i++) {
      double pos = padding + i * step;
      canvas.drawLine(
        Offset(padding, pos),
        Offset(size.width - padding, pos),
        lp,
      );
      canvas.drawLine(
        Offset(pos, padding),
        Offset(pos, size.height - padding),
        lp,
      );
      _drawTxt(
        canvas,
        'ABCDEFGHJKLMNOPQRST'[i],
        Offset(pos, size.height - padding / 2),
        10,
      );
      _drawTxt(canvas, (19 - i).toString(), Offset(padding / 2, pos), 10);
    }

    // 星位
    for (var x in [3, 9, 15]) {
      for (var y in [3, 9, 15]) {
        canvas.drawCircle(
          Offset(padding + x * step, padding + y * step),
          3,
          Paint(),
        );
      }
    }

    // KataGo ownership 依 A19→T1 的 row-major 順序回傳，正好對應
    // painter 的 y=0→18（由上到下）。只標示高於 0.60 的明確控制點。
    final ownershipData = ownership;
    if (ownershipData != null && ownershipData.length == 361) {
      final squareSize = step * 0.27;
      for (int y = 0; y < 19; y++) {
        for (int x = 0; x < 19; x++) {
          if (stones.containsKey("$x,$y")) continue;
          final value = ownershipData[ownershipIndex(x, y)];
          if (value.abs() < ownershipDisplayThreshold) continue;

          final center = Offset(padding + x * step, padding + y * step);
          final rect = Rect.fromCenter(
            center: center,
            width: squareSize,
            height: squareSize,
          );
          _drawOwnershipSquare(canvas, rect, isBlack: value > 0);
        }
      }
    }

    // 棋子
    stones.forEach((k, info) {
      // 試下模式下，info.moveNumber 是從 1 開始計算的 trialMoveCount
      // 一般模式下，是 _currentMoveCount
      // 由於 _stones 已經是當前狀態的 snapshot，我們其實不需要用 moveNumber 來過濾不顯示的棋子
      // 因為 _stones 裡面的就是 "現在該顯示的棋子"
      // 原本的過濾會導致試下模式下，原本盤面上的棋子 (moveNumber > trialMoveCount) 被隱藏
      var pos = k.split(',').map(int.parse).toList();
      double cx = padding + pos[0] * step;
      double cy = padding + pos[1] * step;

      canvas.drawCircle(
        Offset(cx, cy),
        step * 0.45,
        Paint()..color = info.color,
      );
      if (info.color == Colors.white) {
        canvas.drawCircle(
          Offset(cx, cy),
          step * 0.45,
          Paint()
            ..color = Colors.black
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1,
        );
      }
      // 最後一手標記（紅圈）
      // 由於試下模式的手數會與實戰手數重疊，單純用 moveNumber 判斷會導致實戰中的同手數棋子也被標記。
      // 最安全的做法是直接比對 key 是否為 stones 的最後一個 key（因為 Map 會保留插入順序，最後落子的一定在最後面）
      bool isLast = (k == stones.keys.last);

      if (isLast) {
        canvas.drawCircle(
          Offset(cx, cy),
          step * 0.25,
          Paint()
            ..color = Colors.red
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2,
        );
      }
      if (showNumbers) {
        // 如果是試下模式，我們只顯示「試下新增」的棋子手數。
        // 由於試下模式的棋子 moveNumber 是從 1 重新計算的，而原本盤面上的棋子 moveNumber 是實戰手數（通常很大）。
        // 因此我們可以用這個特性：如果 isTrialMode，且 info.moveNumber <= 試下的總手數，才顯示數字。
        // 更嚴謹的做法是比對 _trialMoveCount，但 Painter 沒有傳入 _trialMoveCount。
        // 沒關係，因為試下模式的棋子是在 _history 的基礎上「附加」上去的，
        // 我們可以傳入一個標記來判斷這顆棋子是不是「試下」的棋子。
        // 最簡單的方法是：在試下模式時，我們只畫最後這幾顆棋子的數字。
        // 這裡用一個簡單的邏輯：如果 isTrialMode 為 true，且這顆棋子是屬於試下分支的（這裡我們假設傳進來的 stones 裡面，
        // 實戰棋子的 moveNumber 會大於試下棋子的 moveNumber，但這樣判斷不準確）。

        // ★ 修正：為了讓試下模式只顯示試下手數，我們在 _handleTap 寫入試下棋子時，
        // 可以給它的 moveNumber 加上一個特殊的 offset（例如 10000），或者直接在 painter 裡判斷。
        // 但其實最簡單的做法是，我們知道在試下模式中，實戰棋子是從 _lastBoardState 繼承來的，
        // 它們的 moveNumber 是實戰的手數。而試下新下的棋子 moveNumber 是 1, 2, 3...
        // 所以如果在試下模式，我們只顯示 moveNumber 小於等於當前盤面上所有棋子數量（或者直接不顯示大於某個值的）？
        // 不對，實戰可能只有 5 手，試下也下了 5 手，這樣無法區分。

        // 正確解法：如果 isTrialMode，我們只顯示 info.isTrial == true 的棋子。
        // 但 StoneInfo 目前沒有 isTrial 欄位。
        // 退而求其次：我們傳遞一個 currentMoveCount 給 Painter，代表「進入試下前的實戰手數」。
        // 但 Painter signature 沒改。
        // 我們直接修改這裡：如果 isTrialMode，且這顆棋子的 moveNumber <= 1000（假設試下不會超過 1000 手，而實戰我們會把它的 moveNumber 改成負數或隱藏？不對）

        // 讓我們回到 main.dart 狀態：在試下模式中，新下的棋子其 moveNumber 被設定為 _trialMoveCount (1, 2, 3...)
        // 而繼承自實戰的棋子，其 moveNumber 是實戰的 1, 2, 3...
        // 這樣在 Painter 裡面確實無法區分。
        // 所以我們應該只在「非試下模式」顯示所有手數，而在「試下模式」中，我們只顯示「試下手數」。
        // 為了區分，我們可以在 _handleTap 裡面，把試下棋子的 moveNumber 存成負數，畫的時候取絕對值？
        // 這樣太 hacky。

        // 我們用一個簡單的規則：在試下模式，我們「不顯示」實戰棋子的數字。
        // 怎麼知道誰是實戰棋子？實戰棋子是在 `_lastBoardState` 裡面的。
        // 但我們這裡沒有 `_lastBoardState`。
        // 那就乾脆在試下模式時，**全部不顯示數字**，或者只顯示最後一手的紅圈就好，這樣最乾淨！
        // 如果使用者堅持要看試下的 1,2,3，我們就需要改 StoneInfo。
        // 這裡先採用：試下模式下，如果 showNumbers 為 true，我們仍然顯示，但會混淆。
        // 我們修改條件：
        bool shouldShowNum = showNumbers;
        String displayNum = info.moveNumber.toString();

        if (isTrialMode) {
          // 試下模式下，我們只顯示帶有 10000 offset 的棋子數字
          if (info.moveNumber > 10000) {
            shouldShowNum = true;
            displayNum = (info.moveNumber - 10000).toString();
          } else {
            shouldShowNum = false; // 隱藏實戰棋子的數字
          }
        }

        if (shouldShowNum) {
          _drawTxt(
            canvas,
            displayNum,
            Offset(cx, cy),
            9,
            color: info.color == Colors.black ? Colors.white : Colors.black,
          );
        }
      }
    });

    // 死子標記必須在棋子之後繪製，才會位於棋子上層。除了反方
    // ownership >= 0.80，還要求 ownership stdev <= 0.25，避免把
    // 搜尋中仍不確定的棋誤標為死子。
    final stdevData = ownershipStdev;
    if (ownershipData != null &&
        ownershipData.length == 361 &&
        stdevData != null &&
        stdevData.length == 361) {
      final markerSize = step * 0.30;
      stones.forEach((key, stone) {
        final position = key.split(',').map(int.parse).toList();
        final x = position[0];
        final y = position[1];
        final index = ownershipIndex(x, y);
        final value = ownershipData[index];
        final stdev = stdevData[index];
        final isBlackStone = stone.color == Colors.black;
        if (!shouldShowDeadStoneMarker(
          isBlackStone: isBlackStone,
          ownership: value,
          ownershipStdev: stdev,
        )) {
          return;
        }

        final center = Offset(padding + x * step, padding + y * step);
        final rect = Rect.fromCenter(
          center: center,
          width: markerSize,
          height: markerSize,
        );
        _drawOwnershipSquare(canvas, rect, isBlack: !isBlackStone);
      });
    }
  }

  void _drawOwnershipSquare(Canvas canvas, Rect rect, {required bool isBlack}) {
    canvas.drawRect(
      rect,
      Paint()
        ..color = isBlack
            ? Colors.black.withValues(alpha: 0.90)
            : Colors.white.withValues(alpha: 0.97),
    );
    canvas.drawRect(
      rect,
      Paint()
        ..color = isBlack ? Colors.white54 : Colors.black54
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.7,
    );
  }

  void _drawTxt(
    Canvas c,
    String t,
    Offset p,
    double s, {
    Color color = Colors.black,
  }) {
    final tp = TextPainter(
      text: TextSpan(
        text: t,
        style: TextStyle(
          color: color,
          fontSize: s,
          fontWeight: FontWeight.bold,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, Offset(p.dx - tp.width / 2, p.dy - tp.height / 2));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
