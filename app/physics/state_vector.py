"""Typed state-vector layout for the RH-OB model.

The ODE state y is a flat float64 array; ``Layout`` maps names to index slices so every
block is explicit and inspectable (docs/MODEL_EQUATIONS.md section 7).

Blocks (zone z in ZONES = l [ladle active], d [ladle slow-mixing, optional], v [vessel]):
  M_z            steel mass in zone [kg]
  H_z            steel enthalpy in zone [J] (reference: solid steel at 298.15 K)
  m_z[16]        dissolved species masses [kg] (SPECIES order)
  inc_z[4]       suspended Al2O3 inclusion mass per size class [kg]
  slag[7]        ladle slag oxide masses [kg] (SLAG_OXIDES order)
  H_slag         slag enthalpy [J]
  feo_pool       jet-formed FeO not yet dissolved [kg]
  add[k]         undissolved addition mass per material used in the schedule [kg]
  Tw_ladle[n]    ladle wall node temperatures [K]
  Tw_vlow[n]     lower vessel + snorkel wall node temperatures [K]
  Tw_vup[n]      upper vessel wall node temperatures [K]
  gas[6]         vessel+duct gas inventory [mol] (GAS_SPECIES order)
  acc_in[6]      cumulative gas input [mol]
  acc_exh[6]     cumulative gas exhausted by pumps [mol]
  acc_bypass_ar  cumulative Ar bypassing to atmosphere (fouled nozzles) [mol]
  acc_o2_tuyere  cumulative O2 injected through RH-OB tuyeres [mol]
  acc_skull[2]   cumulative FeO, Al2O3 to vessel skull/surface slag [kg]
  acc_E[k]       energy ledger accumulators [J]
  acc_circ       cumulative circulated steel [kg]
  acc_dc[4]      cumulative decarburization by site: surface, inner, bubble, jet [mol C]
"""
from __future__ import annotations

from .properties import GAS_SPECIES, SLAG_OXIDES, SPECIES
from .cleanliness import N_BINS

ENERGY_TERMS = [
    "rxn_O2_to_O", "rxn_C_O_CO", "rxn_Al2O3", "rxn_SiO2", "rxn_MnO", "rxn_TiO2", "rxn_FeO_form",
    "rxn_FeO_diss", "rxn_solution", "rxn_degas_HN", "rxn_slag_reox", "pc_to_bath",
    "gas_sensible_out", "loss_ladle_shell", "loss_vlow_shell", "loss_vup_shell", "loss_slag_top",
    # internal transfers (for display; NOT part of closure sum)
    "int_to_ladle_wall", "int_to_vlow_wall", "int_to_vup_wall", "int_steel_to_slag", "int_pc_to_offgas",
]
SOURCE_TERMS = ENERGY_TERMS[:12]
SINK_TERMS = ENERGY_TERMS[12:17]
DC_SITES = ["surface", "inner", "bubble", "jet"]


class Layout:
    def __init__(self, zones: list[str], add_materials: list[str], n_wall: tuple[int, int, int]):
        self.zones = zones
        self.add_materials = add_materials
        self.idx: dict[str, object] = {}
        self.size = 0
        for z in zones:
            self._scalar(f"M_{z}")
            self._scalar(f"H_{z}")
            self._block(f"m_{z}", len(SPECIES))
            self._block(f"inc_{z}", N_BINS)
        self._block("slag", len(SLAG_OXIDES))
        self._scalar("H_slag")
        self._scalar("feo_pool")
        self._block("add", len(add_materials))
        self._block("Tw_ladle", n_wall[0])
        self._block("Tw_vlow", n_wall[1])
        self._block("Tw_vup", n_wall[2])
        self._block("gas", len(GAS_SPECIES))
        self._block("acc_in", len(GAS_SPECIES))
        self._block("acc_exh", len(GAS_SPECIES))
        self._scalar("acc_bypass_ar")
        self._scalar("acc_o2_tuyere")
        self._block("acc_skull", 2)
        self._block("acc_E", len(ENERGY_TERMS))
        self._scalar("acc_circ")
        self._block("acc_dc", len(DC_SITES))

    def _scalar(self, name):
        self.idx[name] = self.size
        self.size += 1

    def _block(self, name, n):
        self.idx[name] = slice(self.size, self.size + n)
        self.size += n

    def __getitem__(self, k):
        return self.idx[k]

    def describe(self) -> list[dict]:
        out = []
        for k, v in self.idx.items():
            if isinstance(v, slice):
                out.append({"name": k, "start": v.start, "stop": v.stop, "size": v.stop - v.start})
            else:
                out.append({"name": k, "start": v, "stop": v + 1, "size": 1})
        return out
