import os
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from concurrent.futures import ThreadPoolExecutor

class SparkMusicEngine:
    def __init__(self, client_id=None, client_secret=None):
        # 1. 優先設定基礎配置
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'socket_timeout': 10,
            'retries': 5,
            'nocheckcertificate': True,
        }

        # 2. 初始化執行緒池 (確保在 get_spotify_tracks_async 呼叫前存在)
        self.executor = ThreadPoolExecutor(max_workers=10)

        print(f"--- 🎵 Spotify 引擎初始化中 ---")

        # 3. Spotify 初始化
        if not client_id or not client_secret:
            self.sp = None
            print("⚠️ 警告：Spotify 金鑰缺失！")
        else:
            try:
                auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
                self.sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10)
                # 測試連接
                self.sp.search(q='test', limit=1)
                print("✅ Spotify 引擎啟動成功！")
            except Exception as e:
                self.sp = None
                print(f"❌ Spotify 認證失敗：{e}")

    def _extract_yt_info(self, query):
        """同步提取邏輯，確保回傳的是真正的串流 URL"""
        # 每次提取單曲時，確保不使用 extract_flat，否則拿不到流網址
        opts = self.ydl_opts.copy()

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                if 'entries' in info:
                    if not info['entries']: return None
                    entry = info['entries'][0]
                else:
                    entry = info

                # 🔍 終極網址抓取：排除網頁網址，尋找 googlevideo 連結
                stream_url = None

                # 嘗試 1: 直接找 url 欄位
                raw_url = entry.get('url')
                if raw_url and 'youtube.com' not in raw_url:
                    stream_url = raw_url

                # 嘗試 2: 從 formats 裡挑選最好的純音軌
                if not stream_url and 'formats' in entry:
                    # 篩選沒有影片(vcodec='none')且有網址的格式，取最後一個(通常品質最高)
                    best_audio = [f for f in entry['formats'] if f.get('vcodec') == 'none' and f.get('url')]
                    if best_audio:
                        stream_url = best_audio[-1]['url']

                if not stream_url:
                    print(f"⚠️ 艾瑪警告：無法解析有效串流網址: {entry.get('title')}")
                    return None

                return {
                    'url': stream_url,
                    'title': entry.get('title', 'Unknown Title'),
                    'duration': entry.get('duration', 0)
                }
            except Exception as e:
                print(f"❌ yt-dlp 內部崩潰: {e}")
                return None

    async def get_yt_source(self, search_query):
        """✨ 取得 YouTube 串流 URL"""
        loop = asyncio.get_event_loop()
        target_query = search_query if search_query.startswith("http") else f"ytsearch1:{search_query}"
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._extract_yt_info, target_query),
                timeout=25.0
            )
        except Exception as e:
            print(f"❌ YouTube 提取失敗: {e}")
            return None

    async def get_yt_playlist_urls(self, playlist_url):
        """🎵 解析 YouTube 歌單 (使用 flat 模式提高速度)"""
        loop = asyncio.get_event_loop()
        opts = self.ydl_opts.copy()
        opts['extract_flat'] = True
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(playlist_url, download=False)),
                timeout=30.0
            )
            if 'entries' in info:
                return [f"https://www.youtube.com/watch?v={e['id']}" for e in info['entries'] if e]
            return []
        except Exception as e:
            print(f"❌ 歌單解析失敗: {e}")
            return []

    async def get_spotify_tracks_async(self, spotify_url):
        """🌿 非同步 Spotify 解析"""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, self._get_spotify_tracks_sync, spotify_url),
                timeout=60.0
            )
        except Exception as e:
            print(f"❌ Spotify 解析超時或錯誤: {e}")
            return []

    def _get_spotify_tracks_sync(self, spotify_url):
        """同步 Spotify 解析邏輯"""
        if not self.sp: return []
        tracks = []
        try:
            if 'track' in spotify_url:
                track = self.sp.track(spotify_url)
                artists = ", ".join([a['name'] for a in track['artists']])
                tracks.append(f"{artists} - {track['name']}")
            elif 'playlist' in spotify_url:
                results = self.sp.playlist_tracks(spotify_url)
                items = results['items']
                while results['next']:
                    results = self.sp.next(results)
                    items.extend(results['items'])
                for item in items:
                    if item.get('track'):
                        t = item['track']
                        artists = ", ".join([a['name'] for a in t['artists']])
                        tracks.append(f"{artists} - {t['name']}")
            elif 'album' in spotify_url:
                results = self.sp.album_tracks(spotify_url)
                items = results['items']
                while results['next']:
                    results = self.sp.next(results)
                    items.extend(results['items'])
                album_info = self.sp.album(spotify_url)
                artists = ", ".join([a['name'] for a in album_info['artists']])
                for t in items:
                    tracks.append(f"{artists} - {t['name']}")
            print(f"✅ Spotify 解析完成，取得 {len(tracks)} 首歌曲")
        except Exception as e:
            print(f"❌ Spotify 同步解析錯誤: {e}")
        return tracks