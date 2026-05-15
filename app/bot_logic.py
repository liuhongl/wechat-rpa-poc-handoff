from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


@dataclass(frozen=True)
class BotReply:
    content: str
    matched_question: str | None = None
    score: float = 0.0
    handoff: bool = False


FAQS: dict[str, str] = {
    "需要经营证明吗": "是否需要经营证明取决于具体产品和客户身份。经营类贷款通常可能需要营业执照、流水、经营场地或收入证明等材料，最终以产品要求和审核结果为准。",
    "申请贷款需要哪些资料": "通常需要身份证、实名手机号、银行卡、收入或经营证明。具体资料以产品和风控要求为准。",
    "多久可以放款": "资料齐全并审核通过后才会进入放款流程，具体时间以审核结果和资金方处理为准，不能提前承诺一定放款。",
    "贷款利率是多少": "利率会根据客户资质、产品类型和审批结果确定。请以正式合同或平台展示为准。",
    "可以提前还款吗": "多数产品支持提前还款，但是否有手续费、违约金或利息计算差异，需要以合同条款为准。",
    "逾期会有什么影响": "逾期可能产生罚息、影响信用记录，并影响后续金融服务申请。建议尽快联系工作人员处理。",
    "还款日是哪天": "还款日以账单或合同约定为准。如果你不确定，我可以提醒工作人员帮你核实。",
    "怎么还款": "一般可通过绑定银行卡自动扣款或指定还款入口操作。具体方式以工作人员提供的正式渠道为准。",
    "额度能提高吗": "额度由系统和资金方综合评估，不能人工保证提额。可补充真实有效资料后再评估。",
    "审核没通过怎么办": "审核未通过通常与资质、资料完整度或风控规则有关。可以请工作人员查看是否支持补充资料或更换方案。",
    "是否会上征信": "是否上征信取决于具体产品和资金方，请以合同、授权书和工作人员说明为准。",
}


conversation_memory: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=8))


def _normalize(text: str) -> str:
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _score(user_text: str, question: str) -> float:
    a = _normalize(user_text)
    b = _normalize(question)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    overlap = len(set(a) & set(b)) / max(len(set(b)), 1)
    return ratio * 0.65 + overlap * 0.35


def remember(callback: dict[str, Any]) -> str:
    chat_id = callback.get("chatid") or callback.get("from", {}).get("userid") or "unknown"
    content = extract_text(callback)
    if content:
        conversation_memory[chat_id].append(content)
    return chat_id


def extract_text(callback: dict[str, Any]) -> str:
    msgtype = callback.get("msgtype")
    if msgtype == "text":
        return callback.get("text", {}).get("content", "")
    if msgtype == "mixed":
        items = callback.get("mixed", {}).get("msg_item", [])
        return "\n".join(
            item.get("text", {}).get("content", "")
            for item in items
            if item.get("msgtype") == "text"
        )
    return ""


def answer(callback: dict[str, Any], human_userid: str = "") -> BotReply:
    text = extract_text(callback)
    chat_id = remember(callback)

    best_question = None
    best_score = 0.0
    for question in FAQS:
        score = _score(text, question)
        if score > best_score:
            best_question = question
            best_score = score

    if best_question and best_score >= 0.48:
        return BotReply(
            content=FAQS[best_question],
            matched_question=best_question,
            score=best_score,
        )

    memory_hint = ""
    if conversation_memory[chat_id]:
        memory_hint = "\n\n最近上下文：" + " / ".join(conversation_memory[chat_id])

    mention = f" <@{human_userid}>" if human_userid else ""
    return BotReply(
        content=(
            f"这个问题我暂时不能准确回答，已转人工处理。{mention}"
            f"\n\n工作人员请协助确认客户问题：{text or '未识别到文本内容'}"
            f"{memory_hint}"
        ),
        matched_question=None,
        score=best_score,
        handoff=True,
    )
