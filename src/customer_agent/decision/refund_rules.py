from typing import Any, Literal

from pydantic import BaseModel


class RefundDecision(BaseModel):
    eligibility: Literal["eligible", "ineligible", "unknown"]
    matched_rule_id: str
    action: Literal["request_refund", "draft_for_human", "explain_policy", "handoff"]
    reason: str
    policy_version: str = "policy_v1.0"


def decide_refund(order: dict[str, Any], logistics: dict[str, Any], after_sales: dict[str, Any]) -> RefundDecision:
    if order.get("payment_status") != "paid":
        return RefundDecision(eligibility="ineligible", matched_rule_id="RULE-NOT-PAID", action="explain_policy", reason="订单尚未产生可退款支付")
    if after_sales.get("has_active_case") or after_sales.get("duplicate_request"):
        return RefundDecision(eligibility="unknown", matched_rule_id="RULE-INSUFFICIENT-FACTS", action="handoff", reason="存在进行中的售后或重复申请")
    if order.get("special_type"):
        return RefundDecision(eligibility="unknown", matched_rule_id="RULE-SPECIAL-GOODS", action="handoff", reason="商品属于政策特殊例外，需要人工核对商品属性和适用政策")
    if order.get("order_status") == "unshipped":
        return RefundDecision(eligibility="eligible", matched_rule_id="RULE-UNSHIPPED-PAID", action="request_refund", reason="已支付、未发货、普通商品且无进行中售后单")
    if order.get("order_status") == "shipped" and not logistics.get("signed") and logistics.get("logistics_status") == "in_transit":
        return RefundDecision(eligibility="eligible", matched_rule_id="RULE-SHIPPED-NOT-RECEIVED", action="draft_for_human", reason="已支付、已发货未签收且物流状态正常")
    return RefundDecision(eligibility="unknown", matched_rule_id="RULE-INSUFFICIENT-FACTS", action="handoff", reason="订单事实不满足当前自动判断范围")
