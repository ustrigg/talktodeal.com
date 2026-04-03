"""
Conversation Agent — 对话收集模块

职责：
  和用户对话，收集生成图片/视频所需的信息（主题、风格、行业等），
  当信息收集够了就返回 ready=true，触发后续的 pipeline 生成流程。

使用的模型：GPT-4.1-mini（通过 OpenAI API）
输出格式：强制 JSON（response_format=json_object）

调用方：server.py 的 /chat 端点
"""

import os
import json
from openai import OpenAI
from usage_tracker import record_usage

# souls 目录存放 agent 的人格/角色设定文件（markdown 格式）
SOUL_DIR = os.path.join(os.path.dirname(__file__), "souls")


def _load_soul(name: str) -> str:
    """从 souls 目录加载人格设定文件

    输入: name = "assistant"
    输出: assistant.md 文件的完整内容（字符串）
         如果文件不存在则返回空字符串 ""

    例子:
      _load_soul("assistant")
      → 读取 agents/media/souls/assistant.md 的内容
      → "You are TalkToDeal's AI Media Agent. You help businesses create..."
    """
    path = os.path.join(SOUL_DIR, f"{name}.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ════════════════════════════════════════════════════════════
# GPT 输出格式定义
#
# 这段文字会作为 system prompt 的一部分发给 GPT，
# 告诉它必须用 JSON 格式回复，并定义了每个字段的含义和规则。
# ════════════════════════════════════════════════════════════
EXTRACTION_SCHEMA = """
You must respond in JSON format with this structure:
{
  "ready": true/false,
  "reply": "your message to the user",
  "params": {
    "subject": "what the image/video is about",
    "image_description": "detailed description of the desired image content — what should appear in the picture, the scene, objects, people, atmosphere, mood, etc.",
    "business_name": "company name if provided",
    "industry": "industry/business type",
    "style": "visual style (modern, warm, playful, etc.)",
    "composition": "image composition (close-up, wide, overhead, etc.)",
    "lighting": "lighting style (natural, studio, warm, dramatic)",
    "color_tone": "color preferences",
    "extra_requests": "any specific user requirements",
    "image_count": 1,
    "generate_video": false,
    "video_count": 1,
    "video_description": "detailed description of the video scene — what motion, action, camera movement should happen",
    "video_duration": 8,
    "video_ratio": "16:9"
  }
}

Rules for "ready":
- Before setting ready=true, you MUST confirm details for ALL requested content types in ONE turn:
  * For IMAGE: ask about style, composition, lighting, color tone (offer specific choices)
  * For VIDEO: ask about duration (5s/8s/10s), ratio (16:9/9:16/1:1), camera movement, scene description
  * For BOTH: ask about image AND video details together in the same message
- If user specifies multiple images/videos (e.g. "3 images" / "2 videos"), set image_count/video_count accordingly
- Set ready=true ONLY after user confirms or provides the details
- If user says "just make it" / "go ahead" / "start" / "你看着办" / "不用再问了" / "直接生成" / "随便" / "开始吧" etc., set ready=true IMMEDIATELY with reasonable defaults — do NOT ask any more questions
- Set ready=false if you still need critical info (what the content is about)
- After the first generation in a session, if user gives a new request with enough context from previous conversation, set ready=true without re-asking basic questions

Rules for "reply":
- ALWAYS reply in the SAME LANGUAGE the user is using. If user writes in Chinese, reply in Chinese. If in English, reply in English. Match their language exactly.
- If ready=false: ask follow-up questions. Ask about ALL content types (image + video) in ONE turn, not separately.
- If ready=true: confirm what you'll generate including counts, e.g. "Got it! I'll generate 2 images and 1 video. Please wait..."

Rules for "params":
- Only include fields that have been mentioned or can be inferred
- Use empty string "" for unknown fields
- Merge with previous params from conversation context
- image_count: how many images to generate (default 1, max 4)
- video_count: how many videos to generate (default 1, max 2)

Rules for "generate_video":
- If the user mentions "video", "视频", "动画", "animation", "motion", or "clip" anywhere in the conversation, set generate_video=true
- If user says "image AND video" or "图片和视频", set generate_video=true
- Default is false — only set true when user explicitly or implicitly wants video

Rules for "video_description":
- Separate from image_description — this describes what MOTION and ACTION should happen in the video
- Example: "Camera slowly pushes forward toward steaming dumplings on a table, a customer picks one up with chopsticks, steam rises"
- If user describes different scenes for image vs video, capture them separately

Rules for "image_description":
- This is the MOST IMPORTANT field — it is the primary input for the image/video generation engine
- Summarize EVERYTHING the user described about the visual content into one rich, detailed paragraph
- Include: scene, objects, people, actions, atmosphere, mood, textures, background elements
- Example: if user said "I want an ad showing a cozy restaurant with people enjoying dinner, wine glasses on the table, warm evening vibe" → image_description should be "A cozy upscale restaurant interior during evening hours, couples and small groups enjoying dinner at candlelit tables, wine glasses filled with red wine on white tablecloths, warm ambient atmosphere with soft golden lighting, elegant decor"
- Even if user only gave brief info, expand it into a vivid scene description using context clues from subject/industry/style
"""


def chat(session: dict, user_message: str) -> dict:
    """处理用户消息，返回 AI 回复和收集到的参数

    这是对话 agent 的主函数。每次用户发消息时被 server.py 调用。
    它把完整对话历史 + 已收集参数 + 新消息一起发给 GPT，
    GPT 判断信息是否够了（ready），并继续收集或确认生成。

    输入:
      session = {
        "session_id": "sess_1743580000_a1b2c3",
        "messages": [                           # 之前的对话历史
          {"role": "user", "content": "I need an ad for my restaurant"},
          {"role": "assistant", "content": "What visual style do you prefer?"}
        ],
        "params": {                             # 之前已收集的参数
          "subject": "restaurant ad",
          "industry": "food"
        },
        ...
      }
      user_message = "modern and warm style, go ahead"

    输出（信息够了，ready=true）:
      {
        "ready": true,
        "reply": "Got it! I'll generate a modern, warm-toned restaurant ad image. Please wait...",
        "params": {
          "subject": "restaurant ad",
          "image_description": "An elegant modern restaurant interior with warm ambient lighting, diners enjoying meals at wooden tables, soft golden glow from pendant lights, wine glasses and fresh dishes on white tablecloths, inviting and cozy evening atmosphere",
          "business_name": "",
          "industry": "food",
          "style": "modern and warm",
          "composition": "",
          "lighting": "warm",
          "color_tone": "warm tones",
          "extra_requests": "",
          "generate_video": false,
          "video_duration": 8,
          "video_ratio": "16:9"
        }
      }

    输出（信息不够，ready=false）:
      {
        "ready": false,
        "reply": "That sounds great! A couple more questions:\\n1. Do you have a company name?\\n2. Any color preferences?",
        "params": {
          "subject": "restaurant ad",
          "image_description": "A restaurant advertisement image",
          "industry": "food",
          "style": "modern"
        }
      }

    GPT API 调用细节:
      - 模型: 环境变量 AGENT_MODEL（默认 gpt-4.1-mini）
      - temperature: 0.4（偏低，让回答更稳定、更遵循格式）
      - response_format: json_object（强制 GPT 输出合法 JSON）
      - messages 构成:
          [0] system: 人格设定(assistant.md) + JSON 输出格式要求
          [1] system: 当前已收集的参数（如果有的话）
          [2..n-1] 历史对话（user/assistant 交替）
          [n] user: 本次用户消息
    """
    client = OpenAI()
    model = os.getenv("AGENT_MODEL", "gpt-4.1-mini")

    # 加载 assistant 人格设定（定义 AI 的角色、语气、行为准则）
    assistant_soul = _load_soul("assistant")

    # 拼接 system prompt：人格 + JSON 输出格式要求
    system_prompt = f"""{assistant_soul}

---

{EXTRACTION_SCHEMA}
"""

    # 构建发给 GPT 的 messages 数组
    messages = [{"role": "system", "content": system_prompt}]

    # 如果之前已经收集了一些参数，作为额外的 system message 注入
    # 这样 GPT 知道哪些信息已经有了，不会重复问
    if session.get("params"):
        messages.append({
            "role": "system",
            "content": f"Current collected parameters:\n```json\n{json.dumps(session['params'], indent=2)}\n```"
        })

    # 加入历史对话（让 GPT 有完整上下文）
    for msg in session.get("messages", []):
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 加入本次用户消息
    messages.append({"role": "user", "content": user_message})

    # 调用 GPT API
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        response_format={"type": "json_object"},
    )

    # 记录 token 用量和花费
    usage = response.usage
    record_usage(
        session.get("session_id", "unknown"),
        "conversation",
        usage.prompt_tokens,
        usage.completion_tokens,
    )

    # 解析 GPT 返回的 JSON
    # 例: {"ready": false, "reply": "What style?", "params": {"subject": "restaurant ad"}}
    result_text = response.choices[0].message.content
    result = json.loads(result_text)

    # 合并参数：保留旧参数 + 覆盖新值（只覆盖非空字段）
    # 例:
    #   旧 params: {"subject": "restaurant ad", "industry": "food"}
    #   GPT 返回的 new_params: {"subject": "restaurant ad", "style": "modern", "industry": ""}
    #   合并后: {"subject": "restaurant ad", "industry": "food", "style": "modern"}
    #   注意 industry 保持 "food"，因为 GPT 返回的是空字符串，不覆盖
    new_params = result.get("params", {})
    merged = {**session.get("params", {})}
    for k, v in new_params.items():
        if v and v != "":
            merged[k] = v
    result["params"] = merged

    return result
