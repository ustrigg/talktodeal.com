"""
Media Engineer Agent — Prompt 优化模块

职责：
  把用户在对话中描述的需求参数（主题、风格、行业等）优化成
  适合 Seedream（文生图）和 Seedance（文生视频）API 的专业英文 prompt。

  用户说的往往很简短，比如 "modern restaurant ad"，
  但图片/视频生成 API 需要详细的英文描述才能出好效果，
  所以这个 agent 的作用就是"翻译+扩写"。

使用的模型：GPT-4.1-mini（通过 OpenAI API）
输出格式：强制 JSON（response_format=json_object）

调用方：server.py 的 run_pipeline() → 在后台线程中调用
"""

import os
import json
from openai import OpenAI
from usage_tracker import record_usage

# souls 目录存放 agent 的人格/角色设定文件（markdown 格式）
SOUL_DIR = os.path.join(os.path.dirname(__file__), "souls")


def _load_soul(name: str) -> str:
    """从 souls 目录加载人格设定文件

    输入: name = "media_engineer"
    输出: media_engineer.md 文件的完整内容（字符串）
         如果文件不存在则返回空字符串 ""

    例子:
      _load_soul("media_engineer")
      → 读取 agents/media/souls/media_engineer.md 的内容
      → "You are a professional media prompt engineer..."
    """
    path = os.path.join(SOUL_DIR, f"{name}.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def generate_prompts(params: dict, session_id: str = "unknown") -> dict:
    """把用户参数优化成 Seedream/Seedance 的专业生成 prompt

    这是 media engineer agent 的主函数。在 run_pipeline() 的第一步被调用。
    它把对话 agent 收集到的结构化参数发给 GPT，让 GPT 生成针对
    图片/视频 AI 生成引擎优化过的专业英文 prompt。

    输入:
      params = {
        "subject": "restaurant promotion",       # 主题（简短关键词）
        "image_description": "An elegant restaurant interior during evening service, couples enjoying candlelit dinner, wine glasses on white tablecloths, warm golden pendant lighting, fresh dishes beautifully plated, cozy upscale atmosphere",  # ← 核心！assistant 从对话中总结出的完整画面描述
        "business_name": "Royal Taste Bistro",    # 公司名（可选）
        "industry": "food & dining",              # 行业
        "style": "modern and warm",               # 视觉风格
        "composition": "wide shot",               # 构图
        "lighting": "warm ambient",               # 光线
        "color_tone": "golden warm tones",        # 色调
        "extra_requests": "include wine glasses",  # 额外要求
        "generate_video": true,                   # 是否需要视频
        "video_duration": 8,                      # 视频时长（秒）
        "video_ratio": "16:9"                     # 视频比例
      }
      session_id = "sess_1743580000_a1b2c3"       # 用于 usage 记录

    输出:
      {
        "image_prompt": "A wide-angle photograph of an elegant restaurant interior, Royal Taste Bistro, warm ambient lighting casting golden highlights on polished wooden tables, wine glasses catching soft reflections, modern minimalist decor with warm earth tones, commercial food photography, ultra-high detail, 4K resolution",
        "video_prompt": "Slow cinematic pan across an elegant restaurant interior, warm golden ambient lighting, wine glasses on polished tables, modern sophisticated atmosphere, smooth camera movement, commercial quality, 4K"
      }

    如果用户没有要求视频（generate_video=false），video_prompt 为空字符串:
      {
        "image_prompt": "A professional advertisement for a plumbing company...",
        "video_prompt": ""
      }

    GPT API 调用细节:
      - 模型: 环境变量 AGENT_MODEL（默认 gpt-4.1-mini）
      - temperature: 0.5（适度创意，既专业又不会太死板）
      - response_format: json_object（强制 GPT 输出合法 JSON）
      - messages 构成:
          [0] system: media_engineer 人格设定 + JSON 输出格式要求
          [1] user: 结构化的用户需求参数
    """
    client = OpenAI()
    model = os.getenv("AGENT_MODEL", "gpt-4.1-mini")

    # 加载 media_engineer 人格设定
    # 这个文件里定义了 prompt 工程的专业知识，比如：
    # - Seedream 擅长什么风格
    # - 好的 prompt 应该包含哪些元素（主体、光线、构图、质量词等）
    # - 常见的质量提升关键词（4K, ultra detail, professional photography 等）
    soul = _load_soul("media_engineer")
    needs_video = params.get("generate_video", False)

    # 拼接 system prompt：人格 + 输出格式要求
    system_prompt = f"""{soul}

---

Generate optimized prompts based on the user's requirements below.
The "Image description" field is the PRIMARY source for image prompts.
The "Video description" field is the PRIMARY source for video prompts — it may describe different scenes/actions than the image.
Enrich both with the metadata fields (style, lighting, etc.).
Respond in JSON format:
{{
  "image_prompt": "the optimized image generation prompt in English",
  "video_prompt": "the optimized video generation prompt in English (empty string if video not requested)"
}}
"""

    # 把用户参数组织成易读的文本格式发给 GPT
    # image_description 是最核心的内容描述，其他字段是辅助元数据
    # 如果某个字段用户没提供，用合理的默认值，这样 GPT 至少有个方向
    video_desc = params.get('video_description', '') or params.get('image_description', '')
    user_content = f"""User requirements:
- Image description: {params.get('image_description', params.get('subject', 'professional business advertisement'))}
- Video description: {video_desc}
- Subject: {params.get('subject', 'professional business advertisement')}
- Business: {params.get('business_name', 'generic business')}
- Industry: {params.get('industry', 'general')}
- Style: {params.get('style', 'modern and professional')}
- Composition: {params.get('composition', 'balanced')}
- Lighting: {params.get('lighting', 'natural')}
- Color tone: {params.get('color_tone', 'neutral')}
- Extra requests: {params.get('extra_requests', 'none')}
- Generate video: {needs_video}
"""

    # 调用 GPT API
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )

    # 记录 token 用量和花费
    usage = response.usage
    record_usage(session_id, "media_engineer", usage.prompt_tokens, usage.completion_tokens)

    # 解析 GPT 返回的 JSON
    # 例: {"image_prompt": "A modern restaurant...", "video_prompt": "Slow pan across..."}
    result = json.loads(response.choices[0].message.content)
    return {
        "image_prompt": result.get("image_prompt", ""),
        "video_prompt": result.get("video_prompt", ""),
    }
