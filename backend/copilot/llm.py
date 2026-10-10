"""Talk to the language model (Groq) with function calling and number checking."""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .check import unsupported_numbers
from .facts import call_tool, tool_schemas

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
REPO_ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_NAMES = {"en": "English", "ne": "Nepali (Devanagari script)"}

SYSTEM_PROMPT = """You are the ValleyWatch assistant for flood rescue teams.

Rules you must follow:
1. You know nothing about this flood except what the functions return. Call them.
2. Every number you write must be copied exactly from a function result. Do no
   arithmetic: no sums, differences, percentages or estimates of your own.
3. If the functions do not contain the answer, say that the data does not
   contain it. Never guess. Never give population figures.
4. Write every number as digits, never as a word (write 2, not two).
5. Be brief and plain. Rescue teams read this in a hurry.
6. Results are estimates from satellite images, not field reports. Say so when
   it matters. This is an educational prototype, not an operational tool.
7. Answer in {language}."""


def _ask_groq(messages, use_tools=True):
    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set in .env")
    body = {"model": os.environ.get("GROQ_MODEL", DEFAULT_MODEL), "messages": messages,
            "temperature": 0.2}
    if use_tools:
        body["tools"], body["tool_choice"] = tool_schemas(), "auto"
    for attempt in range(1, 6):
        response = requests.post(GROQ_URL, json=body, timeout=120,
                                 headers={"Authorization": f"Bearer {key}"})
        # The free tier allows few tokens per minute; wait and try again.
        if response.status_code != 429 or attempt == 5:
            break
        time.sleep(8 * attempt)
    if not response.ok:
        raise RuntimeError(f"Language model error {response.status_code}: {response.text[:300]}")
    return response.json()["choices"][0]["message"]


def answer(facts, question, language="en", max_rounds=6):
    """Answer one question from the computed data.

    Returns {'text', 'verified', 'unsupported_numbers', 'functions_called'}.
    'verified' is True only when every number in the text was found in the
    results of the functions the model called.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=LANGUAGE_NAMES[language])},
        {"role": "user", "content": question}]
    seen, called, text = [], [], ""
    retried = False
    for _ in range(max_rounds + 2):
        reply = _ask_groq(messages)
        if reply.get("tool_calls"):
            messages.append({"role": "assistant", "content": reply.get("content") or "",
                             "tool_calls": reply["tool_calls"]})
            for call in reply["tool_calls"]:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = call_tool(facts, name, arguments)
                seen.append(result)
                called.append({"function": name, "arguments": arguments})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result, ensure_ascii=False)})
            continue

        text = (reply.get("content") or "").strip()
        missing = unsupported_numbers(text, seen, question)
        if not missing:
            return {"text": text, "verified": True, "unsupported_numbers": [],
                    "functions_called": called}
        if retried:
            break
        # One chance to correct itself, told exactly which figures failed.
        retried = True
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content":
                         "These numbers are not in the function results: " + ", ".join(missing)
                         + ". Rewrite the answer using only numbers copied exactly from the "
                           "function results, with no calculations. If you need more data, "
                           "call a function."})
    return {"text": text, "verified": False,
            "unsupported_numbers": unsupported_numbers(text, seen, question),
            "functions_called": called}
