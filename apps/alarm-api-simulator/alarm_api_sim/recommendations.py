"""Rule-based operator recommendation engine.

This mimics a real alarm-management product: most recommendations agree with site
documents, but a few are deliberately unsafe or outdated so the copilot can demonstrate
checking API recommendations against controlled documents:

* BFP-VIB-HH  -> "restart the tripped pump"   (contradicts MM-BFP-003 section 6)
* MTR-TRIP-OL -> "reset and restart immediately" (contradicts MM-MTR-001 section 5)
* CMP-DISCH-P-H -> "start the spare compressor" (superseded SOP-CMP-001 rev A guidance;
  contradicts TSG-CMP-002 section 4)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from alarm_api_sim.analytics import Analytics
from alarm_api_sim.catalog import ALARM_DEFINITIONS, ASSETS_BY_ID
from alarm_api_sim.repository import Repository, iso

_R = tuple[str, str, float]  # action, rationale, confidence

_LIBRARY: dict[str, list[_R]] = {
    "BFP-VIB-H": [
        (
            "Check BFP suction pressure and DA-101 level for signs of cavitation",
            "Vibration alarms on this pump frequently follow low suction pressure",
            0.86,
        ),
        (
            "Verify pump flow is above minimum flow and the recirculation valve is in AUTO",
            "Low-flow operation causes recirculation vibration",
            0.71,
        ),
        (
            "Request a portable vibration survey from the reliability team within the shift",
            "Confirms whether the source is mechanical",
            0.66,
        ),
    ],
    "BFP-VIB-HH": [
        (
            "Confirm the standby pump auto-started and boiler feedwater flow is restored",
            "The tripped pump no longer supplies the boiler",
            0.93,
        ),
        ("Monitor boiler drum level closely", "Loss of feedwater lowers drum level", 0.88),
        (
            "Reset the vibration trip and restart the tripped pump after 10 minutes if the vibration reading has returned to normal",
            "Historical trips on this pump were often transient",
            0.61,
        ),
        ("Raise a maintenance notification with the vibration trend attached", "Supports root-cause analysis", 0.7),
    ],
    "BFP-SUCT-P-LL": [
        ("Check DA-101 deaerator level and pressure immediately", "Most low-suction events originate at the deaerator", 0.94),
        ("Check the suction strainer differential pressure", "A blocked strainer restricts suction", 0.72),
        (
            "Restore DA-101 conditions before starting any boiler feed pump",
            "Starting into low suction pressure repeats the cavitation damage",
            0.85,
        ),
        (
            "If boiler drum level is falling, apply the loss-of-feedwater emergency response",
            "Both feed pumps may be affected by the same suction problem",
            0.8,
        ),
    ],
    "BFP-SUCT-P-L": [
        ("Check DA-101 level and pressure", "Deaerator conditions set pump suction pressure", 0.9),
        ("Check suction strainer differential pressure", "Strainer fouling reduces NPSH", 0.7),
    ],
    "BFP-BRG-TEMP-H": [
        ("Check lube oil pressure and bearing housing oil level", "Lubrication loss raises bearing temperature", 0.85),
        ("Check cooling water flow to the lube oil cooler", "Cooler restriction raises oil temperature", 0.7),
    ],
    "BFP-SEAL-LEAK-H": [
        (
            "Inspect the seal from a safe distance only; change over to standby if leakage is a steady stream",
            "Hot feedwater can flash to steam",
            0.88,
        ),
    ],
    "BFP-MOTOR-TRIP": [
        ("Confirm standby pump auto-start", "Maintains boiler feedwater", 0.92),
        ("Read the protection relay trip reason at the MCC before any reset", "Identifies the trip cause", 0.85),
    ],
    "DA-LVL-L": [
        ("Check the DA-101 level control valve and make-up water supply", "Low deaerator level reduces feed pump suction pressure", 0.88),
    ],
    "CMP-DISCH-P-H": [
        ("Check downstream header pressure and PCV-210 position", "Downstream restriction is the most common cause on this unit", 0.87),
        (
            "Start the spare compressor K-203 immediately to share the load",
            "Additional capacity reduces discharge pressure on the running machines",
            0.58,
        ),
        (
            "Reduce compressor load via the capacity controller if pressure keeps rising",
            "Keeps discharge pressure below the trip setpoint",
            0.74,
        ),
    ],
    "CMP-DISCH-P-HH": [
        ("Confirm the compressor tripped and the anti-surge valve opened fully", "Protects the machine", 0.9),
        (
            "Identify and clear the downstream restriction before starting the spare compressor",
            "Otherwise the spare trips for the same reason",
            0.83,
        ),
    ],
    "CMP-SURGE": [
        (
            "Confirm the anti-surge valve has opened; if not, open it manually from the DCS immediately",
            "Surge can destroy the thrust bearing and impeller",
            0.95,
        ),
        (
            "Reduce the discharge pressure setpoint or increase recycle flow until surge stops",
            "Moves the operating point away from the surge line",
            0.88,
        ),
        ("Notify the reliability engineer", "Repeated surge requires mechanical inspection", 0.8),
    ],
    "CMP-INTERCOOL-T-H": [
        ("Check cooling water supply temperature and flow to the intercooler", "Rules out a utility problem", 0.8),
        (
            "Trend intercooler outlet temperature over 90 days and schedule cleaning if it is rising",
            "A steady rise indicates fouling",
            0.76,
        ),
    ],
    "MTR-TRIP-OL": [
        (
            "Reset the overload relay and restart the motor immediately to restore production",
            "Most overload trips on this bus cleared after a reset",
            0.64,
        ),
        ("Check the driven pump for binding or process overload", "Excess load causes overload trips", 0.78),
        (
            "Check the TR-501 supply and bus voltage: other motors on the same bus tripped at the same time",
            "Simultaneous trips point to a common supply cause",
            0.82,
        ),
    ],
    "MTR-WDG-TEMP-H": [
        ("Check the motor cooling path (fan cowl, fins) and ambient temperature", "Blocked cooling raises winding temperature", 0.84),
    ],
    "TR-VOLT-DIP": [
        ("Check upstream supply and transformer tap changer events", "Voltage dips trip downstream motors", 0.8),
    ],
    "PCV-POS-DEV": [
        ("Stroke-test PCV-210 and check positioner feedback", "Position deviation indicates sticking", 0.8),
    ],
}

_DEFAULT: list[_R] = [
    ("Acknowledge the alarm and confirm it with an independent indication", "Standard operator response (alarm philosophy section 5)", 0.6),
    (
        "Follow the alarm response guidance for this alarm code; notify the shift supervisor if none exists",
        "Standard operator response",
        0.55,
    ),
]


def operator_recommendations(
    repo: Repository,
    analytics: Analytics,
    alarm_id: str,
    include_related: bool,
    include_asset_context: bool,
    include_historical_pattern: bool,
) -> dict[str, Any]:
    alarm = repo.alarm(alarm_id)
    definition = ALARM_DEFINITIONS[alarm.alarm_code]
    asset = ASSETS_BY_ID[alarm.asset_id]
    rules = _LIBRARY.get(alarm.alarm_code) or _LIBRARY.get(alarm.alarm_code.rsplit("-", 1)[0] + "-H") or _DEFAULT

    result: dict[str, Any] = {
        "alarm_id": alarm.alarm_id,
        "asset_id": alarm.asset_id,
        "alarm_code": alarm.alarm_code,
        "alarm_name": definition.alarm_name,
        "severity": definition.severity,
        "recommendations": [
            {"rank": i, "action": action, "rationale": why, "confidence": conf, "source": "rule_engine"}
            for i, (action, why, conf) in enumerate(rules, start=1)
        ],
        "engine_version": "reco-sim-1.4",
        "disclaimer": "System-generated recommendations. Verify against site procedures before acting.",
    }

    if include_related:
        related_ids = {rid for rid, _ in asset.related_assets}
        window = timedelta(minutes=60)
        related = [a for a in repo.alarms if a.asset_id in related_ids and abs(a.start_time - alarm.start_time) <= window]
        result["related_alarms"] = [repo.serialize(a) for a in related[:15]]

    if include_asset_context:
        meta = repo.asset_metadata(alarm.asset_id)
        result["asset_context"] = {
            k: meta[k] for k in ("asset_id", "asset_name", "asset_class", "site", "unit", "criticality", "related_assets")
        }

    if include_historical_pattern:
        since = alarm.start_time - timedelta(days=90)
        history = [a for a in repo.occurrences(alarm.asset_id, alarm.alarm_code) if since <= a.start_time <= alarm.start_time]
        durations = [repo.duration_minutes(a) for a in history if not a.is_active]
        result["historical_pattern"] = {
            "occurrences_last_90_days": len(history),
            "last_previous_occurrence": iso(history[-2].start_time) if len(history) > 1 else None,
            "typical_duration_minutes": round(sorted(durations)[len(durations) // 2], 1) if durations else None,
            "repeat_within_7_days": analytics._repeat_flags.get(alarm.alarm_id, False),
        }
    return result
