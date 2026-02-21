import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from ai_engine import GeminiEngine
from music_engine import SparkMusicEngine
import asyncio

load_dotenv()



# ==================== 配置區 ====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_ID = os.getenv("SPOTIFY_ID")
SPOTIFY_SECRET = os.getenv("SPOTIFY_SECRET")
MODEL_ID = 'gemma3:4b'
# ===============================================

# ==================== 初始化 ====================
ai = GeminiEngine(MODEL_ID)
music = SparkMusicEngine(client_id=SPOTIFY_ID, client_secret=SPOTIFY_SECRET)
# ===============================================



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

    async def setup_hook(self):
        try:
            from commands import setup as setup_commands
            await setup_commands(self, ai, music)
            await self.tree.sync()
            print(f"✅ 引擎連動成功！目前核心：{MODEL_ID} (Local)")
            print(f"🎵 音樂控制面板與佇列系統已準備就緒！")
        except Exception as e:
            print(f"❌ 載入失敗: {e}")

bot = SparkBot()

@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="正在唱歌~ ✨")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f"✨ 𝑺𝒑𝒂𝒓𝒌 已經上線了！")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        user_input = message.content.replace(f'<@{bot.user.id}>', '').strip() or "你好"
        if not user_input.startswith('/'):
            async with message.channel.typing():
                try:
                    # 直接呼叫本機模型進行對話
                    answer = await ai.get_chat_response(str(message.channel.id), user_input)
                    await message.reply(answer)
                except Exception as e:
                    print(f"AI Error: {e}")
                    await message.reply(f"🌸 嗚...本機引擎目前有點喘，可能要稍等一下喔。")

    await bot.process_commands(message)

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ 錯誤：找不到 DISCORD_TOKEN！")