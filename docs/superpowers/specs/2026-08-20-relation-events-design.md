# 关系事件流（时变图谱）设计

日期：2026-08-20
状态：已批准（用户确认四节设计 + 实现方案 A）

## 背景与目标

当前 `relations` 表一条边一个确定性 id（`md5(from|to|type)[:12]`），`INSERT OR IGNORE` 去重，
`chapter` 只记首次出现——纯静态快照，关系随剧情的演变全部丢失。势力间关系尤其复杂
（结盟/附庸/联姻/敌对/贸易…且随剧情变化），单一「敌对」类型无法表达。

用户确认的四个决策：
1. 用途（全选）：图谱边演变摘要、任意章节时点查询、关系演变时间线、分析报告体现
2. 范围：**全部关系类型**统一记事件（人物"关系"同样有时变需求）
3. 势力关系性质粒度：**泛化「势力关系」类型 + attrs 存性质**（与人物「关系」模式一致）
4. 实现：**方案 A 双表**——relations 保持当前态 + relation_events 事件流

## 第 1 节 数据模型

### schema（config/novels/xuanjian.yaml）
- 删 relation_type「敌对」
- 加「势力关系」：势力→势力，description 要求性质写 attrs（结盟/附庸/联姻/敌对/贸易/雇佣…，
  规范短词），并明确"关系随剧情变化时也要抽取当前最新状态"
- 人物「关系」不变（已是泛化+attrs）

### 新表（store.py SCHEMA）
```sql
CREATE TABLE IF NOT EXISTS relation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rid TEXT,            -- 对应 relations 确定性 id
    from_id TEXT, to_id TEXT, type TEXT,
    attrs_json TEXT, chapter INTEGER, evidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_rel_events_pair ON relation_events(from_id, to_id, id);
```

`relations` 表结构不变，语义升级为**最新状态**（chapter = 最近一次变化章）。
现有图谱/报告代码零改动兼容。

## 第 2 节 抽取与变化检测（resolve.py）

resolve 的关系写入路径改造为三态（查 `latest_relation_event` 后决定；store 的
`upsert_relation` 保持纯写入职责不变）：

1. 实体对 `(from_id, to_id)` 无历史事件 → `record_relation_event` + upsert relations
2. 最新事件的 `(type, 规范化 attrs)` 与本章相同 → 完全跳过
   （LLM 每章重复抽的持续关系不产生任何行——防事件爆炸的关键）
3. 不同 → 追加新事件 + 刷新 relations 行（attrs/chapter/evidence）

- attrs 规范化：`json.dumps(attrs, sort_keys=True, ensure_ascii=False)` 字符串比较
- 方向语义不变：A→B 与 B→A 是不同边

## 第 3 节 查询与展示

### store.py 新增方法
- `record_relation_event(rid, from_id, to_id, type, attrs_json, chapter, evidence)`
- `latest_relation_event(from_id, to_id) -> Row | None`（按 id 倒序第一条）
- `relations_as_of(chapter) -> list[dict]`：每对取 `chapter<=X` 的最新事件（时间旅行查询）
- `relation_history(from_id, to_id) -> list[dict]`（时间线）

### viz_app.py
- 侧栏「截至章节」滑块：默认最新；拖到 X 章时边数据改用 `relations_as_of(X)`
- 边悬停 title：当前 attrs + 演变摘要（"39章:附庸 → 63章:脱离附庸"格式，取自事件流）
- 新增「关系演变」面板：两个实体下拉 → st.dataframe 列全部事件（章/性质/证据）
- 顺带：type_colors 补 功法/术法 颜色（仙基四拆遗留）

### report.py
势力关系单独成节：每对按时间列演变事件。

## 第 4 节 存量迁移（零 LLM 成本）

1. `scripts/migrate_relation_events.py`（幂等，--dry-run 支持同前两个脚本）：
   - 15 条「敌对」→ type 改「势力关系」+ attrs 补 `{"性质":"敌对"}` + 确定性 id 重算
   - raw_json 同步（否则重放按旧 type 污染）
2. 重放 75 章：`cli --limit 75`（extraction 已缓存，pipeline 第 3 步重放 resolve 走新变化检测，
   自动生成全部历史事件）
3. 验证：
   - 事件数 / 关系数比例（预期 ≤ 2x；过高说明 attrs 措辞漂移产生假事件，需收紧比较规则）
   - 抽查一对有剧情变化的势力的时间线正确性
   - 重放幂等：再跑一次 cli 实体/关系/事件数不变

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM attrs 措辞微漂（"结盟"vs"结为盟友"）产生假事件 | prompt 约束规范短词；事件带 evidence 可人工辨别；第一版接受少量噪声 |
| 重放假事件过多 | 先跑看比例，>3x 再收紧（如只比较关键 attrs 键） |
| 泛化类型后按性质筛选要靠 attrs 查询 | viz「关系演变」面板 + report 分节弥补；不做 attrs 索引（YAGNI） |

## 不做（YAGNI）

- 关系消失（解除）的显式建模：靠事件流性质变化表达（"脱离附庸"是事件不是边删除）
- attrs 语义相似度比较（embedding 等）
- 每章全图快照
