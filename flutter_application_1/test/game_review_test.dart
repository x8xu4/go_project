import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/game_review.dart';
import 'package:flutter_application_1/main.dart';

Map<String, dynamic> reviewPayload({
  List<Map<String, dynamic>>? highlights,
  int? primaryMove,
  String? auto = '本局整理出復盤重點。',
  String? detailed = '依棋局順序查看各個重點。',
}) {
  return {
    'summary': {'selected_count': highlights?.length ?? 0},
    'highlights': highlights ?? <Map<String, dynamic>>[],
    'review_summary': {
      'priority': {'primary_move': primaryMove},
      'rendered': {'auto': auto, 'detailed': detailed},
    },
  };
}

Map<String, dynamic> highlight(
  int move, {
  String player = 'B',
  String actualMove = 'D4',
  String importance = 'important',
  bool variation = false,
}) {
  return {
    'move_number': move,
    'player': player,
    'actual_move': actualMove,
    'importance': importance,
    'variation_available': variation,
  };
}

GameReviewData reviewWithMoves(
  List<int> moves, {
  int? primaryMove,
  bool variation = false,
  String? detailed = '詳細摘要',
}) {
  return GameReviewData.tryParse(
    reviewPayload(
      highlights: [
        for (final move in moves)
          highlight(
            move,
            player: move.isEven ? 'W' : 'B',
            actualMove: move.isEven ? 'Q16' : 'D4',
            importance: move == primaryMove ? 'decisive' : 'important',
            variation: variation && move == moves.first,
          ),
      ],
      primaryMove: primaryMove,
      detailed: detailed,
    ),
  )!;
}

Widget reviewHost(Widget child) {
  return MaterialApp(
    home: Scaffold(backgroundColor: const Color(0xFF1A1A1A), body: child),
  );
}

class ReviewSectionHarness extends StatefulWidget {
  final GameReviewData review;
  final int initialMove;

  const ReviewSectionHarness({
    super.key,
    required this.review,
    required this.initialMove,
  });

  @override
  State<ReviewSectionHarness> createState() => _ReviewSectionHarnessState();
}

class _ReviewSectionHarnessState extends State<ReviewSectionHarness> {
  late int currentMove = widget.initialMove;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        GameReviewSection(
          review: widget.review,
          isAnalyzing: false,
          currentMove: currentMove,
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
          onSelectMove: (move) => setState(() => currentMove = move),
        ),
        TextButton(
          key: const ValueKey('manual-move'),
          onPressed: () => setState(() => currentMove = 99),
          child: const Text('manual'),
        ),
      ],
    );
  }
}

void main() {
  test('no game_review keeps old UI safe', () {
    expect(GameReviewData.tryParse(null), isNull);
    expect(GameReviewData.tryParse('invalid'), isNull);
  });

  test('empty highlights are represented without inventing moves', () {
    final review = GameReviewData.tryParse(reviewPayload())!;
    expect(review.highlights, isEmpty);
    expect(review.primaryMove, isNull);
  });

  test('selected count zero safely suppresses inconsistent highlights', () {
    final payload = reviewPayload(highlights: [highlight(10)]);
    payload['summary'] = {'selected_count': 0};
    final review = GameReviewData.tryParse(payload)!;
    expect(review.highlights, isEmpty);
    expect(review.primaryMove, isNull);
  });

  test('one highlight parses official move fields', () {
    final review = GameReviewData.tryParse(
      reviewPayload(highlights: [highlight(1)]),
    )!;
    expect(review.highlights.single.moveNumber, 1);
    expect(review.highlights.single.actualMove, 'D4');
  });

  test('multiple highlights preserve backend chronological order', () {
    final review = reviewWithMoves([1, 48, 200]);
    expect(review.highlights.map((item) => item.moveNumber), [1, 48, 200]);
  });

  test('primary move comes from backend summary', () {
    expect(reviewWithMoves([10, 20], primaryMove: 20).primaryMove, 20);
  });

  test('malformed optional highlight items are skipped safely', () {
    final review = GameReviewData.tryParse(
      reviewPayload(
        highlights: [
          {'move_number': 'bad'},
          highlight(8),
          {'move_number': 9, 'player': 'X', 'actual_move': 'D4'},
        ],
      ),
    )!;
    expect(review.highlights.map((item) => item.moveNumber), [8]);
  });

  test('missing review summary is safe', () {
    final review = GameReviewData.tryParse({
      'highlights': [highlight(12)],
    })!;
    expect(review.autoSummary, isNull);
    expect(review.detailedSummary, isNull);
    expect(review.primaryMove, isNull);
  });

  test('primary move missing from highlights is ignored', () {
    expect(reviewWithMoves([10, 20], primaryMove: 30).primaryMove, isNull);
  });

  test('importance uses existing user-facing wording', () {
    expect(reviewImportanceLabel('ordinary'), '普通手');
    expect(reviewImportanceLabel('notice'), '值得注意');
    expect(reviewImportanceLabel('important'), '重要手');
    expect(reviewImportanceLabel('decisive'), '明顯局勢轉折');
    expect(reviewImportanceLabel('future'), '復盤重點');
  });

  test('derived review index follows current official move', () {
    final review = reviewWithMoves([1, 48, 200]);
    expect(reviewHighlightIndex(review, 1), 0);
    expect(reviewHighlightIndex(review, 48), 1);
    expect(reviewHighlightIndex(review, 200), 2);
    expect(reviewHighlightIndex(review, 49), isNull);
  });

  test('review jump maps move N directly to official move count N', () {
    int? jumped;
    final didJump = performReviewJump(
      moveNumber: 1,
      totalMoves: 200,
      isTrialMode: false,
      exitTrialMode: () => fail('must not exit a mode that is not active'),
      jumpToOfficialMove: (move) => jumped = move,
    );
    expect(didJump, isTrue);
    expect(jumped, 1);
  });

  test('review jump exits trial before official navigation', () {
    final events = <String>[];
    performReviewJump(
      moveNumber: 160,
      totalMoves: 200,
      isTrialMode: true,
      exitTrialMode: () => events.add('exit-trial'),
      jumpToOfficialMove: (move) => events.add('jump-$move'),
    );
    expect(events, ['exit-trial', 'jump-160']);
  });

  test('invalid review jump cannot clamp to another move', () {
    var called = false;
    expect(
      performReviewJump(
        moveNumber: 201,
        totalMoves: 200,
        isTrialMode: true,
        exitTrialMode: () => called = true,
        jumpToOfficialMove: (_) => called = true,
      ),
      isFalse,
    );
    expect(called, isFalse);
  });

  testWidgets('review entry is absent while analysis is running', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewSection(
          review: reviewWithMoves([10]),
          isAnalyzing: true,
          currentMove: 10,
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
          onSelectMove: (_) {},
        ),
      ),
    );
    expect(find.byKey(const ValueKey('game-review-entry')), findsNothing);
  });

  testWidgets('review entry appears after completed analysis', (tester) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewSection(
          review: reviewWithMoves([10]),
          isAnalyzing: false,
          currentMove: 0,
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
          onSelectMove: (_) {},
        ),
      ),
    );
    expect(find.byKey(const ValueKey('game-review-entry')), findsOneWidget);
    expect(find.text('1 個重點'), findsOneWidget);
  });

  testWidgets('empty review shows message and no start actions', (
    tester,
  ) async {
    final review = GameReviewData.tryParse(reviewPayload())!;
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: review,
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
        ),
      ),
    );
    expect(find.text(emptyGameReviewMessage), findsOneWidget);
    expect(find.byKey(const ValueKey('game-review-start')), findsNothing);
    expect(find.byKey(const ValueKey('game-review-open-all')), findsNothing);
  });

  testWidgets('one highlight keeps start review available', (tester) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: reviewWithMoves([12]),
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
        ),
      ),
    );
    expect(find.byKey(const ValueKey('game-review-start')), findsOneWidget);
  });

  testWidgets('multiple highlight count is visible', (tester) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: reviewWithMoves([10, 30, 50]),
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
        ),
      ),
    );
    expect(find.text('3 個重點'), findsOneWidget);
  });

  testWidgets('primary move is visibly distinguished', (tester) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: reviewWithMoves([10, 30], primaryMove: 30),
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () {},
        ),
      ),
    );
    expect(find.text('優先回看：第 30 手'), findsOneWidget);
  });

  testWidgets('primary action jumps backend primary move', (tester) async {
    var selected = 0;
    final review = reviewWithMoves([10, 30], primaryMove: 30);
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: review,
          onStartReview: () {},
          onOpenAll: () {},
          onOpenPrimary: () => selected = review.primaryMove!,
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('game-review-primary-action')));
    expect(selected, 30);
  });

  testWidgets('start review uses first chronological highlight not primary', (
    tester,
  ) async {
    var selected = 0;
    final review = reviewWithMoves([10, 30], primaryMove: 30);
    await tester.pumpWidget(
      reviewHost(
        GameReviewEntryCard(
          review: review,
          onStartReview: () => selected = review.highlights.first.moveNumber,
          onOpenAll: () {},
          onOpenPrimary: () {},
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('game-review-start')));
    expect(selected, 10);
  });

  testWidgets('review panel displays chronological highlight list', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([1, 48, 200]),
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    final first = tester.getTopLeft(
      find.byKey(const ValueKey('review-highlight-1')),
    );
    final middle = tester.getTopLeft(
      find.byKey(const ValueKey('review-highlight-48')),
    );
    final last = tester.getTopLeft(
      find.byKey(const ValueKey('review-highlight-200')),
    );
    expect(first.dy, lessThan(middle.dy));
    expect(middle.dy, lessThan(last.dy));
  });

  testWidgets('clicking highlight returns exact official move', (tester) async {
    int? selected;
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([1, 48, 200]),
          onSelectMove: (move) => selected = move,
          onClose: () {},
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('review-highlight-48')));
    expect(selected, 48);
  });

  testWidgets('review panel close callback works', (tester) async {
    var closed = false;
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([10]),
          onSelectMove: (_) {},
          onClose: () => closed = true,
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('game-review-close')));
    expect(closed, isTrue);
  });

  testWidgets('previous review highlight navigation works', (tester) async {
    int? selected;
    await tester.pumpWidget(
      reviewHost(
        ReviewHighlightNavigation(
          highlights: reviewWithMoves([10, 20, 30]).highlights,
          currentIndex: 1,
          onSelectMove: (move) => selected = move,
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('review-previous')));
    expect(selected, 10);
  });

  testWidgets('next review highlight navigation works', (tester) async {
    int? selected;
    await tester.pumpWidget(
      reviewHost(
        ReviewHighlightNavigation(
          highlights: reviewWithMoves([10, 20, 30]).highlights,
          currentIndex: 1,
          onSelectMove: (move) => selected = move,
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('review-next')));
    expect(selected, 30);
  });

  testWidgets('review navigation boundary buttons are disabled', (
    tester,
  ) async {
    final highlights = reviewWithMoves([10, 20]).highlights;
    await tester.pumpWidget(
      reviewHost(
        ReviewHighlightNavigation(
          highlights: highlights,
          currentIndex: 0,
          onSelectMove: (_) {},
        ),
      ),
    );
    expect(
      tester
          .widget<TextButton>(find.byKey(const ValueKey('review-previous')))
          .onPressed,
      isNull,
    );
    await tester.pumpWidget(
      reviewHost(
        ReviewHighlightNavigation(
          highlights: highlights,
          currentIndex: 1,
          onSelectMove: (_) {},
        ),
      ),
    );
    expect(
      tester
          .widget<TextButton>(find.byKey(const ValueKey('review-next')))
          .onPressed,
      isNull,
    );
  });

  testWidgets('manual navigation updates and clears review highlight state', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        ReviewSectionHarness(
          review: reviewWithMoves([10, 20, 30]),
          initialMove: 20,
        ),
      ),
    );
    expect(find.text('2 / 3'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('manual-move')));
    await tester.pump();
    expect(find.byKey(const ValueKey('review-position')), findsNothing);
  });

  testWidgets('detailed backend summary is expandable', (tester) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([10], detailed: '後端提供的詳細摘要'),
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    expect(find.text('後端提供的詳細摘要'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('game-review-detail-toggle')));
    await tester.pump();
    expect(find.text('後端提供的詳細摘要'), findsOneWidget);
  });

  testWidgets('missing summaries use safe structural fallback', (tester) async {
    final review = GameReviewData.tryParse({
      'highlights': [highlight(10)],
    })!;
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(review: review, onSelectMove: (_) {}, onClose: () {}),
      ),
    );
    expect(find.text('本局整理出 1 個主要復盤重點。'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('game-review-detail-toggle')),
      findsNothing,
    );
  });

  testWidgets('variation availability is shown without a second PV action', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([10], variation: true),
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    expect(find.text('有推薦變化'), findsOneWidget);
    expect(find.textContaining('查看推薦變化圖'), findsNothing);
  });

  testWidgets('one-highlight review navigation stays compact and safe', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        ReviewHighlightNavigation(
          highlights: reviewWithMoves([10]).highlights,
          currentIndex: 0,
          onSelectMove: (_) {},
        ),
      ),
    );
    expect(find.byKey(const ValueKey('review-position')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow desktop review panel has no RenderFlex overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 620);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([10, 20, 30], primaryMove: 20),
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('game-review-panel')), findsOneWidget);
  });

  testWidgets('identical review data renders deterministically', (
    tester,
  ) async {
    final payload = reviewPayload(
      highlights: [highlight(10), highlight(20)],
      primaryMove: 20,
    );
    final first = GameReviewData.tryParse(payload)!;
    final second = GameReviewData.tryParse(payload)!;
    await tester.pumpWidget(
      reviewHost(
        Row(
          children: [
            Expanded(
              child: GameReviewEntryCard(
                review: first,
                onStartReview: () {},
                onOpenAll: () {},
                onOpenPrimary: () {},
              ),
            ),
            Expanded(
              child: GameReviewEntryCard(
                review: second,
                onStartReview: () {},
                onOpenAll: () {},
                onOpenPrimary: () {},
              ),
            ),
          ],
        ),
      ),
    );
    expect(find.text('2 個重點'), findsNWidgets(2));
    expect(find.text('優先回看：第 20 手'), findsNWidgets(2));
  });

  testWidgets('old main screen still shows commentary and ask controls', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: GoBoardPage()));
    expect(find.textContaining('等待落子或匯入 SGF'), findsOneWidget);
    expect(find.text('提問／為什麼？'), findsOneWidget);
    expect(find.byKey(const ValueKey('game-review-entry')), findsNothing);
  });

  testWidgets('existing trial controls remain available', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: GoBoardPage()));
    await tester.tap(find.text('試下'));
    await tester.pump();
    expect(find.text('結束試下'), findsOneWidget);
    await tester.tap(find.text('結束試下'));
    await tester.pump();
    expect(find.text('試下'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('review panel omits backend engineering metadata', (
    tester,
  ) async {
    final payload = reviewPayload(highlights: [highlight(10)]);
    payload['schema_version'] = 1;
    payload['suppressed'] = [
      {'reason': 'nearby_cluster', 'severity_ratio': 1.2},
    ];
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: GameReviewData.tryParse(payload)!,
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    expect(find.textContaining('severity'), findsNothing);
    expect(find.textContaining('schema'), findsNothing);
    expect(find.textContaining('nearby_cluster'), findsNothing);
  });

  testWidgets('highlight rows display black and white correctly', (
    tester,
  ) async {
    await tester.pumpWidget(
      reviewHost(
        GameReviewPanel(
          review: reviewWithMoves([11, 12]),
          onSelectMove: (_) {},
          onClose: () {},
        ),
      ),
    );
    expect(find.textContaining('第 11 手　黑棋'), findsOneWidget);
    expect(find.textContaining('第 12 手　白棋'), findsOneWidget);
  });
}
