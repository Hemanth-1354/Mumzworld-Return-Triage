import asyncio
import json
from prompts import build_messages
from app import MOCK_ORDERS, OPENROUTER_API_KEY, MODEL, OPENROUTER_BASE
import httpx

async def main():
    customer_text = "This baby formula is untouched but I want to return it."
    order_data = MOCK_ORDERS["ORD-1003"].copy()
    order_data["order_id"] = "ORD-1003"
    messages = build_messages(customer_text, order_data)

    print("Sending messages:", messages)

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 900,
            },
        )
    print("Status:", resp.status_code)
    try:
        resp_data = resp.json()
        print("Response JSON:", json.dumps(resp_data, indent=2))
    except Exception as e:
        print("Raw text:", resp.text)

if __name__ == "__main__":
    asyncio.run(main())
