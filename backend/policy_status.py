from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from federal_register import DEFAULT_USER_AGENT, NormalizedPolicyDocument


REGINFO_SEARCH_URL = (
    "https://www.reginfo.gov/public/Forward?"
    "SearchTarget=Agenda&textfield={rin}"
)
REGINFO_RULE_URL = (
    "https://www.reginfo.gov/public/do/eAgendaViewRule?"
    "RIN={rin}&pubId={pub_id}"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RulemakingAction(StrictModel):
    name: str
    date_text: str
    action_date: date | None = None
    federal_register_citation: str | None = None
    planned: bool = False


class PolicyStatusSnapshot(StrictModel):
    available: bool
    checked_at: datetime
    source_name: str = "Reginfo.gov Unified Agenda"
    source_url: str | None = None
    rin: str | None = None
    publication_id: str | None = None
    agenda_stage: str | None = None
    rin_status: str | None = None
    actions: list[RulemakingAction] = Field(default_factory=list)
    latest_completed_action: RulemakingAction | None = None
    later_material_action_found: bool = False
    status_label: str
    freshness_message: str
    error: str | None = None


class _ReadableHtmlParser(HTMLParser):
    BLOCK_TAGS = {
        "br",
        "div",
        "p",
        "tr",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "table",
        "section",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS or tag in {"td", "th"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{2,}", "\n", value)
        return value.strip()


def _get_text(url: str, *, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")


def _plain_html_text(payload: str) -> str:
    parser = _ReadableHtmlParser()
    parser.feed(payload)
    return parser.text()


def _latest_pub_id(search_html: str, rin: str) -> str:
    normalized = search_html.replace("&amp;", "&")
    pattern = re.compile(
        r"eAgendaViewRule\?[^\"']*"
        + r"RIN="
        + re.escape(rin)
        + r"[^\"']*pubId=(\d+)",
        re.IGNORECASE,
    )
    values = {match.group(1) for match in pattern.finditer(normalized)}
    if not values:
        raise ValueError(f"Reginfo.gov returned no Unified Agenda entries for RIN {rin}")
    return max(values, key=lambda value: int(value))


def _extract_between(
    text: str,
    label: str,
    following_labels: list[str],
) -> str | None:
    stops = "|".join(re.escape(item) for item in following_labels)
    pattern = re.compile(
        re.escape(label)
        + r"\s*(.*?)\s*(?=(?:"
        + stops
        + r")|$)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
    return value or None


def _parse_action_date(value: str) -> tuple[date | None, bool]:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value.strip())
    if not match:
        return None, True

    month, day, year = (int(part) for part in match.groups())
    if month == 0 or day == 0:
        return None, True

    try:
        return date(year, month, day), False
    except ValueError:
        return None, True


def _timetable_text(text: str) -> str:
    start = text.lower().find("timetable:")
    if start < 0:
        return ""
    value = text[start + len("timetable:") :]
    stop_labels = [
        "Regulatory Flexibility Analysis Required:",
        "Government Levels Affected:",
        "Federalism:",
        "Included in the Regulatory Plan:",
        "Agency Contact:",
    ]
    positions = [
        value.lower().find(label.lower())
        for label in stop_labels
        if value.lower().find(label.lower()) >= 0
    ]
    if positions:
        value = value[: min(positions)]
    return value.strip()


def _parse_timetable(text: str) -> list[RulemakingAction]:
    timetable = _timetable_text(text)
    if not timetable:
        return []

    compact = re.sub(r"\s+", " ", timetable)
    compact = re.sub(r"^Action Date FR Cite\s*", "", compact, flags=re.IGNORECASE)

    date_pattern = re.compile(r"\b\d{2}/(?:\d{2}|00)/\d{4}\b")
    matches = list(date_pattern.finditer(compact))
    actions: list[RulemakingAction] = []

    for index, match in enumerate(matches):
        previous_end = matches[index - 1].end() if index else 0
        name_chunk = compact[previous_end : match.start()].strip(" ;|")
        if index:
            name_chunk = re.sub(
                r"^\d+\s+FR\s+\d+\s*",
                "",
                name_chunk,
                flags=re.IGNORECASE,
            )
        name = name_chunk.strip()
        if not name:
            continue

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(compact)
        after = compact[match.end() : next_start].strip()
        cite_match = re.match(r"(\d+\s+FR\s+\d+)\b", after, flags=re.IGNORECASE)
        citation = cite_match.group(1) if cite_match else None

        parsed_date, planned = _parse_action_date(match.group(0))
        actions.append(
            RulemakingAction(
                name=name,
                date_text=match.group(0),
                action_date=parsed_date,
                federal_register_citation=citation,
                planned=planned,
            )
        )

    return actions


def _material_action(name: str) -> bool:
    normalized = name.casefold()
    material_terms = (
        "withdraw",
        "final rule",
        "interim final",
        "effective",
        "rescission",
        "rescind",
        "vacat",
        "stay",
        "delay",
        "suspend",
        "terminate",
    )
    return any(term in normalized for term in material_terms)


def parse_reginfo_status(
    rule_html: str,
    *,
    rin: str,
    publication_id: str,
    source_url: str,
    document_publication_date: date | None,
    checked_at: datetime | None = None,
) -> PolicyStatusSnapshot:
    text = _plain_html_text(rule_html)
    agenda_stage = _extract_between(
        text,
        "Agenda Stage of Rulemaking:",
        ["Major:", "Unfunded Mandates:", "CFR Citation:", "Legal Authority:"],
    )
    rin_status = _extract_between(
        text,
        "RIN Status:",
        ["Agenda Stage of Rulemaking:", "Major:", "Unfunded Mandates:"],
    )
    actions = _parse_timetable(text)

    completed = [
        action
        for action in actions
        if action.action_date is not None and not action.planned
    ]
    latest = max(completed, key=lambda action: action.action_date) if completed else None

    later_material = False
    if document_publication_date is not None:
        later_material = any(
            action.action_date is not None
            and action.action_date > document_publication_date
            and _material_action(action.name)
            for action in completed
        )

    if latest is not None:
        status_label = (
            f"{latest.name} — {latest.action_date.isoformat()}"
            if latest.action_date
            else latest.name
        )
    elif agenda_stage:
        status_label = agenda_stage
    else:
        status_label = "Unified Agenda entry found"

    if later_material:
        freshness = (
            "A later material rulemaking action was found after the analyzed "
            "Federal Register document. Treat the analyzed text as historical "
            "context unless the later action is also reviewed."
        )
    else:
        freshness = (
            "No later material completed action was identified in this Unified "
            "Agenda check. This is a freshness check, not a legal-effect determination."
        )

    return PolicyStatusSnapshot(
        available=True,
        checked_at=checked_at or datetime.now(timezone.utc),
        source_url=source_url,
        rin=rin,
        publication_id=publication_id,
        agenda_stage=agenda_stage,
        rin_status=rin_status,
        actions=actions,
        latest_completed_action=latest,
        later_material_action_found=later_material,
        status_label=status_label,
        freshness_message=freshness,
    )


def unavailable_policy_status(
    message: str,
    *,
    rin: str | None = None,
    checked_at: datetime | None = None,
) -> PolicyStatusSnapshot:
    return PolicyStatusSnapshot(
        available=False,
        checked_at=checked_at or datetime.now(timezone.utc),
        rin=rin,
        status_label="Status check unavailable",
        freshness_message=(
            "PolicyTrace could not confirm later Unified Agenda activity. "
            "The analyzed Federal Register document can still be reviewed, "
            "but current status should be checked manually."
        ),
        error=message,
    )


def fetch_policy_status(
    document: NormalizedPolicyDocument,
    *,
    timeout: int = 20,
) -> PolicyStatusSnapshot:
    rins = [value.strip() for value in document.regulation_id_numbers if value.strip()]
    if not rins:
        return unavailable_policy_status(
            "Federal Register metadata did not provide a Regulation Identifier Number (RIN)."
        )

    rin = rins[0]
    search_url = REGINFO_SEARCH_URL.format(rin=quote(rin, safe=""))
    try:
        search_html = _get_text(search_url, timeout=timeout)
        publication_id = _latest_pub_id(search_html, rin)
        rule_url = REGINFO_RULE_URL.format(
            rin=quote(rin, safe=""),
            pub_id=quote(publication_id, safe=""),
        )
        rule_html = _get_text(rule_url, timeout=timeout)
        return parse_reginfo_status(
            rule_html,
            rin=rin,
            publication_id=publication_id,
            source_url=rule_url,
            document_publication_date=document.publication_date,
        )
    except Exception as exc:
        return unavailable_policy_status(
            f"{type(exc).__name__}: {exc}",
            rin=rin,
        )
