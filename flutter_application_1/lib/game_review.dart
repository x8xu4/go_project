import 'dart:math';

import 'package:flutter/material.dart';

const String emptyGameReviewMessage = '目前沒有選出足夠明確的主要復盤重點。';

class GameReviewHighlight {
  final int moveNumber;
  final String player;
  final String actualMove;
  final String importance;
  final bool variationAvailable;

  const GameReviewHighlight({
    required this.moveNumber,
    required this.player,
    required this.actualMove,
    required this.importance,
    required this.variationAvailable,
  });

  String get playerLabel => player == 'B' ? '黑棋' : '白棋';
  String get importanceLabel => reviewImportanceLabel(importance);
}

class GameReviewData {
  final List<GameReviewHighlight> highlights;
  final int? primaryMove;
  final String? autoSummary;
  final String? detailedSummary;

  const GameReviewData({
    required this.highlights,
    required this.primaryMove,
    required this.autoSummary,
    required this.detailedSummary,
  });

  bool get isEmpty => highlights.isEmpty;

  static GameReviewData? tryParse(Object? raw) {
    if (raw is! Map) return null;

    final highlights = <GameReviewHighlight>[];
    final rawHighlights = raw['highlights'];
    if (rawHighlights is List) {
      for (final item in rawHighlights) {
        final parsed = _parseHighlight(item);
        if (parsed != null) highlights.add(parsed);
      }
    }

    final rawSelectionSummary = raw['summary'];
    final selectionSummary = rawSelectionSummary is Map
        ? rawSelectionSummary
        : const <String, Object?>{};
    final selectedCount = _nonNegativeInt(selectionSummary['selected_count']);
    if (selectedCount == 0) highlights.clear();

    final rawSummary = raw['review_summary'];
    final summary = rawSummary is Map ? rawSummary : const <String, Object?>{};
    final rawPriority = summary['priority'];
    final priority = rawPriority is Map
        ? rawPriority
        : const <String, Object?>{};
    final candidatePrimary = _positiveInt(priority['primary_move']);
    final primary =
        highlights.any((highlight) => highlight.moveNumber == candidatePrimary)
        ? candidatePrimary
        : null;

    final rawRendered = summary['rendered'];
    final rendered = rawRendered is Map
        ? rawRendered
        : const <String, Object?>{};
    return GameReviewData(
      highlights: List.unmodifiable(highlights),
      primaryMove: primary,
      autoSummary: _nonEmptyString(rendered['auto']),
      detailedSummary: _nonEmptyString(rendered['detailed']),
    );
  }
}

GameReviewHighlight? _parseHighlight(Object? raw) {
  if (raw is! Map) return null;
  final moveNumber = _positiveInt(raw['move_number']);
  final player = _nonEmptyString(raw['player']);
  final actualMove = _nonEmptyString(raw['actual_move']);
  final importance = _nonEmptyString(raw['importance']);
  if (moveNumber == null ||
      (player != 'B' && player != 'W') ||
      actualMove == null ||
      importance == null) {
    return null;
  }
  return GameReviewHighlight(
    moveNumber: moveNumber,
    player: player!,
    actualMove: actualMove,
    importance: importance,
    variationAvailable: raw['variation_available'] == true,
  );
}

int? _positiveInt(Object? value) {
  if (value is! num || !value.isFinite) return null;
  final converted = value.toInt();
  return converted > 0 && converted == value ? converted : null;
}

int? _nonNegativeInt(Object? value) {
  if (value is! num || !value.isFinite) return null;
  final converted = value.toInt();
  return converted >= 0 && converted == value ? converted : null;
}

String? _nonEmptyString(Object? value) {
  if (value is! String || value.trim().isEmpty) return null;
  return value.trim();
}

String reviewImportanceLabel(String importance) {
  switch (importance) {
    case 'notice':
      return '值得注意';
    case 'important':
      return '重要手';
    case 'decisive':
      return '明顯局勢轉折';
    case 'ordinary':
      return '普通手';
    default:
      return '復盤重點';
  }
}

int? reviewHighlightIndex(GameReviewData? review, int currentMove) {
  if (review == null) return null;
  final index = review.highlights.indexWhere(
    (highlight) => highlight.moveNumber == currentMove,
  );
  return index < 0 ? null : index;
}

bool shouldShowGameReview(GameReviewData? review, bool isAnalyzing) {
  return review != null && !isAnalyzing;
}

bool performReviewJump({
  required int moveNumber,
  required int totalMoves,
  required bool isTrialMode,
  required VoidCallback exitTrialMode,
  required ValueChanged<int> jumpToOfficialMove,
}) {
  if (moveNumber < 1 || moveNumber > totalMoves) return false;
  if (isTrialMode) exitTrialMode();
  jumpToOfficialMove(moveNumber);
  return true;
}

class GameReviewEntryCard extends StatelessWidget {
  final GameReviewData review;
  final VoidCallback onStartReview;
  final VoidCallback onOpenAll;
  final VoidCallback onOpenPrimary;

  const GameReviewEntryCard({
    super.key,
    required this.review,
    required this.onStartReview,
    required this.onOpenAll,
    required this.onOpenPrimary,
  });

  @override
  Widget build(BuildContext context) {
    final count = review.highlights.length;
    return Container(
      key: const ValueKey('game-review-entry'),
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.amber.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.amber.withValues(alpha: 0.42)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.fact_check_outlined, color: Colors.amber),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  '本局復盤',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Text(
                '$count 個重點',
                key: const ValueKey('game-review-count'),
                style: const TextStyle(color: Colors.amber),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (review.isEmpty)
            const Text(
              emptyGameReviewMessage,
              key: ValueKey('game-review-empty'),
              style: TextStyle(color: Colors.white70, height: 1.35),
            )
          else ...[
            if (review.primaryMove != null)
              TextButton.icon(
                key: const ValueKey('game-review-primary-action'),
                onPressed: onOpenPrimary,
                icon: const Icon(Icons.star, size: 18),
                label: Text('優先回看：第 ${review.primaryMove} 手'),
                style: TextButton.styleFrom(
                  foregroundColor: Colors.amber,
                  padding: EdgeInsets.zero,
                  visualDensity: VisualDensity.compact,
                ),
              ),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                FilledButton.icon(
                  key: const ValueKey('game-review-start'),
                  onPressed: onStartReview,
                  icon: const Icon(Icons.play_arrow, size: 18),
                  label: const Text('開始復盤'),
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.amber,
                    foregroundColor: Colors.black,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
                OutlinedButton(
                  key: const ValueKey('game-review-open-all'),
                  onPressed: onOpenAll,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white70,
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('查看全部'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class GameReviewSection extends StatelessWidget {
  final GameReviewData? review;
  final bool isAnalyzing;
  final int currentMove;
  final VoidCallback onStartReview;
  final VoidCallback onOpenAll;
  final VoidCallback onOpenPrimary;
  final ValueChanged<int> onSelectMove;

  const GameReviewSection({
    super.key,
    required this.review,
    required this.isAnalyzing,
    required this.currentMove,
    required this.onStartReview,
    required this.onOpenAll,
    required this.onOpenPrimary,
    required this.onSelectMove,
  });

  @override
  Widget build(BuildContext context) {
    if (!shouldShowGameReview(review, isAnalyzing)) {
      return const SizedBox.shrink();
    }
    final data = review!;
    final currentIndex = reviewHighlightIndex(data, currentMove);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GameReviewEntryCard(
          review: data,
          onStartReview: onStartReview,
          onOpenAll: onOpenAll,
          onOpenPrimary: onOpenPrimary,
        ),
        if (currentIndex != null && data.highlights.length > 1) ...[
          const SizedBox(height: 10),
          ReviewHighlightNavigation(
            highlights: data.highlights,
            currentIndex: currentIndex,
            onSelectMove: onSelectMove,
          ),
        ],
        const SizedBox(height: 12),
      ],
    );
  }
}

class ReviewHighlightNavigation extends StatelessWidget {
  final List<GameReviewHighlight> highlights;
  final int currentIndex;
  final ValueChanged<int> onSelectMove;

  const ReviewHighlightNavigation({
    super.key,
    required this.highlights,
    required this.currentIndex,
    required this.onSelectMove,
  });

  @override
  Widget build(BuildContext context) {
    if (highlights.length <= 1 ||
        currentIndex < 0 ||
        currentIndex >= highlights.length) {
      return const SizedBox.shrink();
    }
    final previous = currentIndex > 0 ? highlights[currentIndex - 1] : null;
    final next = currentIndex + 1 < highlights.length
        ? highlights[currentIndex + 1]
        : null;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 3),
        child: Row(
          children: [
            Expanded(
              child: TextButton.icon(
                key: const ValueKey('review-previous'),
                onPressed: previous == null
                    ? null
                    : () => onSelectMove(previous.moveNumber),
                icon: const Icon(Icons.chevron_left, size: 18),
                label: const Text('上一個重點', overflow: TextOverflow.ellipsis),
                style: TextButton.styleFrom(
                  foregroundColor: Colors.amber,
                  visualDensity: VisualDensity.compact,
                  textStyle: const TextStyle(fontSize: 11),
                ),
              ),
            ),
            Text(
              '${currentIndex + 1} / ${highlights.length}',
              key: const ValueKey('review-position'),
              style: const TextStyle(color: Colors.white54, fontSize: 11),
            ),
            Expanded(
              child: TextButton.icon(
                key: const ValueKey('review-next'),
                onPressed: next == null
                    ? null
                    : () => onSelectMove(next.moveNumber),
                iconAlignment: IconAlignment.end,
                icon: const Icon(Icons.chevron_right, size: 18),
                label: const Text('下一個重點', overflow: TextOverflow.ellipsis),
                style: TextButton.styleFrom(
                  foregroundColor: Colors.amber,
                  visualDensity: VisualDensity.compact,
                  textStyle: const TextStyle(fontSize: 11),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class GameReviewPanel extends StatefulWidget {
  final GameReviewData review;
  final ValueChanged<int> onSelectMove;
  final VoidCallback onClose;

  const GameReviewPanel({
    super.key,
    required this.review,
    required this.onSelectMove,
    required this.onClose,
  });

  @override
  State<GameReviewPanel> createState() => _GameReviewPanelState();
}

class _GameReviewPanelState extends State<GameReviewPanel> {
  bool _showDetailed = false;

  @override
  Widget build(BuildContext context) {
    final viewport = MediaQuery.sizeOf(context);
    final width = min(560.0, max(280.0, viewport.width - 32));
    final height = min(720.0, max(300.0, viewport.height - 32));
    final review = widget.review;
    final autoSummary =
        review.autoSummary ??
        (review.isEmpty
            ? emptyGameReviewMessage
            : '本局整理出 ${review.highlights.length} 個主要復盤重點。');

    return Dialog(
      key: const ValueKey('game-review-panel'),
      insetPadding: const EdgeInsets.all(16),
      backgroundColor: const Color(0xFF252525),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: SizedBox(
        width: width,
        height: height,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 12, 8, 8),
              child: Row(
                children: [
                  const Icon(Icons.fact_check_outlined, color: Colors.amber),
                  const SizedBox(width: 9),
                  const Expanded(
                    child: Text(
                      '本局復盤',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 19,
                      ),
                    ),
                  ),
                  IconButton(
                    key: const ValueKey('game-review-close'),
                    onPressed: widget.onClose,
                    tooltip: '關閉',
                    icon: const Icon(Icons.close, color: Colors.white70),
                  ),
                ],
              ),
            ),
            const Divider(color: Colors.white24, height: 1),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text(
                    autoSummary,
                    key: const ValueKey('game-review-auto-summary'),
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 15,
                      height: 1.45,
                    ),
                  ),
                  if (review.detailedSummary != null) ...[
                    const SizedBox(height: 6),
                    TextButton.icon(
                      key: const ValueKey('game-review-detail-toggle'),
                      onPressed: () =>
                          setState(() => _showDetailed = !_showDetailed),
                      icon: Icon(
                        _showDetailed ? Icons.expand_less : Icons.expand_more,
                      ),
                      label: Text(_showDetailed ? '收起本局摘要' : '查看本局摘要'),
                      style: TextButton.styleFrom(
                        foregroundColor: Colors.amber,
                        alignment: Alignment.centerLeft,
                        padding: EdgeInsets.zero,
                      ),
                    ),
                    if (_showDetailed)
                      Container(
                        key: const ValueKey('game-review-detailed-summary'),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.18),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          review.detailedSummary!,
                          style: const TextStyle(
                            color: Colors.white70,
                            height: 1.45,
                          ),
                        ),
                      ),
                  ],
                  const SizedBox(height: 14),
                  Text(
                    review.isEmpty ? '復盤重點' : '依棋局順序',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 15,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (review.isEmpty)
                    const Text(
                      emptyGameReviewMessage,
                      key: ValueKey('game-review-panel-empty'),
                      style: TextStyle(color: Colors.white54),
                    )
                  else
                    for (final highlight in review.highlights)
                      _ReviewHighlightTile(
                        highlight: highlight,
                        isPrimary: highlight.moveNumber == review.primaryMove,
                        onTap: () => widget.onSelectMove(highlight.moveNumber),
                      ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ReviewHighlightTile extends StatelessWidget {
  final GameReviewHighlight highlight;
  final bool isPrimary;
  final VoidCallback onTap;

  const _ReviewHighlightTile({
    required this.highlight,
    required this.isPrimary,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      key: ValueKey('review-highlight-${highlight.moveNumber}'),
      margin: const EdgeInsets.only(bottom: 8),
      color: isPrimary
          ? Colors.amber.withValues(alpha: 0.14)
          : Colors.white.withValues(alpha: 0.05),
      child: InkWell(
        onTap: onTap,
        mouseCursor: SystemMouseCursors.click,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          child: Row(
            children: [
              if (isPrimary) ...[
                const Icon(Icons.star, color: Colors.amber, size: 20),
                const SizedBox(width: 7),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '第 ${highlight.moveNumber} 手　${highlight.playerLabel} ${highlight.actualMove}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 3,
                      children: [
                        Text(
                          highlight.importanceLabel,
                          style: const TextStyle(color: Colors.amber),
                        ),
                        if (isPrimary)
                          const Text(
                            '優先回看',
                            style: TextStyle(color: Colors.white70),
                          ),
                        if (highlight.variationAvailable)
                          const Text(
                            '有推薦變化',
                            key: ValueKey('review-variation-available'),
                            style: TextStyle(color: Colors.lightBlueAccent),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.white38),
            ],
          ),
        ),
      ),
    );
  }
}
