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
    def __init__(self, bot, vc, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.vc = vc
        self.cog = cog

        # --- [狀態初始化] 讓按鈕外觀與後端數據同步 ---
        guild_id = vc.guild.id
        mode = self.cog.loop_mode.get(guild_id, 0)
        loop_labels = {0: "🔁 循環: 關閉", 1: "🔂 單曲循環", 2: "🔁 清單循環"}

        # 遍歷組件，動態調整初始 Label 與顏色
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                # 同步循環按鈕文字
                if child.custom_id == "emma_music_loop":
                    child.label = loop_labels.get(mode, "🔁 循環模式")

                # 同步暫停按鈕文字與顏色
                if child.custom_id == "emma_music_toggle":
                    if self.vc.is_paused():
                        child.label = "▶️ 繼續播放"
                        child.style = discord.ButtonStyle.danger
                    else:
                        child.label = "⏸️ 暫停"
                        child.style = discord.ButtonStyle.primary

    @discord.ui.button(label="⏮️ 上一首", style=discord.ButtonStyle.secondary, custom_id="emma_music_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：回溯播放歷史紀錄"""
        guild_id = interaction.guild_id
        last_song = self.cog.last_played.get(guild_id)

        if last_song:
            await self.bot.dispatch_log(f"⏮️ [控制面板] 使用者 {interaction.user.name} 請求回放上一首歌")
            current = self.cog.current_song.get(guild_id)
            if current:
                self.cog.queues[guild_id].insert(0, current)

            self.cog.queues[guild_id].insert(0, last_song)
            self.vc.stop() # 停止當前播放，藉此觸發 check_queue
            await interaction.response.send_message("⏮️ 好的！艾瑪正在幫妳找回剛才的旋律...", ephemeral=True)
        else:
            await self.bot.dispatch_log(f"⚠️ [控制面板] {interaction.user.name} 嘗試按上一首，但歷史紀錄為空")
            await interaction.response.send_message("🌸 艾瑪的記憶體裡找不到上一首歌的紀錄...", ephemeral=True)

    @discord.ui.button(label="⏯️ 暫停/繼續", style=discord.ButtonStyle.primary, custom_id="emma_music_toggle")
    async def toggle_play_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：切換語音客戶端的播放或暫停狀態"""
        if self.vc.is_playing():
            self.vc.pause()
            button.label = "▶️ 繼續播放"
            button.style = discord.ButtonStyle.danger
            await self.bot.dispatch_log(f"⏸️ [控制面板] 使用者 {interaction.user.name} 暫停了播放")
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("⏸️ 已經幫妳按下暫停鍵囉！", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            button.label = "⏸️ 暫停"
            button.style = discord.ButtonStyle.primary
            await self.bot.dispatch_log(f"▶️ [控制面板] 使用者 {interaction.user.name} 恢復了播放")
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("▶️ 音樂繼續響起！讓旋律再次流動吧 ✨", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 艾瑪現在好像沒在唱歌，沒辦法暫停呢~", ephemeral=True)

    @discord.ui.button(label="⏭️ 下一首", style=discord.ButtonStyle.secondary, custom_id="emma_music_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：停止當前播放以進入下一首"""
        if self.vc.is_playing() or self.vc.is_paused():
            await self.bot.dispatch_log(f"⏭️ [控制面板] 使用者 {interaction.user.name} 跳過了目前的歌曲")
            self.vc.stop()
            await interaction.response.send_message("⏭️ 收到！這首歌先休息，我們換下一首～ ✨", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 排隊清單裡已經沒有歌可以跳過囉。", ephemeral=True)

    @discord.ui.button(label="🔀 打亂", style=discord.ButtonStyle.secondary, custom_id="emma_music_shuffle")
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        queue = self.cog.queues.get(guild_id, [])
        if len(queue) > 1:
            random.shuffle(queue)
            await self.bot.dispatch_log(f"🔀 [控制面板] {interaction.user.name} 打亂了隊列")
            await interaction.response.send_message("🔀 隊列已重新洗牌！", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 沒幾首歌，不用洗牌啦～", ephemeral=True)

    @discord.ui.button(label="🔁 循環模式", style=discord.ButtonStyle.success, custom_id="emma_music_loop")
    async def toggle_loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按下按鈕：循環切換 (0:關閉, 1:單曲, 2:清單)"""
        guild_id = interaction.guild_id
        current_mode = self.cog.loop_mode.get(guild_id, 0)
        new_mode = (current_mode + 1) % 3
        self.cog.loop_mode[guild_id] = new_mode

        labels = {0: "🔁 循環: 關閉", 1: "🔂 單曲循環", 2: "🔁 清單循環"}
        button.label = labels[new_mode]

        await self.bot.dispatch_log(f"🔄 [控制面板] 使用者 {interaction.user.name} 切換循環模式為: {labels[new_mode]}")
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
    def __init__(self, bot, ai_engine, music_engine):
        self.bot = bot
        self.ai = ai_engine
        self.music = music_engine
        self.lyrics_engine = LyricsEngine()
        self.last_message = {}

        self.queues = {}
        self.last_played = {}
        self.current_song = {}
        self.loop_mode = {}

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("EmmaMusic")


    def get_loop_status(self, guild_id):
        """根據 guild_id 獲取目前的循環模式文字描述"""
        # 0: 正常, 1: 單曲, 2: 清單
        mode = self.loop_mode.get(guild_id, 0)
        mode_map = {
            0: "正常播放",
            1: "單曲循環中 🔂",
            2: "清單循環中 🔁"
        }
        return mode_map.get(mode, "正常播放")

    def format_time(self, seconds):
        m, s = divmod(int(max(0, seconds)), 60)
        return f"{m:02d}:{s:02d}"

    async def get_ai_response(self, user_id, user_name, question, source="Slash"):
        await self.bot.dispatch_log(f"💬 [{source}] {user_name}: {question}")
        try:
            answer = await self.ai.get_chat_response(str(user_id), question)
            return answer
        except Exception as e:
            await self.bot.dispatch_log(f"💥 [AI 故障] 無法回應 {user_name}: {e}")
            return "🌸 嗚嗚...艾瑪頭好痛，暫時沒辦法回答妳..."

    async def lyrics_sync_task(self, vc, spotify_title, youtube_title, message):
        """確保歌詞載入後立即推送到面板，且即使沒歌詞進度條也要跑"""
        guild_id = message.guild.id
        if not self.current_song.get(guild_id):
            return

        guild_data = self.current_song.get(guild_id, {})
        duration = guild_data.get('duration', 0)

        data_container = {
            'lyrics': {},
            'times': [],
            'ready': False,
            'failed': False
        }

        async def fetch_lyrics_background():
            try:
                data, search_logs = await self.lyrics_engine.get_dynamic_lyrics(
                    spotify_title=spotify_title,
                    youtube_title=youtube_title
                )
                if data and len(data) > 0:
                    data_container['lyrics'] = data
                    data_container['times'] = sorted(data.keys())
                    data_container['ready'] = True
                    await self.bot.dispatch_log(f"✅ [同步任務] 歌詞成功載入，共 {len(data)} 句")
                else:
                    data_container['failed'] = True
                    await self.bot.dispatch_log(f"❌ [同步任務] 找不到動態歌詞：{spotify_title}")
            except Exception as e:
                data_container['failed'] = True
                await self.bot.dispatch_log(f"⚠️ [同步任務崩潰] {e}")

        self.bot.loop.create_task(fetch_lyrics_background())

        # ✨ 重點修正 1：使用字典來儲存 start_time，避開 UnboundLocalError
        tracker = {'start_time': time.time()}
        last_second = -1
        display_duration = duration if duration > 0 else 240

        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            if vc.is_paused():
                # ✨ 重點修正 2：更新字典內的值
                tracker['start_time'] += 0.5
                await asyncio.sleep(0.5)
                continue

            # ✨ 重點修正 3：計算經過時間
            elapsed = (time.time() - tracker['start_time'])
            current_second = int(elapsed)

            if current_second != last_second:
                last_second = current_second
                status_text = self.get_loop_status(guild_id)

                # --- 歌詞顯示邏輯 ---
                if data_container['ready']:
                    current_sentence = "🎵 **(間奏中)** 🎵"
                    for t in reversed(data_container['times']):
                        if elapsed >= t:
                            raw_data = data_container['lyrics'][t]
                            if isinstance(raw_data, list):
                                current_sentence = "\n".join([f"**{str(line).strip()}**" for line in raw_data if line])
                            else:
                                processed = str(raw_data).replace('|', '\n').replace('\\n', '\n')
                                current_sentence = f"**{processed}**"
                            break
                elif data_container['failed']:
                    current_sentence = "🌸 **艾瑪找不到這首歌的動態歌詞呢...**"
                else:
                    current_sentence = "🌸 **艾瑪正在努力同步歌詞與翻譯中...**"

                # --- 進度條渲染 (不論有沒有歌詞都會執行) ---
                bar_len = 14
                prog = min(elapsed / display_duration, 1.0)
                filled = int(prog * bar_len)
                bar_ui = "▬" * filled + "🔘" + "─" * (max(0, bar_len - filled))
                time_label = f"{self.format_time(elapsed)} / {self.format_time(duration)}"

                embed = discord.Embed(
                    title=f"🌸 伴唱中 | {status_text}",
                    description=f"**『 {spotify_title} 』**\n\n{current_sentence}\n\n{bar_ui}\n`{time_label}`",
                    color=0xffb6c1,
                    timestamp=datetime.datetime.now()
                )
                embed.set_footer(text="享受這段旋律吧！ ✨")

                try:
                    view = MusicControlView(self.bot, vc, self)
                    await message.edit(embed=embed, view=view)
                except:
                    break # 訊息被刪除時停止更新

                # ✨ 重點修正 4：移除原本在這裡的 if data_container['failed']: break
                # 這樣即便失敗了，while 循環還是會為了進度條繼續跑

            await asyncio.sleep(0.8)

    async def check_queue(self, interaction, vc):
            """音樂排程管理邏輯 (Music Dispatcher)"""
            # --- 以下內容全部都要縮排 ---
            guild_id = interaction.guild_id
            mode = self.loop_mode.get(guild_id, 0)
            current = self.current_song.get(guild_id)
            queue = self.queues.get(guild_id, [])

            next_item = None

            # 處理循環邏輯
            if mode == 1 and current:
                next_item = current
                await self.bot.dispatch_log(f"🔂 [循環] 單曲循環啟動: {current.get('query')}")
            elif mode == 2 and current:
                queue.append(current)
                if queue:
                    next_item = queue.pop(0)
                await self.bot.dispatch_log(f"🔁 [循環] 清單循環運作中")
            else:
                if queue:
                    next_item = queue.pop(0)

            if next_item:
                # 啟動非同步播放任務
                self.bot.loop.create_task(self.play_music_task(interaction, vc, next_item))
            else:
                self.current_song[guild_id] = None
                await self.bot.dispatch_log(f"🏁 [播放結束] {interaction.guild.name} 的隊列已播放完畢。")

    async def play_music_task(self, interaction, vc, item):
        """音樂播放主執行任務 - 已修正 FFmpeg 參數與面板清理"""
        guild_id = interaction.guild_id
        try:
            # 1. 取得串流網址
            source_data = await self.music.get_yt_source(item['query'])
            if not source_data:
                await self.bot.dispatch_log(f"❌ [播放異常] 無法獲取音訊來源")
                self.bot.loop.create_task(self.check_queue(interaction, vc))
                return

            item['duration'] = source_data.get('duration', 0)
            self.current_song[guild_id] = item
            s_title = item.get('clean_title') or source_data['title']

            # 2. 定義 FFmpeg 參數 (✨ 修正版：解決 Return Code 234)
            import shutil
            FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"

            # 強化的重連參數，確保網路波動時不會斷掉
            # --- ✨ 針對 FFmpeg 8.0.1 的相容性優化版 ---
            FFMPEG_OPTIONS = {
                'before_options': (
                    '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
                    '-nostats -loglevel panic' # 💡 移除 probesize 與 analyzeduration，降低解析報錯率
                ),
                'options': '-vn -af "volume=1.0,aresample=async=1"'
            }

            # 3. 建立音訊來源 (必須在清理舊面板前建立好，確保變數已定義)
            audio_source = discord.FFmpegPCMAudio(
                source_data['url'],
                executable=FFMPEG_EXE,
                **FFMPEG_OPTIONS
            )

            # 4. ✨ 移除舊控制面板 (讓頻道保持整潔)
            if guild_id in self.last_message:
                try:
                    await self.last_message[guild_id].delete()
                except:
                    pass # 訊息已被刪除或過期則忽略

            # 5. 開始播放
            vc.play(
                audio_source,
                after=lambda e: self.bot.loop.create_task(self.check_queue(interaction, vc))
            )

            # 6. 發送新面板並記錄
            view = MusicControlView(self.bot, vc, self)
            embed = discord.Embed(
                title=f"🌸 伴唱中 | {self.get_loop_status(guild_id)}",
                description=f"**『 {s_title} 』**\n\n🌸 **艾瑪正在準備歌詞，請稍候...**",
                color=0xffb6c1
            )
            embed.set_footer(text="享受這段旋律吧！ ✨")

            # 傳送新訊息並存入字典
            msg = await interaction.channel.send(embed=embed, view=view)
            self.last_message[guild_id] = msg

            # 7. 啟動同步歌詞任務
            if msg:
                self.bot.loop.create_task(self.lyrics_sync_task(vc, s_title, source_data['title'], msg))

        except Exception as e:
            await self.bot.dispatch_log(f"💥 [播放任務崩潰] {e}")
            # 發生錯誤時稍微等待，避免光速跳過整個歌單
            await asyncio.sleep(2)
            self.bot.loop.create_task(self.check_queue(interaction, vc))

    # --- 斜線指令部分 ---
    @app_commands.command(name="ask", description="向艾瑪提問任何事 ✨")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        answer = await self.get_ai_response(interaction.user.id, interaction.user.name, question)
        await interaction.followup.send(answer)

    @app_commands.command(name="play", description="播放妳的音樂！")
    async def play(self, interaction: discord.Interaction, input_str: str):
        await interaction.response.defer(thinking=True)
        vc = interaction.guild.voice_client
        if not vc:
            if interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()
            else:
                return await interaction.followup.send("🌸 妳得先進去語音頻道，我才找得到妳呀！")

        guild_id = interaction.guild_id
        if guild_id not in self.queues: self.queues[guild_id] = []

        added_count = 0
        if "spotify.com" in input_str:
            tracks = await self.music.get_spotify_tracks_async(input_str)
            for t in tracks: self.queues[guild_id].append({'query': t, 'clean_title': t})
            added_count = len(tracks)
        elif "list=" in input_str:
            urls = await self.music.get_yt_playlist_urls(input_str)
            for u in urls: self.queues[guild_id].append({'query': u, 'clean_title': None})
            added_count = len(urls)
        else:
            self.queues[guild_id].append({'query': input_str, 'clean_title': None})
            added_count = 1

        await self.bot.dispatch_log(f"📥 [清單更新] {interaction.user.name} 加入了 {added_count} 首歌")

        if not vc.is_playing() and not vc.is_paused():
            if self.queues[guild_id]:
                target = self.queues[guild_id].pop(0)
                await self.play_music_task(interaction, vc, target)
                await interaction.followup.send(f"🌸 音樂啟動！成功將 {added_count} 首歌加入清單 ✨")
        else:
            await interaction.followup.send(f"✅ 好的！已幫妳把 {added_count} 首歌加入排隊囉！")

    @app_commands.command(name="previous", description="⏮️ 播放上一首歌曲")
    async def previous(self, interaction: discord.Interaction):
        """回到上一首歌的指令版本"""
        guild_id = interaction.guild_id
        last_song = self.last_played.get(guild_id)

        if last_song:
            await self.bot.dispatch_log(f"⏮️ [指令回放] {interaction.user.name} 請求回放上一首歌")
            current = self.current_song.get(guild_id)
            if current:
                self.queues[guild_id].insert(0, current)
            self.queues[guild_id].insert(0, last_song)

            vc = interaction.guild.voice_client
            if vc: vc.stop()
            await interaction.response.send_message("⏮️ 正在為妳找回剛才的旋律...", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 艾瑪記不得上一首歌是什麼了...", ephemeral=True)

    @app_commands.command(name="skip", description="跳過這首歌 ⏭️")
    async def skip(self, interaction: discord.Interaction, target: int = None):
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id
        if not vc: return await interaction.response.send_message("🌸 艾瑪不在頻道裡唷。", ephemeral=True)

        if target is not None:
            if guild_id in self.queues and 1 <= target <= len(self.queues[guild_id]):
                for _ in range(target - 1): self.queues[guild_id].pop(0)
                vc.stop()
                await self.bot.dispatch_log(f"🚀 [跳轉] {interaction.user.name} 強制跳轉至第 {target} 首")
                await interaction.response.send_message(f"🚀 收到！直接為妳跳轉到第 {target} 首歌！")
            else:
                await interaction.response.send_message("🌸 找不到那個序號呢~", ephemeral=True)
        else:
            vc.stop()
            await interaction.response.send_message("⏭️ 下一首！艾瑪已經換片囉～ ✨")

    @app_commands.command(name="shuffle", description="🔀 打亂目前的播放隊列")
    async def shuffle(self, interaction: discord.Interaction):
        """指令版：隨機洗牌"""
        guild_id = interaction.guild_id
        if guild_id in self.queues and len(self.queues[guild_id]) > 1:
            random.shuffle(self.queues[guild_id])
            await self.bot.dispatch_log(f"🔀 [指令打亂] {interaction.user.name} 打亂了隊列")
            await interaction.response.send_message(f"🔀 已打亂目前的 **{len(self.queues[guild_id])}** 首歌囉！")
        else:
            await interaction.response.send_message("🌸 隊列裡沒什麼歌可以打亂了~", ephemeral=True)

    @app_commands.command(name="loop", description="🔁 切換循環模式 (關閉/單曲/清單)")
    async def loop_mode_cmd(self, interaction: discord.Interaction):
        """指令版：循環模式切換"""
        guild_id = interaction.guild_id
        current = self.loop_mode.get(guild_id, 0)
        new_mode = (current + 1) % 3
        self.loop_mode[guild_id] = new_mode

        modes = {0: "❌ 關閉", 1: "🔂 單曲循環", 2: "🔁 清單循環"}
        await self.bot.dispatch_log(f"🔄 [指令循環] {interaction.user.name} 將模式設定為 {modes[new_mode]}")
        await interaction.response.send_message(f"🔁 循環模式已切換為：**{modes[new_mode]}**")

    @app_commands.command(name="queue", description="查看當前的點歌清單 🎵")
    async def queue(self, interaction: discord.Interaction):
        q = self.queues.get(interaction.guild_id, [])
        if not q: return await interaction.response.send_message("🌸 目前排隊清單空蕩蕩的。")
        display = "\n".join([f"**{i+1}.** {(x['clean_title'] or x['query'])[:45]}..." for i, x in enumerate(q[:10])])
        embed = discord.Embed(title="🎵 待播放清單 (前 10 首)", description=display, color=0xffb6c1)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leave", description="停止播放並讓艾瑪休息 🚪")
    async def leave(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        if vc:
            # 清理舊面板
            if guild_id in self.last_message:
                try: await self.last_message[guild_id].delete()
                except: pass
                del self.last_message[guild_id]

            self.queues[guild_id] = []
            await vc.disconnect()
            await interaction.response.send_message("🚪 艾瑪先退下了，期待下次再見！🌸")

# ======================================================
# --- 4. 模組載入入口 (Setup) ---
# ======================================================
async def setup(bot, ai_engine, music_engine):
    """Cog 載入函數：將 AskCommand 註冊至機器人"""
    new_cog = AskCommand(bot, ai_engine, music_engine)
    await bot.add_cog(new_cog)
    print(f"✅ [系統日誌] 音樂核心 Cog 已成功載入！")