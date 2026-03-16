import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:convert';
import 'dart:math';
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
  // --- 狀態變數 ---
  // --- 新增解說狀態 ---
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
  
  final TextEditingController _jumpController = TextEditingController();
  final List<List<int>> _directions = [[0, 1], [0, -1], [1, 0], [-1, 0]];

  // --- 1. SGF 匯入 (Web 安全版) ---
  // --- 1. SGF 匯入 (加上真實連線邏輯) ---
  Future<void> _importSGF() async {
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['sgf'],
        withData: true, 
      );

      if (!mounted) return;

      if (result != null && result.files.first.bytes != null) {
        final fileName = result.files.first.name;
        // 將位元組轉為字串
        String sgfContent = utf8.decode(result.files.first.bytes!);
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("正在上傳 $fileName 至 AI 分析...")),
        );

        // --- 加入 HTTP POST 請求 ---
        final response = await http.post(
          Uri.parse('http://127.0.0.1:5001/analyze_sgf'), // 剛才改的 5001 端口
          headers: {"Content-Type": "application/json"},
          body: jsonEncode({"sgf_content": sgfContent}),
        );

        if (response.statusCode == 200) {
          final data = jsonDecode(response.body);
          setState(() {
            // 從後端回傳的 winrates 列表轉成圖表的 FlSpot
            List<dynamic> wrList = data['winrates'];
            _winrateSpots = wrList.asMap().entries.map((e) {
              return FlSpot(e.key.toDouble(), e.value);
            }).toList();
            
            // 更新敗著手數
            _blunderMoves = List<int>.from(data['blunders']);
          });
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("分析完成！")));
        } else {
          throw Exception("伺服器錯誤: ${response.statusCode}");
        }
      }
    } catch (e) {
      debugPrint("連線或分析失敗: $e");
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("分析失敗: $e")),
      );
    }
  }
  
  Future<void> _fetchLogosCommentary(int moveIndex) async {
    try {
      // (連線邏輯不變...)
      final response = await http.post(
        Uri.parse('http://127.0.0.1:5001/get_commentary'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "winrate": _winrateSpots.length > moveIndex ? _winrateSpots[moveIndex].y : 0.5,
          "winrate_change": 0, // 之後可加入計算
          "x": 0, "y": 0,
        }),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          // 直接更新變數，畫面右側會自動變換文字
          _currentTag = data['tag'];
          _currentCommentary = data['commentary'];
        });
      }
    } catch (e) {
      debugPrint("解說獲取失敗: $e");
    }
  }

  void _generateMockAnalysisData() {
    setState(() {
      _winrateSpots = List.generate(60, (i) {
        double val = 0.5 + (sin(i * 0.15) * 0.4);
        return FlSpot(i.toDouble(), val.clamp(0.0, 1.0));
      });
      _blunderMoves = [20, 42]; 
    });
  }

  // --- 2. 核心規則邏輯 ---
  String _getBoardSnapshot(Map<String, StoneInfo> stones) {
    var sortedKeys = stones.keys.toList()..sort();
    return sortedKeys.map((k) => "$k:${stones[k]!.color == Colors.black ? 'B' : 'W'}").join("|");
  }

  Set<String> _getLiberties(int startX, int startY, Color color, Map<String, StoneInfo> currentStones) {
    if (!currentStones.containsKey("$startX,$startY") || currentStones["$startX,$startY"]!.color != color) return {"dummy"};
    
    Set<String> group = {"$startX,$startY"};
    Set<String> liberties = {};
    List<String> queue = ["$startX,$startY"]; // 確保這裡是用 List
    
    int index = 0;
    while (index < queue.length) {
      String current = queue[index++]; // List 支援 [] 運算子
      List<int> pos = current.split(',').map(int.parse).toList();
      
      for (var dir in _directions) {
        int nx = pos[0] + dir[0], ny = pos[1] + dir[1];
        if (nx < 0 || nx >= 19 || ny < 0 || ny >= 19) continue;
        
        String key = "$nx,$ny";
        if (!currentStones.containsKey(key)) {
          liberties.add(key); // 沒棋子，增加氣
        } else if (currentStones[key]!.color == color && !group.contains(key)) {
          group.add(key);
          queue.add(key); // 同色棋子，加入群組繼續搜尋
        }
      }
    }
    return liberties;
  }

  void _removeGroup(int startX, int startY, Color color, Map<String, StoneInfo> currentStones) {
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
        if (currentStones.containsKey(key) && currentStones[key]!.color == color && !visited.contains(key)) {
          visited.add(key); queue.add(key);
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
        _stones = {}; _isBlack = true; _lastBoardState = null;
      } else {
        _stones = Map.from(_history[safeTarget - 1]);
        _isBlack = (safeTarget % 2 == 0);
        _lastBoardState = (safeTarget > 1) ? _getBoardSnapshot(_history[safeTarget - 2]) : null;
      }
    });
  }

  void _handleTap(TapUpDetails details, BuildContext boardContext) {
    if (_currentMoveCount != _history.length) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("請跳至最後一手再落子")));
      return;
    }
    RenderBox renderBox = boardContext.findRenderObject() as RenderBox;
    Offset localPos = renderBox.globalToLocal(details.globalPosition);
    double padding = renderBox.size.width * 0.08, step = (renderBox.size.width - padding * 2) / 18;
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
            if (_getLiberties(nx, ny, opp, next).isEmpty) { _removeGroup(nx, ny, opp, next); captured = true; }
          }
        }
        if (!captured && _getLiberties(x, y, mine, next).isEmpty) return;
        if (_lastBoardState != null && _getBoardSnapshot(next) == _lastBoardState) return;

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
  // --- 4. UI 構建 ---
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        title: const Text("老狗圍棋分析 LogosGo", style: TextStyle(color: Colors.white)),
        backgroundColor: Colors.black,
        elevation: 0,
      ),
      body: Row( // <-- 改成 Row 進行左右佈局
        children: [
          // 左側：棋盤與圖表 (佔據剩餘空間)
          Expanded(
            flex: 3, // 比例 3
            child: SingleChildScrollView(
              child: Column(
                children: [
                  _buildWinrateChart(), // 勝率圖表
                  const SizedBox(height: 20),
                  _buildGoBoard(),      // 棋盤
                  const SizedBox(height: 20),
                  _buildControls(),     // 控制按鈕
                  const SizedBox(height: 40),
                ],
              ),
            ),
          ),
          
          // 右側：老狗解說面板 (固定寬度或比例)
          Expanded(
            flex: 1, // 比例 1
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
                  // 標題欄
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: const BoxDecoration(
                      color: Colors.amber,
                      borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
                    ),
                    child: const Text(
                      "老狗 AI 評價",
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                  ),
                  // 評價標籤 (Tag)
                  Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: Colors.amber.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(5),
                      ),
                      child: Text(
                        _currentTag,
                        style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                  // 解說文字 (Commentary)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: SingleChildScrollView(
                        child: Text(
                          _currentCommentary,
                          style: const TextStyle(color: Colors.white70, fontSize: 17, height: 1.5),
                        ),
                      ),
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.all(16.0),
                    child: Text("Powered by LogosEngine", style: TextStyle(color: Colors.grey, fontSize: 10)),
                  )
                ],
              ),
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _importSGF,
        icon: const Icon(Icons.upload),
        label: const Text("匯入 SGF"),
        backgroundColor: Colors.amber,
      ),
    );
  }
  
  // --- 棋盤組件 ---
  Widget _buildGoBoard() {
    return Center(
      child: Container(
        padding: const EdgeInsets.all(8.0),
        decoration: BoxDecoration(
          color: const Color(0xFFD2B48C), // 棋盤木色
          borderRadius: BorderRadius.circular(8),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.5), blurRadius: 10)],
        ),
        child: GestureDetector(
          onTapUp: (details) => _handleTap(details, context),
          child: CustomPaint(
            size: const Size(500, 500), // 棋盤大小
            painter: GoBoardPainter(stones: _stones,
  lastMoveIndex: _currentMoveCount,
  showNumbers: _showMoveNumbers,),
          ),
        ),
      ),
    );
  }

  // --- 勝率圖表組件 ---
  Widget _buildWinrateChart() {
    return Container(
      height: 200,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: LineChart(
        LineChartData(
          minY: 0, maxY: 1,
          lineBarsData: [
            LineChartBarData(
              spots: _winrateSpots,
              isCurved: true,
              color: Colors.greenAccent,
              barWidth: 3,
              dotData: const FlDotData(show: false),
            ),
          ],
          // ... 其他圖表設定
        ),
      ),
    );
  }

  // --- 控制按鈕組件 ---
  Widget _buildControls() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        IconButton(icon: const Icon(Icons.skip_previous, color: Colors.white), onPressed: _resetGame),
        IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), onPressed: _undo),
        Text("第 $_currentMoveCount 手", style: const TextStyle(color: Colors.white)),
        IconButton(icon: const Icon(Icons.arrow_forward, color: Colors.white), onPressed: () {}),
        const SizedBox(width: 20),
        const Text("顯示手順", style: TextStyle(color: Colors.white)),
        Switch(value: _showMoveNumbers, onChanged: (v) => setState(() => _showMoveNumbers = v)),
      ],
    );
  }

  Widget _buildSidePanel() {
    return Container(
      width: 320, color: Colors.grey[900],
      child: Column(children: [
        Container(height: 220, padding: const EdgeInsets.fromLTRB(10, 30, 20, 10), child: _buildChart()),
        const Divider(color: Colors.white24),
        Expanded(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text("分析區", style: TextStyle(color: Colors.amber, fontWeight: FontWeight.bold)),
          const SizedBox(height: 10),
          Text("當前手數: $_currentMoveCount", style: const TextStyle(color: Colors.white70)),
          Text("總手數: ${_history.length}", style: const TextStyle(color: Colors.white70)),
          const Spacer(),
          ElevatedButton(onPressed: () => setState(() => _showMoveNumbers = !_showMoveNumbers), child: const Text("切換手數顯示")),
          const SizedBox(height: 8),
          ElevatedButton(onPressed: () => setState(() { _stones={}; _history.clear(); _currentMoveCount=0; }), style: ElevatedButton.styleFrom(backgroundColor: Colors.red[900]), child: const Text("清空棋盤")),
        ]))),
      ]),
    );
  }

  Widget _buildChart() {
    return LineChart(LineChartData(
      minY: 0, maxY: 1,
      lineBarsData: [LineChartBarData(
        spots: _winrateSpots, isCurved: true, color: Colors.greenAccent, barWidth: 2,
        dotData: FlDotData(show: true, getDotPainter: (s, p, b, i) => FlDotCirclePainter(radius: _blunderMoves.contains(s.x.toInt()) ? 4 : 0, color: Colors.red)),
      )],
      lineTouchData: LineTouchData(touchCallback: (e, r) {
        if (e is FlTapUpEvent && r?.lineBarSpots != null) _jumpToMove(r!.lineBarSpots![0].x.toInt());
      }),
      titlesData: const FlTitlesData(topTitles: AxisTitles(), rightTitles: AxisTitles(), bottomTitles: AxisTitles()),
    ));
  }

  Widget _buildMoveController() {
    return Container(
      height: 70, color: Colors.black45,
      child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        _navBtn(Icons.first_page, () => _jumpToMove(0)),
        _navBtn(Icons.fast_rewind, () => _jumpToMove(_currentMoveCount - 10)), // 恢復快退
        _navBtn(Icons.chevron_left, () => _jumpToMove(_currentMoveCount - 1)),
        _navBtn(Icons.chevron_right, () => _jumpToMove(_currentMoveCount + 1)),
        _navBtn(Icons.fast_forward, () => _jumpToMove(_currentMoveCount + 10)), // 恢復快進
        _navBtn(Icons.last_page, () => _jumpToMove(_history.length)),
        const SizedBox(width: 10),
        SizedBox(width: 50, child: TextField(
          controller: _jumpController, style: const TextStyle(color: Colors.white), 
          decoration: const InputDecoration(hintText: "GO", hintStyle: TextStyle(color: Colors.white24)),
          onSubmitted: (v) => _jumpToMove(int.tryParse(v) ?? 0),
        )),
      ]),
    );
  }

  Widget _navBtn(IconData i, VoidCallback o) => IconButton(icon: Icon(i, color: Colors.greenAccent), onPressed: o);
}

class GoBoardPainter extends CustomPainter {
  final Map<String, StoneInfo> stones;
  final bool showNumbers;
  final int lastMoveIndex;
  GoBoardPainter({required this.stones, required this.showNumbers, required this.lastMoveIndex});

  @override
  void paint(Canvas canvas, Size size) {
    double padding = size.width * 0.08, step = (size.width - padding * 2) / 18;
    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, size.height), Paint()..color = const Color(0xFFE3C193));
    final lp = Paint()..color = Colors.black..strokeWidth = 1;

    for (int i = 0; i < 19; i++) {
      double pos = padding + i * step;
      canvas.drawLine(Offset(padding, pos), Offset(size.width - padding, pos), lp);
      canvas.drawLine(Offset(pos, padding), Offset(pos, size.height - padding), lp);
      _drawTxt(canvas, 'ABCDEFGHJKLMNOPQRST'[i], Offset(pos, size.height - padding/2), 10);
      _drawTxt(canvas, (19 - i).toString(), Offset(padding/2, pos), 10);
    }
    for (var x in [3, 9, 15]) for (var y in [3, 9, 15]) canvas.drawCircle(Offset(padding + x * step, padding + y * step), 3, Paint());

    stones.forEach((k, info) {
      if (info.moveNumber > lastMoveIndex) return;
      var pos = k.split(',').map(int.parse).toList();
      double cx = padding + pos[0] * step, cy = padding + pos[1] * step;
      canvas.drawCircle(Offset(cx, cy), step * 0.45, Paint()..color = info.color);
      if (info.color == Colors.white) canvas.drawCircle(Offset(cx, cy), step * 0.45, Paint()..color = Colors.black..style = PaintingStyle.stroke);
      if (info.moveNumber == lastMoveIndex) canvas.drawCircle(Offset(cx, cy), step * 0.25, Paint()..color = Colors.red..style = PaintingStyle.stroke..strokeWidth = 2);
      if (showNumbers) _drawTxt(canvas, info.moveNumber.toString(), Offset(cx, cy), 9, color: info.color == Colors.black ? Colors.white : Colors.black);
    });
  }

  void _drawTxt(Canvas c, String t, Offset p, double s, {Color color = Colors.black}) {
    final tp = TextPainter(text: TextSpan(text: t, style: TextStyle(color: color, fontSize: s, fontWeight: FontWeight.bold)), textDirection: TextDirection.ltr)..layout();
    tp.paint(c, Offset(p.dx - tp.width/2, p.dy - tp.height/2));
  }
  @override bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
