from ollama import AsyncClient # 🌸 使用非同步連線，才不會讓 Spark 說話時音樂卡住

class GeminiEngine:
    def __init__(self, api_key=None, model_id='gemma3'):
        self.model_id = model_id
        self.chat_history = {}
        # 🌸 初始化連線客戶端，預設就是連向你自己電腦的 11434 埠
        self.client = AsyncClient(host='http://localhost:11434')

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

            # 🌸 使用非同步呼叫，這樣 Spark 在「思考」時，Discord 的其他功能才不會死當
            response = await self.client.chat(
                model=self.model_id,
                messages=self.chat_history[user_id]
            )

            ai_message = response['message']['content']
            self.chat_history[user_id].append({'role': 'assistant', 'content': ai_message})

            if len(self.chat_history[user_id]) > 20:
                self.chat_history[user_id] = [self.chat_history[user_id][0]] + self.chat_history[user_id][-19:]

            return ai_message

        except Exception as e:
            print(f"❌ Local LLM Error: {e}")
            return "🌸 嗚...大腦連不上 Ollama 了呢...有開啟 Ollama 嗎？✨"