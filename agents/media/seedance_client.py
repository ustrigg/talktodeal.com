"""Seedance video generation client (Volcengine API)."""

import json
import os
import time
import requests


class SeedanceClient:
    def __init__(self):
        self.api_key = os.getenv("VOLCENGINE_API_KEY")
        self.model = os.getenv("SEEDANCE_MODEL", "doubao-seedance-1-5-pro-251215")
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

    def generate(self, prompt: str, output_dir: str, duration: int = 8, ratio: str = "16:9") -> str | None:
        """Generate a video from text prompt. Returns filename or None."""
        os.makedirs(output_dir, exist_ok=True)

        # Step 1: Create task
        resp = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "content": [{"type": "text", "text": prompt}],
                "duration": int(duration),
                "resolution": "720p",
                "ratio": ratio,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            print(f"[Seedance] Create task error {resp.status_code}: {resp.text[:500]}")
            return None

        data = resp.json()
        task_id = data.get("id")
        if not task_id:
            print(f"[Seedance] No task ID in response")
            return None

        print(f"[Seedance] Task created: {task_id}")

        # Step 2: Poll for completion
        poll_url = f"{self.base_url}/{task_id}"
        timeout_sec = 300
        start = time.time()

        while time.time() - start < timeout_sec:
            time.sleep(5)
            poll_resp = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )

            if poll_resp.status_code != 200:
                continue

            poll_data = poll_resp.json()
            status = poll_data.get("status", "")

            if status == "succeeded":
                print(f"[Seedance] Succeeded, full response: {json.dumps(poll_data, indent=2, ensure_ascii=False)[:2000]}")

                video_url = None
                content = poll_data.get("content", {})

                # 结构1 (实际): content.video_url 直接是字符串
                if isinstance(content, dict) and isinstance(content.get("video_url"), str):
                    video_url = content["video_url"]

                # 结构2: content.data[].type=="video_url" 或 "video"
                if not video_url and isinstance(content.get("data"), list):
                    for item in content["data"]:
                        if item.get("type") in ("video_url", "video"):
                            video_url = item.get("url") or item.get("video_url")
                            break

                # 结构3: output.video_url
                if not video_url:
                    video_url = poll_data.get("output", {}).get("video_url")

                if not video_url:
                    print(f"[Seedance] Succeeded but no video URL found in response")
                    return None

                # Step 3: Download
                filename = f"vid_{int(time.time())}.mp4"
                filepath = os.path.join(output_dir, filename)
                dl = requests.get(video_url, timeout=60)
                with open(filepath, "wb") as f:
                    f.write(dl.content)

                print(f"[Seedance] Saved video: {filepath}")
                return filename

            elif status in ("failed", "expired", "cancelled"):
                print(f"[Seedance] Task {status}: {poll_data}")
                return None

            print(f"[Seedance] Polling... status={status}")

        print(f"[Seedance] Task timed out after {timeout_sec}s")
        return None
