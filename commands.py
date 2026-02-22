import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
import random
import os
from lyrics_engine import LyricsEngine



# ======================================================
# --- 1. 音樂控制面板 (按鈕組件) ---
# ======================================================
class MusicControlView(discord.ui.View):
    """定義顯示在播放訊息下方的互動按鈕組"""
    def __init__(self, bot, vc, cog):
        super().__init__(timeout=None) # 設定按鈕不逾時
        self.bot, self.vc, self.cog = bot, vc, cog

    @discord.ui.button(label="⏮️ 上一首", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：回退至上一首播放紀錄"""
        guild_id = interaction.guild_id
        last_song = self.cog.last_played.get(guild_id)

        if last_song:
            # 邏輯：將當前歌曲塞回排隊首位，歷史歌曲插到最前面，停止播放以觸發 check_queue
            current = self.cog.current_song.get(guild_id)
            if current:
                self.cog.queues[guild_id].insert(0, current)

            self.cog.queues[guild_id].insert(0, last_song)
            self.vc.stop()

            await self.bot.dispatch_log(f"⏮️ [按鈕控制] {interaction.user.name} 請求回退上一首歌")
            await interaction.response.send_message("⏮️ 好的！正在找回剛才的旋律...呢。", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 記憶體裡找不到上一首歌的紀錄呢。", ephemeral=True)

    @discord.ui.button(label="⏯️ 暫停/繼續", style=discord.ButtonStyle.primary)
    async def toggle_play_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：切換播放或暫停狀態"""
        user = interaction.user
        if self.vc.is_playing():
            self.vc.pause()
            await self.bot.dispatch_log(f"⏸️ [按鈕控制] {user.name} 暫停了播放")
            await interaction.response.send_message(f"⏸️ 已暫停播放囉！", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await self.bot.dispatch_log(f"▶️ [按鈕控制] {user.name} 恢復了播放")
            await interaction.response.send_message(f"▶️ 音樂繼續響起！ ✨", ephemeral=True)

    @discord.ui.button(label="⏭️ 跳過", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：跳過目前歌曲"""
        if self.vc.is_playing() or self.vc.is_paused():
            await self.bot.dispatch_log(f"⏭️ [按鈕控制] {interaction.user.name} 跳過了歌曲")
            self.vc.stop()
            await interaction.response.send_message("⏭️ 收到！下一首～ ✨", ephemeral=True)

    @discord.ui.button(label="🔁 循環: 關閉", style=discord.ButtonStyle.success)
    async def toggle_loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：循環切換 (0:關閉, 1:單曲, 2:清單)"""
        guild_id = interaction.guild_id
        current_mode = self.cog.loop_mode.get(guild_id, 0)
        new_mode = (current_mode + 1) % 3
        self.cog.loop_mode[guild_id] = new_mode

        labels = {0: "🔁 循環: 關閉", 1: "🔂 單曲循環", 2: "🔁 清單循環"}
        button.label = labels[new_mode]

        await self.bot.dispatch_log(f"🔄 [按鈕控制] {interaction.user.name} 切換循環為: {labels[new_mode]}")
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🗑️ 清空", style=discord.ButtonStyle.danger)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：清空排隊佇列"""
        guild_id = interaction.guild_id
        count = len(self.cog.queues.get(guild_id, []))
        self.cog.queues[guild_id] = []
        await self.bot.dispatch_log(f"🗑️ [按鈕控制] {interaction.user.name} 清空了佇列 ({count} 首)")
        await interaction.response.send_message(f"🗑️ 已經幫妳清空後面的 {count} 首歌囉！", ephemeral=True)

    @discord.ui.button(label="⏹️ 停止並離開", style=discord.ButtonStyle.danger, row=1)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """[第二排右] 徹底結束並斷開連線"""
        guild_id = interaction.guild_id
        await self.bot.dispatch_log(f"⏹️ [按鈕控制] {interaction.user.name} 讓機器人停止並離開頻道")
        # 邏輯：清空清單並中斷語音
        self.cog.queues[guild_id] = []
        if self.vc:
            await self.vc.disconnect()
        await interaction.response.send_message("🚪 好的，艾瑪先去休息囉，期待下次再唱歌給妳聽！🌸", ephemeral=True)



# ======================================================
# --- 2. 指令核心 Cog ---
# ======================================================
class AskCommand(commands.Cog):
    def __init__(self, bot, ai_engine, music_engine):
        self.bot = bot
        self.ai = ai_engine
        self.music = music_engine
        self.lyrics_engine = LyricsEngine()

        # 核心數據存儲
        self.queues = {}       # {guild_id: [item_list]}
        self.last_played = {}  # {guild_id: last_item}
        self.current_song = {} # {guild_id: current_item}
        self.loop_mode = {}    # {guild_id: 0, 1, or 2}

    # --- 🤖 核心功能：統一 AI 對話出口 ---
    async def get_ai_response(self, user_id, user_name, question, source="Slash"):
        """無論來源是斜線指令還是標記，都統一經由這裡處理"""
        await self.bot.dispatch_log(f"💬 [{source}] {user_name}: {question}")
        answer = await self.ai.get_chat_response(str(user_id), question)
        return answer

    # --- 🌸 核心功能：動態歌詞同步與監控 ---
    async def lyrics_sync_task(self, vc, spotify_title, youtube_title, message):
        """動態歌詞監控任務：負責對齊、搜尋 Log 轉發與暫停補償"""
        try:
            # 向引擎索取歌詞與搜尋 Log
            lyric_dict, search_logs = await asyncio.wait_for(
                self.bot.loop.run_in_executor(
                    None, self.lyrics_engine.get_dynamic_lyrics, spotify_title, youtube_title
                ), timeout=10.0
            )
            # 轉發搜尋過程 Log
            for entry in search_logs:
                await self.bot.dispatch_log(f"🔍 [歌詞搜尋] {entry}")
        except Exception as e:
            lyric_dict = None
            await self.bot.dispatch_log(f"⚠️ [歌詞錯誤] 『{spotify_title}』: {e}")

        if not lyric_dict:
            embed = discord.Embed(title="🌸 伴唱時間 🌸", description=f"**『 {spotify_title} 』**\n\n> 🎵 *這首歌暫時沒有動態歌詞呢...*", color=0xffb6c1)
            try: await message.edit(embed=embed)
            except: pass
            return

        # 延遲補償設定
        delay_offset = -1.5
        await self.bot.dispatch_log(f"✅ [歌詞同步] 『{spotify_title}』啟動 (補償: {delay_offset}s)")

        start_time = time.time()
        last_sentence = ""
        sorted_times = sorted(lyric_dict.keys())

        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            # 暫停時推遲基準時間，確保恢復播放後歌詞不跑掉
            if vc.is_paused():
                start_time += 0.1
                await asyncio.sleep(0.1)
                continue

            elapsed = (time.time() - start_time) - delay_offset
            current_sentence = "..."
            for t in sorted_times:
                if elapsed >= t: current_sentence = lyric_dict[t]
                else: break

            if current_sentence != last_sentence:
                last_sentence = current_sentence
                embed = discord.Embed(title="🌸 伴唱時間 🌸", description=f"**『 {spotify_title} 』**\n\n**{current_sentence}**", color=0xffb6c1)
                embed.set_footer(text="正在唱歌~ ✨")
                try: await message.edit(embed=embed)
                except: break
            await asyncio.sleep(0.1)

    # --- 🎵 音樂排程管理邏輯 ---
    def check_queue(self, interaction, vc):
        """播放結束後的回調：負責根據循環模式切換下一首"""
        guild_id = interaction.guild_id
        mode = self.loop_mode.get(guild_id, 0)
        current = self.current_song.get(guild_id)

        next_item = None
        # 分支判斷：模式 1(單曲), 模式 2(清單), 模式 0(不循環)
        if mode == 1 and current:
            next_item = current
        elif mode == 2 and current:
            if guild_id in self.queues:
                self.queues[guild_id].append(current) # 塞回清單最後
                next_item = self.queues[guild_id].pop(0) if self.queues[guild_id] else None
        else:
            if guild_id in self.queues and self.queues[guild_id]:
                next_item = self.queues[guild_id].pop(0)

        if next_item:
            self.bot.loop.create_task(self.play_music_task(interaction, vc, next_item))
        else:
            self.current_song[guild_id] = None # 清空當前紀錄

    async def play_music_task(self, interaction, vc, item):
        """播放任務執行：串流、LOG、按鈕顯示"""
        try:
            guild_id = interaction.guild_id
            # 紀錄歷史與當前狀態
            if self.current_song.get(guild_id) and self.current_song.get(guild_id) != item:
                self.last_played[guild_id] = self.current_song[guild_id]
            self.current_song[guild_id] = item

            # 抓取 YouTube 音訊
            source_data = await self.music.get_yt_source(item['query'])
            if not source_data: return

            s_title = item.get('clean_title') or source_data['title']

            # 判定 FFmpeg 路徑
            FFMPEG_EXE = "ffmpeg" if os.path.exists('/.dockerenv') else r"C:\Users\李冠霖\暫存\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"

            audio_source = discord.FFmpegPCMAudio(
                source_data['url'], executable=FFMPEG_EXE,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )

            # 啟動播放並綁定 check_queue
            vc.play(audio_source, after=lambda e: self.check_queue(interaction, vc))
            await self.bot.dispatch_log(f"🎵 [播放啟動] {s_title}")

            # 發送面板訊息
            view = MusicControlView(self.bot, vc, self)
            embed = discord.Embed(title="🎵 正在播放", description=f"**[{s_title}]**\n\n*🌸 櫻羽艾瑪正在努力同步歌詞...*", color=0xffb6c1)

            if not interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, view=view)
            else:
                msg = await interaction.channel.send(embed=embed, view=view)

            # 啟動歌詞監控
            self.bot.loop.create_task(self.lyrics_sync_task(vc, s_title, source_data['title'], msg))
        except Exception as e:
            await self.bot.dispatch_log(f"💥 [播放異常] {e}")



    # ==================== 🌸 全功能斜線指令區 ====================

# ===== Ask Command =====
    @app_commands.command(name="ask", description="向 Spark 提問 ✨")
    async def ask(self, interaction: discord.Interaction, question: str):
        """對話指令"""
        await interaction.response.defer(thinking=True)
        answer = await self.get_ai_response(interaction.user.id, interaction.user.name, question, source="Slash")
        await interaction.followup.send(answer)

# ===== Play Command =====
    @app_commands.command(name="play", description="播放音樂 (支援 Spotify/YT 單曲或歌單)")
    async def play(self, interaction: discord.Interaction, input_str: str):
        """核心點歌指令"""
        await interaction.response.defer(thinking=True)
        vc = interaction.guild.voice_client or (await interaction.user.voice.channel.connect() if interaction.user.voice else None)
        if not vc: return await interaction.followup.send("🌸 要先进去語音頻道，我才找得到妳！")

        guild_id = interaction.guild_id
        if guild_id not in self.queues: self.queues[guild_id] = []

        added = 0
        if "spotify.com" in input_str:
            tracks = self.music.get_spotify_tracks(input_str)
            for t in tracks: self.queues[guild_id].append({'query': t, 'clean_title': t})
            added = len(tracks)
        elif "list=" in input_str:
            urls = await self.music.get_yt_playlist_urls(input_str)
            for u in urls: self.queues[guild_id].append({'query': u, 'clean_title': None})
            added = len(urls)
        else:
            self.queues[guild_id].append({'query': input_str, 'clean_title': None})
            added = 1

        await self.bot.dispatch_log(f"📥 [點歌] {interaction.user.name} 加入了 {added} 首歌")

        if not vc.is_playing() and not vc.is_paused():
            if self.queues[guild_id]:
                next_item = self.queues[guild_id].pop(0)
                await self.play_music_task(interaction, vc, next_item)
                await interaction.followup.send(f"🌸 音樂啟動！成功加入 {added} 首歌 ✨")
        else:
            await interaction.followup.send(f"✅ 已成功將 {added} 首歌加入排隊清單囉！")

# ===== Loop Command =====
    @app_commands.command(name="loop", description="切換循環模式 (關閉/單曲/清單) 🔁")
    async def loop(self, interaction: discord.Interaction):
        """獨立指令：循環切換"""
        guild_id = interaction.guild_id
        new_mode = (self.loop_mode.get(guild_id, 0) + 1) % 3
        self.loop_mode[guild_id] = new_mode
        modes = {0: "❌ 關閉循環", 1: "🔂 單曲循環", 2: "🔁 清單循環"}
        await self.bot.dispatch_log(f"🔄 [指令] {interaction.user.name} 切換循環為: {modes[new_mode]}")
        await interaction.response.send_message(f"🌸 循環模式已切換為：**{modes[new_mode]}**")

# ===== Prev Command =====
    @app_commands.command(name="prev", description="回退播放上一首紀錄 ⏮️")
    async def prev(self, interaction: discord.Interaction):
        """獨立指令：上一首"""
        vc = interaction.guild.voice_client
        last = self.last_played.get(interaction.guild_id)
        if vc and last:
            current = self.current_song.get(interaction.guild_id)
            if current: self.queues[interaction.guild_id].insert(0, current)
            self.queues[interaction.guild_id].insert(0, last)
            vc.stop()
            await interaction.response.send_message("⏮️ 好的！正在帶您回到上一首紀錄... ✨")
            await self.bot.dispatch_log(f"⏮️ [指令] {interaction.user.name} 使用了回退播放")
        else:
            await interaction.response.send_message("🌸 找不到上一首播放紀錄唷。", ephemeral=True)

# ===== Skip Command =====
    @app_commands.command(name="skip", description="跳過歌曲 ⏭️ (可指定跳至第幾首)")
    @app_commands.describe(target="想要跳轉到的歌曲序號 (例如輸入 3 代表直接播清單第 3 首)")
    async def skip(self, interaction: discord.Interaction, target: int = None):
        """跳過目前曲目，或精確跳轉到佇列中的特定序號"""
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id

        # 1. 檢查語音狀態
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("🌸 目前沒有在唱歌，沒辦法跳過唷。", ephemeral=True)

        # 2. 處理指定序號跳轉邏輯
        if target is not None:
            if guild_id in self.queues and 1 <= target <= len(self.queues[guild_id]):
                # 算出要刪除的歌曲數量 (跳轉到第 N 首，代表要刪除前面 N-1 首)
                removed_count = target - 1
                for _ in range(removed_count):
                    self.queues[guild_id].pop(0)

                # 停止當前播放，觸發 check_queue 播放新的第一首
                vc.stop()

                await self.bot.dispatch_log(f"⏭️ [指令] {interaction.user.name} 執行了精確跳轉，跳過前 {removed_count} 首歌")
                await interaction.response.send_message(f"🚀 好的！立刻幫妳跳轉到第 {target} 首歌 ✨")
            else:
                await interaction.response.send_message(f"🌸 序號超出範圍了呢。目前排隊中只有 {len(self.queues.get(guild_id, []))} 首歌唷。", ephemeral=True)

        # 3. 處理一般的單首跳過
        else:
            vc.stop()
            await self.bot.dispatch_log(f"⏭️ [指令] {interaction.user.name} 跳過了目前的歌曲")
            await interaction.response.send_message("⏭️ 好的！跳過這首歌，播放下一首～✨")

# ===== Clear Command =====
    @app_commands.command(name="clear", description="清空排隊佇列 🗑️")
    async def clear(self, interaction: discord.Interaction):
        """獨立指令：清空"""
        guild_id = interaction.guild_id
        count = len(self.queues.get(guild_id, []))
        self.queues[guild_id] = []
        await self.bot.dispatch_log(f"🗑️ [指令] {interaction.user.name} 清空了佇列 ({count} 首)")
        await interaction.response.send_message(f"🗑️ 已幫妳清空後面的 {count} 首歌囉！")


# ===== Queue Command =====
    @app_commands.command(name="queue", description="查看排隊清單 🎵")
    async def queue(self, interaction: discord.Interaction):
        """列出清單前 10 首"""
        guild_id = interaction.guild_id
        if guild_id in self.queues and self.queues[guild_id]:
            q_text = ""
            for i, item in enumerate(self.queues[guild_id][:10]):
                name = item['clean_title'] or item['query']
                q_text += f"{i+1}. {name[:40]}...\n"
            await interaction.response.send_message(f"🎵 **排隊清單 (前10首)：**\n{q_text}")
        else:
            await interaction.response.send_message("🌸 目前排隊清單是空的唷。")

# ===== Leave Command =====
    @app_commands.command(name="leave", description="停止播放並離開頻道 🚪")
    async def leave(self, interaction: discord.Interaction):
        """離開指令"""
        vc = interaction.guild.voice_client
        if vc:
            self.queues[interaction.guild_id] = []
            await vc.disconnect()
            await interaction.response.send_message("🚪 好的，艾瑪先走一步，有需要再叫我哦！🌸")
            await self.bot.dispatch_log(f"🚪 [離開] Spark 離開了頻道")
        else:
            await interaction.response.send_message("🌸 我本來就不在頻道裡呀？")



async def setup(bot, ai_engine, music_engine):
    """Cog 載入函數"""
    await bot.add_cog(AskCommand(bot, ai_engine, music_engine))