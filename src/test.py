import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
print("KEY=", os.getenv("DEEPSEEK_API_KEY"))

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
completion = client.chat.completions.create(
    model="MiniMax-M2.1",
    messages=[{'role': 'user', 'content': '你是谁？'}]
)
print(completion.choices[0].message.content)
print(os.getenv("DEEPSEEK_API_KEY"))