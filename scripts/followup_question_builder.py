"""Build follow-up messages for unresolved or ambiguous stock candidates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

try:
    from .stock_name_resolver import StockCandidate
except ImportError:
    from stock_name_resolver import StockCandidate


class FollowupQuestionBuilder:
    def build(
        self,
        candidates: Sequence[StockCandidate],
        original_input: str | None = None,
    ) -> str:
        candidate_list = list(candidates)

        if not candidate_list:
            return self._build_not_found_message(original_input)
        if len(candidate_list) == 1:
            return self._build_confirmed_message(candidate_list[0])
        return self._build_multiple_candidates_message(candidate_list, original_input)

    def _build_not_found_message(self, original_input: str | None) -> str:
        target = f"「{original_input}」に該当する銘柄を" if original_input else "該当する銘柄を"
        return (
            f"{target}銘柄マスタから特定できませんでした。\n\n"
            "銘柄コード、または正式な会社名を教えてください。"
        )

    def _build_confirmed_message(self, candidate: StockCandidate) -> str:
        return (
            "分析対象の銘柄を特定しました。\n\n"
            f"{self._build_candidate_details(candidate)}\n\n"
            "この銘柄を対象に分析へ進めます。"
        )

    def _build_multiple_candidates_message(
        self,
        candidates: list[StockCandidate],
        original_input: str | None,
    ) -> str:
        header = (
            f"「{original_input}」に該当する候補が複数見つかりました。"
            if original_input
            else "該当する候補が複数見つかりました。"
        )
        lines = [
            f"{index}. {self._build_candidate_details(candidate)}"
            for index, candidate in enumerate(candidates, start=1)
        ]
        return (
            f"{header}\n"
            "分析する銘柄を番号、または銘柄コードで指定してください。\n\n"
            + "\n".join(lines)
        )

    def _build_candidate_details(self, candidate: StockCandidate) -> str:
        details = f"{candidate.stock_name}（{candidate.stock_code}）"
        extras = [value for value in [candidate.market, candidate.sector] if value]
        if extras:
            details += f" [{' / '.join(extras)}]"
        return details


INTENT_LABELS = {
    "Intent001": "条件に合う銘柄を探す",
    "Intent002": "値上がり期待の銘柄を探す",
    "Intent003": "配当を重視して銘柄を探す",
    "Intent004": "株主優待を重視して銘柄を探す",
    "Intent005": "安定性を重視して銘柄を探す",
    "Intent007": "業界全体を確認する",
    "Intent008": "現在の株価・財務状況を分析する",
    "Intent009": "複数銘柄を比較する",
    "Intent010": "購入・売却判断の材料を確認する",
    "Intent011": "ポートフォリオを考える",
    "latest_news": "最新ニュースを確認する",
    "price_forecast": "今後の値動き予測を確認する",
}


MISSING_FIELD_LABELS = {
    "投資目的": "どの条件を重視して銘柄を探しますか？\n\n1. 値上がり期待\n2. 配当\n3. 株主優待\n4. 安定性\n5. 成長性",
    "銘柄": "分析したい銘柄コード、または正式な会社名を教えてください。",
    "比較対象銘柄": "比較したい銘柄を2つ以上、銘柄コードまたは会社名で教えてください。",
    "業界": "確認したい業界名を教えてください。",
    "予算": "想定している投資予算を教えてください。",
}


def _intent_label(intent: str | None) -> str:
    if not intent:
        return "内容を確認する"
    intent_id = intent.split()[0]
    return INTENT_LABELS.get(intent_id, INTENT_LABELS.get(intent, intent))


def build_for_ambiguous_intent(
    original_input: str,
    intent_candidates: Sequence[str],
) -> str:
    labels = [_intent_label(candidate) for candidate in intent_candidates]
    if not labels:
        labels = [
            "現在の株価・財務状況",
            "今後の値動き予測",
            "購入判断の材料",
            "最新ニュース",
        ]
    choices = "\n".join(f"{index}. {label}" for index, label in enumerate(labels, start=1))
    return f"「{original_input}」について、どの内容を確認しますか？\n\n{choices}"


def build_for_missing_information(
    original_input: str,
    intent: str | None,
    missing_fields: Sequence[str],
    known_entities: dict[str, Any] | None = None,
) -> str:
    del known_entities
    for field in missing_fields:
        if field in MISSING_FIELD_LABELS:
            return MISSING_FIELD_LABELS[field]

    target = _intent_label(intent)
    if missing_fields:
        fields = "、".join(missing_fields)
        return f"{target}ために、{fields}を教えてください。"
    return f"「{original_input}」について、もう少し具体的に教えてください。"


def build_for_multiple_stock_candidates(
    candidates: Sequence[StockCandidate],
    original_input: str | None = None,
) -> str:
    return FollowupQuestionBuilder().build(candidates, original_input=original_input)


def build_for_unknown_stock(original_input: str | None = None) -> str:
    return FollowupQuestionBuilder().build([], original_input=original_input)


def build_for_unsupported_request(original_input: str) -> str:
    return (
        "現在の分析フローでは、その依頼には対応していません。\n\n"
        "現在対応している主な処理は、銘柄分析、銘柄比較、候補銘柄検索、"
        "配当・成長性などの条件検索です。\n"
        f"別の形で依頼する場合は、対象の銘柄や重視したい条件を教えてください。"
    )


def build_for_reclassification(original_input: str) -> str:
    return (
        f"「{original_input}」の目的を特定できませんでした。\n"
        "銘柄分析、銘柄比較、条件検索のどれをしたいか教えてください。"
    )


def build_safe_error_response(error_code: str | None = None) -> str:
    suffix = f"（参照コード: {error_code}）" if error_code else ""
    return (
        "処理中にシステム側の問題が発生しました。"
        "入力内容の曖昧さではないため、詳細をログに記録しました。"
        f"{suffix}"
    )
