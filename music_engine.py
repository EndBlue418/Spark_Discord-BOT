import os
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

class SparkMusicEngine:
    def __init__(self, client_id=None, client_secret=None):
        # 🎀 Youtube-DL 設定：最佳化音質且不下載檔案
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0', # 強制使用 IPv4，避免部分地區連線緩慢
        }

        # 🎀 Spotify 初始化偵錯 (這會顯示在 Docker 終端機)
        print(f"--- 🎵 Spotify 引擎初始化中 ---")

        if not client_id or not client_secret:
            self.sp = None
            print("⚠️ 警告：Spotify 金鑰缺失！Spark 將無法解析 Spotify 連結。")
            return

        try:
            # 使用傳入的憑證啟動 Spotify 客戶端
            auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            # 測試連線
            self.sp.search(q='test', limit=1)
            print("✅ Spotify 引擎啟動成功！")
        except Exception as e:
            self.sp = None
            print(f"❌ Spotify 認證失敗：{e}")

    async def get_yt_source(self, search_query):
        """✨ 核心：取得 YouTube 播放用的串流 URL"""
        loop = asyncio.get_event_loop()

        # 如果是網址就直接抓取；如果是關鍵字就加上 ytsearch 前綴
        target_query = search_query if search_query.startswith("http") else f"ytsearch1:{search_query}"

        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                # 在執行緒池中跑同步的 ydl.extract_info，避免卡住非同步迴圈
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(target_query, download=False))

                if 'entries' in info:
                    if len(info['entries']) > 0:
                        entry = info['entries'][0]
                    else:
                        return None
                else:
                    entry = info

                # 回傳播放網址與標題
                return {
                    'url': entry['url'],
                    'title': entry['title']
                }

        except Exception as e:
            print(f"❌ YouTube 串流提取失敗: {e}")
            return None

    async def get_yt_playlist_urls(self, playlist_url):
        """🎵 解析整個 YouTube 歌單，回傳所有歌曲的連結清單"""
        loop = asyncio.get_event_loop()
        opts = self.ydl_opts.copy()
        opts['extract_flat'] = True # 只抓資訊不抓流，速度快很多

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(playlist_url, download=False))
                if 'entries' in info:
                    # 過濾空值並組成完整網址
                    return [f"https://www.youtube.com/watch?v={e['id']}" for e in info['entries'] if e]
            return []
        except Exception as e:
            print(f"❌ YouTube 歌單解析失敗: {e}")
            return []

    def get_spotify_tracks(self, spotify_url):
        """🌿 將 Spotify 連結（單曲/歌單/專輯）解析為「歌手 - 歌名」關鍵字清單"""
        if not self.sp:
            print("⚠️ 嘗試解析 Spotify 但引擎未啟動")
            return []

        tracks = []
        try:
            # 1. 處理單曲連結 (Track)
            if 'track' in spotify_url:
                track = self.sp.track(spotify_url)
                artists = ", ".join([artist['name'] for artist in track['artists']])
                tracks.append(f"{artists} - {track['name']}")

            # 2. 處理歌單連結 (Playlist)
            elif 'playlist' in spotify_url:
                results = self.sp.playlist_tracks(spotify_url)
                items = results['items']
                # 如果歌單超過 100 首，持續抓取下一頁
                while results['next']:
                    results = self.sp.next(results)
                    items.extend(results['items'])
                for item in items:
                    if item['track']:
                        track = item['track']
                        artists = ", ".join([artist['name'] for artist in track['artists']])
                        tracks.append(f"{artists} - {track['name']}")

            # 3. 處理專輯連結 (Album)
            elif 'album' in spotify_url:
                results = self.sp.album_tracks(spotify_url)
                items = results['items']
                while results['next']:
                    results = self.sp.next(results)
                    items.extend(results['items'])

                album_info = self.sp.album(spotify_url)
                artists = ", ".join([artist['name'] for artist in album_info['artists']])
                for track in items:
                    tracks.append(f"{artists} - {track['name']}")

            print(f"✅ Spotify 解析完成，共取得 {len(tracks)} 首歌曲")
        except Exception as e:
            print(f"❌ Spotify 連結解析出錯: {e}")

        return tracks