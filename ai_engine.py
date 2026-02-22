import os
from ollama import AsyncClient # 🌸 使用非同步連線，才不會讓 Spark 說話時音樂卡住

class GeminiEngine:
    def __init__(self, model_id='gemma3:4b'): # 這裡建議補上妳要的版本號
        self.model_id = model_id
        self.chat_history = {}

        # ✨ 關鍵改動：優先讀取環境變數，若無則預設連線方式
        # 如果是 Docker 環境，我們會傳入 http://host.docker.internal:11434
        # 如果是安卓連電腦，我們會傳入 http://192.168.x.x:11434
        ollama_host = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")

        self.client = AsyncClient(host=ollama_host)

        self.system_prompt = (
            "你叫櫻羽艾瑪，外號是Spark，是一個二次元。你必須全程使用『繁體中文』回覆。"
            "你的回覆風格親切，只用少量emoji。"
            "語氣要像美少女遊戲的對話。"
            "回覆簡短有力，並多用 ✨、🌸、🦋 符號。"
        )

    async def get_chat_response(self, user_id, message):
        try:
            if user_id not in self.chat_history:
                self.chat_history[user_id] = [
                    {'role': 'system', 'content': self.system_prompt}
                ]

            self.chat_history[user_id].append({'role': 'user', 'content': message})

            # 🌸 非同步呼叫，Spark 思考時音樂也不會斷掉喔
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
            print(f"❌ Ollama 連線異常: {e}")
            return "🌸 嗚...大腦連不上 Ollama 了呢...有開啟 Ollama 並設定 OLLAMA_HOST 嗎？✨"