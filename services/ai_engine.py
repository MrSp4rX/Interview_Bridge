import requests
import json
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3"  # or your installed model


def extract_json(text):
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print("JSON Parse Error:", e)
    return None


def fallback_feedback(answer):
    return {
        "grammar_score": 5,
        "confidence_score": 5,
        "improved_answer": "Could not generate improved answer."
    }


def generate_feedback(answer, interview_type="hr", advanced=False):

    if advanced:
        prompt = f"""
You are an expert interview evaluator.

Return ONLY valid JSON. Do not add any explanation.

{{
  "grammar_score": 0,
  "confidence_score": 0,
  "technical_depth_score": 0,
  "improved_answer": ""
}}

Answer:
{answer}
"""
    else:
        prompt = f"""
Return ONLY valid JSON.

{{
  "grammar_score": 0,
  "confidence_score": 0,
  "improved_answer": ""
}}

Answer:
{answer}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json"   # 🔥 THIS IS CRITICAL
            }
        )

        data = response.json()

        raw_text = data.get("response", "")
        print("RAW LLM TEXT:", raw_text)

        parsed = extract_json(raw_text)

        if parsed:
            return parsed

        return fallback_feedback(answer)

    except Exception as e:
        print("LLM ERROR:", e)
        return fallback_feedback(answer)
