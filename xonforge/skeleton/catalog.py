"""What the skeleton generators draw from (XONFORGE_SPEC.md §5). Attribute keys are neutral: how an attribute is
phrased ("older than", "on the same team as") is the renderer's work (§6).

On an ordinal attribute, ``greater`` means the higher value: older, taller, later, a higher score, faster.
Categorical attributes are single-valued: one team, club or department per person. ``VALUES`` names the values that
value facts use.
"""
NAMES = ("Ada", "Amir", "Ana", "Arjun", "Ben", "Bo", "Cleo", "Dara", "Dev", "Eli", "Esme", "Femi", "Finn", "Gia",
         "Hana", "Hugo", "Ines", "Ira", "Joel", "Jun", "Kira", "Lars", "Lena", "Mara", "Milo", "Nia", "Noor", "Omar",
         "Pia", "Quinn", "Rosa", "Rui", "Sana", "Tove", "Theo", "Vera", "Vik", "Wren", "Yara", "Zeno")
PRONOUNS = ("she", "he", "they")
ORDINAL = ("age", "height", "arrival", "score", "speed")
CATEGORICAL = ("team", "club", "department", "table", "cabin")
VALUES = {
    "team": ("red", "blue", "green", "gold"),
    "club": ("chess", "drama", "choir", "robotics"),
    "department": ("sales", "design", "research", "finance"),
    "table": ("one", "two", "three", "four"),
    "cabin": ("north", "south", "east", "west"),
}

# v1 (§14 step 8). Judged plants are labeled by review and routed to the judged split (§5.3b, §9).
JUDGED_PLANTS = ("causal_inconsistency", "commonsense_impossibility", "implicature_tension")
V1_PLANT_TYPES = ("temporal_arithmetic", "quantity_arithmetic", "spatial_containment", "coreference_trap",
                  "negation_scope", "quantifier_violation", "uniqueness_violation", "colocation_conflict",
                  "calendar_age", "cardinality_mismatch", "unit_conversion", "knowledge_perspective",
                  *JUDGED_PLANTS)
TRAPS = ("arity_control", "quoted_speech", "hypothetical", "legitimate_correction", "state_change",
         "reported_belief", "time_zone", "unit_equivalence", "overnight_span", "same_name", "role_handover",
         "approximation", "perspective_error")
