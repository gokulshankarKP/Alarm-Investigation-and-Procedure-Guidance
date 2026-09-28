"""Static master data: assets and alarm definitions.

Asset tags, alarm codes, priorities and setpoints are aligned with the RAG corpus in
``rag/documents`` (SOP-BFP-001, SOP-CMP-001, MM-MTR-001, ALM-PHIL-001, ...), so API data
and document guidance describe the same plant.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Asset:
    asset_id: str
    asset_name: str
    asset_class: str
    site: str
    unit: str
    criticality: str  # A / B / C (ALM-PHIL-001 section 4)
    description: str
    manufacturer: str
    model: str
    install_date: str
    parent_asset_id: str | None = None
    related_assets: tuple[tuple[str, str], ...] = ()  # (asset_id, relationship)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlarmDefinition:
    alarm_code: str
    alarm_name: str
    severity: str  # low / medium / high / critical
    priority: int  # 1 (critical) .. 4 (low)
    alarm_type: str  # process / device / safety / system
    setpoint: float | None
    uom: str
    is_trip: bool = False


SEVERITY_PRIORITY = {"critical": 1, "high": 2, "medium": 3, "low": 4}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
MAX_RESPONSE_MINUTES = {"critical": 5, "high": 15, "medium": 30, "low": 60}  # ALM-PHIL-001 s3


def _a(*args, **kwargs) -> Asset:
    return Asset(*args, **kwargs)


ASSETS: tuple[Asset, ...] = (
    # --- NorthPlant, Unit 1: boiler feedwater system -------------------------------------
    _a(
        "BFP-101",
        "Boiler Feed Pump 101",
        "boiler_feed_pump",
        "NorthPlant",
        "Unit 1",
        "A",
        "Multistage barrel-type centrifugal boiler feed pump, duty pump",
        "Sulzer-like (synthetic)",
        "MC-8/6",
        "2014-03-12",
        "BLR-101",
        (
            ("M-101", "driver"),
            ("DA-101", "suction_source"),
            ("FCV-101", "min_flow_valve"),
            ("BFP-102", "standby_pump"),
            ("BLR-101", "discharge_destination"),
        ),
        {"rated_flow_tph": "220", "rated_head_barg": "140", "speed_rpm": "2980"},
    ),
    _a(
        "BFP-102",
        "Boiler Feed Pump 102",
        "boiler_feed_pump",
        "NorthPlant",
        "Unit 1",
        "A",
        "Multistage barrel-type centrifugal boiler feed pump, standby (auto-start)",
        "Sulzer-like (synthetic)",
        "MC-8/6",
        "2014-03-12",
        "BLR-101",
        (
            ("M-102", "driver"),
            ("DA-101", "suction_source"),
            ("FCV-102", "min_flow_valve"),
            ("BFP-101", "duty_pump"),
            ("BLR-101", "discharge_destination"),
        ),
        {"rated_flow_tph": "220", "rated_head_barg": "140", "speed_rpm": "2980"},
    ),
    _a(
        "DA-101",
        "Deaerator 101",
        "deaerator",
        "NorthPlant",
        "Unit 1",
        "A",
        "Spray-tray deaerator and storage tank feeding BFP-101/102",
        "Synthetic",
        "DT-40",
        "2014-01-20",
        "BLR-101",
        (("BFP-101", "feeds"), ("BFP-102", "feeds")),
        {"capacity_m3": "40"},
    ),
    _a(
        "M-101",
        "BFP-101 Drive Motor M-101",
        "motor",
        "NorthPlant",
        "Unit 1",
        "A",
        "1.2 MW 6.6 kV induction motor driving BFP-101",
        "Synthetic",
        "IM-1200",
        "2014-03-12",
        "BFP-101",
        (("BFP-101", "drives"),),
        {"rated_kw": "1200", "voltage_kv": "6.6"},
    ),
    _a(
        "M-102",
        "BFP-102 Drive Motor M-102",
        "motor",
        "NorthPlant",
        "Unit 1",
        "A",
        "1.2 MW 6.6 kV induction motor driving BFP-102",
        "Synthetic",
        "IM-1200",
        "2014-03-12",
        "BFP-102",
        (("BFP-102", "drives"),),
        {"rated_kw": "1200", "voltage_kv": "6.6"},
    ),
    _a(
        "FCV-101",
        "Min-Flow Recirculation Valve FCV-101",
        "valve",
        "NorthPlant",
        "Unit 1",
        "B",
        "Minimum-flow recirculation valve for BFP-101",
        "Synthetic",
        "RV-4",
        "2014-03-12",
        "BFP-101",
        (("BFP-101", "protects"), ("DA-101", "returns_to")),
    ),
    _a(
        "FCV-102",
        "Min-Flow Recirculation Valve FCV-102",
        "valve",
        "NorthPlant",
        "Unit 1",
        "B",
        "Minimum-flow recirculation valve for BFP-102",
        "Synthetic",
        "RV-4",
        "2014-03-12",
        "BFP-102",
        (("BFP-102", "protects"), ("DA-101", "returns_to")),
    ),
    _a(
        "BLR-101",
        "Boiler 101",
        "boiler",
        "NorthPlant",
        "Unit 1",
        "A",
        "Water-tube steam boiler, Unit 1",
        "Synthetic",
        "WT-250",
        "2013-11-01",
        None,
        (("BFP-101", "fed_by"), ("BFP-102", "fed_by"), ("DA-101", "feedwater_source")),
    ),
    # --- NorthPlant, Unit 3: cooling water -----------------------------------------------
    _a(
        "CWP-301",
        "Cooling Water Pump 301",
        "pump",
        "NorthPlant",
        "Unit 3",
        "B",
        "Cooling water circulation pump",
        "Synthetic",
        "CW-900",
        "2016-05-01",
        None,
        (("CTF-302", "serves"),),
    ),
    _a(
        "CTF-302",
        "Cooling Tower Fan 302",
        "fan",
        "NorthPlant",
        "Unit 3",
        "C",
        "Induced-draft cooling tower fan",
        "Synthetic",
        "CTF-12",
        "2016-05-01",
        None,
        (("CWP-301", "cooled_loop"),),
    ),
    # --- EastRefinery, Unit 2: process gas compression -----------------------------------
    *(
        _a(
            f"K-20{n}",
            f"Process Gas Compressor K-20{n}",
            "compressor",
            "EastRefinery",
            "Unit 2",
            "A",
            "Two-stage centrifugal process gas compressor" + (" (installed spare)" if n == 3 else ""),
            "Synthetic",
            "PGC-2S",
            "2017-08-15",
            None,
            (
                (f"E-20{n}", "intercooler"),
                (f"UV-20{n}", "anti_surge_valve"),
                ("PCV-210", "downstream_pressure_control"),
                (f"M-20{n}", "driver"),
                *((f"K-20{m}", "parallel_compressor") for m in (1, 2, 3) if m != n),
            ),
            {"normal_discharge_barg": "7.4-8.2", "trip_discharge_barg": "9.0"},
        )
        for n in (1, 2, 3)
    ),
    *(
        _a(
            f"E-20{n}",
            f"Intercooler E-20{n}",
            "heat_exchanger",
            "EastRefinery",
            "Unit 2",
            "B",
            f"Interstage gas cooler for K-20{n}",
            "Synthetic",
            "STX-2",
            "2017-08-15",
            f"K-20{n}",
            ((f"K-20{n}", "cools"),),
        )
        for n in (1, 2, 3)
    ),
    *(
        _a(
            f"UV-20{n}",
            f"Anti-Surge Valve UV-20{n}",
            "valve",
            "EastRefinery",
            "Unit 2",
            "A",
            f"Anti-surge recycle valve for K-20{n}",
            "Synthetic",
            "ASV-6",
            "2017-08-15",
            f"K-20{n}",
            ((f"K-20{n}", "protects"),),
        )
        for n in (1, 2, 3)
    ),
    *(
        _a(
            f"M-20{n}",
            f"K-20{n} Drive Motor M-20{n}",
            "motor",
            "EastRefinery",
            "Unit 2",
            "A",
            f"MV induction motor driving K-20{n}",
            "Synthetic",
            "IM-2500",
            "2017-08-15",
            f"K-20{n}",
            ((f"K-20{n}", "drives"),),
        )
        for n in (1, 2, 3)
    ),
    _a(
        "PCV-210",
        "Header Pressure Control Valve PCV-210",
        "valve",
        "EastRefinery",
        "Unit 2",
        "B",
        "Downstream header pressure control valve for the Unit 2 compressors",
        "Synthetic",
        "PCV-8",
        "2017-08-15",
        None,
        (("K-201", "controls_discharge_of"), ("K-202", "controls_discharge_of"), ("K-203", "controls_discharge_of")),
    ),
    # --- EastRefinery, Unit 4: heater section ---------------------------------------------
    _a(
        "H-401",
        "Crude Heater H-401",
        "fired_heater",
        "EastRefinery",
        "Unit 4",
        "A",
        "Crude charge fired heater",
        "Synthetic",
        "FH-30",
        "2012-02-01",
        None,
        (("P-402", "fed_by"),),
    ),
    _a(
        "P-402",
        "Heater Feed Pump P-402",
        "pump",
        "EastRefinery",
        "Unit 4",
        "B",
        "Charge pump feeding H-401",
        "Synthetic",
        "CP-300",
        "2012-02-01",
        None,
        (("H-401", "feeds"),),
    ),
    # --- SouthPlant, Unit 5: process motors on a common bus ----------------------------
    *(
        _a(
            f"M-50{n}",
            f"Process Motor M-50{n}",
            "motor",
            "SouthPlant",
            "Unit 5",
            "A",
            f"LV induction motor driving process pump P-50{n}, supplied from MCC-5 bus / TR-501",
            "Synthetic",
            "IM-250",
            "2019-06-10",
            None,
            ((f"P-50{n}", "drives"), ("TR-501", "supplied_by"), *((f"M-50{m}", "same_bus_motor") for m in (1, 2, 3) if m != n)),
            {"rated_kw": "250", "voltage_kv": "0.69"},
        )
        for n in (1, 2, 3)
    ),
    *(
        _a(
            f"P-50{n}",
            f"Process Pump P-50{n}",
            "pump",
            "SouthPlant",
            "Unit 5",
            "B",
            f"Process pump driven by M-50{n}",
            "Synthetic",
            "PP-150",
            "2019-06-10",
            None,
            ((f"M-50{n}", "driven_by"),),
        )
        for n in (1, 2, 3)
    ),
    _a(
        "TR-501",
        "Unit 5 Supply Transformer TR-501",
        "transformer",
        "SouthPlant",
        "Unit 5",
        "A",
        "11/0.69 kV transformer feeding the MCC-5 bus",
        "Synthetic",
        "TX-2500",
        "2019-06-10",
        None,
        (("M-501", "supplies"), ("M-502", "supplies"), ("M-503", "supplies")),
    ),
)

ASSETS_BY_ID: dict[str, Asset] = {a.asset_id: a for a in ASSETS}


def _d(code, name, severity, alarm_type, setpoint, uom, is_trip=False) -> AlarmDefinition:
    return AlarmDefinition(code, name, severity, SEVERITY_PRIORITY[severity], alarm_type, setpoint, uom, is_trip)


ALARM_DEFINITIONS: dict[str, AlarmDefinition] = {
    d.alarm_code: d
    for d in (
        _d("BFP-VIB-H", "High bearing vibration", "medium", "device", 7.1, "mm/s"),
        _d("BFP-VIB-HH", "Very high bearing vibration - pump trip", "high", "safety", 11.0, "mm/s", True),
        _d("BFP-BRG-TEMP-H", "High bearing temperature", "medium", "device", 85, "degC"),
        _d("BFP-BRG-TEMP-HH", "Very high bearing temperature - pump trip", "high", "safety", 95, "degC", True),
        _d("BFP-SUCT-P-L", "Low suction pressure", "medium", "process", 3.8, "barg"),
        _d("BFP-SUCT-P-LL", "Very low suction pressure - pump trip", "critical", "safety", 3.2, "barg", True),
        _d("BFP-DISCH-P-L", "Low discharge pressure", "medium", "process", 120, "barg"),
        _d("BFP-MIN-FLOW-L", "Low flow (below minimum flow)", "low", "process", 60, "t/h"),
        _d("BFP-SEAL-LEAK-H", "Mechanical seal leakage", "medium", "device", None, "switch"),
        _d("BFP-MOTOR-TRIP", "Drive motor trip", "high", "device", None, "status", True),
        _d("DA-LVL-L", "Deaerator low level", "medium", "process", 45, "%"),
        _d("DA-P-L", "Deaerator low pressure", "medium", "process", 1.5, "barg"),
        _d("BLR-DRUM-LVL-L", "Boiler drum low level", "high", "safety", -100, "mm"),
        _d("FCV-POS-DEV", "Recirculation valve position deviation", "low", "device", 10, "%"),
        _d("CMP-DISCH-P-H", "High discharge pressure", "medium", "process", 8.6, "barg"),
        _d("CMP-DISCH-P-HH", "Discharge pressure trip", "high", "safety", 9.0, "barg", True),
        _d("CMP-DISCH-T-H", "High discharge temperature", "medium", "process", 150, "degC"),
        _d("CMP-INTERCOOL-T-H", "High intercooler gas outlet temperature", "medium", "process", 50, "degC"),
        _d("CMP-SURGE", "Compressor surge detected", "critical", "safety", None, "status"),
        _d("CMP-VIB-H", "High shaft vibration", "medium", "device", 60, "um"),
        _d("CMP-LUBE-P-L", "Low lube oil pressure", "high", "device", 1.4, "barg"),
        _d("PCV-POS-DEV", "Control valve position deviation", "medium", "device", 10, "%"),
        _d("MTR-TRIP-OL", "Motor overload trip", "high", "device", None, "status", True),
        _d("MTR-TRIP-EF", "Motor earth fault trip", "high", "safety", None, "status", True),
        _d("MTR-WDG-TEMP-H", "High winding temperature", "medium", "device", 130, "degC"),
        _d("MTR-WDG-TEMP-HH", "Winding temperature trip", "high", "device", 145, "degC", True),
        _d("MTR-PHASE-IMB", "Phase current imbalance", "medium", "device", 10, "%"),
        _d("MTR-VIB-H", "High motor vibration", "medium", "device", 4.5, "mm/s"),
        _d("TR-VOLT-DIP", "Bus voltage dip", "high", "process", 90, "%"),
        _d("CWP-FLOW-L", "Low cooling water flow", "medium", "process", 800, "m3/h"),
        _d("CTF-VIB-H", "Cooling tower fan high vibration", "low", "device", 7.1, "mm/s"),
        _d("HTR-TEMP-H", "Heater outlet high temperature", "high", "process", 370, "degC"),
        _d("P-DISCH-P-L", "Pump low discharge pressure", "medium", "process", 12, "barg"),
    )
}
