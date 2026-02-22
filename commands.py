import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
import random
import os
import datetime
import logging
from lyrics_engine import LyricsEngine

# ======================================================
# --- 1. 音樂控制面板 (MusicControlView) ---
# ======================================================
class MusicControlView(discord.ui.View):
    """
    這是一個高度互動的 Discord UI 組件。
    它會附加在艾瑪的播放訊息下方，提供使用者即時的播放控制權，
    省去輸入斜線指令的麻煩，並同步將動作記錄到日誌系統中。
    """
    def __init__(self, bot, vc, cog):
        # timeout=None 確保這個 View 在機器人運作期間永久有效，不會因為逾時而失效
        super().__init__(timeout=None)
        self.bot = bot
        self.vc = vc
        self.cog = cog

    @discord.ui.button(label="⏮️ 上一首", style=discord.ButtonStyle.secondary, custom_id="emma_music_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：回溯播放歷史紀錄"""
        guild_id = interaction.guild_id
        last_song = self.cog.last_played.get(guild_id)

        if last_song:
            await self.bot.dispatch_log(f"⏮️ [控制面板] 使用者 {interaction.user.name} 請求回放上一首歌")
            # 邏輯：將當前歌曲塞回排隊首位，將歷史歌曲插到最前面
            current = self.cog.current_song.get(guild_id)
            if current:
                self.cog.queues[guild_id].insert(0, current)

            self.cog.queues[guild_id].insert(0, last_song)
            self.vc.stop() # 停止當前播放，藉此觸發 check_queue
            await interaction.response.send_message("⏮️ 好的！艾瑪正在幫妳找回剛才的旋律...呢。", ephemeral=True)
        else:
            await self.bot.dispatch_log(f"⚠️ [控制面板] {interaction.user.name} 嘗試按上一首，但歷史紀錄為空")
            await interaction.response.send_message("🌸 艾瑪的記憶體裡找不到上一首歌的紀錄呢。", ephemeral=True)

    @discord.ui.button(label="⏯️ 暫停/繼續", style=discord.ButtonStyle.primary, custom_id="emma_music_toggle")
    async def toggle_play_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：切換語音客戶端的播放或暫停狀態"""
        if self.vc.is_playing():
            self.vc.pause()
            await self.bot.dispatch_log(f"⏸️ [控制面板] 使用者 {interaction.user.name} 暫停了播放")
            await interaction.response.send_message("⏸️ 已經幫妳按下暫停鍵囉！", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await self.bot.dispatch_log(f"▶️ [控制面板] 使用者 {interaction.user.name} 恢復了播放")
            await interaction.response.send_message("▶️ 音樂繼續響起！讓旋律再次流動吧 ✨", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 艾瑪現在好像沒在唱歌，沒辦法暫停呢。", ephemeral=True)

    @discord.ui.button(label="⏭️ 下一首", style=discord.ButtonStyle.secondary, custom_id="emma_music_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：停止當前播放以進入下一首"""
        if self.vc.is_playing() or self.vc.is_paused():
            await self.bot.dispatch_log(f"⏭️ [控制面板] 使用者 {interaction.user.name} 跳過了目前的歌曲")
            self.vc.stop() # 停止會自動觸發 after 回調中的 check_queue
            await interaction.response.send_message("⏭️ 收到！這首歌先休息，我們換下一首～ ✨", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 排隊清單裡已經沒有歌可以跳過囉。", ephemeral=True)

    @discord.ui.button(label="🔁 循環模式", style=discord.ButtonStyle.success, custom_id="emma_music_loop")
    async def toggle_loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：循環切換 (0:關閉, 1:單曲, 2:清單)"""
        guild_id = interaction.guild_id
        current_mode = self.cog.loop_mode.get(guild_id, 0)
        new_mode = (current_mode + 1) % 3
        self.cog.loop_mode[guild_id] = new_mode

        # 更新按鈕文字以即時反應狀態
        labels = {0: "🔁 循環: 關閉", 1: "🔂 單曲循環", 2: "🔁 清單循環"}
        button.label = labels[new_mode]

        await self.bot.dispatch_log(f"🔄 [控制面板] 使用者 {interaction.user.name} 切換循環模式為: {labels[new_mode]}")
        # 編輯原始訊息以反映按鈕標籤的更改
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🗑️ 清空", style=discord.ButtonStyle.danger, custom_id="emma_music_clear")
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：清除所有後續等待播放的曲目"""
        guild_id = interaction.guild_id
        queue_count = len(self.cog.queues.get(guild_id, []))
        self.cog.queues[guild_id] = []

        await self.bot.dispatch_log(f"🗑️ [控制面板] 使用者 {interaction.user.name} 清空了佇列 (共 {queue_count} 首)")
        await interaction.response.send_message(f"🗑️ 已經幫妳把後面的 {queue_count} 首歌都清理掉囉！", ephemeral=True)

    @discord.ui.button(label="⏹️ 停止並離開", style=discord.ButtonStyle.danger, row=1, custom_id="emma_music_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：徹底結束播放、清空佇列並中斷語音連線"""
        guild_id = interaction.guild_id
        await self.bot.dispatch_log(f"⏹️ [控制面板] 使用者 {interaction.user.name} 請求讓艾瑪離開語音頻道")

        self.cog.queues[guild_id] = []
        if self.vc:
            await self.vc.disconnect()

        await interaction.response.send_message("🚪 好的，艾瑪先去休息休息，期待下次再唱歌給妳聽！🌸", ephemeral=True)

# ======================================================
# --- 2. 指令核心模組 (AskCommand Cog) ---
# ======================================================
class AskCommand(commands.Cog):
    """
    這是艾瑪的「大腦」核心。
    負責統合 AI 對話、音樂搜尋、FFmpeg 串流播放、
    以及最重要的：進度條與歌詞同步系統。
    """
    def __init__(self, bot, ai_engine, music_engine):
        self.bot = bot
        self.ai = ai_engine
        self.music = music_engine
        self.lyrics_engine = LyricsEngine()

        # 核心數據儲存 (使用字典以支援多伺服器併發)
        self.queues = {}       # {guild_id: [歌曲列表]}
        self.last_played = {}  # {guild_id: 上一首曲目資訊}
        self.current_song = {} # {guild_id: 當前播放曲目資訊}
        self.loop_mode = {}    # {guild_id: 循環模式代碼}

        # 設定日誌格式
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("EmmaMusic")

    def format_time(self, seconds):
        """將秒數格式化為 mm:ss 顯示，例如將 125 秒轉為 02:05"""
        m, s = divmod(int(max(0, seconds)), 60)
        return f"{m:02d}:{s:02d}"

    async def get_ai_response(self, user_id, user_name, question, source="Slash"):
        """統一的 AI 對話處理入口，包含日誌分發"""
        await self.bot.dispatch_log(f"💬 [{source}] {user_name}: {question}")
        try:
            answer = await self.ai.get_chat_response(str(user_id), question)
            return answer
        except Exception as e:
            await self.bot.dispatch_log(f"💥 [AI 故障] 無法回應 {user_name}: {e}")
            return "🌸 嗚嗚...艾瑪頭好痛，暫時沒辦法回答妳..."

    # ------------------------------------------------------
    # --- 🌸 核心亮點：進度條與動態歌詞同步系統---
    # ------------------------------------------------------
    async def lyrics_sync_task(self, vc, spotify_title, youtube_title, message):
        """
        1. 修正 f-string 內包含反斜線造成的初始化失敗。
        2. 校準時間偏移，解決歌詞提前問題。
        3. 強化翻譯救援，支援列表與特殊字串格式。
        """
        guild_id = message.guild.id
        duration = self.current_song.get(guild_id, {}).get('duration', 0)

        lyric_dict = {}
        sorted_times = []
        is_lyrics_ready = False

        # 1. 🚀 背景異步載入
        async def fetch_lyrics_background():
            nonlocal lyric_dict, sorted_times, is_lyrics_ready
            try:
                data, search_logs = await self.bot.loop.run_in_executor(
                    None, self.lyrics_engine.get_dynamic_lyrics, spotify_title, youtube_title
                )
                if data:
                    lyric_dict = data
                    sorted_times = sorted(lyric_dict.keys())
                    is_lyrics_ready = True
                    for entry in search_logs:
                        await self.bot.dispatch_log(f"🔍 [歌詞搜尋] {entry}")
                    await self.bot.dispatch_log(f"✅ [歌詞就緒] 翻譯數據已載入。")
            except Exception as e:
                await self.bot.dispatch_log(f"⚠️ [加載失敗] {e}")

        self.bot.loop.create_task(fetch_lyrics_background())

        # 2. 🕰️ 時間對齊校準
        # 調低 offset 避免歌詞提前，並精確同步啟動時刻
        delay_offset = 0
        start_time = time.time()
        last_second = 0
        display_duration = duration if duration > 0 else 240

        # 3. 監控迴圈
        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            if vc.is_paused():
                start_time += 0.5
                await asyncio.sleep(0.5)
                continue

            elapsed = (time.time() - start_time) + delay_offset
            current_second = int(elapsed)

            if current_second != last_second:
                last_second = current_second

                # --- 翻譯救援邏輯
                current_sentence = "🌸 **正在準備伴唱...**"

                if is_lyrics_ready and lyric_dict:
                    current_sentence = "🎵 **(間奏中)** 🎵"
                    for t in sorted_times:
                        if elapsed >= t:
                            raw_data = lyric_dict[t]

                            # 🛠️ 邏輯：先處理好文字，再塞進 f-string
                            if isinstance(raw_data, list):
                                # 將 [原文, 翻譯] 合併成帶有換行的粗體字串
                                processed_text = "\n".join([str(line) for line in raw_data if line])
                                current_sentence = f"**{processed_text}**"
                            elif isinstance(raw_data, str):
                                # 修正：在 f-string 外處理換行符號
                                processed_text = raw_data.replace('|', '\n').replace('\\n', '\n')
                                current_sentence = f"**{processed_text}**"
                            else:
                                current_sentence = f"**{str(raw_data)}**"
                        else:
                            break

                # --- 進度條 UI (🔘) ---
                bar_len = 14
                prog = min(elapsed / display_duration, 1.0)
                filled = int(prog * bar_len)
                bar_ui = "▬" * filled + "🔘" + "─" * (max(0, bar_len - filled))

                time_label = f"{self.format_time(elapsed)} / {self.format_time(duration)}" if duration > 0 else self.format_time(elapsed)

                # 4. 渲染 Embed
                embed = discord.Embed(
                    title="🌸 伴唱同步中",
                    description=f"**『 {spotify_title} 』**\n\n{current_sentence}\n\n{bar_ui}\n`{time_label}`",
                    color=0xffb6c1,
                    timestamp=datetime.datetime.now()
                )
                embed.set_footer(text="享受這段旋律吧！ ✨")

                try:
                    await message.edit(embed=embed)
                except Exception:
                    break

            await asyncio.sleep(0.5)

    # ------------------------------------------------------
    # --- 🎵 音樂排程管理邏輯 (Music Dispatcher) ---
    # ------------------------------------------------------

    def check_queue(self, interaction, vc):
        """
        當一首歌播放結束後由 FFmpeg 自動觸發。
        負責根據目前的循環模式 (Loop Mode) 來挑選下一首曲目。
        """
        guild_id = interaction.guild_id
        mode = self.loop_mode.get(guild_id, 0) # 0:無, 1:單曲, 2:清單
        current = self.current_song.get(guild_id)

        next_item = None

        # 決定下一首
        if mode == 1 and current:
            next_item = current
            self.bot.dispatch_log(f"🔂 [循環] 正在執行單曲循環：{current['query']}")
        elif mode == 2 and current:
            if guild_id in self.queues:
                self.queues[guild_id].append(current) # 播完後插回清單尾端
                next_item = self.queues[guild_id].pop(0) if self.queues[guild_id] else None
                self.bot.dispatch_log(f"🔁 [循環] 正在執行清單循環")
        else:
            if guild_id in self.queues and self.queues[guild_id]:
                next_item = self.queues[guild_id].pop(0)

        # 執行下一首播放
        if next_item:
            self.bot.loop.create_task(self.play_music_task(interaction, vc, next_item))
        else:
            self.current_song[guild_id] = None
            self.bot.dispatch_log(f"🏁 [播放結束] 伺服器 {interaction.guild.name} 的播放隊列已清空")

    async def play_music_task(self, interaction, vc, item):
        """
        音樂播放的主執行任務。
        包含：URL 解析、FFmpeg 裝甲參數初始化、訊息發送、同步任務掛載。
        """
        try:
            guild_id = interaction.guild_id

            # 歷史紀錄保存 (供 /prev 指令使用)
            if self.current_song.get(guild_id) and self.current_song.get(guild_id) != item:
                self.last_played[guild_id] = self.current_song[guild_id]

            # 抓取 YouTube 數據
            source_data = await self.music.get_yt_source(item['query'])
            if not source_data:
                await self.bot.dispatch_log(f"❌ [播放異常] 無法獲取音訊來源：{item['query']}")
                return

            # 更新曲目狀態
            item['duration'] = source_data.get('duration', 0)
            self.current_song[guild_id] = item
            s_title = item.get('clean_title') or source_data['title']

            # 🔍 自動偵測 FFmpeg：優先找系統指令 (Termux/Docker)，找不到才用 Windows 備份路徑
            import shutil
            FFMPEG_EXE = shutil.which("ffmpeg") or r"C:\Users\李冠霖\暫存\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"

            # 🛠️ 強化型 FFmpeg 參數：防止 IO Error、EOF 錯誤與串流中斷
            FFMPEG_OPTIONS = {
                'before_options': (
                    '-reconnect 1 '
                    '-reconnect_at_eof 1 '        # 遇到檔案結尾強制重連 (修復 IO Error)
                    '-reconnect_streamed 1 '
                    '-reconnect_delay_max 5 '
                    '-headers "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
                    '-probesize 10M '             # 增加探測緩衝
                    '-analyzeduration 0'
                ),
                'options': '-vn',
            }

            # 建立音訊來源
            audio_source = discord.FFmpegPCMAudio(source_data['url'], executable=FFMPEG_EXE, **FFMPEG_OPTIONS)

            # 開始播放並綁定後續動作
            vc.play(audio_source, after=lambda e: self.check_queue(interaction, vc))
            await self.bot.dispatch_log(f"🎵 [音樂啟動] 正在播放：{s_title} | 預計時長：{self.format_time(item['duration'])}")

            # 發送 UI 面板
            view = MusicControlView(self.bot, vc, self)
            embed = discord.Embed(
                title="🎵 正在播放",
                description=f"**[{s_title}]**\n\n*🌸 艾瑪正在為妳啟動動態歌詞與翻譯...*",
                color=0xffb6c1
            )

            # 🚀 關鍵點：獲取傳回的 message 物件以啟動同步循環
            msg = None
            if not interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, view=view)
            else:
                msg = await interaction.channel.send(embed=embed, view=view)

            if msg:
                self.bot.loop.create_task(self.lyrics_sync_task(vc, s_title, source_data['title'], msg))

        except Exception as e:
            await self.bot.dispatch_log(f"💥 [播放任務崩潰] {e}")

    # ======================================================
    # --- 3. 斜線指令系統 (Slash Commands) ---
    # ======================================================

    @app_commands.command(name="ask", description="向艾瑪提問任何事 ✨")
    async def ask(self, interaction: discord.Interaction, question: str):
        """讓使用者與艾瑪對話的指令"""
        await interaction.response.defer(thinking=True)
        answer = await self.get_ai_response(interaction.user.id, interaction.user.name, question, source="Slash")
        await interaction.followup.send(answer)

    @app_commands.command(name="play", description="點燃妳的音樂！支援 Spotify 連結、YouTube 連結或直接搜尋。")
    @app_commands.describe(input_str="輸入歌曲標題、YouTube 網址或 Spotify 網址")
    async def play(self, interaction: discord.Interaction, input_str: str):
        """主要的音樂點歌指令"""
        await interaction.response.defer(thinking=True)

        # 1. 確保艾瑪在語音頻道內
        vc = interaction.guild.voice_client
        if not vc:
            if interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()
                await self.bot.dispatch_log(f"🎤 [語音進入] 艾瑪已應邀進入頻道：{interaction.user.voice.channel.name}")
            else:
                return await interaction.followup.send("🌸 妳得先進去語音頻道，我才找得到妳呀！")

        guild_id = interaction.guild_id
        if guild_id not in self.queues:
            self.queues[guild_id] = []

        # 2. 解析並加入清單
        added_count = 0
        if "spotify.com" in input_str:
            tracks = self.music.get_spotify_tracks(input_str)
            for t in tracks:
                self.queues[guild_id].append({'query': t, 'clean_title': t})
            added_count = len(tracks)
        elif "list=" in input_str:
            urls = await self.music.get_yt_playlist_urls(input_str)
            for u in urls:
                self.queues[guild_id].append({'query': u, 'clean_title': None})
            added_count = len(urls)
        else:
            self.queues[guild_id].append({'query': input_str, 'clean_title': None})
            added_count = 1

        await self.bot.dispatch_log(f"📥 [清單更新] {interaction.user.name} 加入了 {added_count} 首歌")

        # 3. 如果目前沒在唱歌，立即啟動播放任務
        if not vc.is_playing() and not vc.is_paused():
            if self.queues[guild_id]:
                target = self.queues[guild_id].pop(0)
                await self.play_music_task(interaction, vc, target)
                await interaction.followup.send(f"🌸 音樂啟動！成功將 {added_count} 首歌加入排隊清單 ✨")
        else:
            await interaction.followup.send(f"✅ 好的！已幫妳把 {added_count} 首歌加入排隊囉！")

    @app_commands.command(name="skip", description="跳過這首歌 ⏭️")
    @app_commands.describe(target="想要跳轉到的歌曲序號 (例如輸入 3 直接播排隊中第 3 首)")
    async def skip(self, interaction: discord.Interaction, target: int = None):
        """跳過目前曲目或精確跳轉"""
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("🌸 艾瑪目前沒有在唱歌，沒辦法跳過唷。", ephemeral=True)

        if target is not None:
            if guild_id in self.queues and 1 <= target <= len(self.queues[guild_id]):
                removed = target - 1
                for _ in range(removed): self.queues[guild_id].pop(0)
                vc.stop()
                await self.bot.dispatch_log(f"🚀 [跳轉] {interaction.user.name} 強制跳轉，跳過前 {removed} 首")
                await interaction.response.send_message(f"🚀 收到！跳過中間曲目，直接為妳播放第 {target} 首歌！")
            else:
                await interaction.response.send_message("🌸 序號超出範圍了啦！", ephemeral=True)
        else:
            vc.stop()
            await interaction.response.send_message("⏭️ 下一首！出發～ ✨")

    @app_commands.command(name="queue", description="查看當前的點歌清單 🎵")
    async def queue(self, interaction: discord.Interaction):
        """顯示目前正在等待播放的前 10 首歌曲"""
        q = self.queues.get(interaction.guild_id, [])
        if not q:
            return await interaction.response.send_message("🌸 目前排隊清單空蕩蕩的，快去點歌吧！")

        display = "\n".join([f"**{i+1}.** {(x['clean_title'] or x['query'])[:45]}..." for i, x in enumerate(q[:10])])
        embed = discord.Embed(title="🎵 待播放清單 (前 10 首)", description=display, color=0xffb6c1)
        if len(q) > 10:
            embed.set_footer(text=f"還有額外 {len(q)-10} 首歌正在候選中...")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leave", description="停止播放並讓艾瑪休息 🚪")
    async def leave(self, interaction: discord.Interaction):
        """斷開連線並清空隊列"""
        vc = interaction.guild.voice_client
        if vc:
            self.queues[interaction.guild_id] = []
            await vc.disconnect()
            await interaction.response.send_message("🚪 艾瑪先退下了，有音樂需要隨時叫我！🌸")
            await self.bot.dispatch_log(f"🚪 [中斷] {interaction.user.name} 結束了播放會話")
        else:
            await interaction.response.send_message("🌸 我本來就不在頻道裡呀？")

# ======================================================
# --- 4. 模組載入入口 (Setup) ---
# ======================================================
async def setup(bot, ai_engine, music_engine):
    """Cog 載入函數：將 AskCommand 註冊至機器人"""
    new_cog = AskCommand(bot, ai_engine, music_engine)
    await bot.add_cog(new_cog)
    print(f"✅ [系統日誌] 音樂核心 Cog 已成功載入！(FLAGSHIP VERSION: 400+ lines)")