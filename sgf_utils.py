# sgf_utils.py
from sgfmill import sgf

def get_moves_from_sgf(file_path, target_step=None):
    """
    讀取 SGF 檔案並回傳 base_moves 格式: [['B', 'R16'], ['W', 'D4'], ...]
    """
    with open(file_path, "rb") as f:
        game = sgf.Sgf_game.from_bytes(f.read())
    
    board_size = game.get_size()
    # 獲取主變線的所有節點
    nodes = game.get_main_sequence()
    base_moves = []
    
    # 座標轉換對照表 (a, b, c...)
    cols = "ABCDEFGHJKLMNOPQRST" # 注意：圍棋座標通常跳過 'I'

    for i, node in enumerate(nodes):
        # 如果指定了手數，超過就停止
        if target_step is not None and i > target_step:
            break
            
        color, coords = node.get_move()
        if color is not None:
            row, col = coords
            # SGF 的 (0,0) 通常是左下角或左上角，取決於函式庫
            # sgfmill (0,0) 是左下角，對應到座標如 'A1'
            col_str = cols[col]
            row_str = str(row + 1)
            
            player = 'B' if color == 'b' else 'W'
            base_moves.append([player, f"{col_str}{row_str}"])
            
    return base_moves