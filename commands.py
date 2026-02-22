import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
from lyrics_engine import LyricsEngine
import os

# --- 1. 音樂控制面板 (按鈕組件) ---
class MusicControlView(discord.ui.View):
    def __init__(self, bot, vc, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.vc = vc
        self.cog = cog

    @discord.ui.button(label="⏯️ 暫停/繼續", style=discord.ButtonStyle.primary)
    async def toggle_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc.is_playing():
            self.vc.pause()
            await interaction.response.send_message("⏸️ 已暫停音樂", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await interaction.response.send_message("▶️ 音樂繼續響起！", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 目前沒有音樂在播放中", ephemeral=True)

    @discord.ui.button(label="⏭️ 跳過", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. 檢查是否有正在播放的東西
        if self.vc.is_playing() or self.vc.is_paused():
            # 🌸 關鍵：直接叫停當前音軌，這會觸發 play() 裡的 after 回呼來跑 check_queue
            self.vc.stop()

            # 給按鈕一個明確的回饋
            await interaction.response.send_message("⏭️ 好的！立刻幫妳切換到下一首 ✨", ephemeral=True)

            # 🦋 額外保證：如果過了 2 秒還沒下一首，手動戳一下 check_queue (可選)
            # self.cog.check_queue(interaction, self.vc)
        else:
            await interaction.response.send_message("🌸 咦？目前沒歌在播，艾瑪不知道要跳過誰呢。", ephemeral=True)

    @discord.ui.button(label="⏹️ 停止並離開", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.queues[interaction.guild_id] = []
        await self.vc.disconnect()
        await interaction.response.send_message("⏹️ 艾瑪先告退了，期待下次再唱歌🌸", ephemeral=True)

# --- 2. 指令核心 Cog ---
class AskCommand(commands.Cog):
    def __init__(self, bot, ai_engine, music_engine):
        self.bot = bot
        self.ai = ai_engine
        self.music = music_engine
        self.lyrics_engine = LyricsEngine()
        self.queues = {}

    # --- 🌸 核心功能：動態歌詞同步監控任務 ---
    async def lyrics_sync_task(self, vc, spotify_title, youtube_title, message):
        """✨ 修正版：支援傳入雙標題，確保備援機制能啟動"""
        try:
            # 🚀 同時餵入兩個標題：Spotify 用於第一輪精準比對，YT 用於第二輪備援
            lyric_dict = await asyncio.wait_for(
                self.bot.loop.run_in_executor(
                    None,
                    self.lyrics_engine.get_dynamic_lyrics,
                    spotify_title,
                    youtube_title
                ),
                timeout=5.0  # 稍微放寬時間，因為可能要搜兩輪
            )
        except Exception as e:
            lyric_dict = None
            print(f"🌸 歌詞抓取出錯：{e}")

        if not lyric_dict:
            embed = discord.Embed(
                title="🌸 伴唱時間 🌸",
                description=f"**『 {spotify_title} 』**\n\n> 🎵 *這首歌暫時沒有動態歌詞呢...*",
                color=0xffb6c1
            )
            embed.set_footer(text="雖然沒歌詞，但我會一直陪你聽完的哦 ✨")
            try: await message.edit(embed=embed)
            except: pass
            return

        # 🦋 進入同步循環
        start_time = time.time()
        last_sentence = ""
        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            if vc.is_paused():
                await asyncio.sleep(1)
                start_time += 1
                continue

            elapsed = time.time() - start_time
            current_sentence = "..."

            sorted_times = sorted(lyric_dict.keys())
            for t in sorted_times:
                if elapsed >= t:
                    current_sentence = lyric_dict[t]
                else:
                    break

            if current_sentence != last_sentence:
                last_sentence = current_sentence
                embed = discord.Embed(
                    title="🌸 伴唱時間 🌸",
                    description=f"**『 {spotify_title} 』**\n\n{current_sentence}",
                    color=0xffb6c1
                )
                embed.set_footer(text="正在唱歌~ ✨")
                try: await message.edit(embed=embed)
                except: break

            await asyncio.sleep(0.1)

    def check_queue(self, interaction, vc):
        guild_id = interaction.guild_id
        if guild_id in self.queues and len(self.queues[guild_id]) > 0:
            next_item = self.queues[guild_id].pop(0)
            self.bot.loop.create_task(self.play_music_task(interaction, vc, next_item))

    async def play_music_task(self, interaction, vc, item):
        """✨ 智慧播放任務：對接雙標題傳送邏輯"""
        try:
            query = item['query']
            spotify_title = item.get('clean_title')

            source_data = await self.music.get_yt_source(query)
            if not source_data: return

            # ✨ 修正：分別定義兩個搜尋目標
            # s_title: 如果有 Spotify 乾淨標題就用，否則用 YT 標題
            # y_title: 永遠攜帶 YouTube 原始標題作為備援
            s_title = spotify_title if spotify_title else source_data['title']
            y_title = source_data['title']
            # 判斷是否在 Docker 環境中 (檢查 /.dockerenv 檔案)
            if os.path.exists('/.dockerenv'):
                FFMPEG_EXE = "ffmpeg"  # Docker 內部直接使用系統指令
            else:
                # 妳本機 Windows 的開發路徑
                FFMPEG_EXE = r"C:\Users\李冠霖\暫存\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"
            # ✨ --- 修正結束 --- ✨
            audio_source = discord.FFmpegPCMAudio(
                source_data['url'],
                executable=FFMPEG_EXE,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )
            audio_source = discord.FFmpegPCMAudio(
                source_data['url'],
                executable=FFMPEG_EXE,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )

            vc.play(audio_source, after=lambda e: self.check_queue(interaction, vc))

            view = MusicControlView(self.bot, vc, self)
            embed = discord.Embed(
                title="🎵 正在播放",
                description=f"**[{s_title}]**\n\n*🌸 正在抓取動態歌詞...*",
                color=0xffb6c1
            )
            embed.set_footer(text="直接點擊下方按鈕控制音樂 ✨")

            if not interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, view=view)
            else:
                msg = await interaction.channel.send(embed=embed, view=view)

            # 🚀 關鍵修正：呼叫歌詞同步時，同時傳入 s_title 與 y_title
            self.bot.loop.create_task(self.lyrics_sync_task(vc, s_title, y_title, msg))

        except Exception as e:
            print(f"❌ Play Music Task Error: {e}")

    @app_commands.command(name="ask", description="向 Spark 提問 ✨")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        try:
            user_id = f"user_{interaction.user.id}"
            answer = await self.ai.get_chat_response(user_id, question)
            await interaction.followup.send(answer)
        except Exception as e:
            await interaction.followup.send(f"🌸 哎呀，剛剛走神了...請再說一次好嗎？")

    @app_commands.command(name="play", description="播放音樂 並加入到佇列最後 (支援單曲/Spotify/YT歌單)")
    async def play(self, interaction: discord.Interaction, input_str: str):
        await interaction.response.defer(thinking=True)
        vc = interaction.guild.voice_client
        if not vc:
            if interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()
            else:
                return await interaction.followup.send("🌸 要先在語音頻道，我才找得到你！")

        guild_id = interaction.guild_id
        if guild_id not in self.queues: self.queues[guild_id] = []

        added_count = 0
        if "open.spotify.com" in input_str or "spotify.com" in input_str:
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

        if not vc.is_playing() and not vc.is_paused():
            if self.queues[guild_id]:
                next_item = self.queues[guild_id].pop(0)
                await self.play_music_task(interaction, vc, next_item)
                await interaction.followup.send(f"🌸 音樂啟動！成功加入 {added_count} 首歌 ✨")
        else:
            await interaction.followup.send(f"✅ 已成功將 {added_count} 首歌加入排隊清單囉！🌸")

    @app_commands.command(name="skip", description="跳過歌曲 ⏭️")
    async def skip(self, interaction: discord.Interaction, target: int = None):
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("🌸 目前沒有在唱歌哦！", ephemeral=True)

        if target is not None:
            if guild_id in self.queues and 1 <= target <= len(self.queues[guild_id]):
                for _ in range(target - 1): self.queues[guild_id].pop(0)
                vc.stop()
                await interaction.response.send_message(f"🚀 好的！立刻跳轉到第 {target} 首歌 ✨")
            else:
                await interaction.response.send_message(f"🌸 序號超出範圍了呢。", ephemeral=True)
        else:
            vc.stop()
            await interaction.response.send_message("⏭️ 好的！跳過這首歌～✨")

    @app_commands.command(name="queue", description="查看目前的排隊清單 🎵")
    async def queue(self, interaction: discord.Interaction):
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
        vc = interaction.guild.voice_client
        if vc:
            self.queues[interaction.guild_id] = []
            await vc.disconnect()
            await interaction.response.send_message("🚪 好的，艾瑪先走一步，有需要再叫我哦!🌸")
        else:
            await interaction.response.send_message("🌸 我本來就不在頻道裡呀？")

async def setup(bot, ai_engine, music_engine):
    await bot.add_cog(AskCommand(bot, ai_engine, music_engine))