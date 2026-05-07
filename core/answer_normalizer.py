"""
题库答案归一化器

将题库原始答案文本映射为 clicker 可用的格式（选项字母）。

支持 5 种题库答案格式：
  1. 字母前缀: "D: 沿门框墙全高布置" / "A：平整场地" / "D、1.6lae"
  2. 纯字母: "A" / "B"
  3. 纯文本: "下浮7%" / "材料员"
  4. 多选分隔: "A|答案分隔|B" 或 "文本1|答案分隔|文本2"
  5. 判断: "正确" / "错误"

移植自 exam_auto.py，适配 GUI 引擎的 options 格式。
"""

import difflib
import logging
import re

logger = logging.getLogger(__name__)


def normalize_bank_answer(answer_text: str, options: list, question_type: str) -> str:
    """将题库原始答案归一化为 clicker 可用的格式。

    Parameters
    ----------
    answer_text : str
        题库返回的原始答案文本。
    options : list
        选项列表，每项为 dict，至少包含 'text' 字段。
        元素模式下还包含 'element_ref' 和 'index'。
    question_type : str
        题目类型：'single'|'multi'|'judge'|'fill'|'essay'

    Returns
    -------
    str
        归一化后的答案：
        - 单选题 → 单个字母 "D"
        - 多选题 → "A|答案分隔|B"
        - 判断题 → "正确" 或 "错误"
        - 填空/简答 → 原始文本
    """
    if not answer_text or not answer_text.strip():
        return answer_text

    is_judge = question_type == "judge"
    is_multi = question_type == "multi"

    # 填空/简答：原样返回
    if question_type in ("fill", "essay"):
        return answer_text.strip()

    # 无选项时只能做纯字母提取
    if not options:
        return _extract_letter_only(answer_text) or answer_text.strip()

    letters = match_answer_to_letters(answer_text, options, is_multi, is_judge)
    if not letters:
        # 归一化失败，尝试纯字母提取
        fallback = _extract_letter_only(answer_text)
        return fallback or answer_text.strip()

    if is_multi:
        return "|答案分隔|".join(letters)
    return letters[0] if letters else answer_text.strip()


def match_answer_to_letters(answer_text: str, options: list,
                            is_multi: bool, is_judge: bool) -> list[str]:
    """将题库的答案文本映射到页面选项的字母。

    Parameters
    ----------
    answer_text : str
        题库原始答案文本。
    options : list
        选项列表，每项为 dict，包含 'text' 字段。
    is_multi : bool
        是否为多选题。
    is_judge : bool
        是否为判断题。

    Returns
    -------
    list[str]
        匹配到的选项字母列表，如 ["A", "C"]。
    """
    valid_letters = _get_valid_letters(options)
    answer_text = answer_text.strip()

    # 判断题
    if is_judge:
        if any(w in answer_text for w in ("正确", "True", "true", "√", "对")):
            target = "正确"
        elif any(w in answer_text for w in ("错误", "False", "false", "×", "错")):
            target = "错误"
        else:
            target = answer_text
        for opt in options:
            opt_text = opt.get("text", "") if isinstance(opt, dict) else ""
            if target in opt_text or opt_text in target:
                letter = opt.get("letter", "") if isinstance(opt, dict) else ""
                if letter:
                    return [letter]
        return []

    # 多选题：拆分 |答案分隔|
    if is_multi and "答案分隔" in answer_text:
        parts = [p.strip() for p in answer_text.split("答案分隔") if p.strip()]
        letters = []
        for part in parts:
            sub_parts = _split_delimited_text(part)
            for sp in sub_parts:
                letter = _extract_letter_from_answer(sp, options, valid_letters)
                if letter:
                    letters.append(letter)
        seen = set()
        return [l for l in letters if l in valid_letters and not (l in seen or seen.add(l))]

    # 单选题 / 非答案分隔的多选题
    # 先检查是否含顿号拼接（可能是多选答案但没用答案分隔格式）
    if is_multi and ("、" in answer_text or "，" in answer_text):
        sub_parts = _split_delimited_text(answer_text)
        if len(sub_parts) >= 2:
            letters = []
            for sp in sub_parts:
                letter = _extract_letter_from_answer(sp, options, valid_letters)
                if letter:
                    letters.append(letter)
            if letters:
                seen = set()
                return [l for l in letters if l in valid_letters and not (l in seen or seen.add(l))]

    letter = _extract_letter_from_answer(answer_text, options, valid_letters)
    if letter:
        return [letter]

    return []


def _get_valid_letters(options: list) -> set[str]:
    """从选项列表获取有效字母集合。

    优先使用 option['letter']（元素模式），否则按索引生成（A=0, B=1...）。
    """
    letters = set()
    for i, opt in enumerate(options):
        if isinstance(opt, dict) and opt.get("letter"):
            letters.add(opt["letter"])
        else:
            letters.add(chr(ord("A") + i))
    return letters


def _extract_letter_from_answer(answer: str, options: list,
                                valid_letters: set[str]) -> str | None:
    """从单个答案文本中提取选项字母。

    优先级：字母前缀 > 纯字母 > 文本匹配选项。
    """
    answer = answer.strip()
    if not answer:
        return None

    # 1. 字母前缀: "D: xxx" / "A：xxx" / "D、xxx" / "D.xxx" / "D xxx"
    m = re.match(r'^([A-Z])\s*[.:：、；;\s]', answer)
    if m and m.group(1) in valid_letters:
        return m.group(1)

    # 2. 纯字母: "A" / "B"
    if re.match(r'^[A-Z]$', answer) and answer in valid_letters:
        return answer

    # 3. 文本匹配选项
    norm_ans = _norm(answer)
    if not norm_ans:
        return None

    scored = []
    for i, opt in enumerate(options):
        opt_text = opt.get("text", "") if isinstance(opt, dict) else str(opt)
        norm_opt = _norm(opt_text)
        if not norm_opt:
            continue
        s = difflib.SequenceMatcher(None, norm_ans, norm_opt).ratio()
        if norm_ans in norm_opt or norm_opt in norm_ans:
            s = max(s, 0.95)
        letter = opt.get("letter", chr(ord("A") + i)) if isinstance(opt, dict) else chr(ord("A") + i)
        scored.append((letter, s))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[1])
    # 最佳选项明显高于次佳时才采用
    if len(scored) >= 2:
        gap = scored[0][1] - scored[1][1]
        if scored[0][1] >= 0.5 and gap >= 0.15:
            return scored[0][0]
    elif scored[0][1] >= 0.5:
        return scored[0][0]

    return None


def _split_delimited_text(text: str) -> list[str]:
    """拆分顿号/逗号分隔的文本为子项。

    例: "结构类型、檐高、建筑面积" → ["结构类型", "檐高", "建筑面积"]
    只有当子项数量 >= 2 且每个子项不太长时才拆分（避免误拆长句）。
    """
    for sep in ("、", "，", ","):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 2 and all(len(p) <= 20 for p in parts):
                return parts
    return [text]


def _extract_letter_only(answer_text: str) -> str | None:
    """无选项时的纯字母提取。

    仅处理字母前缀格式（如 "D: xxx" → "D"），不进行文本匹配。
    """
    answer_text = answer_text.strip()
    m = re.match(r'^([A-Z])\s*[.:：、；;\s]', answer_text)
    if m:
        return m.group(1)
    if re.match(r'^[A-Z]$', answer_text):
        return answer_text
    return None


def _norm(s: str) -> str:
    """归一化文本用于比较：去空白、标点、括号。"""
    return re.sub(r'[\s　,，。、；：""''（）()\[\]【】\-—_]', '', s).lower()
