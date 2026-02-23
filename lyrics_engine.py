import asyncio
import requests
import re
import html
import difflib
from pykakasi import kakasi
from concurrent.futures import ThreadPoolExecutor

class LyricsEngine:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        self._kks = kakasi()
        # 🎀 建立執行緒池處理 CPU 密集型運算 (kakasi 和 difflib)
        self.executor = ThreadPoolExecutor(max_workers=4)

    def _has_japanese(self, text):
        return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text))

    def _to_romaji_sync(self, text):
        """同步的羅馬拼音轉換 (在 executor 裡跑)"""
        if not text or not self._has_japanese(text): return None
        try:
            result = self._kks.convert(text)
            romaji_list = [item.get('hepburn') or item.get('romaji') or "" for item in result]
            romaji = " ".join(filter(None, romaji_list))
            return f"-# {romaji}" if romaji else None
        except: return None

    def clean_search_query(self, query):
        if not query: return ""
        query = re.sub(r'\(.*?\)|\[.*?\]|【.*?】', '', query)
        garbage = ['official video', 'official mv', 'official audio', 'music video', 'lyrics', 'lyric', 'full audio', 'hd', 'hq', '1080p', '4k', 'mv', '字幕', 'feat\.', 'ft\.']
        pattern = re.compile('|'.join(map(re.escape, garbage)), re.IGNORECASE)
        query = pattern.sub('', query)
        return query.strip()

    def _is_trustworthy_sync(self, target, candidate, logs):
        """同步的比對邏輯 (在 executor 裡跑)"""
        if not candidate: return False
        t_clean = target.lower().replace(" ", "")
        c_clean = candidate.lower().replace(" ", "")
        ratio = difflib.SequenceMatcher(None, t_clean, c_clean).ratio()
        threshold = 0.8 if len(target) < 20 else 0.5
        logs.append(f"📊 標題比對: {ratio:.2f} (門檻: {threshold}) -> `{candidate}`")
        return ratio >= threshold

    def parse_lrc(self, lrc_content):
        lyric_dict = {}
        if not lrc_content: return None
        clean_content = html.unescape(lrc_content)
        for line in clean_content.split('\n'):
            match = re.search(r'\[(\d{2}):(\d{2})(?:\.(\d{2,3}))?\](.*)', line)
            if match:
                m, s = int(match.group(1)), int(match.group(2))
                ms_val = match.group(3)
                ms = int(ms_val) if ms_val else 0
                if ms_val and len(ms_val) == 2: ms *= 10
                total_sec = m * 60 + s + (ms / 1000.0)
                text = match.group(4).strip()
                if text: lyric_dict[total_sec] = text
        return lyric_dict if lyric_dict else None

    async def _merge_lyrics_async(self, original, translated):
        """✨ 核心改動：將羅馬拼音轉換丟到執行緒池，不卡住主迴圈"""
        if not original: return None
        loop = asyncio.get_event_loop()
        merged = {}

        # 收集所有的轉換任務
        tasks = []
        timestamps = list(original.keys())

        for timestamp in timestamps:
            text = original[timestamp]
            # 將 CPU 運算丟進 ThreadPool
            tasks.append(loop.run_in_executor(self.executor, self._to_romaji_sync, text))

        # 等待所有轉換完成
        romajis = await asyncio.gather(*tasks)

        for i, timestamp in enumerate(timestamps):
            text = original[timestamp]
            romaji = romajis[i]

            line_content = f"{text}"
            if romaji: line_content += f"\n{romaji}"

            trans_text = translated.get(timestamp) if translated else None
            if trans_text and trans_text != text:
                line_content += f"\n*{trans_text}*"
            merged[timestamp] = line_content
        return merged

    async def get_dynamic_lyrics(self, spotify_title=None, youtube_title=None):
        """✨ 核心改動：改為 async 函式"""
        current_logs = []

        if spotify_title:
            current_logs.append(f"🔍 [第一輪] 嘗試 Spotify 標題: `{spotify_title}`")
            # 這裡需要 await
            res = await self._try_qq(spotify_title, current_logs) or await self._try_netease(spotify_title, current_logs)
            if res:
                current_logs.append("✅ 成功匹配歌詞！")
                return res, current_logs

        if youtube_title:
            target_yt = self.clean_search_query(youtube_title)
            current_logs.append(f"🔍 [第二輪] 啟動 YT 備援搜尋: `{target_yt}`")
            res = await self._try_qq(target_yt, current_logs) or await self._try_netease(target_yt, current_logs)
            if res:
                current_logs.append("✅ 成功匹配歌詞！")
                return res, current_logs

        current_logs.append("❌ 遺憾...無法找到匹配的動態歌詞。")
        return None, current_logs

    async def _try_qq(self, target_name, logs):
        loop = asyncio.get_event_loop()
        try:
            search_query = self.clean_search_query(target_name)
            # 將同步請求丟進 executor
            res = await loop.run_in_executor(None, lambda: requests.get(
                "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                params={"w": search_query, "format": "json", "n": 1},
                headers={"Referer": "https://y.qq.com/"}, timeout=3).json())

            song = res.get('data', {}).get('song', {}).get('list', [])[0]
            res_title = f"{song.get('singer', [{}])[0].get('name')} {song.get('songname')}"

            # 這裡的比對也要丟進 executor，避免長字串比對卡死
            trustworthy = await loop.run_in_executor(self.executor, self._is_trustworthy_sync, target_name, res_title, logs)
            if not trustworthy: return None

            l_res = await loop.run_in_executor(None, lambda: requests.get(
                "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
                params={"songmid": song.get('songmid'), "format": "json", "nobase64": 1, "platform": "yqq.json"},
                headers={"Referer": "https://y.qq.com/"}, timeout=3).json())

            parsed = self.parse_lrc(l_res.get('lyric'))
            if parsed:
                return await self._merge_lyrics_async(parsed, self.parse_lrc(l_res.get('trans')))
            return None
        except: return None

    async def _try_netease(self, target_name, logs):
        loop = asyncio.get_event_loop()
        try:
            search_query = self.clean_search_query(target_name)
            res = await loop.run_in_executor(None, lambda: requests.get(
                "https://music.163.com/api/search/get",
                params={"s": search_query, "type": 1, "limit": 1}, timeout=3).json())

            song = res.get('result', {}).get('songs', [])[0]
            res_title = f"{song.get('artists', [{}])[0].get('name')} {song.get('name')}"

            trustworthy = await loop.run_in_executor(self.executor, self._is_trustworthy_sync, target_name, res_title, logs)
            if not trustworthy: return None

            l_res = await loop.run_in_executor(None, lambda: requests.get(
                "https://music.163.com/api/song/lyric",
                params={"id": song.get('id'), "lv": -1, "kv": -1, "tv": -1}, timeout=3).json())

            l_data = l_res
            parsed = self.parse_lrc(l_data.get('lrc', {}).get('lyric'))
            if parsed:
                return await self._merge_lyrics_async(parsed, self.parse_lrc(l_data.get('tlyric', {}).get('lyric')))
            return None
        except: return None