import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/main.dart';

void main() {
  test('native backend endpoint validates loopback configuration', () {
    final endpoint = BackendEndpointConfig.fromNative({
      'host': '127.0.0.1',
      'port': 53123,
      'instanceToken': 'launch-token',
    });

    expect(endpoint.port, 53123);
    expect(endpoint.instanceToken, 'launch-token');
    expect(
      () => BackendEndpointConfig.fromNative({
        'host': '192.0.2.1',
        'port': 53123,
        'instanceToken': 'launch-token',
      }),
      throwsFormatException,
    );
  });

  testWidgets('bootstrap shows startup state then passes endpoint to page', (
    tester,
  ) async {
    final completion = Completer<BackendEndpointConfig>();
    await tester.pumpWidget(
      MaterialApp(
        home: LogosGoBootstrap(
          endpointResolver: () => completion.future,
          pageBuilder: (endpoint) => Text('ready:${endpoint.port}'),
        ),
      ),
    );

    expect(find.text('正在啟動 LogosGo…'), findsOneWidget);
    completion.complete(const BackendEndpointConfig(port: 53123));
    await tester.pump();
    expect(find.text('ready:53123'), findsOneWidget);
  });

  testWidgets('bootstrap provides a useful startup error and retry', (
    tester,
  ) async {
    var attempts = 0;
    Future<BackendEndpointConfig> resolve() async {
      attempts += 1;
      if (attempts == 1) throw Exception('測試啟動錯誤');
      return const BackendEndpointConfig(port: 53124);
    }

    await tester.pumpWidget(
      MaterialApp(
        home: LogosGoBootstrap(
          endpointResolver: resolve,
          pageBuilder: (endpoint) => Text('ready:${endpoint.port}'),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('LogosGo 啟動失敗'), findsOneWidget);
    expect(find.text('測試啟動錯誤'), findsOneWidget);
    await tester.tap(find.text('重試'));
    await tester.pump();
    await tester.pump();
    expect(find.text('ready:53124'), findsOneWidget);
  });

  test('backend endpoint config keeps the development default centralized', () {
    const endpoint = BackendEndpointConfig();

    expect(
      endpoint.uri('/analysis/start').toString(),
      'http://127.0.0.1:5001/analysis/start',
    );
    expect(
      endpoint.uri('/analysis/job-123').toString(),
      'http://127.0.0.1:5001/analysis/job-123',
    );
    expect(
      endpoint.uri('/analysis/job-123/cancel').toString(),
      'http://127.0.0.1:5001/analysis/job-123/cancel',
    );
    expect(
      endpoint.uri('/analysis/job-123/ask').toString(),
      'http://127.0.0.1:5001/analysis/job-123/ask',
    );
    expect(
      endpoint.uri('/analyze_position').toString(),
      'http://127.0.0.1:5001/analyze_position',
    );
  });

  test(
    'backend endpoint config supports an arbitrary local port and token',
    () {
      const endpoint = BackendEndpointConfig(
        port: 53123,
        instanceToken: 'runner-instance-token',
      );

      expect(
        endpoint.uri('/health').toString(),
        'http://127.0.0.1:53123/health',
      );
      expect(endpoint.headers(), {
        logosGoInstanceHeader: 'runner-instance-token',
      });
      expect(endpoint.headers(json: true), {
        'Content-Type': 'application/json',
        logosGoInstanceHeader: 'runner-instance-token',
      });
    },
  );

  test('position analysis button only follows its own loading state', () {
    expect(canStartPositionAnalysis(false), isTrue);
    expect(canStartPositionAnalysis(true), isFalse);
  });

  test(
    'objective loss prefers observed loss over candidate comparison gap',
    () {
      final record = <String, dynamic>{
        'observed_winrate_loss': 0.031,
        'observed_score_loss': 1.4,
        'winrate_loss': 0.077,
        'score_loss': 2.8,
      };

      expect(objectiveWinrateLossForDisplay(record), 0.031);
      expect(objectiveScoreLossForDisplay(record), 1.4);
    },
  );

  test('objective loss supports legacy payload fallback', () {
    final record = <String, dynamic>{'winrate_loss': 0.077, 'score_loss': 2.8};

    expect(objectiveWinrateLossForDisplay(record), 0.077);
    expect(objectiveScoreLossForDisplay(record), 2.8);
  });

  test('ownership index follows A19 to T1 row-major order', () {
    expect(ownershipIndex(0, 0), 0); // A19
    expect(ownershipIndex(18, 0), 18); // T19
    expect(ownershipIndex(0, 18), 342); // A1
    expect(ownershipIndex(18, 18), 360); // T1
  });

  test(
    'dead stone marker requires strong opposite ownership and low stdev',
    () {
      expect(
        shouldShowDeadStoneMarker(
          isBlackStone: true,
          ownership: -0.85,
          ownershipStdev: 0.15,
        ),
        isTrue,
      );
      expect(
        shouldShowDeadStoneMarker(
          isBlackStone: false,
          ownership: 0.85,
          ownershipStdev: 0.15,
        ),
        isTrue,
      );
      expect(
        shouldShowDeadStoneMarker(
          isBlackStone: true,
          ownership: -0.70,
          ownershipStdev: 0.10,
        ),
        isFalse,
      );
      expect(
        shouldShowDeadStoneMarker(
          isBlackStone: false,
          ownership: 0.90,
          ownershipStdev: 0.30,
        ),
        isFalse,
      );
    },
  );

  test('reliable PV uses pre-move base and alternates players', () {
    final steps = parseReliablePv({
      'pv_reliable': true,
      'pv_base_move': 48,
      'pv_first_player': 'B',
      'player': 'B',
      'best_move': 'Q16',
      'best_pv': ['Q16', 'D4', 'pass'],
    }, 49);

    expect(steps, isNotNull);
    expect(steps![0].player, 'B');
    expect(steps[0].x, 15);
    expect(steps[0].y, 3);
    expect(steps[1].player, 'W');
    expect(steps[2].player, 'B');
    expect(steps[2].isPass, isTrue);
    expect(
      parseReliablePv({
        'pv_reliable': true,
        'pv_base_move': 49,
        'pv_first_player': 'B',
        'player': 'B',
        'best_move': 'Q16',
        'best_pv': ['Q16'],
      }, 49),
      isNull,
    );
  });

  test('variation replay handles captures without mutating base board', () {
    final base = <String, VariationStone>{
      '1,1': const VariationStone('W', 2),
      '0,1': const VariationStone('B', 1),
      '1,0': const VariationStone('B', 3),
      '2,1': const VariationStone('B', 5),
    };
    final step = parseGtpVariationStep('B', 'B17')!;
    final replay = replayVariation(
      baseBoard: base,
      steps: [step],
      startingPlayer: 'B',
    );

    expect(replay, isNotNull);
    expect(replay!.history.single.containsKey('1,1'), isFalse);
    expect(replay.history.single['1,2']?.player, 'B');
    expect(base.containsKey('1,1'), isTrue);
    expect(base.containsKey('1,2'), isFalse);
  });

  test('variation history is growable and continuation uses N plus 1', () {
    final replay = replayVariation(
      baseBoard: const <String, VariationStone>{},
      steps: [
        parseGtpVariationStep('B', 'D4')!,
        parseGtpVariationStep('W', 'Q16')!,
      ],
      startingPlayer: 'B',
    )!;
    final history = trialHistoryFromReplay(replay);

    expect(history, hasLength(2));
    expect(() => history.add(<String, StoneInfo>{}), returnsNormally);
    history.removeLast();
    expect(() => history.clear(), returnsNormally);

    final continuation = replayVariation(
      baseBoard: replay.history.last,
      steps: [parseGtpVariationStep('B', 'C3')!],
      startingPlayer: 'B',
      previousBoardSignature: replay.previousBoardSignature,
      startingTrialMoveNumber: 2,
    )!;
    final continuedStone = continuation.history.single['2,16'];
    expect(continuedStone?.moveNumber, trialMoveNumberOffset + 3);
    expect(variationDisplayMoveNumber(continuedStone!.moveNumber, true), 3);
  });

  test('successive variations use independent history and restart at one', () {
    final firstReplay = replayVariation(
      baseBoard: const <String, VariationStone>{},
      steps: [parseGtpVariationStep('B', 'D4')!],
      startingPlayer: 'B',
    )!;
    final firstHistory = trialHistoryFromReplay(firstReplay);
    firstHistory.clear();

    final secondReplay = replayVariation(
      baseBoard: const <String, VariationStone>{},
      steps: [parseGtpVariationStep('B', 'Q16')!],
      startingPlayer: 'B',
    )!;
    final secondHistory = trialHistoryFromReplay(secondReplay);
    final secondStone = secondHistory.single['15,3'];

    expect(firstHistory, isEmpty);
    expect(secondHistory, hasLength(1));
    expect(variationDisplayMoveNumber(secondStone!.moveNumber, true), 1);
  });

  test('trial numbers hide formal stones and display relative sequence', () {
    expect(variationDisplayMoveNumber(84, false), 84);
    expect(variationDisplayMoveNumber(84, true), isNull);
    expect(variationDisplayMoveNumber(trialMoveNumberOffset + 1, true), 1);
    expect(variationDisplayMoveNumber(trialMoveNumberOffset + 7, true), 7);
  });

  test('variation temporarily enables numbers and restores prior setting', () {
    expect(restoredMoveNumbersValue(true, false), isFalse);
    expect(restoredMoveNumbersValue(true, true), isTrue);
    expect(restoredMoveNumbersValue(false, null), isFalse);
  });

  test(
    'commentary hides full PV only when a usable board variation exists',
    () {
      const commentary =
          '這一手讓原本的領先幅度縮小。\n\n'
          'KataGo 推薦變化的開頭是：S9 → P9 → O8 → O9 → N8 → Q9。\n\n'
          '落子方勝率：67.6% → 61.2%。';

      final withVariation = commentaryForDisplay(
        commentary,
        hasVariation: true,
      );
      expect(withVariation, contains('領先幅度縮小'));
      expect(withVariation, isNot(contains('S9 → P9')));
      expect(withVariation, contains('67.6% → 61.2%'));
      expect(commentaryForDisplay(commentary, hasVariation: false), commentary);
    },
  );

  testWidgets('recommended variation link is visibly clickable', (
    WidgetTester tester,
  ) async {
    var tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: RecommendedVariationLink(
            label: '推薦變化　黑 67.6% / +3.0 目',
            onTap: () => tapped = true,
          ),
        ),
      ),
    );

    expect(find.textContaining('推薦變化'), findsOneWidget);
    await tester.tap(find.byType(RecommendedVariationLink));
    expect(tapped, isTrue);
  });

  testWidgets('main screen exposes game controls', (WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(home: GoBoardPage()));

    expect(find.text('LogosGo'), findsOneWidget);
    expect(find.text('試下'), findsOneWidget);
    expect(find.text('形勢判斷'), findsOneWidget);
    expect(find.text('匯入 SGF'), findsOneWidget);

    await tester.ensureVisible(find.text('形勢判斷'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('形勢判斷'));
    await tester.pumpAndSettle();
    expect(find.text('請先匯入 SGF 棋譜'), findsOneWidget);
  });

  testWidgets('manual trial can place a move and exit without exception', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: GoBoardPage()));

    await tester.tap(find.text('試下'));
    await tester.pump();
    expect(find.text('結束試下'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('go-board-gesture')));
    await tester.pump();
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('結束試下'));
    await tester.pump();
    expect(find.text('試下'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
