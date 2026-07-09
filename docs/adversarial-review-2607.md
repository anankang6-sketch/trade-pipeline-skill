# 对抗性审查报告（2026-07-08，Claude Sonnet 5）

> 本文档由 Claude Sonnet 5 对 trade-pipeline-skill 项目做的一次对抗性审查（三个并行视角：Skill 护栏、代码健壮性、市场认可度）。
> 用途：交给另一个模型（GPT / Gemini 等）做独立交叉验证，检验结论是否站得住脚、是否有遗漏或过度判断的地方。
> 审查范围：commit 92a43f3 时的仓库状态。

---

## 视角一：Skill 定义的护栏与可用性

### 1. 触发词脆弱性
- `.claude/skills/trade-pipeline-run/SKILL.md` L4-19、`.claude/skills/trade-pipeline-init/SKILL.md` L4-15：triggers 是硬编码中文短语枚举，无语义/正则泛化。
- init 的触发词里有裸词 `"init"` `"setup"`（init/SKILL.md L9），容易在讨论其他项目时误触发。
- 两个 Skill 的 description 相似度较高，config.yaml 还是示例数据时 init 会被 run 的逻辑二次触发（run/SKILL.md L34），存在职责重叠。

### 2. 护栏可被绕过之处
- `trade-pipeline-run/SKILL.md` L73：`Do NOT add --interactive flag (default to review.json mode for safety)` —— 唯一的安全护栏，但只是孤立提示，没有说明原因，纯靠模型"听话"，没有机制层面强制。
- `run/SKILL.md` L86-87：buyer 匹配失败后，"帮你编辑 review.json 并重新运行"——把选择正确 buyer 的高风险决策完全下放给 Claude，没有要求把候选 buyer 清单完整展示、要求用户显式指认后才写入 `resolved_value`。这是外贸场景最危险的一步（PI/CI 抬头/地址写错）却缺少强制确认。
- 全文没有一处要求"生成的 PI/CI 是正式对外文件，发送前需要用户二次确认金额/抬头"。从"价格填好了"这句话到 `main.py` 自动重新生成 PI/CI，中间没有强制人工确认关卡。
- `understanding/llm_parser.py` L412-414：Claude API 调用失败会静默 fallback 到规则模式，SKILL.md 没有提示用户"这次结果可能是降级模式，请留意"。

### 3. 错误恢复/幂等性
- `pipeline/main.py` 本身的中间态设计比较严谨（review.json、packing_review.json、precheck.md、显式 `--confirm`/`--confirm-packing`）。
- 但 SKILL.md 层面只覆盖了 buyer 匹配失败一种失败模式（run/SKILL.md L82-87），Excel 解析异常、PL 装箱信息缺失生成的 packing_review.json（main.py L275-297）等其他中间态，SKILL.md 没有对应的续跑指导——用户可能卡在 Skill 没教过的错误分支里。

### 4. `--use-llm` 隐私风险零文档化
- README.md / README_DEV.md / CLAUDE.md / 两个 SKILL.md 全文搜索"隐私/privacy/发送到"均无命中。
- `--use-llm` 会把询价单原始内容（客户名、产品、数量，`llm_parser.py` L383 截取前 4000 字符）发送到 Anthropic API，没有任何文档提示这一点，也没有 opt-in/脱敏机制。

**最严重3项（按严重程度）：**
1. PI/CI 生成/回写全链路缺少强制性人工确认环节
2. buyer review.json 的编辑权限模糊，候选清单未强制展示
3. `--use-llm` 数据出境风险零文档化

---

## 视角二：核心代码健壮性

### 1. buyer_matcher.py 四级匹配 —— 子串包含无阈值
- `buyer_matcher.py` L117-129：模糊匹配用双向子串包含 `norm_name in norm_extracted or norm_extracted in norm_name`，没有相似度阈值、编辑距离、长度比例校验。
- "Global Fasteners LLC" 和 "Global Fasteners Trading LLC"（可能是完全不同的两家公司）只要一个是另一个的子串就会匹配成功。
- `test_buyer_matcher.py` L35-41 只验证了正向案例（"Metiz" 匹配 "Metiz Trading"），**没有任何负样本测试**验证两个相似但不同公司应该被拒绝匹配。
- 判断：这是外贸场景最危险的静默错误——发错 PI 抬头。

### 2. UUID 锚定回写 —— 只防格式扰动，不防生态外篡改
- `price_updater.py` 对行插入/重排确实免疫（`test_uuid_anchor.py` L88-135），也做了重复 UUID 检测（L79/86）和孤儿校验。
- 前提假设是"Excel 由 quote_writer 原样生成、仅改单价列"。
- 整行复制粘贴（UUID 随行复制）→ 会被检测到重复 UUID 并抛 `PriceUpdateError`，这层是稳的。
- WPS/网易邮箱大师编辑保存 → 隐藏列属性可能被非 Office 软件破坏，`_find_uuid_column` 只扫描前 20 行（L19），表头挪位会直接报错阻断（尚可接受）。
- 压缩成图片转手誊抄 → UUID 机制完全失效，代码无法应对，也确实无法应对。

### 3. canonicalizer.py 翻译表 —— 硬编码字典，未命中静默直通
- `canonicalizer.py` L55-66：`cn_en` 列表硬编码约 10 条中文→英文映射。
- `_normalize_description`（L67-70）未匹配到任何一条时，**原样保留中文，不报错、不警告、不进入 review 流程**。
- 与 buyer_matcher "未命中就硬阻断" 的设计哲学矛盾：新客户用字典外的中文品名（如"膨胀螺栓"）会静默流入下游 Writer，报价单可能中英文夹杂发给客户。

### 4. 测试覆盖缺口
- 30 个源文件 vs 15 个测试文件。
- **无 `test_extractor.py`**——Excel 解析的唯一入口，零直接测试覆盖。
- 未发现空 Excel、多 sheet、合并单元格、超大文件相关的测试用例。
- `price_updater` 容错测试只覆盖插入空行/乱序，没测"UUID 列被误删/隐藏列被手动显示后误编辑"。

**最严重3项（按严重程度）：**
1. buyer 模糊匹配子串包含无阈值（`buyer_matcher.py` L117-129），最可能导致真实事故，且无负样本测试
2. canonicalizer 硬编码翻译表静默直通（`canonicalizer.py` L55-70），与项目"失败就硬阻断"哲学自相矛盾
3. extractor.py 零测试覆盖，所有下游正确性都建立在这一步之上

**行业圈子最可能吐槽的点**：核心卖点"UUID 锚点回写"本质是 openpyxl 扫描隐藏列做字典映射，一旦文件脱离 Excel 生态（微信/邮件压缩转发、WPS 另存、图片化传阅）立刻失效——"实验室级鲁棒性，生产级易碎"。

---

## 视角三：市场认可度的第一性原理分析

判断前提：目标用户是"没有 ERP、靠 Excel + 邮件 + 微信处理单据的 1-3 人小外贸团队，五金/紧固件行业"。

### 逐条失败模式对照
1. **分发触达问题**：目标用户的信息源是行业群、展会、软件销售电话，不是 GitHub。开源发布约等于把货铺在目标客户从不逛的商场里，触达率趋近于零。
2. **安装门槛 vs 用户技术水平落差**：git clone / pip install / 配置 Claude Code 插件，对非技术外贸业务员是硬门槛，"厂二代懂技术"是幸存者偏差，同行大多不具备。
3. **信任/责任问题**：PI/CI 是有法律效力的对外单证，出错（金额、条款、税号）造成实际货款损失或纠纷。免费工具作者不担责，企业 SaaS 有客服、有 SLA、可甩锅——这一点个人开源项目结构性地竞争不过。
4. **同质化竞争**：国内已有金蝶/管家婆/易族等外贸 ERP 插件及大量收费报价单 SaaS，产品力未必更强，但有销售、有本地化支持、有人天天推销，渠道压制个人项目。
5. **可持续性**：单人业余维护，用户默认"半年后没人理"，单据格式一旦需要变更（客户要求改模板）没人及时改就被弃用。
6. **其他**：强依赖 Claude Code 这个还很小众的载体，等于在小众生态里做小众行业工具，双重收窄；且强绑定作者本人五金/紧固件行业经验，换行业（服装、电子）单据字段和逻辑不同，复用性差，天花板低。

**最可能的3个原因（从高到低）：**
1. 分发渠道错配——目标用户根本不在 GitHub/开源生态里，项目对他们几乎不可见
2. 责任兜底缺失——单证出错代价大，免费个人工具没人敢担责，只能停留在"自己玩玩"
3. 安装门槛与用户技术水平不匹配——git/pip/Claude Code 这套流程对非技术外贸业务员比原问题本身还难

---

## 综合结论（供交叉验证参考）

三个视角收敛到同一判断：**代码/Skill 层面是"够用但有几处执行漏洞"（护栏思路对，但缺强制机制），真正决定项目能否被认可的变量不在代码质量，而在于能否触达真实目标用户、以及用户是否愿意把有法律效力的单据工作交给没有责任主体的免费工具——这是产品和渠道问题，加测试解决不了。**

请你独立判断：
- 上述问题是否成立？是否有过度推断或站不住脚的地方？
- 是否有遗漏的、更严重的风险点？
- 三个"最严重"排序是否合理，还是应该调整？
