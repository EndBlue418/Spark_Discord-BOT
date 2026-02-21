import os
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

class SparkMusicEngine:
    def __init__(self, client_id=None, client_secret=None):
        # 🎀 Youtube-DL 設定
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
        }

        # 🎀 Spotify 初始化偵錯
        print(f"--- Spotify 引擎初始化中 ---")
        print(f"收到 ID: {'已取得' if client_id else '空值(None)'}")
        print(f"收到 Secret: {'已取得' if client_secret else '空值(None)'}")

        if not client_id or not client_secret:
            self.sp = None
            print("⚠️ 警告：主程式傳過來的 Spotify 金鑰是空的！請檢查 Spark.py 的 os.getenv 是否正確。")
            return

        try:
            # ✨ 這裡確保直接使用傳進來的參數
            auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            self.sp.search(q='test', limit=1)
            print("✅ Spotify 引擎啟動成功！")
        except Exception as e:
            self.sp = None
            print(f"⚠️ Spotify 認證失敗，請檢查金鑰是否正確：{e}")

    # ... get_yt_source 等其餘程式碼保持不變 ...

    async def get_yt_source(self, search_query):
        """取得播放用的串流 URL ✨"""
        loop = asyncio.get_event_loop()

        # 如果是網址就直接抓，不是就搜尋
        target_query = search_query if search_query.startswith("http") else f"ytsearch1:{search_query}"

        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(target_query, download=False))

                if 'entries' in info:
                    if len(info['entries']) > 0:
                        entry = info['entries'][0]
                    else:
                        return None
                else:
                    entry = info

                return {
                    'url': entry['url'],
                    'title': entry['title']
                }

        except Exception as e:
            print(f"❌ 取得串流失敗: {e}")
            return None

    async def get_yt_playlist_urls(self, playlist_url):
        """解析 YouTube 歌單 🎵"""
        loop = asyncio.get_event_loop()
        opts = self.ydl_opts.copy()
        opts['extract_flat'] = True

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(playlist_url, download=False))
                if 'entries' in info:
                    return [f"https://www.youtube.com/watch?v={e['id']}" for e in info['entries'] if e]
            return []
        except Exception as e:
            print(f"❌ 解析歌單失敗: {e}")
            return []

    def get_spotify_tracks(self, spotify_url):
        """將 Spotify 連結解析為關鍵字清單 🌿"""
        if not self.sp:
            return []

        tracks = []
        try:
            # 歌曲連結
            if 'track' in spotify_url:
                track = self.sp.track(spotify_url)
                artists = ", ".join([artist['name'] for artist in track['artists']])
                tracks.append(f"{artists} - {track['name']}")

            # 歌單連結
            elif 'playlist' in spotify_url:
                results = self.sp.playlist_tracks(spotify_url)
                items = results['items']
                while results['next']:
                    results = self.sp.next(results)
                    items.extend(results['items'])
                for item in items:
                    if item['track']:
                        track = item['track']
                        artists = ", ".join([artist['name'] for artist in track['artists']])
                        tracks.append(f"{artists} - {track['name']}")

            # 專輯連結
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

        except Exception as e:
            print(f"❌ Spotify 解析失敗: {e}")

        return tracks