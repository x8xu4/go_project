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
  runApp(const MaterialApp(
    debugShowCheckedModeBanner: false,
    home: GoBoardPage(),
  ));
}

class StoneInfo {
  final Color color;
  final int moveNumber;
  StoneInfo(this.color, this.moveNumber);
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
  final List<Map<String, StoneInfo>> _history = [];
  String? _lastBoardState;
  bool _isBlack = true;
  bool _showMoveNumbers = false;
  int _currentMoveCount = 0;
  final FocusNode _focusNode = FocusNode();
  bool _showBlackWinrate = true; // true = 黑棋勝率，false = 白棋勝率
  bool _isTrialMode = false;
  List<Map<String, StoneInfo>> _trialHistory = [];
  int _trialMoveCount = 0;

  // ★ 修正落子偏移：用 GlobalKey 取得棋盤的真實位置
  final GlobalKey _boardKey = GlobalKey();
  final TextEditingController _jumpController = TextEditingController();
  final List<List<int>> _directions = [
    [0, 1],
    [0, -1],
    [1, 0],
    [-1, 0]
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

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("正在載入 $fileName ...")),
      );

      // ★ 本地解析 SGF，不需要後端也能顯示棋譜
      _parseSGFLocally(sgfContent);

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("棋譜載入完成！")),
      );
    } catch (e) {
      debugPrint("載入失敗: $e");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("載入失敗: $e")),
        );
      }
    }
  }

  // ★ 本地 SGF 解析：把棋譜一步步重建成 _history
  Future <void> _parseSGFLocally(String sgf) async {
    Map<String, StoneInfo> currentStones = {};
    List<Map<String, StoneInfo>> newHistory = [];
    int moveNum = 0;
    String lastCoord = '';

    final moveRegex = RegExp(r'\(;([BW])\[([a-s]{0,2})\]');

    // 單獨抓第一手（格式是 ;B[ 不是 (;B[）
    final firstMoveRegex = RegExp(r';([BW])\[([a-s]{2})\]');
    final firstMatch = firstMoveRegex.firstMatch(sgf);

    // 把第一手位置記下來，之後間距從這裡算
    int lastPos = firstMatch?.start ?? 0;

    // 先處理第一手
    final List<RegExpMatch> allMatches = [];
    if (firstMatch != null) allMatches.add(firstMatch);

    // 再加上後面 (;B[ 格式的落子，但要排除跟第一手重複的
    for (final m in moveRegex.allMatches(sgf)) {
      if (m.start > lastPos) allMatches.add(m);
    }

    final matches = allMatches;

    for (final match in matches) {
      final colorChar = match.group(1)!;
      final coord = match.group(2)!;

      // ★ 間距超過 50 代表進入變化圖注釋區，停止解析
      if (lastPos != 0 && (match.start - lastPos) > 200){
      debugPrint("間距中斷在第${moveNum+1}手，間距${match.start - lastPos}，座標$coord");
      break;
      } 
      lastPos = match.start;

      bool expectedBlack = (moveNum % 2 == 0);
      bool isBlackMove = colorChar == 'B';
if (moveNum > 0 && expectedBlack != isBlackMove) {
  debugPrint("顏色不交替中斷：第${moveNum+1}手 應該${expectedBlack ? '黑' : '白'}但是$colorChar");
  break;
}

      // ★ 同座標連續出現代表進入變化圖，停止
      if (newHistory.isNotEmpty && coord == lastCoord){
      debugPrint("重複座標中斷在第${moveNum+1}手，座標$coord");
      break;
      } 
      lastCoord = coord;

      if (coord.isEmpty || coord.length < 2) continue; // pass

      int x = coord.codeUnitAt(0) - 'a'.codeUnitAt(0);
      int y = coord.codeUnitAt(1) - 'a'.codeUnitAt(0);

      if (x < 0 || x >= 19 || y < 0 || y >= 19) continue;

      Color mine = colorChar == 'B' ? Colors.black : Colors.white;
      Color opp = colorChar == 'B' ? Colors.white : Colors.black;

      String key = "$x,$y";
      if (moveNum >= 203) debugPrint("第${moveNum+1}手: $colorChar[$coord] 位置${match.start}");
      moveNum++;
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
      _currentMoveCount = newHistory.length;
      if (newHistory.isNotEmpty) {
        _stones = Map.from(newHistory.last);
      } else {
        _stones = {};
      }
      _isBlack = (_currentMoveCount % 2 == 0);
      _lastBoardState = null;
      // ★ 先用平線填滿，後端回來後再更新
      _winrateSpots = List.generate(newHistory.length, (i) {
        return FlSpot(i.toDouble(), 0.5);
      });
    });
    await _tryServerAnalysis(sgf);
  }

  Future<void> _tryServerAnalysis(String sgfContent) async {
  try {
    debugPrint("開始連接後端...");
    final response = await http.post(
      Uri.parse('http://127.0.0.1:5001/analyze_sgf'),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"sgf_content": sgfContent}),
    ).timeout(const Duration(seconds: 600));
    debugPrint("後端回應狀態碼: ${response.statusCode}");
    debugPrint("回應內容前100字: ${response.body.substring(0, min(100, response.body.length))}");
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      debugPrint("後端回傳 winrates 長度: ${(data['winrates'] as List).length}");
      setState(() {
        List<dynamic> wrList = data['winrates'];
        _winrateSpots = wrList.asMap().entries.map((e) {
          return FlSpot(e.key.toDouble(), e.value);
        }).toList();
        _blunderMoves = List<int>.from(data['blunders']);
      });
      debugPrint("_winrateSpots 長度: ${_winrateSpots.length}");
      _fetchLogosCommentary(_currentMoveCount);
    }
  } catch (e) {
    debugPrint("後端連線例外: $e");
    setState(() {
      _winrateSpots = List.generate(_history.length, (i) {
        return FlSpot(i.toDouble(), 0.5);
      });
    });
  }
}

  Future<void> _fetchLogosCommentary(int moveIndex) async {
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:5001/get_commentary'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "winrate":
              _winrateSpots.length > moveIndex ? _winrateSpots[moveIndex].y : 0.5,
          "winrate_change": moveIndex > 0 && _winrateSpots.length > moveIndex
    ? (_winrateSpots[moveIndex].y - _winrateSpots[moveIndex - 1].y)
    : 0.0,
          "x": 0,
          "y": 0,
        }),
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _currentTag = data['tag'];
          _currentCommentary = data['commentary'];
        });
      }
    } catch (e) {
      debugPrint("解說獲取失敗: $e");
    }
  }

  // --- 2. 核心規則邏輯 ---
  String _getBoardSnapshot(Map<String, StoneInfo> stones) {
    var sortedKeys = stones.keys.toList()..sort();
    return sortedKeys
        .map((k) =>
            "$k:${stones[k]!.color == Colors.black ? 'B' : 'W'}")
        .join("|");
  }

  Set<String> _getLiberties(
      int startX, int startY, Color color, Map<String, StoneInfo> currentStones) {
    if (!currentStones.containsKey("$startX,$startY") ||
        currentStones["$startX,$startY"]!.color != color) return {"dummy"};
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
      int startX, int startY, Color color, Map<String, StoneInfo> currentStones) {
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
      _trialMoveCount = safeTarget;
      if (safeTarget == 0) {
        // 試下模式跳到0，回到試下起點
        _stones = _history.isNotEmpty ? Map.from(_history[_currentMoveCount - 1]) : {};
        _isBlack = (_currentMoveCount % 2 == 0);
      } else {
        _stones = Map.from(_trialHistory[safeTarget - 1]);
        _isBlack = ((_currentMoveCount + safeTarget) % 2 == 0);
      }
    });
    return;
  }
  int safeTarget = target.clamp(0, _history.length);
  setState(() {
    _currentMoveCount = safeTarget;
    if (safeTarget == 0) {
      _stones = {};
      _isBlack = true;
      _lastBoardState = null;
    } else {
      _stones = Map.from(_history[safeTarget - 1]);
      _isBlack = (safeTarget % 2 == 0);
      _lastBoardState =
          (safeTarget > 1) ? _getBoardSnapshot(_history[safeTarget - 2]) : null;
    }
  });
  _fetchLogosCommentary(safeTarget);
}

  void _resetGame() {
    setState(() {
      _stones = {};
      _history.clear();
      _currentMoveCount = 0;
      _isBlack = true;
      _lastBoardState = null;
    });
  }

  void _undo() {
    if (_currentMoveCount <= 0) return;
    _jumpToMove(_currentMoveCount - 1);
  }

  // ★ 修正落子位置：使用 GlobalKey 取得棋盤真實座標
  void _handleTap(TapUpDetails details) {
    if (!_isTrialMode && _currentMoveCount != _history.length) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text("請跳至最後一手再落子")));
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
            _getBoardSnapshot(next) == _lastBoardState) return;

        setState(() {
          _lastBoardState = _getBoardSnapshot(_stones);
          _stones = next;
          if (_isTrialMode) {
            _trialHistory.add(Map.from(_stones));
            _trialMoveCount++;
          } else {
            _history.add(Map.from(_stones));
            _currentMoveCount++;
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
        _jumpToMove(_currentMoveCount - 1);
      } else if (event.logicalKey == LogicalKeyboardKey.arrowRight) {
        _jumpToMove(_currentMoveCount + 1);
      }
    }
  },
  child:Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        title: const Text("LogosGo",
            style: TextStyle(color: Colors.white)),
        backgroundColor: Colors.black,
        elevation: 0,
        actions: [
          TextButton.icon(
            onPressed: _importSGF,
            icon: const Icon(Icons.upload_file, color: Colors.amber),
            label: const Text("匯入 SGF", style: TextStyle(color: Colors.amber)),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: Row(
        children: [
          // 左側：棋盤與控制
          Expanded(
            flex: 3,
            child: Column(
              children: [
                Expanded(child:_buildGoBoard()),
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
                border: Border.all(color: Colors.amber.withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: const BoxDecoration(
                      color: Colors.amber,
                      borderRadius:
                          BorderRadius.vertical(top: Radius.circular(10)),
                    ),
                    child: const Text(
                      "老狗 AI 評價",
                      style: TextStyle(
                          fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: Colors.amber.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(5),
                      ),
                      child: Text(
                        _currentTag,
                        style: const TextStyle(
                            color: Colors.amber,
                            fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                  Row(
  mainAxisAlignment: MainAxisAlignment.center,
  children: [
    TextButton(
      onPressed: () => setState(() => _showBlackWinrate = true),
      child: Text("黑棋勝率",
          style: TextStyle(
              color: _showBlackWinrate ? Colors.black : Colors.white38,
              fontWeight: FontWeight.bold)),
      style: TextButton.styleFrom(
        backgroundColor: _showBlackWinrate ? Colors.amber : Colors.transparent,
      ),
    ),
    const SizedBox(width: 8),
    TextButton(
      onPressed: () => setState(() => _showBlackWinrate = false),
      child: Text("白棋勝率",
          style: TextStyle(
              color: !_showBlackWinrate ? Colors.black : Colors.white38,
              fontWeight: FontWeight.bold)),
      style: TextButton.styleFrom(
        backgroundColor: !_showBlackWinrate ? Colors.amber : Colors.transparent,
      ),
    ),
  ],
),
                  // 勝率圖
                  SizedBox(height: 200, child: _buildWinrateChart()),
                  const Divider(color: Colors.white24, height: 1),
                  // 手數資訊
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Text(
                      "第 $_currentMoveCount 手 / 共 ${_history.length} 手",
                      style: const TextStyle(color: Colors.white54, fontSize: 13),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: SingleChildScrollView(
                        child: Text(
                          _currentCommentary,
                          style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 17,
                              height: 1.5),
                        ),
                      ),
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.all(16.0),
                    child: Text("Powered by LogosEngine",
                        style:
                            TextStyle(color: Colors.grey, fontSize: 10)),
                  )
                ],
              ),
            ),
          ),
        ],
      ),
      ),
    );
  }

  // --- 棋盤組件（使用 GlobalKey）---
  Widget _buildGoBoard() {
    return LayoutBuilder(
      builder: (context, constraints) {
        // 取寬高較小的那邊，確保棋盤是正方形且不超出範圍
        double boardSize = (constraints.maxWidth < constraints.maxHeight
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
            BoxShadow(
                color: Colors.black.withOpacity(0.5), blurRadius: 10)
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
              lastMoveIndex: _currentMoveCount,
              showNumbers: _showMoveNumbers,
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
          maxX: _winrateSpots.length > 1 ? (_winrateSpots.length - 1).toDouble() : 10,
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
                getDotPainter: (s, p, b, i) => FlDotCirclePainter(
                  radius:
                      _blunderMoves.contains(s.x.toInt()) ? 4 : 0,
                  color: Colors.red,
                ),
              ),
            ),
            LineChartBarData(
    spots: _winrateSpots.length > _currentMoveCount
        ? [_showBlackWinrate
            ? _winrateSpots[_currentMoveCount]
            : FlSpot(_winrateSpots[_currentMoveCount].x,
                1 - _winrateSpots[_currentMoveCount].y)]
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
          lineTouchData: LineTouchData(touchCallback: (e, r) {
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
          _navBtn(Icons.fast_rewind, "-5", () => _jumpToMove((_isTrialMode ? _trialMoveCount : _currentMoveCount) - 5)),
          _navBtn(Icons.chevron_left, "-1", () => _jumpToMove((_isTrialMode ? _trialMoveCount : _currentMoveCount) - 1)),
          // 輸入數字跳到指定手順
          SizedBox(
            width: 64,
            child: TextField(
              controller: _jumpController,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              textAlign: TextAlign.center,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                hintText: "${_isTrialMode ? _trialMoveCount : _currentMoveCount}",
                hintStyle: const TextStyle(color: Colors.white38),
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 8, vertical: 8),
                enabledBorder: OutlineInputBorder(
                  borderSide:
                      BorderSide(color: Colors.greenAccent.withOpacity(0.5)),
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
        _navBtn(Icons.chevron_right, "+1", () => _jumpToMove((_isTrialMode ? _trialMoveCount : _currentMoveCount) + 1)),
        _navBtn(Icons.fast_forward, "+5", () => _jumpToMove((_isTrialMode ? _trialMoveCount : _currentMoveCount) + 5)),
        _navBtn(Icons.last_page, "最後", () => _jumpToMove(_isTrialMode ? _trialHistory.length : _history.length)),
          // 顯示手順 Switch
          const SizedBox(width: 16),
          const Text("手順", style: TextStyle(color: Colors.white70, fontSize: 13)),
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
        _trialMoveCount = 0;
        if (_currentMoveCount > 0) {
          _stones = Map.from(_history[_currentMoveCount - 1]);
        } else {
          _stones = {};
        }
        _isBlack = (_currentMoveCount % 2 == 0);
      } else {
        // 進入試下
        _isTrialMode = true;
        _trialHistory.clear();
        _trialMoveCount = 0;
      }
    });
  },
  style: ElevatedButton.styleFrom(
    backgroundColor: _isTrialMode ? Colors.redAccent : Colors.blueGrey,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
  ),
  child: Text(
    _isTrialMode ? "結束試下" : "試下",
    style: const TextStyle(color: Colors.white, fontSize: 13),
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
        Text(label,
            style: const TextStyle(color: Colors.white54, fontSize: 10)),
      ],
    );
  }
}

// --- GoBoardPainter（padding 比例與 _handleTap 保持一致）---
class GoBoardPainter extends CustomPainter {
  final Map<String, StoneInfo> stones;
  final bool showNumbers;
  final int lastMoveIndex;

  GoBoardPainter({
    required this.stones,
    required this.showNumbers,
    required this.lastMoveIndex,
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
          Offset(padding, pos), Offset(size.width - padding, pos), lp);
      canvas.drawLine(
          Offset(pos, padding), Offset(pos, size.height - padding), lp);
      _drawTxt(canvas, 'ABCDEFGHJKLMNOPQRST'[i],
          Offset(pos, size.height - padding / 2), 10);
      _drawTxt(
          canvas, (19 - i).toString(), Offset(padding / 2, pos), 10);
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

    // 棋子
    stones.forEach((k, info) {
      if (info.moveNumber > lastMoveIndex) return;
      var pos = k.split(',').map(int.parse).toList();
      double cx = padding + pos[0] * step;
      double cy = padding + pos[1] * step;

      canvas.drawCircle(
          Offset(cx, cy), step * 0.45, Paint()..color = info.color);
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
      if (info.moveNumber == lastMoveIndex) {
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
        _drawTxt(
          canvas,
          info.moveNumber.toString(),
          Offset(cx, cy),
          9,
          color: info.color == Colors.black ? Colors.white : Colors.black,
        );
      }
    });
  }

  void _drawTxt(Canvas c, String t, Offset p, double s,
      {Color color = Colors.black}) {
    final tp = TextPainter(
      text: TextSpan(
          text: t,
          style: TextStyle(
              color: color, fontSize: s, fontWeight: FontWeight.bold)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, Offset(p.dx - tp.width / 2, p.dy - tp.height / 2));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}