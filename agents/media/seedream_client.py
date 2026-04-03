"""Seedream image generation client (Volcengine API)."""

import os
import time
import base64
import requests


class SeedreamClient:
    def __init__(self):
        self.api_key = os.getenv("VOLCENGINE_API_KEY")
        self.model = os.getenv("SEEDREAM_MODEL", "doubao-seedream-4-5-251128")
        self.endpoint = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    def generate(self, prompt: str, output_dir: str, size: str = "2048x2048") -> str | None:
        """Generate an image from text prompt. Returns filename or None."""
        os.makedirs(output_dir, exist_ok=True)

        resp = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "prompt": prompt,
                "size": size,
                "response_format": "b64_json",
                "watermark": False,
            },
            timeout=120,
        )

        if resp.status_code != 200:
            print(f"[Seedream] Error {resp.status_code}: {resp.text[:500]}")
            return None

        data = resp.json()
        if not data.get("data"):
            print(f"[Seedream] No data in response")
            return None

        b64 = data["data"][0].get("b64_json")
        if not b64:
            print(f"[Seedream] No b64_json in response")
            return None

        filename = f"img_{int(time.time())}.png"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64))

        print(f"[Seedream] Saved image: {filepath}")
        return filename
