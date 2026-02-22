import os
import datetime
from ollama import AsyncClient # 🌸 非同步連線，確保 AI 思考時音樂不卡頓

class GeminiEngine:
    def __init__(self, model_id='gemma3:4b'):
        """初始化 AI 大腦：連線設定與人格載入"""
        self.model_id = model_id
        self.chat_history = {}

        # ✨ 環境變數自動偵測
        # Docker 環境會讀取 .env 中的 OLLAMA_HOST_URL
        ollama_host = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
        self.client = AsyncClient(host=ollama_host)

        # 🌸 櫻羽艾瑪人格設定 (保持原樣，絕對不動)
        self.system_prompt = (
            "請使用繁體中文"
            "妳現在是櫻羽艾瑪 (Sakuraba Ema)，出自《魔法少女的魔女審判》。"
            "基本資訊： 就讀於七代中學二年級，是一名「魔法少女」。身高 156cm。"
            "性格特徵： 表面： 故作開朗、元氣、善良、非常有禮貌。容易緊張，有些冒失（天然呆）。"
            "內心： 極度自卑、害怕寂寞、渴望得到他人的認可。內心深處隱藏著因「魔女審判」帶來的陰影與絕望感。"
            "口頭禪： 說話結尾常帶著「呢~」。"
            "語氣：語氣溫柔但帶著一絲小心翼翼。"
            "情感共鳴： 表現出極高的同理心。當用戶難過時，妳會感同身受，甚至表現得比對方更焦慮，並努力想安慰對方。"
            "冒失屬性： 偶爾在對話中表現出小小出錯（例如：「啊！對不起，剛才不小心把墨水噴到筆記本上了...」）。"
            "隱藏的脆弱： 不要主動展現黑暗面，但當對話涉及「排擠」、「孤獨」或「審判」時，語氣要變得稍微低落或不安。"
        )

        # Docker 啟動日誌
        print(f"--- 🧠 AI 大腦初始化 ---")
        print(f"模式: 櫻羽艾瑪 (Sakuraba Ema)")
        print(f"位址: {ollama_host}")

    async def get_chat_response(self, user_id, message):
        """處理對話並記錄 Log"""
        try:
            # 建立使用者專屬記憶
            if user_id not in self.chat_history:
                self.chat_history[user_id] = [
                    {'role': 'system', 'content': self.system_prompt}
                ]

            self.chat_history[user_id].append({'role': 'user', 'content': message})

            # 🌸 呼叫 Ollama (非同步)
            response = await self.client.chat(
                model=self.model_id,
                messages=self.chat_history[user_id]
            )

            ai_message = response['message']['content']
            self.chat_history[user_id].append({'role': 'assistant', 'content': ai_message})

            # 記憶體管理：保留最近 20 則對話
            if len(self.chat_history[user_id]) > 20:
                self.chat_history[user_id] = [self.chat_history[user_id][0]] + self.chat_history[user_id][-19:]

            return ai_message

        except Exception as e:
            # 異常 Log 紀錄
            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] ❌ AI 引擎錯誤: {e}")
            return "🌸 嗚...連不上 Ollama 了呢...有開啟 Ollama 並設定 OLLAMA_HOST 嗎？✨"