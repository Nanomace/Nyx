from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print("Loaded API key:", "YES" if api_key else "NO")

client = genai.Client(api_key=api_key)

print("\nFetching available models...\n")

models = client.models.list()

for m in models:
    print(m.name)