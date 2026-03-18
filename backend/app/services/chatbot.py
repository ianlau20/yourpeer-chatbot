from app.llm.gemini_client import gemini_reply

def generate_reply(message: str) -> str:
    return gemini_reply(message)