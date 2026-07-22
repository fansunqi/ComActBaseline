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
