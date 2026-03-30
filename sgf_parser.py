import urllib.request
import urllib.parse
import json
import os
import sys
import time
import argparse
import codecs

# 模拟真实的 PC 网页浏览器
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.foxwq.com/chess/rank.html',
    'Accept': 'application/json, text/plain, */*'
}

def get_uid(username):
    # 既然这个接口你之前跑通了，我们就保留它
    url = f"https://h5.foxwq.com/getFechInfo/wxnseed/txwq_fetch_personal_info?username={urllib.parse.quote(username)}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return str(data.get('uid')) if data.get('uid') != 0 else None
    except: return None

def game_list(uid):
    # 【核心改动】尝试野狐最新的 Web 棋谱列表接口
    # 如果这个还报 404，说明腾讯已经全面禁止了通过 URL 参数直接查询
    url = "https://h5.foxwq.com/getFechInfo/wxnseed/txwq_fetch_chess_list"
    
    # 尝试改回简单的 GET 参数
    params = {
        "uid": uid,
        "page": "1",
        "type": "4",
        "RelationTag": "0"
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    
    try:
        req = urllib.request.Request(full_url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode('utf-8')
            res = json.loads(raw)
            # 兼容：有些返回在 'data' 下，有些在根目录
            data = res.get('data', res)
            return data.get('chesslist', [])
    except Exception as e:
        print(f"列表获取失败: {e}")
        return []

def download_sgf(cid, fn):
    # 下载接口尝试改用这个
    url = f"https://h5.foxwq.com/getFechInfo/wxnseed/txwq_fetch_chess?chessid={cid}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            data = res.get('data', res)
            sgf = data.get('chess', '')
            if sgf:
                with codecs.open(fn, 'w', 'utf-8') as f:
                    f.write(sgf)
                return True
    except: pass
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    args = parser.parse_args()

    uid = get_uid(args.username)
    if not uid:
        print(f"用户 {args.username} 不存在。")
        sys.exit()

    if not os.path.exists(args.username):
        os.makedirs(args.username)

    print(f"正在尝试抓取 {args.username} (UID: {uid})...")
    items = game_list(uid)
    
    if not items:
        print("【结果】无法获取对局列表。")
        print("原因分析：腾讯已在服务端屏蔽了非登录状态的棋谱查询接口。")
    else:
        success = 0
        for item in items:
            cid = item['chessid']
            date = item.get('starttime', '0000.00.00').split(' ')[0].replace('-', '.')
            filename = f"{args.username}/{date}_{cid[-5:]}.sgf"
            if download_sgf(cid, filename):
                print(f"成功下载: {filename}")
                success += 1
                time.sleep(0.5)
        print(f"\n任务结束，共抓取 {success} 份。")