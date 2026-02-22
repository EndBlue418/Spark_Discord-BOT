import requests
import re
import html
import difflib
from pykakasi import kakasi

class LyricsEngine:
    def __init__(self):
        # 標頭設定，模擬瀏覽器請求
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        # 初始化 pykakasi (用於日文轉羅馬拼音)
        self._kks = kakasi()

    def _has_japanese(self, text):
        """檢查字串中是否有日文字元"""
        return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text))

    def _to_romaji(self, text):
        """將日文歌詞轉換為羅馬拼音，並套用 Discord 小字語法"""
        if not text or not self._has_japanese(text): return None
        try:
            result = self._kks.convert(text)
            romaji_list = [item.get('hepburn') or item.get('romaji') or "" for item in result]
            romaji = " ".join(filter(None, romaji_list))
            # 使用 -# 語法讓拼音在 Discord 中顯示為小字
            return f"-# {romaji}" if romaji else None
        except: return None

    def clean_search_query(self, query):
        """清理搜尋關鍵字，移除括號與無關標籤 (如 MV、Official 等)"""
        if not query: return ""
        query = re.sub(r'\(.*?\)|\[.*?\]|【.*?】', '', query)
        garbage = ['official video', 'official mv', 'official audio', 'music video', 'lyrics', 'lyric', 'full audio', 'hd', 'hq', '1080p', '4k', 'mv', '字幕', 'feat\.', 'ft\.']
        pattern = re.compile('|'.join(map(re.escape, garbage)), re.IGNORECASE)
        query = pattern.sub('', query)
        return query.strip()

    def _is_trustworthy(self, target, candidate, logs):
        """🔍 驗證機制：計算搜尋結果與目標標題的相似度"""
        if not candidate: return False
        t_clean = target.lower().replace(" ", "")
        c_clean = candidate.lower().replace(" ", "")
        ratio = difflib.SequenceMatcher(None, t_clean, c_clean).ratio()

        # 針對短標題設定嚴格門檻 (0.8)，長標題則寬鬆一點 (0.5)
        threshold = 0.8 if len(target) < 20 else 0.5
        logs.append(f"📊 標題比對: {ratio:.2f} (門檻: {threshold}) -> `{candidate}`")
        return ratio >= threshold

    def parse_lrc(self, lrc_content):
        """解析 LRC 格式的歌詞文字為 {秒數: 內容} 的字典"""
        lyric_dict = {}
        if not lrc_content: return None
        clean_content = html.unescape(lrc_content)
        for line in clean_content.split('\n'):
            # 正則匹配時間標籤 [mm:ss.xx]
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

    def _merge_lyrics(self, original, translated):
        """將原文、羅馬拼音、翻譯歌詞合併為 Discord 顯示格式"""
        if not original: return None
        merged = {}
        for timestamp, text in original.items():
            line_content = f"{text}"
            romaji = self._to_romaji(text)
            if romaji: line_content += f"\n{romaji}"

            trans_text = translated.get(timestamp) if translated else None
            # 如果有翻譯且與原文不同，則加上斜體翻譯
            if trans_text and trans_text != text:
                line_content += f"\n*{trans_text}*"
            merged[timestamp] = line_content
        return merged

    def get_dynamic_lyrics(self, spotify_title=None, youtube_title=None):
        """🌸 雙源強效搜尋入口 (回傳: 歌詞字典, 日誌列表)"""
        current_logs = []

        # 第一輪：優先嘗試 Spotify 提供的精準標題
        if spotify_title:
            current_logs.append(f"🔍 [第一輪] 嘗試 Spotify 標題: `{spotify_title}`")
            res = self._try_qq(spotify_title, current_logs) or self._try_netease(spotify_title, current_logs)
            if res:
                current_logs.append("✅ 成功匹配歌詞！")
                return res, current_logs

        # 第二輪：YouTube 標題備援 (通常較雜亂)
        if youtube_title:
            target_yt = self.clean_search_query(youtube_title)
            current_logs.append(f"🔍 [第二輪] 啟動 YT 備援搜尋: `{target_yt}`")
            res = self._try_qq(target_yt, current_logs) or self._try_netease(target_yt, current_logs)
            if res:
                current_logs.append("✅ 成功匹配歌詞！")
                return res, current_logs

        current_logs.append("❌ 遺憾...無法找到匹配的動態歌詞。")
        return None, current_logs

    def _try_qq(self, target_name, logs):
        """嘗試從 QQ 音樂抓取"""
        try:
            search_query = self.clean_search_query(target_name)
            res = requests.get("https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                params={"w": search_query, "format": "json", "n": 1},
                headers={"Referer": "https://y.qq.com/"}, timeout=3)
            song = res.json().get('data', {}).get('song', {}).get('list', [])[0]
            res_title = f"{song.get('singer', [{}])[0].get('name')} {song.get('songname')}"

            if not self._is_trustworthy(target_name, res_title, logs): return None

            l_res = requests.get("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
                params={"songmid": song.get('songmid'), "format": "json", "nobase64": 1, "platform": "yqq.json"},
                headers={"Referer": "https://y.qq.com/"}, timeout=3)
            lyric_data = l_res.json()
            parsed = self.parse_lrc(lyric_data.get('lyric'))
            return self._merge_lyrics(parsed, self.parse_lrc(lyric_data.get('trans'))) if parsed else None
        except: return None

    def _try_netease(self, target_name, logs):
        """嘗試從 網易雲音樂 抓取"""
        try:
            search_query = self.clean_search_query(target_name)
            res = requests.get("https://music.163.com/api/search/get",
                params={"s": search_query, "type": 1, "limit": 1}, timeout=3)
            song = res.json().get('result', {}).get('songs', [])[0]
            res_title = f"{song.get('artists', [{}])[0].get('name')} {song.get('name')}"

            if not self._is_trustworthy(target_name, res_title, logs): return None

            l_res = requests.get("https://music.163.com/api/song/lyric",
                params={"id": song.get('id'), "lv": -1, "kv": -1, "tv": -1}, timeout=3)
            l_data = l_res.json()
            parsed = self.parse_lrc(l_data.get('lrc', {}).get('lyric'))
            return self._merge_lyrics(parsed, self.parse_lrc(l_data.get('tlyric', {}).get('lyric'))) if parsed else None
        except: return None