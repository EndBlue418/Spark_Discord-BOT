import os
import datetime
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

# 核心引擎載入
from ai_engine import GeminiEngine
from music_engine import SparkMusicEngine

load_dotenv()

# ==================== 配置區 ====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_ID = os.getenv("SPOTIFY_ID")
SPOTIFY_SECRET = os.getenv("SPOTIFY_SECRET")

OLLAMA_URL = os.getenv("OLLAMA_HOST_URL", "http://localhost:11434")
MODEL_ID = 'gemma3:4b'

LOG_CHANNEL_ID = 1474497872258138337
# ===============================================

ai = GeminiEngine(MODEL_ID)
music = SparkMusicEngine(client_id=SPOTIFY_ID, client_secret=SPOTIFY_SECRET)

class SparkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def dispatch_log(self, content: str):
        """✨ 核心 Log 轉發：同時發送到終端機與 Discord 頻道"""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] {content}")

        try:
            channel = self.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"`[{now}]` {content}")
        except Exception as e:
            print(f"❌ Log 頻道發送失敗: {e}")

    async def setup_hook(self):
        """初始化 Cog 擴充功能與同步指令"""
        try:
            from commands import setup as setup_commands
            await setup_commands(self, ai, music)
            await self.tree.sync()
            await self.dispatch_log(f"✅ 系統初始化完成 | 模型: {MODEL_ID} | 模型位址: {OLLAMA_URL}")
        except Exception as e:
            await self.dispatch_log(f"❌ 初始化失敗: {e}")

bot = SparkBot()

@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="正在唱歌~ ✨")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    await bot.dispatch_log(f"🚀 **✨ 𝑺𝒑𝒂𝒓𝒌 準備就緒！**")

@bot.event
async def on_message(message):
    """精簡版對話攔截邏輯 - 修正警告版"""
    if message.author == bot.user:
        return

    # 1. 攔截 Slash Command
    # 修正 DeprecationWarning: 使用 interaction_metadata 代替 interaction
    if message.content.startswith('/') or message.interaction_metadata is not None:
        return

    # 2. 判斷是否為「標註」或「私訊」
    is_mentioned = bot.user.mentioned_in(message)
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_prefixed = message.content.startswith(bot.command_prefix)

    if (is_mentioned or is_dm) and not is_prefixed:
        ask_cog = bot.get_cog("AskCommand")
        if ask_cog:
            # 清理標籤
            clean_input = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
            if not clean_input: clean_input = "你好"

            async with message.channel.typing():
                try:
                    # 統一出口：轉發至 Cog 處理
                    answer = await ask_cog.get_ai_response(
                        message.author.id, message.author.name, clean_input, source="Mention"
                    )
                    await message.reply(answer, allowed_mentions=discord.AllowedMentions.none())
                except Exception as e:
                    await bot.dispatch_log(f"❌ AI 錯誤: {e}")
                    await message.reply("🌸 嗚...大腦連線好像有點不穩。")
            return # 處理完畢就結束

    # 3. 處理傳統指令 (!play 等)
    await bot.process_commands(message)

# ==================== 啟動區 ====================

async def main():
    async with bot:
        if DISCORD_TOKEN:
            print("⚙️ 正在啟動 Discord 客戶端...")
            await bot.start(DISCORD_TOKEN)
        else:
            print("❌ 錯誤：找不到 DISCORD_TOKEN，請檢查 .env 檔案！")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 程式已由使用者關閉")