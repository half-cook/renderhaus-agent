from __future__ import annotations

import re
from typing import TypedDict

from agent.deep_agent.routing import job_type
from agent.studio_agent_next import StudioAgentOutput


class MediaCostRecord(TypedDict):
    request_id: str
    tool: str
    provider: str
    model: str | None
    status: str
    provider_cost_estimate_cents: int | None
    fee_estimate_cents: int | None
    total_estimate_cents: int | None
    currency: str


def append_media_costs(output: StudioAgentOutput, ledger: dict[str, MediaCostRecord], scope: str) -> None:
    records = [row for _, row in sorted(ledger.items()) if row["request_id"] == scope]
    if not records:
        return
    known_cents = sum(row["total_estimate_cents"] or 0 for row in records)
    unknown = any(row["total_estimate_cents"] is None for row in records)
    total = f"Estimated media cost ${known_cents / 100:.2f} USD"
    total += " plus unknown charges." if unknown else "."
    lines, brief = [], []
    labels = {"t2v": "Video", "i2v": "Video", "reference_video": "Video",
              "tts": "Voiceover", "motion_graphics": "Assembly"}
    for row in records:
        cents = row["total_estimate_cents"]
        cost = "unknown" if cents is None else f"${cents / 100:.2f} USD"
        model = f" ({row['model']})" if row["model"] else ""
        lines.append(f"- {row['tool']}{model}: {cost}.")
        label = labels.get(job_type(row["tool"]), row["provider"])
        brief.append(f"{label} {cost.removesuffix(' USD')}")
    section = "## Estimated media costs\n\n" + "\n".join(lines) + f"\n\n{total}\n"
    section += "Recorded estimates include platform fees. Model token costs are separate."
    narrative = re.sub(
        r"^#{1,6}\s+(?:(?:estimated\s+)?(?:media\s+)?)?(?:costs?|pricing|spend|budget)\b.*?(?=^#{1,6}\s|\Z)",
        "", output.markdown, flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
    ).rstrip()
    output.markdown = narrative[:max(0, 30_000 - len(section) - 2)].rstrip() + "\n\n" + section
    synopsis = output.summary.split("Estimated media costs:", 1)[0].rstrip()
    cost_summary = "Estimated media costs: " + "; ".join(brief) + ". " + total
    if len(cost_summary) > 320:
        cost_summary = total + f" See the full response for all {len(records)} paid steps."
    prefix = synopsis[:max(0, 320 - len(cost_summary) - 1)].rstrip()
    output.summary = (prefix + " " + cost_summary).strip()
