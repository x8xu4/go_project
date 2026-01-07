#!/bin/python
# coding=utf-8
import urllib.request
import urllib.parse
import urllib.error
import json
import codecs
import time
import sys
import os
import argparse

def game_list(lastCode):
    values = {
        "type": 4,
        "lastCode": lastCode,
        "uid": uid, 
        "RelationTag": 0
    }
    data = urllib.parse.urlencode(values).encode("utf-8")
    url = "http://happyapp.huanle.qq.com/cgi-bin/CommonMobileCGI/TXWQFetchChessList"
    request = urllib.request.Request(url, data)
    response = urllib.request.urlopen(request)
    raw_data = response.read()
    try:
        decoded_data = raw_data.decode("utf-8")
    except UnicodeDecodeError:
        decoded_data = raw_data.decode("gbk")  # 如果 utf-8 失败，尝试用 gbk 解析

    chesslist = json.loads(decoded_data)['chesslist']

    chessid = []
    fn = []

    for d in chesslist:
        starttime = d['starttime'].split(' ')[0].replace('-', '.')
        if end is not None and end < starttime:
            continue
        if start is not None and start > starttime:
            # 返回空列表表示停止搜索
            return [], []
        
        chessid.append(d['chessid'])    
        cid_short = d['chessid'][10:]
        blackenname = d['blackenname']
        whiteenname = d['whiteenname']
        filename = f"{USERNAME}/{starttime} {blackenname} VS {whiteenname} ({cid_short}).SGF"
        fn.append(filename)
    return chessid, fn

def download_sgf(cid, fn):
    values = {"chessid": cid}
    data = urllib.parse.urlencode(values).encode("utf-8")
    url = "http://happyapp.huanle.qq.com/cgi-bin/CommonMobileCGI/TXWQFetchChess"
    sgf = ""
    for i in range(10): # 失败重试10次
        try:
            request = urllib.request.Request(url, data)
            response = urllib.request.urlopen(request)
            sgf = json.loads(response.read().decode("utf-8"))['chess']
            break
        except Exception as e:
            if i == 9:
                print(f"下载失败: {fn}, 错误: {e}")
                return # 失败跳过

    with codecs.open(fn, 'w', 'utf-8') as f:
        f.write(sgf)

def download_all_user_sgf():
    print(f"开始抓取用户 {USERNAME} 的棋谱...")
    chessid, fn = game_list("")
    if not chessid:
        print("未找到任何棋谱。")
        return
        
    idx = 0
    # 处理第一页
    for i in range(len(chessid)):
        download_sgf(chessid[i], fn[i])
        print(idx + i + 1, fn[i])
        time.sleep(0.3)

    # 循环处理后续页面
    while True:
        lastCode = chessid[-1]
        idx += len(chessid)
        chessid, fn = game_list(lastCode)

        if not chessid:
            break

        for i in range(len(chessid)):
            download_sgf(chessid[i], fn[i])
            print(idx + i + 1, fn[i])
            time.sleep(0.3)
    print("下载完成！")

# 程序入口
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', type=str, help='用户名')
    parser.add_argument('--start', type=str, help='开始时间 2020.01.01')
    parser.add_argument('--end', type=str, help='结束时间 2020.12.31')
    args = parser.parse_args()

    USERNAME = args.username
    start = args.start
    end = args.end

    if not USERNAME:
        print('请指定用户名，例如：python sgf_parser.py --username 柯洁')
        sys.exit()

    USERNAME_URL = urllib.parse.quote(USERNAME)
    # 获取 UID 的接口
    info_url = f"http://h5.foxwq.com/getFechInfo/wxnseed/txwq_fetch_personal_info?srcuid=0&dstuid=0&dstuin=0&username={USERNAME_URL}&accounttype=0&clienttype=0"
    
    try:
        req = urllib.request.Request(info_url)
        resp = urllib.request.urlopen(req)
        info_data = json.loads(resp.read())
        uid = str(info_data['uid'])
    except Exception as e:
        print(f"无法获取用户信息，请检查用户名是否正确或网络是否连接。错误: {e}")
        sys.exit()

    if not os.path.isdir(USERNAME):
        os.mkdir(USERNAME)

    download_all_user_sgf()