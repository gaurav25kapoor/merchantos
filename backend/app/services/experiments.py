import hashlib
from uuid import UUID


EXPERIMENTS = {
    "upsell_strategy": {
        "variants": ("control", "treatment"),
        "enabled_variants": ("treatment",),
        "description": "Controls enhanced upsell presentation.",
    }
}


class GrowthExperimentService:
    def get_experiment_config(self, experiment_name: str) -> dict:
        config = EXPERIMENTS.get(experiment_name)
        if config:
            return dict(config)
        return {"variants": ("control", "treatment"), "enabled_variants": ("treatment",), "description": "Default deterministic experiment."}

    def assign_variant(self, session_id: UUID, experiment_name: str) -> str:
        config = self.get_experiment_config(experiment_name)
        variants = tuple(config["variants"])
        digest = hashlib.sha256(f"{session_id}:{experiment_name}".encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(variants)
        return variants[index]

    def is_feature_enabled(self, session_id: UUID, experiment_name: str) -> bool:
        variant = self.assign_variant(session_id, experiment_name)
        config = self.get_experiment_config(experiment_name)
        return variant in set(config["enabled_variants"])
