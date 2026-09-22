# sgf_utils.py
from sgfmill import boards, sgf


GTP_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


def _coords_to_gtp(row, col):
    return f"{GTP_COLUMNS[col]}{row + 1}"


def _gtp_to_coords(coordinate, board_size):
    coordinate = coordinate.upper()
    if coordinate == "PASS":
        return None
    if len(coordinate) < 2 or coordinate[0] not in GTP_COLUMNS:
        raise ValueError(f"無效的 GTP 座標: {coordinate}")
    col = GTP_COLUMNS.index(coordinate[0])
    row = int(coordinate[1:]) - 1
    if not (0 <= row < board_size and 0 <= col < board_size):
        raise ValueError(f"GTP 座標超出棋盤: {coordinate}")
    return row, col


def get_initial_stones_from_game(game):
    """回傳 root setup stones，供 KataGo initialStones 使用。"""
    black_points, white_points, _ = game.get_root().get_setup_stones()
    initial_stones = [
        ["B", _coords_to_gtp(row, col)] for row, col in sorted(black_points)
    ]
    initial_stones.extend(
        ["W", _coords_to_gtp(row, col)] for row, col in sorted(white_points)
    )
    return initial_stones


def _count_stones(board, colour):
    return sum(
        1
        for row, col in board.board_points
        if board.get(row, col) == colour
    )


def _play_and_count_captures(board, colour, coords):
    if coords is None:
        return 0
    opponent = "w" if colour == "b" else "b"
    before = _count_stones(board, opponent)
    board.play(coords[0], coords[1], colour)
    after = _count_stones(board, opponent)
    return max(0, before - after)


def get_capture_counts(game, move_count=None, extra_moves=None):
    """Replay 到指定手數並回傳真正因提子而移除的累積棋子數。"""
    board_size = game.get_size()
    board = boards.Board(board_size)
    total_moves = get_moves_from_game(game)
    if move_count is None:
        move_count = len(total_moves)
    if not 0 <= move_count <= len(total_moves):
        raise ValueError(f"move_count 超出範圍（0～{len(total_moves)}）")

    captures = {"B": 0, "W": 0}
    moves_played = 0
    for node in game.get_main_sequence():
        colour, coords = node.get_move()
        if colour is not None and moves_played >= move_count:
            break

        # Setup stones 直接套用，不列入任何一方的提子數。
        black, white, empty = node.get_setup_stones()
        if black or white or empty:
            board.apply_setup(black, white, empty)

        if colour is None:
            continue
        captures[colour.upper()] += _play_and_count_captures(board, colour, coords)
        moves_played += 1

    for player, coordinate in extra_moves or []:
        colour = player.lower()
        coords = _gtp_to_coords(coordinate, board_size)
        captures[player] += _play_and_count_captures(board, colour, coords)

    return {
        "black_captures": captures["B"],
        "white_captures": captures["W"],
    }


def get_moves_from_game(game, target_step=None):
    """把 sgfmill game 的主變化轉成 KataGo analysis moves 格式。"""
    board_size = game.get_size()
    if board_size > 25:
        raise ValueError("目前只支援 25 路以下棋盤的 GTP 座標")

    nodes = game.get_main_sequence()
    base_moves = []
    for node in nodes:
        color, coords = node.get_move()
        if color is None:
            continue
        if target_step is not None and len(base_moves) >= target_step:
            break

        player = "B" if color == "b" else "W"
        if coords is None:
            base_moves.append([player, "pass"])
            continue

        # sgfmill 會把 SGF 左上角 aa 轉成 (board_size - 1, 0)，
        # 因此 row + 1 正好是 KataGo/GTP 從棋盤下方起算的列號。
        row, col = coords
        base_moves.append([player, _coords_to_gtp(row, col)])

    return base_moves


def get_moves_from_sgf_bytes(sgf_bytes, target_step=None):
    game = sgf.Sgf_game.from_bytes(sgf_bytes)
    return get_moves_from_game(game, target_step=target_step)


def get_moves_from_sgf_content(sgf_content, target_step=None):
    return get_moves_from_sgf_bytes(
        sgf_content.encode("utf-8"), target_step=target_step
    )


def get_moves_from_sgf(file_path, target_step=None):
    """
    讀取 SGF 檔案並回傳 KataGo moves 格式: [['B', 'R16'], ['W', 'D4'], ...]
    """
    with open(file_path, "rb") as f:
        return get_moves_from_sgf_bytes(f.read(), target_step=target_step)
