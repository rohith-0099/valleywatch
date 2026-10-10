"""Talk to the language model (Groq) with function calling and number checking."""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .check import numbers_typed_by_model
from .slots import fill, to_slots
from .facts import call_tool, tool_schemas

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
REPO_ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_NAMES = {"en": "English", "ne": "Nepali (Devanagari script)"}

SYSTEM_PROMPT = """You are the ValleyWatch assistant for flood rescue teams.

Rules you must follow:
1. You know nothing about this flood except what the functions return. Call them.
2. NEVER type a digit or a number word. Every value in a function result comes
   with a "write_this" placeholder in curly braces, for example {{buildings_hit}}.
   Write the placeholder exactly; the system replaces it with the value. Lists
   have one placeholder per row and one for the whole list: use those, do not
   retype names with numbers. Units (km², km, %) are already inside the
   placeholder: do not add them again.
3. Do no arithmetic: no sums, differences, percentages or estimates of your own.
4. If the functions do not contain the answer, say that the data does not
   contain it. Never guess. Never give population figures.
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
        # 429: the free tier allows few tokens per minute; wait and try again.
        # 400 "tool_use_failed": the model wrote a malformed function call;
        # asking again usually gives a valid one.
        malformed_call = response.status_code == 400 and "tool_use_failed" in response.text
        if not (response.status_code == 429 or malformed_call) or attempt == 5:
            break
        time.sleep(8 * attempt if response.status_code == 429 else 1)
    if not response.ok:
        raise RuntimeError(f"Language model error {response.status_code}: {response.text[:300]}")
    return response.json()["choices"][0]["message"]


def answer(facts, question, language="en", max_rounds=6):
    """Answer one question from the computed data.

    Returns {'text', 'verified', 'problems', 'functions_called'}. 'verified'
    is True only when the model typed no number itself and every placeholder
    it used exists; 'text' then has the placeholders filled in.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=LANGUAGE_NAMES[language])},
        {"role": "user", "content": question}]
    registry, called, raw, problems = {}, [], "", []
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
                if "error" in result:
                    view = result
                else:
                    view, slots = to_slots(name, arguments, result, language)
                    registry.update(slots)
                called.append({"function": name, "arguments": arguments})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(view, ensure_ascii=False)})
            continue

        raw = (reply.get("content") or "").strip()
        typed = numbers_typed_by_model(raw, question)
        text, unknown = fill(raw, registry)
        problems = ([f"typed the number {n}" for n in typed]
                    + [f"used unknown placeholder {{{k}}}" for k in unknown])
        if not problems:
            return {"text": text, "verified": True, "problems": [], "functions_called": called}
        if retried:
            break
        # One chance to correct itself, told exactly what was wrong.
        retried = True
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
                         "Your answer broke the rules: " + "; ".join(problems) + ". Rewrite it. "
                         "Type no digits or number words. Use only placeholders that appear as "
                         "\"write_this\" in the function results. Call a function if you need "
                         "more data."})
    text, _ = fill(raw, registry)
    return {"text": text, "verified": False, "problems": problems, "functions_called": called}
