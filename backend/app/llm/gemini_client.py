import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_model = os.getenv("GEMINI_MODEL")

if not gemini_api_key:
    raise RuntimeError("Missing GEMINI_API_KEY")
if not gemini_model:
    raise RuntimeError("Missing GEMINI_MODEL")

genai.configure(api_key=gemini_api_key)
model = genai.GenerativeModel(gemini_model)

def gemini_reply(prompt: str) -> str:
    response = model.generate_content(prompt)
    return getattr(response, "text", "") or ""