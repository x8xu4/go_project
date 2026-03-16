import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:convert';
import 'dart:math';
import 'dart:io';
import 'package:http/http.dart' as http;

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

  // ★ 修正落子偏移：用 GlobalKey 取得棋盤的真實位置
  final GlobalKey _boardKey = GlobalKey();
  final TextEditingController _jumpController = TextEditingController();
  final List<List<int>> _directions = [
    [0, 1],
    [0, -1],
    [1, 0],
    [-1, 0]
  ];

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

      // 嘗試連後端分析（失敗也不影響棋譜顯示）
      _tryServerAnalysis(sgfContent);
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
  void _parseSGFLocally(String sgf) {
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
      if (lastPos != 0 && (match.start - lastPos) > 50) break;
      lastPos = match.start;

      // ★ 同座標連續出現代表進入變化圖，停止
      if (newHistory.isNotEmpty && coord == lastCoord) break;
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
    });
  }

  // 嘗試後端分析（失敗靜默處理）
  Future<void> _tryServerAnalysis(String sgfContent) async {
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:5001/analyze_sgf'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"sgf_content": sgfContent}),
      ).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          List<dynamic> wrList = data['winrates'];
          _winrateSpots = wrList.asMap().entries.map((e) {
            return FlSpot(e.key.toDouble(), e.value);
          }).toList();
          _blunderMoves = List<int>.from(data['blunders']);
        });
      }
    } catch (_) {
      // 後端不在線時靜默忽略，棋譜仍可正常瀏覽
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
          "winrate_change": 0,
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
    if (_currentMoveCount != _history.length) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text("請跳至最後一手再落子")));
      return;
    }

    final RenderBox? renderBox =
        _boardKey.currentContext?.findRenderObject() as RenderBox?;
    if (renderBox == null) return;

    // 轉換為棋盤內的本地座標
    Offset localPos = renderBox.globalToLocal(details.globalPosition);

    const double boardSize = 650.0;
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
          _history.add(Map.from(_stones));
          _currentMoveCount++;
          _isBlack = !_isBlack;
        });

        _fetchLogosCommentary(_currentMoveCount);
      }
    }
  }

  // --- 4. UI 構建 ---
  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
                  // 勝率圖
                  SizedBox(height: 140, child: _buildWinrateChart()),
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
    );
  }

  // --- 棋盤組件（使用 GlobalKey + 固定 650 大小）---
  Widget _buildGoBoard() {
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
            size: const Size(650, 650),
            painter: GoBoardPainter(
              stones: _stones,
              lastMoveIndex: _currentMoveCount,
              showNumbers: _showMoveNumbers,
            ),
          ),
        ),
      ),
    );
  }

  // --- 勝率圖表 ---
  Widget _buildWinrateChart() {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: LineChart(
        LineChartData(
          minY: 0,
          maxY: 1,
          lineBarsData: [
            LineChartBarData(
              spots: _winrateSpots,
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
          ],
          lineTouchData: LineTouchData(touchCallback: (e, r) {
            if (e is FlTapUpEvent && r?.lineBarSpots != null) {
              _jumpToMove(r!.lineBarSpots![0].x.toInt());
            }
          }),
          titlesData: const FlTitlesData(
            topTitles: AxisTitles(),
            rightTitles: AxisTitles(),
            bottomTitles: AxisTitles(),
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
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // 跳到第 0 手
          _navBtn(Icons.first_page, "第0手", () => _jumpToMove(0)),
          // 往前跳 5 手
          _navBtn(Icons.fast_rewind, "-5",
              () => _jumpToMove(_currentMoveCount - 5)),
          _navBtn(Icons.chevron_left, "-1", () => _jumpToMove(_currentMoveCount - 1)),
          // 輸入數字跳到指定手順
          SizedBox(
            width: 64,
            child: TextField(
              controller: _jumpController,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              textAlign: TextAlign.center,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                hintText: "$_currentMoveCount",
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
          _navBtn(Icons.chevron_right, "+1", () => _jumpToMove(_currentMoveCount + 1)),
          // 往後跳 5 手
          _navBtn(Icons.fast_forward, "+5",
              () => _jumpToMove(_currentMoveCount + 5)),
          // 跳到最後一手
          _navBtn(
              Icons.last_page, "最後", () => _jumpToMove(_history.length)),
          // 顯示手順 Switch
          const SizedBox(width: 16),
          const Text("手順", style: TextStyle(color: Colors.white70, fontSize: 13)),
          Switch(
            value: _showMoveNumbers,
            onChanged: (v) => setState(() => _showMoveNumbers = v),
            activeColor: Colors.greenAccent,
          ),
        ],
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