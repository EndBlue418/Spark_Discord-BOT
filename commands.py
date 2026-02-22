import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
from lyrics_engine import LyricsEngine
import os

# --- 1. 音樂控制面板 (按鈕組件) ---
# --- 1. 音樂控制面板 (按鈕組件 - 加強 LOG 版) ---
class MusicControlView(discord.ui.View):
    """定義顯示在音樂訊息下方的互動按鈕"""
    def __init__(self, bot, vc, cog):
        super().__init__(timeout=None)
        self.bot, self.vc, self.cog = bot, vc, cog

    @discord.ui.button(label="⏯️ 暫停/繼續", style=discord.ButtonStyle.primary)
    async def toggle_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        """切換播放或暫停狀態"""
        user = interaction.user
        if self.vc.is_playing():
            self.vc.pause()
            await self.bot.dispatch_log(f"⏸️ [音樂控制] {user.name} 按下了暫停")
            await interaction.response.send_message(f"⏸️ {user.name} 把音樂暫停了唷", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await self.bot.dispatch_log(f"▶️ [音樂控制] {user.name} 恢復了播放")
            await interaction.response.send_message(f"▶️ {user.name} 讓音樂繼續響起！", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 目前沒有音樂在播放中", ephemeral=True)

    @discord.ui.button(label="⏭️ 跳過", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        """跳過目前正在播放的曲目"""
        user = interaction.user
        if self.vc.is_playing() or self.vc.is_paused():
            await self.bot.dispatch_log(f"⏭️ [音樂控制] {user.name} 決定跳過這首歌")
            self.vc.stop()
            await interaction.response.send_message(f"⏭️ 收到！{user.name} 幫大家切換到下一首 ✨", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 目前沒歌在播，沒辦法跳過唷。", ephemeral=True)

    @discord.ui.button(label="⏹️ 停止並離開", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """清空佇列並徹底離開語音頻道"""
        user = interaction.user
        await self.bot.dispatch_log(f"⏹️ [音樂控制] {user.name} 強制結束了音樂並讓機器人離開")

        self.cog.queues[interaction.guild_id] = []
        await self.vc.disconnect()
        await interaction.response.send_message(f"⏹️ {user.name} 讓艾瑪先休息了🌸", ephemeral=True)

# --- 2. 指令核心 Cog ---
class AskCommand(commands.Cog):
    def __init__(self, bot, ai_engine, music_engine):
        self.bot = bot
        self.ai = ai_engine
        self.music = music_engine
        self.lyrics_engine = LyricsEngine()
        self.queues = {} # 儲存格式: {guild_id: [歌曲資訊字典]}

    # --- 🤖 核心功能：統一 AI 窗口 (解決 @Bug 與 Prompt 不同步) ---
    async def get_ai_response(self, user_id, user_name, question, source="Slash"):
        """
        ✨ 無論 /ask 還是 @標註，都統一經由這個函數處理
        source: 用於辨識來源 (Slash 或 Mention)
        """
        # 1. 發送統一格式的 Log
        await self.bot.dispatch_log(f"💬 [{source}] {user_name}: {question}")

        # 2. 呼叫 AI Engine (這裡會使用妳最細緻的 Prompt)
        answer = await self.ai.get_chat_response(str(user_id), question)

        return answer

    # --- 🌸 核心功能：動態歌詞同步監控任務 ---
    async def lyrics_sync_task(self, vc, spotify_title, youtube_title, message):
        """
        ✨ 優化版動態歌詞同步：
        1. 修正 Tuple Unpacking 避免報錯
        2. 加入 delay_offset 補償網路延遲
        3. 提高採樣頻率確保對齊
        """
        try:
            # 🚀 正確拆解元組 (lyric_dict 為歌詞，search_logs 為搜尋紀錄)
            lyric_dict, search_logs = await asyncio.wait_for(
                self.bot.loop.run_in_executor(
                    None, self.lyrics_engine.get_dynamic_lyrics, spotify_title, youtube_title
                ),
                timeout=8.0
            )
            # 將搜尋過程發送到 Log 頻道
            for entry in search_logs:
                await self.bot.dispatch_log(entry)

        except Exception as e:
            lyric_dict = None
            await self.bot.dispatch_log(f"⚠️ [歌詞錯誤] {spotify_title}: {e}")

        if not lyric_dict:
            embed = discord.Embed(title="🌸 伴唱時間 🌸", description=f"**『 {spotify_title} 』**\n\n> 🎵 *這首歌暫時沒有動態歌詞呢...*", color=0xffb6c1)
            embed.set_footer(text="雖然沒歌詞，但我會一直陪你聽完的哦 ✨")
            try: await message.edit(embed=embed)
            except: pass
            return

        # 🦋 延遲補償設定 (秒)
        # 負值代表「提早送出歌詞」，用來抵消 Discord 的顯示延遲
        delay_offset = -2

        await self.bot.dispatch_log(f"✅ [歌詞同步] {spotify_title} 已啟動 (補償: {delay_offset}s)")

        start_time = time.time()
        last_sentence = ""
        sorted_times = sorted(lyric_dict.keys())

        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            if vc.is_paused():
                start_time += 0.05 # 暫停時持續推遲基準時間
                await asyncio.sleep(0.05)
                continue

            # 計算經過時間並加入補償
            elapsed = (time.time() - start_time) - delay_offset

            current_sentence = "..."
            for t in sorted_times:
                if elapsed >= t:
                    current_sentence = lyric_dict[t]
                else:
                    break

            # 內容有變動才編輯訊息，避免觸發 Discord 限速
            if current_sentence != last_sentence:
                last_sentence = current_sentence
                embed = discord.Embed(
                    title="🌸 伴唱時間 🌸",
                    description=f"**『 {spotify_title} 』**\n\n**{current_sentence}**",
                    color=0xffb6c1
                )
                embed.set_footer(text="正在唱歌~ ✨")
                try:
                    await message.edit(embed=embed)
                except:
                    break

            # 保持檢查頻率
            await asyncio.sleep(0.1)

    def check_queue(self, interaction, vc):
        """播放佇列中的下一首歌曲"""
        guild_id = interaction.guild_id
        if guild_id in self.queues and len(self.queues[guild_id]) > 0:
            next_item = self.queues[guild_id].pop(0)
            self.bot.loop.create_task(self.play_music_task(interaction, vc, next_item))

    async def play_music_task(self, interaction, vc, item):
        """✨ 播放核心任務：處理串流與環境路徑"""
        try:
            query = item['query']
            spotify_title = item.get('clean_title')

            # 獲取 YT 音訊源
            source_data = await self.music.get_yt_source(query)
            if not source_data: return

            s_title = spotify_title if spotify_title else source_data['title']
            y_title = source_data['title']

            # 環境路徑判斷 (Docker vs Local)
            if os.path.exists('/.dockerenv'):
                FFMPEG_EXE = "ffmpeg"
                tag = "Docker (Mac)"
            else:
                FFMPEG_EXE = r"C:\Users\李冠霖\暫存\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"
                tag = "Windows Local"

            audio_source = discord.FFmpegPCMAudio(
                source_data['url'], executable=FFMPEG_EXE,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )

            # 播放音軌
            vc.play(audio_source, after=lambda e: self.check_queue(interaction, vc))
            await self.bot.dispatch_log(f"🎵 [播放啟動] {s_title} (環境: {tag})")

            # 發送控制面板訊息
            view = MusicControlView(self.bot, vc, self)
            embed = discord.Embed(title="🎵 正在播放", description=f"**[{s_title}]**\n\n*🌸 正在抓取動態歌詞...*", color=0xffb6c1)
            embed.set_footer(text="直接點擊下方按鈕控制音樂 ✨")

            msg = await (interaction.followup.send(embed=embed, view=view) if not interaction.response.is_done() else interaction.channel.send(embed=embed, view=view))

            # 啟動歌詞同步任務
            self.bot.loop.create_task(self.lyrics_sync_task(vc, s_title, y_title, msg))
        except Exception as e:
            await self.bot.dispatch_log(f"💥 [播放異常] {e}")

    # ==================== 斜線指令區 ====================



    @app_commands.command(name="ask", description="向 Spark 提問 ✨")
    async def ask(self, interaction: discord.Interaction, question: str):
        """與 AI 引擎對話功能"""
        await interaction.response.defer(thinking=True)

        # 使用統一窗口獲取回應
        answer = await self.get_ai_response(
            interaction.user.id,
            interaction.user.name,
            question,
            source="Slash"
        )

        # 允許標註用戶，但不允許標註 everyone
        allowed_mentions = discord.AllowedMentions(everyone=False, users=True)
        await interaction.followup.send(answer, allowed_mentions=allowed_mentions)



    @app_commands.command(name="play", description="播放音樂 並加入到佇列最後")
    async def play(self, interaction: discord.Interaction, input_str: str):
        """支援 Spotify/YT 單曲或歌單"""
        await interaction.response.defer(thinking=True)
        vc = interaction.guild.voice_client or (await interaction.user.voice.channel.connect() if interaction.user.voice else None)
        if not vc: return await interaction.followup.send("🌸 要先在語音頻道，我才找得到你！")

        guild_id = interaction.guild_id
        if guild_id not in self.queues: self.queues[guild_id] = []

        added_count = 0
        # 處理音樂來源
        if "spotify.com" in input_str or "open.spotify.com" in input_str:
            tracks = self.music.get_spotify_tracks(input_str)
            for t in tracks: self.queues[guild_id].append({'query': t, 'clean_title': t})
            added_count = len(tracks)
        elif "list=" in input_str:
            urls = await self.music.get_yt_playlist_urls(input_str)
            for u in urls: self.queues[guild_id].append({'query': u, 'clean_title': None})
            added_count = len(urls)
        else:
            self.queues[guild_id].append({'query': input_str, 'clean_title': None})
            added_count = 1

        await self.bot.dispatch_log(f"📥 [加入清單] {added_count} 首歌來自 {interaction.user.name}")

        if not vc.is_playing() and not vc.is_paused():
            if self.queues[guild_id]:
                next_item = self.queues[guild_id].pop(0)
                await self.play_music_task(interaction, vc, next_item)
                await interaction.followup.send(f"🌸 音樂啟動！成功加入 {added_count} 首歌 ✨")
        else:
            await interaction.followup.send(f"✅ 已成功將 {added_count} 首歌加入排隊清單囉！🌸")



    @app_commands.command(name="skip", description="跳過歌曲 ⏭️")
    async def skip(self, interaction: discord.Interaction, target: int = None):
        """跳過或精確跳轉"""
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("🌸 目前沒有在唱歌哦！", ephemeral=True)

        if target is not None:
            if guild_id in self.queues and 1 <= target <= len(self.queues[guild_id]):
                for _ in range(target - 1): self.queues[guild_id].pop(0)
                vc.stop()
                await interaction.response.send_message(f"🚀 好的！立刻跳轉到第 {target} 首歌 ✨")
                await self.bot.dispatch_log(f"⏭️ [跳轉] 指定跳至第 {target} 首")
            else:
                await interaction.response.send_message(f"🌸 序號超出範圍了呢。", ephemeral=True)
        else:
            vc.stop()
            await interaction.response.send_message("⏭️ 好的！跳過這首歌～✨")
            await self.bot.dispatch_log(f"⏭️ [跳過] 使用者跳過當前播放")



    @app_commands.command(name="queue", description="查看目前的排隊清單 🎵")
    async def queue(self, interaction: discord.Interaction):
        """列出清單前 10 首"""
        guild_id = interaction.guild_id
        if guild_id in self.queues and self.queues[guild_id]:
            q_text = ""
            for i, item in enumerate(self.queues[guild_id][:10]):
                display_name = item['clean_title'] if item['clean_title'] else item['query']
                q_text += f"{i+1}. {display_name[:40]}...\n"
            await interaction.response.send_message(f"🎵 **目前的排隊清單 (顯示前10首)：**\n{q_text}")
        else:
            await interaction.response.send_message("🌸 排隊清單是空的！")



    @app_commands.command(name="leave", description="停止播放並讓 Spark 離開頻道 🚪")
    async def leave(self, interaction: discord.Interaction):
        """徹底中斷並關閉服務"""
        vc = interaction.guild.voice_client
        if vc:
            self.queues[interaction.guild_id] = []
            await vc.disconnect()
            await interaction.response.send_message("🚪 好的，艾瑪先走一步，有需要再叫我哦!🌸")
            await self.bot.dispatch_log(f"🚪 [離開] Spark 已離開語音頻道")
        else:
            await interaction.response.send_message("🌸 我本來就不在頻道裡呀？")



    @app_commands.command(name="shuffle", description="隨機打亂目前的排隊清單 🎲")
    async def shuffle(self, interaction: discord.Interaction):
        """將佇列中的歌曲隨機排序"""
        guild_id = interaction.guild_id

        # 檢查是否有排隊清單，且清單內至少要有 2 首歌才需要打亂
        if guild_id in self.queues and len(self.queues[guild_id]) > 1:
            import random

            # 執行打亂動作
            random.shuffle(self.queues[guild_id])

            # 發送 Log
            await self.bot.dispatch_log(f"🎲 [打亂清單] {interaction.user.name} 重新洗牌了 {len(self.queues[guild_id])} 首歌")

            # 回饋給使用者
            embed = discord.Embed(
                title="🎲 重新洗牌！",
                description=f"已經幫妳把剩下的 **{len(self.queues[guild_id])}** 首歌順序打亂囉 ✨",
                color=0x9b59b6 # 紫色代表隨機與神祕
            )
            await interaction.response.send_message(embed=embed)

        elif guild_id in self.queues and len(self.queues[guild_id]) == 1:
            await interaction.response.send_message("🌸 清單裡只有一首歌，打亂了也還是同一首呀！呢。", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 目前排隊清單是空的，沒辦法洗牌唷！", ephemeral=True)




async def setup(bot, ai_engine, music_engine):
    """Cog 載入函數"""
    await bot.add_cog(AskCommand(bot, ai_engine, music_engine))