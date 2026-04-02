# TalkToDeal 方案B 双轨制落地评审

## 日期：2026-04-01

---

## 一、三方案对比评审

### 方案 A：只改首页 → ❌ 不推荐
- **致命问题**：你现在 Google Ads 投 HVAC 关键词，落地页如果讲"企业记忆层"，用户会直接跳出
- 搜索 "HVAC work order software" 的人不关心你的宏大叙事，他要的是 "我的技工说的话能变成工单吗"
- 质量分暴跌 → CPC 飙升 → 白花钱

### 方案 C：多垂直矩阵 → ⏳ 太早
- 现在连 HVAC 都还没跑通 PMF，就做 plumbing/electrical/roofing 是资源浪费
- 但架构要预留，方案 B 天然兼容未来扩展到 C

### 方案 B：双轨制 → ✅ 最佳选择
- 品牌站和转化站分离，各干各的活
- HVAC 广告页专注拿线索，主站首页专注讲故事
- MIC 产品作为**抓手**贯穿两个站，但叙事层级不同：
  - HVAC 页：MIC 是 "解决你技工不写工单的工具"
  - 主站：MIC 是 "企业记忆入口之一，最强的那个"

---

## 二、方案 B 核心认知对齐

你说的这句话决定了整个信息架构：

> **核心是企业记忆，全场景数据抓取。MIC 是最好的入门抓手。**

翻译成网站结构就是：

```
talktodeal.com/          → 你是谁（企业记忆 + 全通道）
talktodeal.com/hvac      → 你能帮 HVAC 做什么（MIC → 工单 → 钱）
talktodeal.com/call      → 体验：打电话给 AI
talktodeal.com/how       → 体验：在线和 AI 对话
talktodeal.com/demo      → 预约 Demo（重定向 Google Calendar）
```

---

## 三、主站首页（/）信息架构

### 标题推荐
**"Capture every conversation. Build business memory. Execute instantly."**

理由：
- 第一句讲输入（抓取）→ 对应你的 MIC + 全通道
- 第二句讲核心（记忆）→ 这是你真正的壁垒
- 第三句讲输出（执行）→ 这是客户花钱的理由

### 分屏结构

#### Screen 1: Hero
- 标题：Capture every conversation. Build business memory. Execute instantly.
- 副标题：90% of business value is trapped in speech. We turn it into structured data, memory, and automated execution.
- CTA: Book a Demo / See HVAC Use Case
- 右侧：简化的 Voice → Memory → Execution 动画流

#### Screen 2: The Problem（大痛点，不限 HVAC）
- 标题：Your business runs on conversations. None of them are captured.
- 三张卡片：
  1. Field techs talk, nothing gets written down
  2. Phone calls with customers disappear after hangup
  3. Emails, chats, voicemails — scattered across 10 tools

#### Screen 3: Multi-Channel Input（全通道）
- 标题：Every channel. One memory.
- 视觉：7 个输入通道汇入一个中心
  - 🎙️ On-site mic (MIC series) ← 重点高亮，标注 "Our hardware"
  - 📞 Phone calls
  - 📧 Email
  - 🌐 Website chat
  - 💬 WeChat / WhatsApp
  - 📱 Social media DMs
  - 🗣️ Meeting recordings
- 底部：MIC 产品小展示 + "Built for the field. All-day battery. No app needed."

#### Screen 4: Business Memory（核心壁垒）
- 标题：From conversations to business memory.
- 三步流程：
  1. Capture → raw voice/text from any channel
  2. Structure → AI extracts entities, intent, pricing, commitments
  3. Remember → persistent memory layer, searchable, connected
- 关键句：Every conversation becomes an asset, not a liability.

#### Screen 5: Reason & Execute（执行层）
- 标题：Memory that acts.
- AI 识别：
  - 机会（Opportunities）→ 自动创建报价
  - 风险（Risks）→ 告警和升级
  - 任务（Tasks）→ 自动派发
  - 承诺（Commitments）→ 跟踪和提醒
- 输出通道：Work order / Invoice / Dispatch / Follow-up / CRM update

#### Screen 6: Industry Proof（垂直验证）
- 标题：Proven in the field. Ready for every trade.
- HVAC 大卡片（主推，有完整案例）
- Plumbing / Electrical / Roofing 小卡片（coming soon 状态）
- "See full HVAC use case →" 链接到 /hvac

#### Screen 7: Trust Layer
- Integrations bar: ServiceTitan, Housecall Pro, Jobber, QuickBooks, HubSpot, Salesforce
- Security: End-to-end encrypted, SOC 2 ready, TCPA compliant
- Stats: 10+ teams / X conversations captured

#### Screen 8: CTA
- 标题：Stop losing business conversations.
- CTA: Book a Demo / Call AI Demo / See HVAC Use Case
- 价格提示：Starting at $99/month per team

---

## 四、HVAC 广告页（/hvac）信息架构

直接把当前 index.html 搬过去，微调：

### 标题推荐
**"Stop losing job details between the truck and the office."**

理由：
- 直击 HVAC 老板最痛的点
- 搜索意图精准匹配
- 不需要解释 AI、记忆层、平台

### 需要微调的部分
1. Hero 标题换成上面这句
2. 增加 FAQ 区（录音合法性、隐私、培训时间、上线周期）
3. 增加简单定价区
4. CTA 更强调 "Start in 5 minutes, no training needed"

---

## 五、执行步骤

### 第一步：固化 HVAC 页
- 复制 index.html → hvac/index.html
- 微调标题和 FAQ
- 首页导航添加 /hvac 链接

### 第二步：构建新主站首页
- 新写 index.html
- 新增 styles-home.css（或扩展现有 styles.css）
- 8 屏结构，保持 Apple 级设计语言

### 第三步：更新导航体系
- 主站导航：Platform / HVAC / Try It / Demo
- HVAC 页导航：← Back to Platform / Problem / Solution / Demo

### 第四步：验证
- 预览两个页面
- 确保 /call 和 /how 从两个页面都能正确跳转
- 推送 GitHub → Cloudflare Pages 自动部署

---

## 六、风险提示

1. **SEO 权重转移**：当前 / 页面已有的 HVAC 关键词排名会丢失，需要确保 /hvac 被搜索引擎快速收录
2. **广告落地页 URL 需要改**：Google Ads 的落地页 URL 从 / 改成 /hvac
3. **两套页面维护成本**：后续改产品信息要改两个地方

---

## 七、结论

**方案 B 是当前阶段唯一正确选择。**

核心逻辑：
- 你需要一个"给投资人和合作方看"的品牌站 → /
- 你需要一个"给 HVAC 老板看"的转化站 → /hvac
- MIC 在两个站都出现，但叙事角度不同
- 未来加行业只需要复制 /hvac 模板改术语

等你确认，我立刻开始执行第一步。
