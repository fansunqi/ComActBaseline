# ComAct 本地 SolidWorks 测试记录

## 贯穿孔薄板

- 测试时间：2026-07-22
- 模型：`Qwen3.5-397B-A17B`
- 流程：ComAct `PromptAgent` + 原仓库 SolidWorks few-shot + 本地 COM 执行环境
- 配置：最多 6 轮，`temperature=0.2`，`top_p=0.9`，无 RAG
- 测例来源：`SolidWorksTutorial/LLMPlanner/web/static/prompt-catalog.js`
- 原始 Prompt：`创建 80×60×10mm 的薄板，并在板中心加工直径 6mm 的贯穿孔。`

### 执行过程

ComAct 共运行 4 轮：

1. 生成 `FeatureExtrusionCut3` 调用，但 SolidWorks 2025 COM 接口不存在该方法。
2. 根据终端错误改用 `FeatureExtrusionCut`，该方法同样不存在。
3. 改用凸台 API `FeatureExtrusion3`。脚本没有抛出异常，但没有创建切除特征。
4. Agent 仅根据无异常的终端输出判断任务完成，返回 `DONE`。

### 实际几何验证

| 检查项 | 预期 | 实际 |
| --- | --- | --- |
| 包围盒 | 80×60×10 mm | 80×60×10 mm |
| 实体数量 | 1 | 1 |
| 中心孔 | ⌀6 mm 贯穿孔 | 未创建 |
| 面数 | 7 | 6 |
| 体积 | 约 47,717.3 mm³ | 48,000.0 mm³ |
| 特征树 | 凸台、草图、切除 | 凸台、第二草图，无切除 |
| Agent 最终决策 | 成功时 `DONE` | `DONE`（误判） |

### 结论

本次测试失败。ComAct 成功创建了尺寸正确的薄板和中心圆草图，但没有完成贯穿切除。该结果暴露出两个问题：

1. 模型不能准确生成 SolidWorks 2025 的切除拉伸 COM API。
2. 当前流程只依据脚本异常和屏幕反馈判断完成，缺少体积、面数或特征树等几何验收，因此产生了 false positive。

完整运行轨迹保存在本地：

`results/local_baseline/swtutorial_through_hole/20260722@112427/`

## SolidWorksTutorial 五测例批量测试

- 测试时间：2026-07-22
- 模型与配置：同上
- 测例来源：`SolidWorksTutorial/LLMPlanner/web/static/prompt-catalog.js`
- 隔离措施：每个测例完成几何验证后均调用 `CloseAllDocuments(True)` 和 `ExitApp()`，确认 `SLDWORKS` 进程退出后再开始下一项

### 汇总

| 测例 | Agent 轮数 | 最终决策 | 实际结果 |
| --- | ---: | --- | --- |
| 反向拉伸 | 2 | `DONE` | 失败（误判） |
| 旋转圆柱 | 5 | `DONE` | 成功 |
| 全边圆角 | 6 | `CODE` | 失败 |
| 六角螺母 | 4 | `DONE` | 失败（误判） |
| 法兰盘 | 5 | `DONE` | 成功 |

实际成功率为 **2/5（40%）**。Agent 对其中 4 项返回 `DONE`，但只有 2 项通过几何验证。

### 1. 反向拉伸

- Prompt：`在上视基准面创建 50×50mm 方形轮廓，向基准面负法向拉伸 30mm。`
- Agent：第 1 轮生成脚本，第 2 轮因脚本无异常而返回 `DONE`
- 实际：只创建了 50×50mm 草图，没有实体和拉伸特征
- 验证：实体数 0；特征树只有 `Sketch1`
- 结论：失败，`FeatureExtrusion3` 没有创建特征但也没有抛出异常，导致 false positive
- 轨迹：`results/local_baseline/swtutorial_reverse_extrusion/20260722@152121/`

### 2. 旋转圆柱

- Prompt：`使用旋转特征创建直径 40mm、高 80mm 的实心圆柱。`
- Agent：共 5 轮；先后出现输出超长导致代码解析失败、`FeatureRevolve2` 参数数量错误和类型不匹配，最终根据类型库签名修正
- 实际：成功创建 1 个旋转实体和 `Revolution` 特征
- 包围盒：40×80×40 mm
- 体积：100,530.965 mm³，与理论值一致
- 结论：成功
- 轨迹：`results/local_baseline/swtutorial_revolve_cylinder/20260722@152225/`

### 3. 全边圆角

- Prompt：`创建 100mm 立方体，并对全部棱边做 R5mm 圆角。`
- Agent：运行满 6 轮，最终仍为 `CODE`
- 实际：100×100×100mm 立方体创建成功，但所有圆角尝试均失败
- 验证：1 个实体、6 个面、12 条边、体积 1,000,000 mm³；特征树只有 `Extrusion`，没有圆角特征
- 主要错误：错误使用 `CreateFillet`、`FeatureFillet5`、`SelectByObject` 和错误参数数量的 `FeatureFillet`
- 结论：失败
- 轨迹：`results/local_baseline/swtutorial_all_edge_fillet/20260722@152702/`

### 4. 六角螺母

- Prompt：`创建对边距 30mm、厚 8mm 的正六角螺母，中心有直径 10mm 的贯穿孔，厚度方向关于原点居中。`
- Agent：共 4 轮，最终返回 `DONE`
- 实际：成功创建六边形草图，但没有创建拉伸实体，也没有中心孔
- 草图包围范围：30×34.641mm；实体数 0；特征树只有 `Sketch1`
- 主要错误：先错误调用 `CreatePolygon`，修正草图后又使用无效的拉伸/切除组合；COM 未抛出异常
- 结论：失败，false positive
- 轨迹：`results/local_baseline/swtutorial_hex_nut/20260722@153107/`

### 5. 法兰盘

- Prompt：`创建直径 100mm、厚 12mm 的圆形法兰，中心贯穿孔直径 30mm，并在节圆直径 80mm 上均布 6 个直径 8mm 的贯穿孔。`
- Agent：共 5 轮；最终将外轮廓、中心孔和 6 个螺栓孔放在同一草图中一次拉伸
- 实际：成功创建完整法兰实体
- 验证：1 个实体、10 个面，包围盒 100×100×12mm
- 体积：82,146.365 mm³，与理论值 `π×(50²-15²-6×4²)×12` 完全一致
- 结论：成功
- 轨迹：`results/local_baseline/swtutorial_flange/20260722@153404/`

### 批量测试结论

1. 草图加单一主特征的任务表现较好：旋转圆柱与单草图多内环法兰均成功。
2. 需要选择已有边或调用圆角、切除等特定 API 时，模型容易生成不存在的方法或错误签名。
3. 多个 SolidWorks COM 特征创建方法在失败时返回空值而不抛出异常；当前 Agent 只检查终端异常，容易把“草图存在但实体不存在”误判为完成。
4. 后续评测应在接受 `DONE` 前检查实体数、包围盒、体积和关键特征类型。
