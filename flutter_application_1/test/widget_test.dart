import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/main.dart';

void main() {
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
}
