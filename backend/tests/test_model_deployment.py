"""模型注册与部署预检的接口级用例：用 MODE-0001 ~ MODE-0003 核对部署结果。

运行：cd backend && .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app
from app.services.model import reset_state

OWNER_1 = {"X-Operator": quote("赵启明"), "X-Role": quote("模型负责人")}
OWNER_3 = {"X-Operator": quote("林知远"), "X-Role": quote("模型负责人")}
CATALOG_MEMBER = {"X-Operator": quote("钱多多"), "X-Role": quote("数据目录成员")}
VIEWER = {"X-Operator": quote("访客"), "X-Role": quote("普通查看者")}


class ModelDeploymentTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_state()
        self.client = TestClient(app)

    def helper(self, model_code: str):
        items = self.client.get(f"/api/model?keyword={model_code}", headers=OWNER_1).json()["items"]
        return {row["模型版本"]: row for row in items}

    def test_precheck_three_conclusions(self) -> None:
        ok = self.client.get("/api/model/1/precheck").json()
        self.assertEqual(ok["结论"], "可部署")
        self.assertEqual(ok["训练数据"]["数据集编号"], "DS-CUSTOMER-001")

        gap = self.client.get("/api/model/3/precheck").json()
        self.assertEqual(gap["结论"], "需补充证据")
        self.assertIn("RMSE", "；".join(gap["缺失证据"]))

        rejected = self.client.get("/api/model/6/precheck").json()
        self.assertEqual(rejected["结论"], "拒绝部署")
        self.assertTrue(any("轮廓系数" in reason for reason in rejected["拒绝原因"]))

    def test_registry_and_catalog_share_field_manifest(self) -> None:
        registry = self.client.get("/api/model/registry").json()
        models = {item["模型编号"]: item for item in registry["items"]}
        # MODE-0001 与 MODE-0003 分别引用两份训练数据，字段清单来自共用定义。
        self.assertEqual(
            [field["字段名"] for field in models["MODE-0001"]["训练数据"]["字段清单"]],
            ["客户ID", "年龄", "在网时长", "月消费", "投诉次数", "是否流失"],
        )
        manifests = self.client.get("/api/catalog/field-manifests").json()["items"]
        shared = {item["数据集编号"]: [f["字段名"] for f in item["字段清单"]] for item in manifests}
        for model in models.values():
            code = model["训练数据"]["数据集编号"]
            self.assertEqual(
                [field["字段名"] for field in model["训练数据"]["字段清单"]],
                shared[code],
            )
        catalog_entry = self.client.get("/api/catalog/1", headers=VIEWER).json()
        self.assertEqual(
            [field["字段名"] for field in catalog_entry["字段清单"]],
            shared["DS-CUSTOMER-001"],
        )

    def test_duplicate_registration_keeps_single_record(self) -> None:
        before = self.client.get("/api/model?keyword=MODE-0001", headers=OWNER_1).json()["total"]
        response = self.client.post("/api/model", headers=OWNER_1, json={"values": {
            "模型编号": "MODE-0001", "模型名称": "客户流失预警模型", "模型类型": "分类",
            "训练数据": "DS-CUSTOMER-001", "评估指标": "AUC=0.95;准确率=0.94", "模型版本": "v1.1.0",
        }})
        self.assertEqual(response.status_code, 200)
        self.assertIn("未新增副本", response.json()["message"])
        after = self.client.get("/api/model?keyword=MODE-0001", headers=OWNER_1).json()["total"]
        self.assertEqual(before, after)
        self.assertEqual(self.helper("MODE-0001")["v1.1.0"]["评估指标"], "AUC=0.95;准确率=0.94")

    def test_only_owner_can_deploy_and_versions_stay_single_active(self) -> None:
        denied = [
            self.client.post("/api/model/1/actions", headers=CATALOG_MEMBER, json={"values": {"action": "部署模型"}}),
            self.client.post("/api/model/1/actions", headers=VIEWER, json={"values": {"action": "部署模型"}}),
            self.client.post("/api/model/1/actions", headers=OWNER_3, json={"values": {"action": "部署模型"}}),
        ]
        self.assertEqual([response.status_code for response in denied], [403, 403, 403])

        for entry_id in (1, 2):
            response = self.client.post(
                f"/api/model/{entry_id}/actions", headers=OWNER_1, json={"values": {"action": "部署模型"}},
            )
            self.assertTrue(response.json()["ok"], response.json()["message"])

        versions = self.helper("MODE-0001")
        active = [version for version, row in versions.items() if row["是否生效"]]
        self.assertEqual(active, ["v1.1.0"])
        self.assertEqual(versions["v1.0.0"]["status"], "已下线")

    def test_concurrent_deploy_only_one_version_active(self) -> None:
        for version, score in (("v9.1.0", 0.60), ("v9.2.0", 0.62)):
            self.client.post("/api/model", headers=OWNER_3, json={"values": {
                "模型编号": "MODE-0003", "模型名称": "授信风险分群模型", "模型类型": "聚类",
                "训练数据": "DS-RISK-003", "评估指标": f"轮廓系数={score}",
                "模型版本": version, "部署路径": f"/models/mode-0003/{version}", "模型状态": "训练完成",
            }})

        def deploy(version: str) -> bool:
            row = self.helper("MODE-0003")[version]
            response = self.client.post(
                f"/api/model/{row['id']}/actions", headers=OWNER_3, json={"values": {"action": "部署模型"}},
            )
            return bool(response.json()["ok"])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(deploy, ["v9.1.0", "v9.2.0"]))
        self.assertTrue(all(results))
        rows = self.helper("MODE-0003")
        self.assertEqual(sum(1 for row in rows.values() if row["是否生效"]), 1)

    def test_failed_deploy_rolls_back_to_previous_metric_snapshot(self) -> None:
        self.client.post("/api/model/2/actions", headers=OWNER_1, json={"values": {"action": "部署模型"}})
        registration = self.client.post("/api/model", headers=OWNER_1, json={"values": {
            "模型编号": "MODE-0001", "模型名称": "客户流失预警模型", "模型类型": "分类",
            "训练数据": "DS-CUSTOMER-001", "评估指标": "AUC=0.99;准确率=0.99",
            "模型版本": "v1.9.0", "部署路径": "/models/mode-0001/v1.1.0", "模型状态": "训练完成",
        }}).json()
        entry_id = registration["entry"]["id"]

        response = self.client.post(
            f"/api/model/{entry_id}/actions", headers=OWNER_1, json={"values": {"action": "部署模型"}},
        )
        self.assertFalse(response.json()["ok"])
        failed = self.client.get(f"/api/model/{entry_id}", headers=OWNER_1).json()
        self.assertEqual(failed["评估指标"], "AUC=0.934;准确率=0.921")
        self.assertFalse(failed["是否生效"])
        self.assertTrue(self.helper("MODE-0001")["v1.1.0"]["是否生效"])

    def test_transfer_owner_keeps_history_and_rereads_per_owner(self) -> None:
        for entry_id in (1, 2):
            self.client.post(
                f"/api/model/{entry_id}/actions", headers=OWNER_1, json={"values": {"action": "部署模型"}},
            )
        transfer = self.client.post("/api/model/1/actions", headers=OWNER_1, json={
            "values": {"action": "变更归属", "负责人": "林知远"},
        })
        self.assertEqual(transfer.status_code, 200)
        self.assertIn("历史发布仍按原责任人留档", transfer.json()["message"])

        self.assertEqual(self.client.get("/api/model/1", headers=OWNER_1).json()["可执行动作"], [])
        self.assertIn("变更归属", self.client.get("/api/model/1", headers=OWNER_3).json()["可执行动作"])

        history = self.client.get("/api/model/deployments?model_code=MODE-0001", headers=OWNER_3).json()["items"]
        self.assertTrue(all(item["归属负责人"] == "赵启明" for item in history))
        self.assertTrue(all(item["执行人"] == "赵启明" for item in history))

    def test_viewer_reads_readonly_registry(self) -> None:
        page = self.client.get("/api/model", headers=VIEWER).json()
        self.assertEqual(page["total"], 6)
        self.assertTrue(all(item["readonly"] for item in page["items"]))
        self.assertIn("只读注册信息", page["items"][0]["只读说明"])
        export = self.client.get("/api/model/export", headers=VIEWER).json()
        self.assertEqual(export["total"], 6)


if __name__ == "__main__":
    unittest.main()
