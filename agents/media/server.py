"""
TalkToDeal AI Media Agent — API 服务器

这是整个 Media Agent 的后端入口。Flask 应用，监听 HTTP 请求，处理：
1. 用户发消息 → 调 GPT 对话 → 返回回复
2. 信息收集够了 → 后台线程生成图片/视频 → 前端轮询拿结果
3. 提供生成的媒体文件下载
4. IP 限流防止滥用
"""

import os
import json
import time
import threading

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# 加载 .env 文件里的 API key 等环境变量
load_dotenv()

from conversation import chat as conversation_chat
from media_engineer import generate_prompts
from seedream_client import SeedreamClient
from seedance_client import SeedanceClient

app = Flask(__name__)
# CORS: 允许前端（不同端口/域名）访问这个 API，开发时前端在 file:// 或其他端口
CORS(app)

# ════════════════════════════════════════════════════════════
# 路径和常量配置
# ════════════════════════════════════════════════════════════
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")    # 对话 session JSON 文件存储目录
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "output")         # 生成的图片/视频存储目录
RATE_LIMIT_PATH = os.path.join(os.path.dirname(__file__), "ips", "ip_rate_limit.json")  # IP 限流数据文件
MAX_GENERATES_PER_IP_PER_DAY = 100  # 每个 IP 每天最多生成次数（测试阶段放宽）
MAX_GENERATES_PER_SESSION = 10      # 每个 session 最多生成次数（测试阶段放宽，和前端 MAX_GENERATES_PER_SESSION 保持一致）
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RATE_LIMIT_PATH), exist_ok=True)

# 初始化图片和视频生成客户端（从 .env 读取 API key）
seedream = SeedreamClient()   # Seedream: 文生图（同步，调一次直接返回图片）
seedance = SeedanceClient()   # Seedance: 文生视频（异步，提交任务→轮询→下载）
_rate_lock = threading.Lock() # 线程锁，防止多个请求同时读写 IP 限流文件
_session_locks: dict[str, threading.Lock] = {}  # 每个 session 一把锁，防止 pipeline 线程和轮询请求同时读写同一个 session 文件
_session_locks_lock = threading.Lock()           # 管理 _session_locks 字典本身的锁


# ════════════════════════════════════════════════════════════
# Session 管理（JSON 文件持久化）
# 每个用户对话是一个独立的 session，存为 sessions/sess_xxx.json
#
# 线程安全：每个 session_id 有独立的锁。pipeline 后台线程写 session
# 的同时，轮询请求也可能在读同一个 session。用 per-session lock 保证
# 同一个 session 的读写不会并发冲突，同时不同 session 之间互不阻塞。
# ════════════════════════════════════════════════════════════

def _get_session_lock(session_id: str) -> threading.Lock:
    """获取指定 session 的线程锁（没有就创建一个）"""
    with _session_locks_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


import re

def _is_chinese_session(session: dict) -> bool:
    """检测用户是否在用中文对话（看最后几条 user 消息里有没有中文字符）"""
    for msg in reversed(session.get("messages", [])):
        if msg["role"] == "user":
            return bool(re.search(r'[\u4e00-\u9fff]', msg["content"]))
    return False


def _session_path(session_id: str) -> str:
    """把 session_id 转成安全的文件路径，过滤掉特殊字符防止路径注入

    输入: session_id = "sess_1743580000_a1b2c3"
    输出: "agents/media/sessions/sess_1743580000_a1b2c3.json"
    """
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "_-")
    return os.path.join(SESSIONS_DIR, f"{safe_id}.json")


def load_session(session_id: str) -> dict:
    """从磁盘读取 session，如果不存在则创建新的默认 session（线程安全）

    输入: session_id = "sess_1743580000_a1b2c3"
    输出（已存在的 session）:
      {
        "session_id": "sess_1743580000_a1b2c3",
        "stage": "gathering",            # 当前阶段: gathering(收集信息) | generating(生成中) | done(完成)
        "messages": [                     # 完整对话历史，每次调 GPT 时都会传入
          {"role": "user", "content": "I need an ad for my restaurant"},
          {"role": "assistant", "content": "What style do you prefer?"}
        ],
        "params": {                       # conversation agent 从对话中提取并累积的参数
          "subject": "restaurant ad",
          "style": "modern",
          "industry": "food"
        },
        "media": [                        # 已生成的媒体文件列表
          {"type": "image", "filename": "sess_xxx/img_170000.png", "prompt": "..."}
        ],
        "generate_count": 1,              # 这个 session 已经生成了几次
        "status_text": "",                # 当前生成进度提示（前端轮询时读取）
        "created_at": 1743580000.0        # session 创建时间戳
      }
    输出（新 session）:
      {
        "session_id": "sess_1743580000_a1b2c3",
        "stage": "gathering",
        "messages": [],
        "params": {},
        "media": [],
        "generate_count": 0,
        "status_text": "",
        "created_at": 1743580000.0
      }
    """
    lock = _get_session_lock(session_id)
    with lock:
        path = _session_path(session_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return {
        "session_id": session_id,
        "stage": "gathering",
        "messages": [],
        "params": {},
        "media": [],
        "generate_count": 0,
        "status_text": "",
        "created_at": time.time(),
    }


def save_session(session: dict):
    """把 session dict 写入磁盘 JSON 文件（线程安全）

    输入: session dict（同上结构）
    输出: 无（副作用：写入 sessions/sess_xxx.json）
    """
    lock = _get_session_lock(session["session_id"])
    with lock:
        path = _session_path(session["session_id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════
# IP 限流
# 通过记录每个 IP 地址当天的生成次数来防止滥用
# 数据存在 data/ip_rate_limit.json，格式：
# {"date": "2026-04-02", "ips": {"73.162.55.100": 3, "192.168.1.5": 1}}
# 每天自动重置（和前端 localStorage 限流逻辑类似，但这个在服务端，用户无法绕过）
# ════════════════════════════════════════════════════════════

def _get_client_ip() -> str:
    """获取客户端真实 IP 地址

    输入: 无（从当前 HTTP request 的 headers 里读取）
    输出: "73.162.55.100"（客户端 IP 字符串）

    优先级：X-Forwarded-For > X-Real-IP > remote_addr
    因为如果部署了 Nginx 反向代理，remote_addr 会是 127.0.0.1，
    真实 IP 在 X-Forwarded-For 或 X-Real-IP header 里
    """
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
        or request.headers.get("X-Real-IP", "") \
        or request.remote_addr


def _load_rate_limits() -> dict:
    """从磁盘加载 IP 限流数据，过期则重置

    输入: 无
    输出:
      {"date": "2026-04-02", "ips": {"73.162.55.100": 3}}  # 正常返回
      {"date": "2026-04-03", "ips": {}}                     # 新的一天，自动重置
      {"date": "2026-04-02", "ips": {}}                     # 文件不存在，返回空
    """
    if os.path.exists(RATE_LIMIT_PATH):
        with open(RATE_LIMIT_PATH, "r") as f:
            data = json.load(f)
        today = time.strftime("%Y-%m-%d")
        if data.get("date") != today:
            return {"date": today, "ips": {}}
        return data
    return {"date": time.strftime("%Y-%m-%d"), "ips": {}}


def _save_rate_limits(data: dict):
    """把 IP 限流数据写入磁盘

    输入: {"date": "2026-04-02", "ips": {"73.162.55.100": 3}}
    输出: 无（副作用：写入 data/ip_rate_limit.json）
    """
    with open(RATE_LIMIT_PATH, "w") as f:
        json.dump(data, f, indent=2)


def check_ip_rate_limit() -> int:
    """查询当前请求的 IP 今天已经生成了几次

    输入: 无（从当前 HTTP request 获取 IP）
    输出: 3（这个 IP 今天生成了 3 次）
         0（这个 IP 今天还没生成过）
    """
    ip = _get_client_ip()
    with _rate_lock:
        data = _load_rate_limits()
        return data["ips"].get(ip, 0)


def increment_ip_rate_limit():
    """给当前 IP 的今日生成计数 +1

    输入: 无（从当前 HTTP request 获取 IP）
    输出: 无（副作用：ip_rate_limit.json 里对应 IP 的计数 +1，终端打印日志）
    例子:
      调用前: {"date": "2026-04-02", "ips": {"73.162.55.100": 2}}
      调用后: {"date": "2026-04-02", "ips": {"73.162.55.100": 3}}
      终端打印: [RateLimit] IP=73.162.55.100 generates_today=3
    """
    ip = _get_client_ip()
    with _rate_lock:
        data = _load_rate_limits()
        data["ips"][ip] = data["ips"].get(ip, 0) + 1
        _save_rate_limits(data)
    print(f"[RateLimit] IP={ip} generates_today={data['ips'][ip]}")


# ════════════════════════════════════════════════════════════
# 生成 Pipeline（在后台线程中运行，不阻塞 HTTP 响应）
#
# 流程：
#   1. 调 media_engineer（GPT）把用户参数优化成 Seedream/Seedance 的英文 prompt
#   2. 调 Seedream API 生成图片 → 保存到 output/sess_xxx/img_xxx.png
#   3. （可选）调 Seedance API 生成视频 → 保存到 output/sess_xxx/vid_xxx.mp4
#   4. 更新 session 状态为 done，前端轮询时就能拿到结果
# ════════════════════════════════════════════════════════════

def run_pipeline(session_id: str):
    """在后台线程中执行图片/视频生成

    输入: session_id = "sess_1743580000_a1b2c3"
    输出: 无（副作用：
      - 生成的文件保存在 output/sess_xxx/ 目录
      - session JSON 更新为 stage="done" + media 列表
      - 如果失败则 stage 回退到 "gathering" + 错误信息
    ）

    成功后 session 变成:
      {
        "stage": "done",
        "media": [{"type": "image", "filename": "sess_xxx/img_170000.png", "prompt": "..."}],
        "reply": "Done! Generated: 1x image. Would you like any adjustments?"
      }

    失败后 session 变成:
      {
        "stage": "gathering",
        "reply": "Sorry, generation failed: API error. Please try again."
      }
    """
    session = load_session(session_id)

    try:
        # Step 1: 调 GPT (media_engineer agent) 把用户参数优化成专业的生成 prompt
        # 例如用户说 "modern restaurant ad" → 优化为 "A modern restaurant interior, warm ambient lighting,
        # elegant table setting, soft bokeh background, commercial photography, 4K, high detail"
        session["status_text"] = "Crafting optimized prompts..."
        save_session(session)

        prompts = generate_prompts(session["params"], session_id=session_id)
        print(f"[Pipeline] Image prompt: {prompts['image_prompt']}")
        print(f"[Pipeline] Video prompt: {prompts['video_prompt']}")

        # Step 2: 生成图片（支持多张）
        media_dir = os.path.join(MEDIA_DIR, session_id)
        image_count = min(int(session["params"].get("image_count", 1) or 1), 4)  # 最多 4 张
        img_success = 0

        for i in range(image_count):
            label = f" ({i+1}/{image_count})" if image_count > 1 else ""
            session["status_text"] = f"Generating image{label}..."
            save_session(session)

            img_filename = seedream.generate(prompts["image_prompt"], media_dir)
            if img_filename:
                session["media"].append({
                    "type": "image",
                    "filename": f"{session_id}/{img_filename}",
                    "prompt": prompts["image_prompt"],
                })
                save_session(session)  # 立即写入磁盘，前端轮询能马上看到
                img_success += 1

        if img_success == 0:
            session["stage"] = "gathering"
            session["status_text"] = ""
            if _is_chinese_session(session):
                session["reply"] = "抱歉，图片生成失败了。请重试或调整一下描述。"
            else:
                session["reply"] = "Sorry, image generation failed. Please try again or adjust your description."
            save_session(session)
            return

        # Step 3: 生成视频（支持多个）
        video_failed = False
        if session["params"].get("generate_video"):
            video_count = min(int(session["params"].get("video_count", 1) or 1), 2)  # 最多 2 个
            vid_success = 0

            for i in range(video_count):
                label = f" ({i+1}/{video_count})" if video_count > 1 else ""
                session["status_text"] = f"Generating video{label} — this takes a minute..."
                save_session(session)

                vid_filename = seedance.generate(
                    prompts["video_prompt"],
                    media_dir,
                    duration=session["params"].get("video_duration", 8),
                    ratio=session["params"].get("video_ratio", "16:9"),
                )

                if vid_filename:
                    session["media"].append({
                        "type": "video",
                        "filename": f"{session_id}/{vid_filename}",
                        "prompt": prompts["video_prompt"],
                    })
                    save_session(session)  # 立即写入磁盘
                    vid_success += 1

            video_failed = vid_success == 0

        # 全部生成完毕，更新 session 状态
        session["stage"] = "done"
        session["status_text"] = ""
        img_count = sum(1 for m in session["media"] if m["type"] == "image")
        vid_count = sum(1 for m in session["media"] if m["type"] == "video")
        is_zh = _is_chinese_session(session)
        if is_zh:
            parts = []
            if img_count: parts.append(f"{img_count}张图片")
            if vid_count: parts.append(f"{vid_count}个视频")
            reply = f"完成！已生成：{'、'.join(parts)}。"
            if video_failed:
                reply += "视频生成失败了，您可以再试一次。"
            else:
                reply += "需要调整，或者想生成其他内容吗？"
            session["reply"] = reply
        else:
            parts = []
            if img_count: parts.append(f"{img_count}x image{'s' if img_count > 1 else ''}")
            if vid_count: parts.append(f"{vid_count}x video{'s' if vid_count > 1 else ''}")
            reply = f"Done! Generated: {', '.join(parts)}."
            if video_failed:
                reply += " Video generation failed — you can try again."
            else:
                reply += " Would you like any adjustments, or want to generate something else?"
            session["reply"] = reply
        save_session(session)

    except Exception as e:
        # 生成失败，回退到 gathering 状态让用户可以重试
        print(f"[Pipeline] Error: {e}")
        session["stage"] = "gathering"
        session["status_text"] = ""
        is_zh = _is_chinese_session(session)
        if is_zh:
            session["reply"] = f"抱歉，生成失败：{str(e)}。请重试。"
        else:
            session["reply"] = f"Sorry, generation failed: {str(e)}. Please try again."
        save_session(session)


# ════════════════════════════════════════════════════════════
# API 路由
# ════════════════════════════════════════════════════════════

@app.route("/chat", methods=["POST"])
def chat_endpoint():
    """处理用户发来的消息

    这是前端每次用户发消息时调用的主要端点。

    输入 (POST JSON body):
      { "session_id": "sess_1743580000_a1b2c3", "message": "I need an ad for my restaurant" }

    输出（还在收集信息时）:
      { "reply": "What visual style do you prefer?", "stage": "gathering" }

    输出（信息够了，开始生成）:
      { "reply": "Got it! Generating a modern restaurant ad...", "stage": "generating" }
      此时后台线程已启动 run_pipeline()，前端应开始轮询 GET /session/:id

    输出（每 session 生成次数超限）:
      { "reply": "You've reached the generation limit...", "stage": "limited" }

    输出（IP 每日生成次数超限）:
      { "reply": "You've reached the daily trial limit...", "stage": "limited" }

    输出（正在生成中又发消息）:
      { "reply": "Still generating your content, please wait...", "stage": "generating" }
    """
    data = request.json
    session_id = data.get("session_id")
    message = data.get("message", "").strip()

    if not session_id or not message:
        return jsonify({"error": "session_id and message required"}), 400

    session = load_session(session_id)

    # 正在生成中，不接受新消息
    if session["stage"] == "generating":
        return jsonify({
            "reply": "Still generating your content, please wait...",
            "stage": "generating",
        })

    # 这个 session 的生成次数已达上限（后端检查，和前端的 MAX_GENERATES_PER_SESSION 对应）
    if session["generate_count"] >= MAX_GENERATES_PER_SESSION:
        return jsonify({
            "reply": "You've reached the generation limit for this trial session. Book a demo to explore more!",
            "stage": "limited",
        })

    # IP 每日总生成次数检查（跨 session 累计，用户无法通过前端手段绕过）
    if check_ip_rate_limit() >= MAX_GENERATES_PER_IP_PER_DAY:
        return jsonify({
            "reply": "You've reached the daily trial limit. Book a demo to unlock full access!",
            "stage": "limited",
        })

    # 记录用户消息到 session 历史
    session["messages"].append({"role": "user", "content": message})

    # 调 conversation agent (GPT-4o-mini)
    # 传入完整 session（含对话历史+已收集参数）和当前消息
    # 返回: { "ready": true/false, "reply": "...", "params": {...} }
    result = conversation_chat(session, message)

    # 记录 assistant 回复到 session 历史
    session["messages"].append({"role": "assistant", "content": result["reply"]})
    # 合并新收集到的参数（conversation agent 会累积合并）
    session["params"] = result["params"]

    if result["ready"]:
        # AI 判断信息收集够了，启动生成
        session["stage"] = "generating"
        session["generate_count"] += 1
        session["media"] = []  # 清空之前的媒体（新一轮生成）
        save_session(session)
        increment_ip_rate_limit()  # IP 生成计数 +1

        # 在后台线程中运行 pipeline（不阻塞 HTTP 响应）
        thread = threading.Thread(target=run_pipeline, args=(session_id,), daemon=True)
        thread.start()

        return jsonify({"reply": result["reply"], "stage": "generating"})
    else:
        # 信息还不够，继续收集
        session["stage"] = "gathering"
        save_session(session)
        return jsonify({"reply": result["reply"], "stage": "gathering"})


@app.route("/session/<session_id>", methods=["GET"])
def session_status(session_id):
    """前端轮询用：检查生成进度和结果

    前端在 stage=generating 时每 3 秒调一次这个接口

    输入: URL 参数 session_id = "sess_1743580000_a1b2c3"

    输出（还在生成中）:
      { "stage": "generating", "status_text": "Generating image..." }

    输出（生成完成）:
      {
        "stage": "done",
        "status_text": "",
        "media": [{"type": "image", "filename": "sess_xxx/img_170000.png"}],
        "reply": "Done! Generated: 1x image."
      }
      注意: reply 返回一次后会被清空，防止前端刷新时重复显示
    """
    session = load_session(session_id)

    # 检测卡住的 session：如果 generating 超过 10 分钟，说明 pipeline 线程被杀了（如 Flask debug 重载）
    # 自动恢复为 gathering/done，把已生成的媒体保留
    if session["stage"] == "generating":
        session_file = _session_path(session_id)
        if os.path.exists(session_file):
            last_modified = os.path.getmtime(session_file)
            stuck_seconds = time.time() - last_modified
            if stuck_seconds > 600:  # 10 分钟没更新
                is_zh = _is_chinese_session(session)
                if session.get("media"):
                    session["stage"] = "done"
                    img_count = sum(1 for m in session["media"] if m["type"] == "image")
                    vid_count = sum(1 for m in session["media"] if m["type"] == "video")
                    if is_zh:
                        parts = []
                        if img_count: parts.append(f"{img_count}张图片")
                        if vid_count: parts.append(f"{vid_count}个视频")
                        session["reply"] = f"生成过程中断了，已保留已生成的{'、'.join(parts)}。您可以继续生成其他内容。"
                    else:
                        parts = []
                        if img_count: parts.append(f"{img_count}x image{'s' if img_count > 1 else ''}")
                        if vid_count: parts.append(f"{vid_count}x video{'s' if vid_count > 1 else ''}")
                        session["reply"] = f"Generation was interrupted. Kept {', '.join(parts)} already generated. You can continue."
                else:
                    session["stage"] = "gathering"
                    session["reply"] = "抱歉，生成过程中断了，请重试。" if is_zh else "Sorry, generation was interrupted. Please try again."
                session["status_text"] = ""
                save_session(session)

    response = {
        "stage": session["stage"],
        "status_text": session.get("status_text", ""),
        "media": session.get("media", []),
    }

    if session["stage"] in ("done", "gathering"):
        response["reply"] = session.get("reply", "")
        if response["reply"]:
            session["reply"] = ""
            save_session(session)

    return jsonify(response)


@app.route("/session/<session_id>/history", methods=["GET"])
def session_history(session_id):
    """返回完整对话历史（前端刷新页面时用来恢复聊天记录）

    输入: URL 参数 session_id = "sess_1743580000_a1b2c3"

    输出:
      {
        "messages": [
          {"role": "user", "content": "I need an ad for my restaurant"},
          {"role": "assistant", "content": "What style do you prefer?"},
          {"role": "user", "content": "modern and warm"},
          {"role": "assistant", "content": "Got it! Generating..."}
        ],
        "media": [
          {"type": "image", "filename": "sess_xxx/img_170000.png", "prompt": "..."}
        ],
        "stage": "done"
      }
    """
    session = load_session(session_id)
    return jsonify({
        "messages": session.get("messages", []),
        "media": session.get("media", []),
        "stage": session["stage"],
    })


@app.route("/media/<path:filename>", methods=["GET"])
def serve_media(filename):
    """提供生成的图片/视频文件下载

    前端 <img src="/media/sess_xxx/img_170000.png"> 会请求这个路由

    输入: URL 路径 filename = "sess_1743580000_a1b2c3/img_170000.png"
    输出: 对应的文件内容（图片或视频的二进制数据）
    """
    return send_from_directory(MEDIA_DIR, filename)


@app.route("/health", methods=["GET"])
def health():
    """健康检查接口，用于确认服务器是否在运行"""
    return jsonify({"status": "ok", "time": time.time()})


@app.route("/stats", methods=["GET"])
def stats():
    """监控面板：session 数量、IP 限流状态、生成的图片/视频数量

    输入: 无
    输出:
      {
        "sessions": {
          "total": 12,                    # session 文件总数
          "by_stage": {"gathering": 3, "generating": 1, "done": 8},
          "details": [                    # 每个 session 的摘要
            {
              "session_id": "sess_xxx",
              "stage": "done",
              "generate_count": 2,
              "messages_count": 6,
              "media_count": 2,
              "created_at": 1743580000.0
            }
          ]
        },
        "ip_rate_limits": {
          "date": "2026-04-03",
          "limit_per_ip": 100,
          "ips": {"73.162.55.100": 5, "192.168.1.5": 2},
          "total_generates_today": 7
        },
        "media_files": {
          "images": 10,
          "videos": 3,
          "total_size_mb": 45.2
        },
        "limits": {
          "max_generates_per_session": 10,
          "max_generates_per_ip_per_day": 100
        },
        "usage": { ... }                  # GPT token 用量（来自 usage_tracker）
      }
    """
    from usage_tracker import get_totals

    # ── Sessions 统计 ──
    session_details = []
    by_stage = {}
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, fname), "r", encoding="utf-8") as f:
                s = json.load(f)
            stage = s.get("stage", "unknown")
            by_stage[stage] = by_stage.get(stage, 0) + 1
            session_details.append({
                "session_id": s.get("session_id", fname),
                "stage": stage,
                "generate_count": s.get("generate_count", 0),
                "messages_count": len(s.get("messages", [])),
                "media_count": len(s.get("media", [])),
                "created_at": s.get("created_at", 0),
            })
        except Exception:
            continue

    # 按创建时间倒排（最新的在前面）
    session_details.sort(key=lambda x: x["created_at"], reverse=True)

    # ── IP 限流统计 ──
    with _rate_lock:
        rate_data = _load_rate_limits()
    total_generates_today = sum(rate_data["ips"].values())

    # ── 媒体文件统计 ──
    images = 0
    videos = 0
    total_bytes = 0
    for root, dirs, files in os.walk(MEDIA_DIR):
        for f in files:
            fpath = os.path.join(root, f)
            total_bytes += os.path.getsize(fpath)
            if f.endswith((".png", ".jpg", ".jpeg", ".webp")):
                images += 1
            elif f.endswith((".mp4", ".webm", ".mov")):
                videos += 1

    return jsonify({
        "sessions": {
            "total": len(session_details),
            "by_stage": by_stage,
            "details": session_details,
        },
        "ip_rate_limits": {
            "date": rate_data.get("date", ""),
            "limit_per_ip": MAX_GENERATES_PER_IP_PER_DAY,
            "ips": rate_data.get("ips", {}),
            "total_generates_today": total_generates_today,
        },
        "media_files": {
            "images": images,
            "videos": videos,
            "total_size_mb": round(total_bytes / 1024 / 1024, 2),
        },
        "limits": {
            "max_generates_per_session": MAX_GENERATES_PER_SESSION,
            "max_generates_per_ip_per_day": MAX_GENERATES_PER_IP_PER_DAY,
        },
        "usage": get_totals(),
        "time": time.time(),
    })


# ════════════════════════════════════════════════════════════
# 主页 + 静态文件（本地开发时 Flask 同时 serve 整个网站）
# 生产环境由 Nginx 处理，这些路由不会被触发
# ════════════════════════════════════════════════════════════
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # talktodeal/ 根目录


@app.route("/")
def homepage():
    """主页"""
    return send_from_directory(SITE_ROOT, "index.html")


@app.route("/agents/media/")
def media_agent_page():
    """Media Agent 前端页面"""
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    """serve 主页的静态资源（CSS/JS/图片等）"""
    filepath = os.path.join(SITE_ROOT, filename)
    if os.path.isfile(filepath):
        return send_from_directory(SITE_ROOT, filename)
    return "Not found", 404


# ════════════════════════════════════════════════════════════
# 启动服务器
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5090))
    print(f"[Media Agent] Starting on port {port}")
    # debug=True: 代码修改后自动重启，显示详细错误信息（生产环境应关闭）
    app.run(host="0.0.0.0", port=port, debug=True)
