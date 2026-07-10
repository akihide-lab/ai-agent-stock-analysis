"""Route a beginner's natural-language stock question to selection and analysis."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from agent_jobs import finish_job, update_job
from search_stocks import (
    connect_read_only,
    load_candidates,
    natural_language_search,
    summarize_stocks,
)
from stock_name_resolver import StockCandidate, StockNameResolver
from query_flow_models import ClassificationResult
import followup_question_builder
import stock_domain_router


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market_analysis.db"
LOG_DIRECTORY = PROJECT_ROOT / "logs"
ANALYZE_SCRIPT = PROJECT_ROOT / "scripts" / "analyze_stock.py"
logger = logging.getLogger(__name__)

BUY_SELL_WORDS = ("買い", "買う", "購入", "売り", "売る", "売却", "保有", "持ち続け")
ANALYZE_WORDS = ("分析", "調べ", "どう", "評価", "レポート")
COMPARE_WORDS = ("比較", "どっち", "どちら")
PORTFOLIO_WORDS = ("ポートフォリオ", "資産配分", "NISA")
INDUSTRY_WORDS = ("業界", "セクター")
DIVIDEND_WORDS = ("配当", "高配当", "利回り")
GROWTH_WORDS = ("成長", "伸び", "上がり", "値上がり", "利益", "稼げ")
STABILITY_WORDS = ("安定", "安全", "長期", "初心者")
BENEFIT_WORDS = ("優待", "株主優待")
SEARCH_WORDS = ("おすすめ", "オススメ", "良さそう", "探し", "検索", "選んで")
UNSUPPORTED_WORDS = (
    "メール",
    "送信",
    "投稿",
    "注文して",
    "発注",
    "自動売買",
    "口座",
    "ログイン",
)
HIGH_CONFIDENCE_THRESHOLD = 0.80
LOW_CONFIDENCE_THRESHOLD = 0.50
AMBIGUOUS_INTENT_CANDIDATES = [
    "Intent008",
    "price_forecast",
    "Intent010",
    "latest_news",
]
KNOWN_INTENTS = {
    "Intent001 おすすめ銘柄検索",
    "Intent002 値上がり期待銘柄検索",
    "Intent003 高配当銘柄検索",
    "Intent004 株主優待銘柄検索",
    "Intent005 安定銘柄検索",
    "Intent007 業界分析",
    "Intent008 単一銘柄分析",
    "Intent009 銘柄比較",
    "Intent010 売買相談",
    "Intent011 ポートフォリオ作成",
}
STOCK_REQUIRED_INTENTS = {
    "Intent008 単一銘柄分析",
    "Intent009 銘柄比較",
    "Intent010 売買相談",
}


@dataclass
class QuestionDecision:
    user_question: str
    primary_intent: str
    secondary_intents: list[str] = field(default_factory=list)
    entities: dict[str, object] = field(default_factory=dict)
    missing_information: dict[str, list[str]] = field(
        default_factory=lambda: {"required": [], "optional": [], "defaulted": []}
    )
    route: str = "select_and_analyze"
    classification_status: str = "classified"
    intent_candidates: list[str] = field(default_factory=list)
    confidence: float | None = None
    error_code: str | None = None
    selected_stock_code: str | None = None
    selected_stock_name: str | None = None
    selection_reasons: list[str] = field(default_factory=list)
    data_freshness: list[dict[str, object]] = field(default_factory=list)
    report_path: str | None = None
    log_path: str | None = None
    message: str = ""
    detected_domain: str | None = None
    detected_intent: str | None = None
    intent_status: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    resolved_stock_candidates: list[dict[str, object]] = field(default_factory=list)
    selected_flow: str | None = None
    early_return: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "初心者の自然言語質問を受け取り、銘柄選定からHTMLレポート生成まで実行します。"
        )
    )
    parser.add_argument("question", help="例: 初心者向けにおすすめの株を選んで")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="候補選定時に表示・記録する件数（既定: 5）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="質問解釈と銘柄選定だけ行い、レポート生成はしません。",
    )
    parser.add_argument(
        "--skip-web-update",
        action="store_true",
        help="Web更新を省略し、既存DBだけでレポートを生成します。",
    )
    parser.add_argument(
        "--skip-finance",
        action="store_true",
        help="Web更新時に財務データ取得を省略します。",
    )
    parser.add_argument(
        "--job-id",
        help="agent_jobs.py から起動された場合のジョブID。",
    )
    return parser.parse_args()


def normalize_text(value: object) -> str:
    return str(value or "").replace("　", " ").lower()


def contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def normalize_intent_code(intent: str | None) -> str:
    return str(intent or "").split()[0]


def classify_confidence(confidence: float | None) -> str:
    if confidence is None or confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "classified"
    if confidence >= LOW_CONFIDENCE_THRESHOLD:
        return "ambiguous"
    return "insufficient"


def safe_entities_from_candidates(candidates: list[StockCandidate]) -> dict[str, object]:
    if not candidates:
        return {}
    return {
        "銘柄": [
            {
                "stock_code": candidate.stock_code,
                "stock_name": candidate.stock_name,
                "sector": candidate.sector,
                "market": candidate.market,
            }
            for candidate in candidates
        ]
    }


def classify_pre_db(
    user_question: str,
    domain_result: stock_domain_router.DomainClassification | None = None,
) -> ClassificationResult | None:
    normalized = normalize_text(user_question)
    if not normalized.strip():
        return ClassificationResult(
            status="insufficient",
            missing_fields=["依頼内容"],
            confidence=0.0,
        )

    if contains_any(normalized, UNSUPPORTED_WORDS):
        return ClassificationResult(status="unsupported", confidence=0.95)

    has_stock_code = bool(re.search(r"(?<!\d)(\d{4})(?!\d)", user_question))
    has_analysis_word = contains_any(normalized, ANALYZE_WORDS)
    has_decisive_word = contains_any(
        normalized,
        BUY_SELL_WORDS
        + COMPARE_WORDS
        + DIVIDEND_WORDS
        + GROWTH_WORDS
        + STABILITY_WORDS
        + BENEFIT_WORDS
        + INDUSTRY_WORDS
        + PORTFOLIO_WORDS,
    )

    if "どう" in normalized and not has_stock_code and not has_decisive_word:
        return ClassificationResult(
            status="ambiguous",
            intent_candidates=AMBIGUOUS_INTENT_CANDIDATES,
            confidence=0.60,
        )

    if contains_any(normalized, SEARCH_WORDS) and not has_decisive_word:
        return ClassificationResult(
            status="insufficient",
            intent="Intent001 おすすめ銘柄検索",
            missing_fields=["投資目的"],
            confidence=0.70,
        )

    if has_analysis_word or has_decisive_word or has_stock_code:
        return None

    if domain_result is not None and domain_result.is_stock:
        return None

    return ClassificationResult(status="unsupported", confidence=0.40)


def build_followup_decision(
    user_question: str,
    result: ClassificationResult,
    message: str,
    data_freshness: list[dict[str, object]] | None = None,
) -> QuestionDecision:
    missing = {
        "required": list(result.missing_fields),
        "optional": [],
        "defaulted": [],
    }
    return QuestionDecision(
        user_question=user_question,
        primary_intent=result.intent or "",
        secondary_intents=[],
        entities=result.entities,
        missing_information=missing,
        route="followup_required",
        classification_status=result.status,
        intent_candidates=list(result.intent_candidates),
        confidence=result.confidence,
        error_code=result.error_code,
        data_freshness=data_freshness or [],
        message=message,
    )


def write_system_error_log(
    user_input: str,
    exc: Exception,
    request_id: str | None = None,
) -> Path:
    LOG_DIRECTORY.mkdir(exist_ok=True)
    error_code = request_id or f"ERR-{uuid.uuid4().hex[:10]}"
    path = LOG_DIRECTORY / f"question_flow_error_{datetime.now().astimezone():%Y%m%d_%H%M%S_%f}.json"
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "request_id": error_code,
        "user_input": user_input,
        "status": "system_error",
        "intent": None,
        "entities": {},
        "missing_fields": [],
        "error_code": error_code,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "stack_trace": traceback.format_exc(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_stock_master(db_path: Path) -> pd.DataFrame:
    query = """
        SELECT
            stock_code,
            stock_name,
            sector
        FROM v_agent_stock_master
        ORDER BY stock_code
    """
    with connect_read_only(db_path) as connection:
        frame = pd.read_sql_query(query, connection)
    frame["name_norm"] = frame["stock_name"].map(normalize_text)
    return frame[["stock_code", "stock_name", "sector", "name_norm"]]


def load_data_freshness(db_path: Path) -> list[dict[str, object]]:
    query = """
        SELECT
            data_name,
            latest_date,
            record_count
        FROM v_agent_data_freshness
        ORDER BY data_name
    """
    with connect_read_only(db_path) as connection:
        frame = pd.read_sql_query(query, connection)
    return frame.to_dict(orient="records")


def match_stocks(question: str, master: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_text(question)
    code_matches = re.findall(r"(?<!\d)(\d{4})(?!\d)", question)
    if code_matches:
        return master[master["stock_code"].astype(str).isin(code_matches)]

    matches = []
    for _, row in master.iterrows():
        name = row["name_norm"]
        if not name:
            continue
        compact_name = name.replace("株式会社", "").replace("(株)", "")
        if name in normalized or compact_name in normalized:
            matches.append(row)
    return pd.DataFrame(matches, columns=master.columns).drop_duplicates("stock_code")


def infer_intent(question: str, matched_stocks: pd.DataFrame) -> tuple[str, list[str]]:
    normalized = normalize_text(question)
    secondary: list[str] = []

    if contains_any(normalized, PORTFOLIO_WORDS):
        return "Intent011 ポートフォリオ作成", secondary
    if contains_any(normalized, COMPARE_WORDS):
        return "Intent009 銘柄比較", secondary
    if contains_any(normalized, INDUSTRY_WORDS) and matched_stocks.empty:
        return "Intent007 業界分析", secondary
    if not matched_stocks.empty and contains_any(normalized, BUY_SELL_WORDS):
        secondary.append("Intent008 単一銘柄分析")
        return "Intent010 売買相談", secondary
    if not matched_stocks.empty:
        return "Intent008 単一銘柄分析", secondary
    if contains_any(normalized, DIVIDEND_WORDS):
        return "Intent003 高配当銘柄検索", secondary
    if contains_any(normalized, BENEFIT_WORDS):
        return "Intent004 株主優待銘柄検索", secondary
    if contains_any(normalized, STABILITY_WORDS):
        return "Intent005 安定銘柄検索", secondary
    if contains_any(normalized, GROWTH_WORDS):
        return "Intent002 値上がり期待銘柄検索", secondary
    return "Intent001 おすすめ銘柄検索", secondary


def extract_entities(
    question: str,
    primary_intent: str,
    matched_stocks: pd.DataFrame,
    master: pd.DataFrame,
) -> dict[str, object]:
    normalized = normalize_text(question)
    entities: dict[str, object] = {}
    if not matched_stocks.empty:
        entities["銘柄"] = [
            {
                "stock_code": str(row.stock_code),
                "stock_name": row.stock_name,
                "sector": row.sector,
            }
            for row in matched_stocks.itertuples()
        ]

    sectors = [str(value) for value in master["sector"].dropna().unique()]
    matched_sector = next((sector for sector in sectors if sector and sector in question), None)
    if matched_sector:
        entities["業界"] = matched_sector

    if contains_any(normalized, DIVIDEND_WORDS):
        entities["投資目的"] = "配当収入"
    elif contains_any(normalized, BENEFIT_WORDS):
        entities["投資目的"] = "株主優待"
    elif contains_any(normalized, STABILITY_WORDS):
        entities["投資目的"] = "安定性"
    elif contains_any(normalized, GROWTH_WORDS):
        entities["投資目的"] = "値上がり益"
    elif primary_intent == "Intent001 おすすめ銘柄検索":
        entities["投資目的"] = "バランス"

    if "短期" in question:
        entities["投資期間"] = "短期"
    elif "中期" in question:
        entities["投資期間"] = "中期"
    elif "長期" in question:
        entities["投資期間"] = "長期"

    if "初心者" in question or "安全" in question:
        entities["リスク"] = "安全重視"

    return entities


def required_missing(primary_intent: str, entities: dict[str, object]) -> list[str]:
    if primary_intent in {"Intent008 単一銘柄分析", "Intent010 売買相談"}:
        return [] if entities.get("銘柄") else ["銘柄"]
    if primary_intent == "Intent009 銘柄比較":
        stocks = entities.get("銘柄") or []
        return [] if isinstance(stocks, list) and len(stocks) >= 2 else ["比較対象銘柄"]
    if primary_intent == "Intent007 業界分析":
        return [] if entities.get("業界") else ["業界"]
    if primary_intent == "Intent011 ポートフォリオ作成":
        return ["予算"]
    return []


def classify_with_db(
    user_question: str,
    db_path: Path,
    master: pd.DataFrame,
) -> tuple[ClassificationResult, list[StockCandidate], pd.DataFrame]:
    try:
        resolver = StockNameResolver(db_path)
        stock_candidates = resolver.resolve(user_question)
    except Exception as exc:
        error_code = f"ERR-{uuid.uuid4().hex[:10]}"
        write_system_error_log(user_question, exc, request_id=error_code)
        logger.debug(
            "Failed to resolve stock name; returned system_error",
            extra={"error_code": error_code},
        )
        return (
            ClassificationResult(
                status="system_error",
                error_code=error_code,
                error_message=str(exc),
            ),
            [],
            pd.DataFrame(columns=master.columns),
        )

    if stock_candidates:
        matched_stocks = pd.DataFrame(
            [
                {
                    "stock_code": candidate.stock_code,
                    "stock_name": candidate.stock_name,
                    "sector": candidate.sector,
                    "name_norm": normalize_text(candidate.stock_name),
                }
                for candidate in stock_candidates
            ]
        )
    else:
        matched_stocks = match_stocks(user_question, master)

    normalized_question = normalize_text(user_question)
    primary_intent, secondary_intents = infer_intent(user_question, matched_stocks)
    if matched_stocks.empty and contains_any(normalized_question, ANALYZE_WORDS):
        primary_intent = "Intent008 単一銘柄分析"
    if (
        matched_stocks.empty
        and "株" in normalized_question
        and not contains_any(normalized_question, SEARCH_WORDS)
    ):
        primary_intent = "Intent008 単一銘柄分析"
    entities = extract_entities(user_question, primary_intent, matched_stocks, master)
    if stock_candidates:
        entities.update(safe_entities_from_candidates(stock_candidates))

    if primary_intent not in KNOWN_INTENTS:
        return (
            ClassificationResult(status="unsupported", intent=primary_intent, confidence=0.30),
            stock_candidates,
            matched_stocks,
        )

    missing = required_missing(primary_intent, entities)
    if primary_intent == "Intent001 おすすめ銘柄検索" and "投資目的" not in entities:
        missing.append("投資目的")

    if primary_intent in STOCK_REQUIRED_INTENTS:
        if len(stock_candidates) > 1:
            return (
                ClassificationResult(
                    status="ambiguous",
                    intent=primary_intent,
                    entities=safe_entities_from_candidates(stock_candidates),
                    confidence=0.90,
                ),
                stock_candidates,
                matched_stocks,
            )
        if len(stock_candidates) == 0 and missing:
            return (
                ClassificationResult(
                    status="insufficient",
                    intent=primary_intent,
                    entities=entities,
                    missing_fields=missing,
                    confidence=0.70,
                ),
                stock_candidates,
                matched_stocks,
            )

    if missing:
        return (
            ClassificationResult(
                status="insufficient",
                intent=primary_intent,
                entities=entities,
                missing_fields=missing,
                confidence=0.70,
            ),
            stock_candidates,
            matched_stocks,
        )

    return (
        ClassificationResult(
            status="classified",
            intent=primary_intent,
            intent_candidates=secondary_intents,
            entities=entities,
            confidence=0.90,
        ),
        stock_candidates,
        matched_stocks,
    )


def build_search_query(question: str, entities: dict[str, object], primary_intent: str) -> str:
    parts = [question]
    purpose = str(entities.get("投資目的") or "")
    risk = str(entities.get("リスク") or "")

    if "配当" in purpose and "配当" not in question:
        parts.append("高配当")
    if "安定" in purpose or risk == "安全重視":
        parts.append("安定")
    if "値上がり" in purpose:
        parts.append("上昇")
    if primary_intent == "Intent001 おすすめ銘柄検索":
        parts.append("好調")
    return " ".join(parts)


def select_candidate(
    question: str,
    db_path: Path,
    primary_intent: str,
    entities: dict[str, object],
    limit: int,
) -> tuple[pd.DataFrame, list[str]]:
    summary = summarize_stocks(load_candidates(db_path))
    search_query = build_search_query(question, entities, primary_intent)
    results, reasons = natural_language_search(summary, search_query)
    return results.head(limit).copy(), reasons


def run_report(
    stock_code: str,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
) -> Path:
    if skip_web_update:
        from generate_stock_report import generate_report

        return generate_report(stock_code, db_path.expanduser().resolve(strict=True), None, None)

    command = [sys.executable, str(ANALYZE_SCRIPT), stock_code, "--db", str(db_path)]
    if skip_finance:
        command.append("--skip-finance")
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1200,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:] or process.stdout[-4000:])
    match = re.search(r"HTML生成が完了しました:\s*(.+)", process.stdout)
    if match:
        return Path(match.group(1).strip())
    return PROJECT_ROOT / "reports" / f"stock_report_{stock_code}.html"


def write_decision_log(decision: QuestionDecision, candidates: pd.DataFrame | None) -> Path:
    LOG_DIRECTORY.mkdir(exist_ok=True)
    path = LOG_DIRECTORY / f"question_flow_{datetime.now().astimezone():%Y%m%d_%H%M%S_%f}.json"
    payload = asdict(decision)
    if candidates is not None:
        display = candidates.copy()
        for column in ("roe", "dividend_yield"):
            if column in display:
                display[column] = display[column].astype(float) * 100
        payload["candidates"] = display.to_dict(orient="records")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def main() -> None:
    args = parse_args()
    try:
        if args.job_id:
            update_job(args.job_id, status="running", stage="checking_data_freshness")

        domain_result = stock_domain_router.classify(args.question)
        if not domain_result.is_stock:
            classification = ClassificationResult(
                status="unsupported",
                intent=None,
                confidence=domain_result.confidence,
            )
            if domain_result.domain == "unknown":
                message = "依頼内容を特定できませんでした。何を確認したいか、もう少し具体的に教えてください。"
                selected_flow = "followup"
            else:
                message = "株式分析フローの対象外です。通常フローへ渡してください。"
                selected_flow = "general_request"
            decision = build_followup_decision(args.question, classification, message)
            decision.detected_domain = domain_result.domain
            decision.detected_intent = classification.intent
            decision.intent_status = classification.status
            decision.missing_fields = list(classification.missing_fields)
            decision.selected_flow = selected_flow
            decision.route = selected_flow
            decision.early_return = True
            log_path = write_decision_log(decision, None)
            decision.log_path = str(log_path)
            log_path.write_text(
                json.dumps({**asdict(decision), "candidates": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if args.job_id:
                finish_job(
                    args.job_id,
                    status="succeeded",
                    stage="general_request",
                    question_flow_log=decision.log_path,
                )
            print("質問解釈:")
            print(f"- detected_domain: {decision.detected_domain}")
            print(f"- selected_flow: {decision.selected_flow}")
            print(f"- early_return: {decision.early_return}")
            print(f"- message: {decision.message}")
            print(f"質問フローログ: {decision.log_path}")
            return

        pre_db_result = classify_pre_db(args.question, domain_result)
        if pre_db_result is not None:
            if pre_db_result.status == "ambiguous":
                message = followup_question_builder.build_for_ambiguous_intent(
                    original_input=args.question,
                    intent_candidates=pre_db_result.intent_candidates,
                )
            elif pre_db_result.status == "insufficient":
                message = followup_question_builder.build_for_missing_information(
                    original_input=args.question,
                    intent=pre_db_result.intent,
                    missing_fields=pre_db_result.missing_fields,
                    known_entities=pre_db_result.entities,
                )
            elif pre_db_result.status == "unsupported":
                message = followup_question_builder.build_for_unsupported_request(args.question)
            elif pre_db_result.status == "system_error":
                message = followup_question_builder.build_safe_error_response(
                    pre_db_result.error_code
                )
            else:
                message = followup_question_builder.build_for_reclassification(args.question)

            decision = build_followup_decision(args.question, pre_db_result, message)
            decision.detected_domain = domain_result.domain
            decision.detected_intent = pre_db_result.intent
            decision.intent_status = pre_db_result.status
            decision.missing_fields = list(pre_db_result.missing_fields)
            decision.selected_flow = "followup"
            decision.early_return = True
            log_path = write_decision_log(decision, None)
            decision.log_path = str(log_path)
            log_path.write_text(
                json.dumps({**asdict(decision), "candidates": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if args.job_id:
                finish_job(
                    args.job_id,
                    status="succeeded",
                    stage="followup_required",
                    question_flow_log=decision.log_path,
                )
            print("質問解釈:")
            print(f"- status: {decision.classification_status}")
            print(f"- route: {decision.route}")
            print(f"- message: {decision.message}")
            print(f"質問フローログ: {decision.log_path}")
            return

        db_path = args.db.expanduser().resolve(strict=True)
        if args.job_id:
            update_job(args.job_id, stage="loading_stock_master")
        master = load_stock_master(db_path)
        classification, stock_candidates, matched_stocks = classify_with_db(
            args.question,
            db_path,
            master,
        )

        if classification.status in {
            "ambiguous",
            "insufficient",
            "unsupported",
            "system_error",
        }:
            if classification.status == "ambiguous" and stock_candidates:
                message = followup_question_builder.build_for_multiple_stock_candidates(
                    stock_candidates,
                    original_input=args.question,
                )
            elif classification.status == "ambiguous":
                message = followup_question_builder.build_for_ambiguous_intent(
                    original_input=args.question,
                    intent_candidates=classification.intent_candidates,
                )
            elif classification.status == "insufficient" and classification.missing_fields == ["銘柄"]:
                message = followup_question_builder.build_for_unknown_stock(args.question)
            elif classification.status == "insufficient":
                message = followup_question_builder.build_for_missing_information(
                    original_input=args.question,
                    intent=classification.intent,
                    missing_fields=classification.missing_fields,
                    known_entities=classification.entities,
                )
            elif classification.status == "unsupported":
                message = followup_question_builder.build_for_unsupported_request(args.question)
            else:
                message = followup_question_builder.build_safe_error_response(
                    classification.error_code
                )

            data_freshness: list[dict[str, object]] = []
            decision = build_followup_decision(
                args.question,
                classification,
                message,
                data_freshness=data_freshness,
            )
            decision.detected_domain = domain_result.domain
            decision.detected_intent = classification.intent
            decision.intent_status = classification.status
            decision.missing_fields = list(classification.missing_fields)
            decision.resolved_stock_candidates = [asdict(candidate) for candidate in stock_candidates]
            decision.selected_flow = "followup"
            decision.early_return = True
            log_path = write_decision_log(
                decision,
                pd.DataFrame([asdict(candidate) for candidate in stock_candidates])
                if stock_candidates
                else None,
            )
            decision.log_path = str(log_path)
            log_path.write_text(
                json.dumps(
                    {
                        **asdict(decision),
                        "candidates": [asdict(candidate) for candidate in stock_candidates],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            if args.job_id:
                finish_job(
                    args.job_id,
                    status="succeeded",
                    stage="followup_required",
                    question_flow_log=decision.log_path,
                )
            print("質問解釈:")
            print(f"- status: {decision.classification_status}")
            if decision.primary_intent:
                print(f"- primary_intent: {decision.primary_intent}")
            print(f"- route: {decision.route}")
            print(f"- message: {decision.message}")
            print(f"質問フローログ: {decision.log_path}")
            return

        data_freshness = load_data_freshness(db_path)

        if args.job_id:
            update_job(args.job_id, stage="interpreting_question")
        primary_intent = classification.intent or "Intent001 おすすめ銘柄検索"
        secondary_intents = list(classification.intent_candidates)
        entities = dict(classification.entities)
        missing = {
            "required": required_missing(primary_intent, entities),
            "optional": [],
            "defaulted": [],
        }
        if "投資期間" not in entities:
            missing["defaulted"].append("投資期間: 中長期")
        if "リスク" not in entities:
            missing["defaulted"].append("リスク: 普通")

        decision = QuestionDecision(
            user_question=args.question,
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            entities=entities,
            missing_information=missing,
            classification_status=classification.status,
            confidence=classification.confidence,
            data_freshness=data_freshness,
        )
        decision.detected_domain = domain_result.domain
        decision.detected_intent = primary_intent
        decision.intent_status = classification.status
        decision.missing_fields = list(missing["required"])

        candidates: pd.DataFrame | None = None
        if missing["required"]:
            decision.route = "followup_required"
            decision.message = "分析に必要な情報が不足しています。"
            decision.selected_flow = "followup"
            decision.early_return = True
        elif primary_intent in {
            "Intent001 おすすめ銘柄検索",
            "Intent002 値上がり期待銘柄検索",
            "Intent003 高配当銘柄検索",
            "Intent004 株主優待銘柄検索",
            "Intent005 安定銘柄検索",
            "Intent006 成長株検索",
            "Intent007 業界分析",
        }:
            if args.job_id:
                update_job(args.job_id, stage="selecting_candidates")
            candidates, reasons = select_candidate(
                args.question, db_path, primary_intent, entities, args.limit
            )
            if candidates.empty:
                decision.route = "no_candidate"
                decision.message = "条件に合う候補銘柄が見つかりませんでした。"
                decision.selected_flow = "no_candidate"
                decision.early_return = True
            else:
                selected = candidates.iloc[0]
                decision.route = "select_and_analyze"
                decision.selected_stock_code = str(selected["stock_code"])
                decision.selected_stock_name = str(selected["stock_name"])
                decision.selection_reasons = reasons
                decision.selected_flow = "select_and_analyze"
        else:
            stocks = entities.get("銘柄") or []
            selected_stock = stocks[0]
            decision.route = "analyze_stock"
            decision.selected_stock_code = str(selected_stock["stock_code"])
            decision.selected_stock_name = str(selected_stock["stock_name"])
            decision.selection_reasons = ["質問文で銘柄が指定されているため、その銘柄を分析"]
            decision.resolved_stock_candidates = list(stocks)
            decision.selected_flow = "analyze_stock"

        if args.job_id:
            update_job(
                args.job_id,
                stage="decision_ready",
                primary_intent=decision.primary_intent,
                route=decision.route,
                selected_stock_code=decision.selected_stock_code,
                selected_stock_name=decision.selected_stock_name,
            )

        if decision.selected_stock_code and not args.dry_run:
            if args.job_id:
                update_job(args.job_id, stage="generating_report")
            report_path = run_report(
                decision.selected_stock_code,
                db_path,
                args.skip_web_update,
                args.skip_finance,
            )
            decision.report_path = str(report_path)

        log_path = write_decision_log(decision, candidates)
        decision.log_path = str(log_path)
        log_path.write_text(
            json.dumps(
                {
                    **asdict(decision),
                    "candidates": candidates.to_dict(orient="records") if candidates is not None else [],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        if args.job_id:
            finish_job(
                args.job_id,
                status="succeeded",
                stage="completed",
                selected_stock_code=decision.selected_stock_code,
                selected_stock_name=decision.selected_stock_name,
                report_path=decision.report_path,
                question_flow_log=decision.log_path,
            )

        print("質問解釈:")
        print(f"- primary_intent: {decision.primary_intent}")
        if decision.secondary_intents:
            print(f"- secondary_intents: {', '.join(decision.secondary_intents)}")
        print(f"- route: {decision.route}")
        if decision.selected_stock_code:
            print(
                f"- selected_stock: {decision.selected_stock_code} "
                f"{decision.selected_stock_name}"
            )
        if decision.selection_reasons:
            print(f"- selection_reasons: {' / '.join(decision.selection_reasons)}")
        if missing["required"]:
            print(f"- required_missing: {', '.join(missing['required'])}")
        if decision.report_path:
            print(f"HTMLレポート: {decision.report_path}")
        print(f"質問フローログ: {decision.log_path}")
    except Exception as exc:
        error_code = f"ERR-{uuid.uuid4().hex[:10]}"
        error_log = write_system_error_log(args.question, exc, request_id=error_code)
        if args.job_id:
            finish_job(
                args.job_id,
                status="failed",
                stage="failed",
                error=f"system_error: {error_code}",
            )
        logger.debug("Unexpected error while handling user request", exc_info=True)
        print("質問解釈:")
        print("- status: system_error")
        print("- route: system_error")
        print(f"- message: {followup_question_builder.build_safe_error_response(error_code)}")
        print(f"エラーログ: {error_log}")


if __name__ == "__main__":
    main()
