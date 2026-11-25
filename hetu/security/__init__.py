"""Hetu 安全模块（嵌入式）—— 依据 ARTEX-KO-PLUS 评估裁定的机制吸收 + fail-open 反例否决。

三件套:
  posture  全局安全态势(ACTIVE/FROZEN), 演化与高风险的总闸, 读失败=FROZEN(fail-closed)
  policy   动作策略门, 无规则/求值异常/审计不可写 一律 DENY(fail-closed)
  verifier 主张核验器(证据优先), 引证不实=REJECTED, 数据不足=INCONCLUSIVE, 永不因错误给 VERIFIED

否决清单(ARTEX guard/intercept 的 fail-open 反例, 本模块逐条反做):
  拦截器为 nil 直接放行        -> 无策略对象时由调用方显式声明, 策略存在而求值失败=DENY
  工具未启用拦截直接放行        -> 无匹配规则=DENY
  规则未匹配且审批器未启用放行  -> 无匹配规则=DENY
  LLM 判断失败默认 allow       -> 本模块零 LLM 依赖; 任何内部异常=保守态
"""
from .policy import ALLOW, DENY, REQUIRE_APPROVAL, ActionPolicy, Decision
from .posture import ACTIVE, FROZEN, SecurityPosture
from .verifier import INCONCLUSIVE, REJECTED, VERIFIED, ClaimVerifier

__all__ = [
    "ACTIVE", "FROZEN", "SecurityPosture",
    "ALLOW", "DENY", "REQUIRE_APPROVAL", "ActionPolicy", "Decision",
    "VERIFIED", "REJECTED", "INCONCLUSIVE", "ClaimVerifier",
]
