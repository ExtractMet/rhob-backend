"""Typed configuration objects (Pydantic v2).

Every adjustable number carries metadata (json_schema_extra):
  unit, meaning (description), physical bounds (ge/le), default, change frequency,
  data source and provenance (ILLUSTRATIVE = demo default, not plant tuned).
The data dictionary (datasets/data_dictionary.csv and docs/DATA_DICTIONARY.md) is
GENERATED from these models by scripts/generate_data_dictionary.py, so the code and the
dictionary cannot drift apart.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..physics.geometry import preset_for_capacity


def P(default, unit: str, lo=None, hi=None, desc: str = "", freq: str = "per commissioning",
      src: str = "ILLUSTRATIVE demo default", prov: str = "USER-DEFINED"):
    kw = {"default": default, "description": desc,
          "json_schema_extra": {"unit": unit, "change_frequency": freq, "source": src,
                                "provenance": prov}}
    if lo is not None:
        kw["ge"] = lo
    if hi is not None:
        kw["le"] = hi
    return Field(**kw)


class Mode(str, Enum):
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    ENGINEERING_BATCH_SIMULATION = "ENGINEERING_BATCH_SIMULATION"
    WHAT_IF = "WHAT_IF"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SHADOW_ONLINE = "SHADOW_ONLINE"
    OPERATOR_ADVISORY = "OPERATOR_ADVISORY"
    APPROVED_CLOSED_LOOP_EDGE_ONLY = "APPROVED_CLOSED_LOOP_EDGE_ONLY"


class EquipmentVariant(str, Enum):
    RH = "RH"            # conventional RH, oxygen hardware absent/disabled
    RH_OB = "RH_OB"      # submerged oxygen tuyeres in lower vessel
    RH_KTB = "RH_KTB"    # top lance (distinct variant) - NOT implemented in this release


class Layer(BaseModel):
    material: str = Field(..., description="Refractory library key (physics/properties.py)")
    thickness_m: float = Field(..., ge=0.002, le=0.6, json_schema_extra={"unit": "m"})


class GeometryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capacity_t: float = P(300.0, "t", 60, 420, "Nominal ladle liquid-steel capacity")
    ladle_inner_diameter_m: float = P(3.85, "m", 2.0, 5.0, "Mean inner diameter of ladle working lining")
    ladle_freeboard_m: float = P(0.45, "m", 0.1, 1.5, "Distance steel level to ladle rim")
    ladle_wall_layers: list[Layer] = Field(default_factory=lambda: [
        Layer(material="MgO-C (10% C)", thickness_m=0.18),
        Layer(material="High-alumina brick (safety)", thickness_m=0.065),
        Layer(material="Insulating board", thickness_m=0.02),
        Layer(material="Steel shell", thickness_m=0.04)])
    snorkel_inner_diameter_m: float = P(0.75, "m", 0.3, 1.0, "Inner diameter of up-leg and down-leg snorkels")
    snorkel_length_m: float = P(1.45, "m", 0.8, 2.5, "Snorkel length from vessel bottom to tip")
    snorkel_wall_thickness_m: float = P(0.25, "m", 0.1, 0.45, "Snorkel refractory + castable wall")
    immersion_depth_m: float = P(0.55, "m", 0.2, 0.9, "Snorkel submerged depth below ladle steel level", "per heat")
    lift_nozzle_count: int = P(12, "-", 2, 24, "Number of argon lift nozzles in the up-leg")
    lift_nozzle_height_above_tip_m: float = P(0.20, "m", 0.05, 0.6, "Height of lift-gas nozzle row above snorkel tip")
    vessel_inner_diameter_m: float = P(3.0, "m", 1.6, 3.8, "Lower vacuum vessel inner diameter")
    vessel_lower_height_m: float = P(2.6, "m", 1.5, 4.0, "Lower vessel height (steel-wetted region)")
    vessel_height_m: float = P(10.5, "m", 6.0, 14.0, "Total internal height of vacuum vessel")
    duct_and_cooler_volume_m3: float = P(85.0, "m3", 10, 300, "Evacuated volume of off-gas duct, cooler and dust catcher")
    vessel_wall_layers: list[Layer] = Field(default_factory=lambda: [
        Layer(material="MgO-Cr (direct bonded)", thickness_m=0.30),
        Layer(material="Fireclay brick", thickness_m=0.065),
        Layer(material="Insulating board", thickness_m=0.03),
        Layer(material="Steel shell", thickness_m=0.03)])
    upper_vessel_wall_layers: list[Layer] = Field(default_factory=lambda: [
        Layer(material="MgO-Cr (direct bonded)", thickness_m=0.23),
        Layer(material="Fireclay brick", thickness_m=0.065),
        Layer(material="Insulating board", thickness_m=0.04),
        Layer(material="Steel shell", thickness_m=0.03)])
    oxygen_tuyere_count: int = P(2, "-", 0, 8, "Submerged RH-OB oxygen tuyeres (0 = none installed)")
    oxygen_tuyere_height_above_bottom_m: float = P(0.10, "m", 0.05, 0.6, "Tuyere axis above vessel bottom")

    @classmethod
    def from_capacity(cls, capacity_t: float) -> "GeometryConfig":
        p = preset_for_capacity(capacity_t)
        return cls(capacity_t=capacity_t, ladle_inner_diameter_m=round(p["ladle_inner_diameter_m"], 3),
                   snorkel_inner_diameter_m=round(p["snorkel_inner_diameter_m"], 3),
                   snorkel_length_m=round(p["snorkel_length_m"], 3), immersion_depth_m=round(p["immersion_depth_m"], 3),
                   vessel_inner_diameter_m=round(p["vessel_inner_diameter_m"], 3), vessel_height_m=round(p["vessel_height_m"], 2),
                   duct_and_cooler_volume_m3=round(p["duct_and_cooler_volume_m3"], 1))


class VacuumConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pump_curve: list[list[float]] = Field(
        default_factory=lambda: preset_for_capacity(300)["pump_curve"],
        description="[[suction pressure Pa abs, dry-air-equivalent capacity kg/h], ...] ascending P",
        json_schema_extra={"unit": "Pa_abs, kg/h", "source": "ILLUSTRATIVE; replace by OEM ejector curve"})
    pump_health: float = P(1.0, "-", 0.0, 1.2, "Capacity multiplier (1 = as rated; <1 = degraded steam/condensers)", "per heat")
    air_leak_kg_h: float = P(15.0, "kg/h", 0.0, 500.0, "Air in-leakage into vessel/duct (choked; ~independent of P)", "per heat")
    suction_temperature_K: float = P(320.0, "K", 280, 450, "Gas temperature at pump suction (after cooler)")
    duct_gas_temperature_K: float = P(450.0, "K", 300, 900, "Mean gas temperature in duct/cooler volume")
    vent_gas: Literal["N2", "Ar", "air"] = P("N2", "-", desc="Gas used for vacuum break (affects N pick-up)")
    vent_rate_mol_s: float = P(400.0, "mol/s", 10, 3000, "Vent valve flow at vacuum break")
    pressure_controller_band_frac: float = P(0.06, "-", 0.01, 0.5, "Pressure-control throttle band as fraction of set-point")


class KineticsConfig(BaseModel):
    """Kinetic / transport / calibration parameters (all ILLUSTRATIVE, calibratable)."""
    model_config = ConfigDict(extra="forbid")
    circulation_model: Literal["kuwabara", "energy_balance"] = P("kuwabara", "-", desc="Circulation correlation")
    circulation_multiplier: float = P(1.0, "-", 0.3, 2.0, "Calibration factor on circulation rate", "per campaign",
                                      "tracer/mixing test", "ESTIMATED")
    circulation_multiplier_sd: float = P(0.20, "-", 0.0, 1.0, "1-sigma relative uncertainty of circulation (uncalibrated)")
    downleg_velocity_max_m_s: float = P(1.6, "m/s", 0.5, 3.0, "Hydraulic saturation velocity in down-leg")
    energy_balance_loss_coeff: float = P(4.0, "-", 1.0, 20.0, "Total loss coefficient (energy-balance gas-lift model)")
    energy_balance_efficiency: float = P(0.04, "-", 0.01, 0.5, "Fraction of isothermal expansion work converted to circulation")
    lift_nozzle_fouling: float = P(1.0, "-", 0.0, 1.0, "Effective fraction of lift gas reaching the up-leg (1 = clean)", "per heat")
    k_C_surface_m_s: float = P(1.5e-3, "m/s", 1e-5, 5e-3, "Carbon mass-transfer coefficient at vessel free surface")
    kO_over_kC: float = P(0.6, "-", 0.2, 1.5, "Ratio k_O/k_C (sqrt diffusivity ratio, penetration theory)")
    splash_enhancement: float = P(9.0, "-", 0.0, 60.0, "Free-surface area enhancement per (m/s)^0.5 of actual lift-gas superficial velocity")
    splash_enhancement_max: float = P(16.0, "-", 1.0, 30.0, "Upper bound of free surface area factor")
    inner_site_rate_1_s: float = P(0.02, "1/s", 0.0, 0.2, "Volumetric rate constant of in-bath CO nucleation site")
    co_nucleation_overpressure_Pa: float = P(3000.0, "Pa", 0.0, 2e4, "Critical over-pressure for CO bubble nucleation (2 sigma / r)")
    bubble_equilibrium_approach: float = P(0.45, "-", 0.0, 1.0, "Approach of Ar lift bubbles to C/O/H/N equilibrium")
    k_H_m_s: float = P(6.0e-4, "m/s", 1e-5, 5e-3, "Hydrogen liquid-side mass-transfer coefficient")
    k_N_m_s: float = P(3.5e-4, "m/s", 1e-5, 5e-3, "Nitrogen liquid-side mass-transfer coefficient")
    k_r0_N_mol_m2_s_atm: float = P(2.0, "mol/(m2 s atm)", 0.01, 20.0, "N2 dissociation rate constant, S/O-free iron")
    K_O_poison: float = P(220.0, "1/wt%", 0.0, 1000.0, "Surface-adsorption constant of O in N2 kinetics")
    K_S_poison: float = P(130.0, "1/wt%", 0.0, 1000.0, "Surface-adsorption constant of S in N2 kinetics")
    jet_mass_transfer_capacity_m3_s: float = P(0.10, "m3/s", 0.0, 2.0, "k*A of oxygen-jet interface for solute transport")
    o2_absorption_lambda: float = P(8.0, "1/m", 0.1, 30.0, "O2 absorption exponent per metre of tuyere submergence")
    post_combustion_fraction: float = P(0.35, "-", 0.0, 1.0, "Fraction of slip O2 burning CO in the freeboard")
    post_combustion_heat_to_bath: float = P(0.30, "-", 0.0, 1.0, "Fraction of post-combustion heat transferred to steel")
    feo_dissolution_1_s: float = P(0.08, "1/s", 0.0, 2.0, "Dissolution rate constant of jet FeO into bath")
    feo_to_skull_1_s: float = P(0.004, "1/s", 0.0, 0.5, "Loss of jet FeO to vessel skull/slag")
    deox_rate_1_s: float = P(0.05, "1/s", 0.001, 1.0, "Relaxation rate of deoxidation reactions to equilibrium")
    k_slag_metal_m_s: float = P(2.0e-5, "m/s", 0.0, 1e-3, "Ladle slag-metal O-transfer coefficient (reoxidation)")
    gamma_FeO_slag: float = P(2.0, "-", 0.5, 5.0, "Raoultian activity coefficient of FeO in ladle slag")
    leak_o2_absorption: float = P(0.7, "-", 0.0, 1.0, "Fraction of leaked O2 absorbed by the vessel bath")
    holdup_time_constant_s: float = P(5.0, "s", 1.0, 60.0, "Time constant for steel hold-up response to vacuum")
    three_zone: bool = P(True, "-", desc="Enable stagnant ladle sub-zone (three-zone model)")
    dead_zone_fraction: float = P(0.15, "-", 0.0, 0.5, "Mass fraction of ladle steel in slow-mixing zone")
    dead_zone_exchange_ratio: float = P(0.25, "-", 0.0, 2.0, "Exchange flow active<->dead zone per unit circulation")
    dead_zone_natural_exchange_kg_s: float = P(80.0, "kg/s", 0.0, 2000.0, "Natural-convection exchange without circulation")
    inclusion_bubble_capture: float = P(2.5e-3, "1/s per Nm3/s", 0.0, 0.1, "Bubble-capture coefficient for 10 um inclusions")
    inclusion_aggregation_multiplier: float = P(1.0, "-", 0.0, 10.0, "Multiplier on Saffman-Turner collision kernel")


class ThermalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    h_steel_ladle_wall_W_m2K: float = P(1500.0, "W/(m2 K)", 100, 10000, "Steel->ladle hot face convection")
    h_steel_vessel_wall_W_m2K: float = P(3000.0, "W/(m2 K)", 100, 20000, "Steel->vessel/snorkel wall convection")
    emissivity_steel: float = P(0.35, "-", 0.05, 0.95, "Free steel surface emissivity in vessel")
    emissivity_slag: float = P(0.80, "-", 0.1, 1.0, "Ladle slag surface emissivity")
    emissivity_shell: float = P(0.85, "-", 0.1, 1.0, "Ladle/vessel shell emissivity")
    view_factor_ladle_top: float = P(0.65, "-", 0.0, 1.0, "View factor ladle top -> surroundings")
    h_shell_convection_W_m2K: float = P(10.0, "W/(m2 K)", 2, 60, "Natural convection at shells")
    ambient_temperature_K: float = P(308.0, "K", 250, 340, "Shop ambient temperature", "per shift")
    surroundings_temperature_K: float = P(420.0, "K", 280, 900, "Radiative sink seen by ladle top (hood/vessel underside)")
    slag_thickness_m: float = P(0.10, "m", 0.0, 0.4, "Ladle slag layer thickness", "per heat")
    ladle_hot_face_initial_K: float = P(1650.0, "K", 900, 1873, "Ladle hot face T at RH arrival (ladle thermal history)", "per heat")
    ladle_shell_initial_K: float = P(560.0, "K", 300, 800, "Ladle shell T at arrival", "per heat")
    vessel_preheat_K: float = P(1450.0, "K", 800, 1773, "Vessel inner wall T at heat start (preheat/previous heat)", "per heat")
    vessel_shell_initial_K: float = P(470.0, "K", 300, 800, "Vessel shell temperature", "per heat")
    wall_nodes_working_lining: int = P(4, "-", 2, 10, "Finite-volume nodes in working lining")


class EconomicsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str = "INR"
    oxygen_per_Nm3: float = P(12.0, "INR/Nm3", 0, 1e4, "Oxygen price (ILLUSTRATIVE)")
    argon_per_Nm3: float = P(45.0, "INR/Nm3", 0, 1e4, "Argon price (ILLUSTRATIVE)")
    steam_per_t: float = P(1800.0, "INR/t", 0, 1e5, "Steam price for ejectors (ILLUSTRATIVE)")
    steam_kg_per_kg_gas: float = P(4.5, "kg/kg", 0.5, 30, "Ejector steam per kg of pumped gas (ILLUSTRATIVE)")
    electricity_per_kWh: float = P(8.0, "INR/kWh", 0, 100, "Electricity price")
    refractory_per_min: float = P(900.0, "INR/min", 0, 1e5, "Vessel/snorkel refractory wear cost per treatment minute")
    delay_penalty_per_min: float = P(2500.0, "INR/min", 0, 1e6, "Caster sequence delay penalty")
    alloy_prices_per_kg: dict[str, float] = Field(default_factory=lambda: {
        "Al_shot": 230.0, "FeSi75": 120.0, "LC_FeMn": 160.0, "Mn_metal": 210.0, "FeTi70": 420.0, "FeNb65": 3300.0,
        "FeV80": 2600.0, "LC_FeCr": 210.0, "Ni_cathode": 1500.0, "Cu_scrap": 700.0, "FeMo": 3000.0, "Carbon": 60.0,
        "Cooling_scrap": 38.0}, json_schema_extra={"unit": "INR/kg", "source": "ILLUSTRATIVE"})


class OperatingLimits(BaseModel):
    """Hard equipment limits. MUST be supplied by the site engineer; demo values are placeholders."""
    model_config = ConfigDict(extra="forbid")
    argon_min_NL_min: float = P(300.0, "NL/min", 0, 1e4, "Minimum lift gas to keep nozzles open")
    argon_max_NL_min: float = P(3200.0, "NL/min", 100, 2e4, "Maximum lift gas")
    oxygen_max_Nm3_h: float = P(3000.0, "Nm3/h", 0, 1e4, "Maximum oxygen flow through tuyeres")
    oxygen_max_total_Nm3: float = P(900.0, "Nm3", 0, 5e3, "Maximum oxygen per heat (refractory/tuyere wear)")
    oxygen_min_vessel_depth_m: float = P(0.22, "m", 0.05, 1.0, "Minimum vessel bath depth above tuyere for oxygen ON")
    oxygen_max_vessel_pressure_Pa: float = P(30000.0, "Pa_abs", 1000, 101325, "Oxygen permitted only below this pressure")
    pressure_min_Pa: float = P(50.0, "Pa_abs", 10, 1000, "Lowest controllable vessel pressure")
    temperature_max_K: float = P(1953.0, "K", 1800, 2000, "Steel over-temperature alarm")
    temperature_min_K: float = P(1823.0, "K", 1773, 1900, "Steel under-temperature alarm (freezing risk in snorkels)")
    max_treatment_time_s: float = P(2700.0, "s", 300, 7200, "Maximum RH occupancy for the caster sequence")
    oxygen_safety_prerequisites_confirmed: bool = P(True, "-", desc="SIMULATED interlock: O2 line purge/pressure/valves OK. Unknown -> False")


class GradeCard(BaseModel):
    model_config = ConfigDict(extra="allow")
    grade_id: str
    description: str = ""
    family: str = "ULC"
    C_max_ppm: float = 30.0
    N_max_ppm: float = 40.0
    H_max_ppm: float = 2.0
    O_diss_max_after_deox_ppm: float = 10.0
    Al_min_wtpct: float = 0.030
    Al_max_wtpct: float = 0.060
    Si_max_wtpct: Optional[float] = 0.03
    Mn_min_wtpct: Optional[float] = None
    Mn_max_wtpct: Optional[float] = None
    Ti_min_wtpct: Optional[float] = None
    Ti_max_wtpct: Optional[float] = None
    Nb_min_wtpct: Optional[float] = None
    Nb_max_wtpct: Optional[float] = None
    T_end_min_K: float = 1858.0
    T_end_max_K: float = 1878.0
    caster_superheat_target_K: float = 30.0
    transfer_to_caster_s: float = 900.0
    max_treatment_time_s: float = 2400.0
    total_oxygen_max_ppm: Optional[float] = 30.0
    priority: list[str] = Field(default_factory=lambda: ["C", "T", "Al", "N", "H"])
    rh_ob_suitable: bool = True


class HeatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heat_id: str = "SYNTHETIC-001"
    grade_id: str = "IF-ULC"
    steel_mass_t: float = P(300.0, "t", 50, 420, "Liquid steel mass at RH arrival", "per heat", "ladle weighing", "MEASURED")
    T_arrival_K: float = P(1893.0, "K", 1800, 1973, "Steel temperature at arrival", "per heat", "dip thermocouple", "MEASURED")
    composition_ppm: dict[str, float] = Field(default_factory=lambda: {
        "C": 380.0, "O": 620.0, "H": 4.5, "N": 38.0, "Al": 0.0, "Si": 30.0, "Mn": 1500.0, "Ti": 0.0,
        "S": 70.0, "P": 120.0, "Cr": 200.0, "Ni": 150.0, "Nb": 0.0, "V": 20.0, "Cu": 200.0, "Mo": 20.0},
        json_schema_extra={"unit": "ppm (mass)", "provenance": "LAB ANALYZED (synthetic)"})
    slag_mass_t: float = P(3.5, "t", 0.0, 20.0, "Ladle slag mass (carry-over + additions)", "per heat", "estimate", "ESTIMATED")
    slag_composition_wtpct: dict[str, float] = Field(default_factory=lambda: {
        "FeO": 14.0, "MnO": 5.0, "SiO2": 12.0, "Al2O3": 14.0, "CaO": 45.0, "MgO": 9.0, "TiO2": 1.0})
    source_timestamp_utc: Optional[str] = None
    assay_confidence: Literal["high", "medium", "low"] = "medium"

    @field_validator("composition_ppm")
    @classmethod
    def _check_comp(cls, v):
        for k, x in v.items():
            if x < 0:
                raise ValueError(f"negative concentration for {k}")
        tot = sum(v.values()) * 1e-6
        if tot > 0.35:
            raise ValueError("sum of solutes > 35 wt%: outside dilute-solution validity domain")
        return v

    @field_validator("slag_composition_wtpct")
    @classmethod
    def _check_slag(cls, v):
        s = sum(v.values())
        if v and not (95.0 <= s <= 105.0):
            raise ValueError(f"slag composition sums to {s:.1f} wt% (expected ~100)")
        return v


class Phase(BaseModel):
    """One operating phase of the schedule (piecewise-constant manipulated variables)."""
    model_config = ConfigDict(extra="forbid")
    stage: str
    duration_s: float = Field(..., ge=0, le=7200)
    pressure_setpoint_Pa: float = Field(101325.0, ge=10, le=110000)
    pressure_setpoint_end_Pa: Optional[float] = Field(None, ge=10, le=110000)
    argon_NL_min: float = Field(0.0, ge=0, le=20000)
    oxygen_Nm3_h: float = Field(0.0, ge=0, le=10000)
    oxygen_ramp_s: float = Field(20.0, ge=0, le=600)
    vacuum_pump_on: bool = True
    snorkels_immersed: bool = True
    vent: bool = False
    note: str = ""


class Addition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t_s: float = Field(..., ge=0)
    material: str
    mass_kg: float = Field(..., ge=0, le=20000)
    yield_override: Optional[float] = Field(None, ge=0.0, le=1.0)
    purpose: str = "alloying"
    auto_target_Al_ppm: Optional[float] = Field(None, ge=0, le=5000, description="If set (Al_shot only), mass is computed at addition time from the O-probe reading to reach this Al target")


class SampleRequest(BaseModel):
    t_s: float = Field(..., ge=0)
    kinds: list[str] = Field(default_factory=lambda: ["C", "O", "H", "N", "Al", "T"])
    lab_delay_s: float = Field(240.0, ge=0, le=3600)


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phases: list[Phase]
    additions: list[Addition] = Field(default_factory=list)
    samples: list[SampleRequest] = Field(default_factory=list)
    abort_at_s: Optional[float] = None


class SolverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["BDF", "Radau", "LSODA"] = P("BDF", "-", desc="scipy.integrate.solve_ivp stiff method")
    rtol: float = P(1e-6, "-", 1e-9, 1e-3, "Relative tolerance")
    max_step_s: float = P(10.0, "s", 0.1, 60.0, "Maximum internal step (1-10 s substeps)")
    record_interval_s: float = P(10.0, "s", 1.0, 120.0, "Trajectory recording interval")
    mass_residual_tol: float = P(1e-6, "-", 1e-12, 1e-2, "Max relative elemental closure residual")
    energy_residual_tol: float = P(1e-4, "-", 1e-10, 1e-1, "Max relative energy closure residual")
    wall_time_budget_s: float = P(120.0, "s", 1, 3600, "Solver time-out budget per run")
    seed: int = 20240601


class PlantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plant_id: str = "INDUSTRY-X"
    station_id: str = "RH-OB-1"
    upstream_shop: str = "BOF-2"
    route: str = "BOF-RHOB-CC"
    caster_id: str = "CC-2"
    timezone: str = "Asia/Kolkata"
    variant: EquipmentVariant = EquipmentVariant.RH_OB
    chemical_heating_enabled: bool = P(True, "-", desc="Al + O2 chemical heating permitted & validated at site")
    atmospheric_pressure_Pa: float = P(101325.0, "Pa_abs", 85000, 106000, "Local barometric pressure", "per shift", "barometer", "MEASURED")
    geometry: GeometryConfig = Field(default_factory=GeometryConfig)
    vacuum: VacuumConfig = Field(default_factory=VacuumConfig)
    kinetics: KineticsConfig = Field(default_factory=KineticsConfig)
    thermal: ThermalConfig = Field(default_factory=ThermalConfig)
    limits: OperatingLimits = Field(default_factory=OperatingLimits)
    economics: EconomicsConfig = Field(default_factory=EconomicsConfig)
    config_version: str = "demo-1.0.0"

    @model_validator(mode="after")
    def _variant(self):
        if self.variant == EquipmentVariant.RH_KTB:
            raise ValueError("RH-KTB (top-lance) variant is a DISTINCT equipment type and is not implemented in "
                             "this release; select RH or RH_OB.")
        if self.variant == EquipmentVariant.RH and self.geometry.oxygen_tuyere_count > 0:
            # conventional RH: tuyeres are treated as not installed
            self.geometry.oxygen_tuyere_count = 0
        return self


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Mode = Mode.DEMO_SYNTHETIC
    plant: PlantConfig = Field(default_factory=PlantConfig)
    heat: HeatInput = Field(default_factory=HeatInput)
    grade: Optional[GradeCard] = None
    schedule: Optional[Schedule] = None
    solver: SolverConfig = Field(default_factory=SolverConfig)
    scenario_name: str = "baseline"
    scenario_id: Optional[str] = None
    synthetic_plant_truth: bool = Field(True, description="Also run a perturbed 'plant' twin to generate synthetic measurements")
